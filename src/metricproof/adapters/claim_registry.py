"""Safe YAML adapter for the versioned, atomic Claim registry."""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from metricproof.adapters.limits import MAX_FILE_BYTES
from metricproof.adapters.yaml_support import load_single_yaml
from metricproof.application.errors import ExitCode
from metricproof.application.registry_errors import ClaimRegistryError
from metricproof.domain.claim_identity import (
    ClaimContext,
    ClaimFingerprint,
    ClaimIdentitySnapshot,
    ClaimMigrationMethod,
    ClaimMigrationStatus,
    StableClaimId,
)
from metricproof.domain.claims import ClaimDisposition, ClaimKind
from metricproof.domain.links import (
    ClaimLink,
    DerivedLink,
    DerivedOperand,
    DerivedOperation,
    DirectLink,
    LinkScale,
    MetricReference,
    NumericTolerance,
    RoundingMode,
    RoundingPolicy,
    StandardDeviationMode,
)
from metricproof.domain.models import NumericUnit, SourceLocation
from metricproof.domain.registry import (
    CLAIM_REGISTRY_SCHEMA_VERSION,
    ClaimRegistry,
    ClaimRegistryEntry,
    ClaimRegistryStatus,
    IgnoreReason,
    IgnoreRecord,
    RegistryMigrationRecord,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class _RawLocation(_StrictModel):
    path: str
    selector: str = ""
    line: int | None = None
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None
    char_start: int | None = None
    char_end: int | None = None


class _RawContext(_StrictModel):
    summary: str
    structural_anchor: str
    prefix_anchor: str
    suffix_anchor: str
    syntactic_context: str
    occurrence_ordinal: int
    table_anchor: str | None = None
    table_row: int | None = None
    table_column: int | None = None


class _RawFingerprint(_StrictModel):
    version: str
    digest: str
    path: str
    structural_anchor: str
    context_digest: str
    semantic_digest: str
    components: list[list[str]]


class _RawIdentity(_StrictModel):
    claim_id: str
    fingerprint: _RawFingerprint
    location: _RawLocation
    raw_text: str
    kind: Literal[
        "direct_result",
        "derived_result",
        "summary_statistic",
        "experiment_quantity",
        "unknown",
    ]
    disposition: Literal[
        "likely_experiment_claim",
        "possible_experiment_claim",
        "ambiguous",
        "non_experiment",
    ]
    context: _RawContext


class _RawTolerance(_StrictModel):
    absolute: str
    relative: str


class _RawMetricReference(_StrictModel):
    source_file: str
    run_id: str
    metric_name: str
    source_selector: str
    scale: Literal["identity", "fraction_to_percent", "percent_to_fraction"]


class _RawDirectLink(_StrictModel):
    type: Literal["direct"]
    metric: _RawMetricReference
    confirmed_fingerprint: str
    tolerance_override: _RawTolerance | None = None
    note: str = ""


class _RawOperand(_StrictModel):
    name: str
    metric: _RawMetricReference


class _RawRounding(_StrictModel):
    decimal_places: int | None = None
    mode: Literal["half_up"] = "half_up"


class _RawDerivedLink(_StrictModel):
    type: Literal["derived"]
    operation: Literal["subtraction", "relative_change", "mean", "standard_deviation"]
    operands: list[_RawOperand]
    output_unit: Literal["scalar", "ratio", "percent_points"]
    output_scale: Literal["identity", "fraction_to_percent", "percent_to_fraction"]
    confirmed_fingerprint: str
    rounding: _RawRounding = Field(default_factory=_RawRounding)
    standard_deviation_mode: Literal["sample", "population"] | None = None
    tolerance_override: _RawTolerance | None = None
    note: str = ""


class _RawIgnore(_StrictModel):
    reason: Literal[
        "non_experimental_number",
        "out_of_scope",
        "unsupported_syntax",
        "user_decision",
    ]
    note: str = ""


class _RawMigration(_StrictModel):
    status: Literal["exact", "migrated", "ambiguous", "missing", "collision"]
    method: Literal[
        "stable_id",
        "versioned_context",
        "structural_context",
        "local_context",
        "none",
    ]
    score: int
    previous_path: str
    current_path: str | None = None
    evidence: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class _RawEntry(_StrictModel):
    identity: _RawIdentity
    status: Literal["active", "ignored", "broken", "ambiguous", "missing"]
    link: _RawDirectLink | _RawDerivedLink | None = None
    ignore: _RawIgnore | None = None
    note: str = ""
    migration: _RawMigration | None = None


class _RawRegistry(_StrictModel):
    schema_version: str
    claims: list[_RawEntry] = Field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]


class YamlClaimRegistryRepository:
    """Read, validate, and atomically replace one local claims.yml file."""

    def load(self, project_root: Path, registry_path: str) -> ClaimRegistry:
        root = _project_root(project_root, registry_path)
        path = _resolve_registry_path(root, registry_path, must_exist=False)
        if not path.exists():
            return ClaimRegistry()
        if not path.is_file():
            raise _error(registry_path, "", "registry path is not a file", "use a YAML file")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise _error(
                registry_path,
                "",
                f"registry exceeds {MAX_FILE_BYTES} bytes",
                "reduce the registry size",
            )
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeError as error:
            raise _error(
                registry_path,
                "",
                f"registry is not valid UTF-8: {error}",
                "save claims.yml as UTF-8",
            ) from error
        except OSError as error:
            raise _environment_error(
                registry_path, f"registry could not be read: {error}"
            ) from error
        try:
            loaded = load_single_yaml(text, exact_numbers=False)
        except yaml.YAMLError as error:
            raise _error(
                registry_path,
                "",
                f"invalid safe YAML: {error}",
                "fix YAML syntax and remove unsafe or duplicate keys",
            ) from error
        try:
            raw = _RawRegistry.model_validate(loaded)
        except ValidationError as error:
            first = error.errors(include_url=False)[0]
            field = ".".join(str(part) for part in first["loc"])
            raise _error(
                registry_path,
                field,
                first["msg"],
                "use only documented claims.yml fields and strict value types",
            ) from error
        if raw.schema_version != CLAIM_REGISTRY_SCHEMA_VERSION:
            raise _error(
                registry_path,
                "schema_version",
                f"unsupported schema version {raw.schema_version!r}",
                f"set schema_version to {CLAIM_REGISTRY_SCHEMA_VERSION!r}",
            )
        try:
            entries = tuple(
                sorted(
                    (_entry_from_raw(item) for item in raw.claims), key=lambda item: item.claim_id
                )
            )
            return ClaimRegistry(schema_version=raw.schema_version, entries=entries)
        except (ValueError, InvalidOperation) as error:
            raise _error(
                registry_path,
                "claims",
                str(error),
                "correct the invalid identity, link, status, tolerance, or duplicate Claim ID",
            ) from error

    def save(
        self,
        project_root: Path,
        registry_path: str,
        registry: ClaimRegistry,
    ) -> None:
        root = _project_root(project_root, registry_path)
        path = _resolve_registry_path(root, registry_path, must_exist=False)
        parent = path.parent
        if not parent.is_dir():
            raise _error(
                registry_path,
                "",
                "registry parent directory does not exist",
                "create the configured project-local parent directory",
            )
        payload = {
            "schema_version": registry.schema_version,
            "claims": [_entry_payload(entry) for entry in registry.entries],
        }
        text = yaml.safe_dump(
            payload,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
            width=100,
        )
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except OSError as error:
            if temporary is not None:
                with suppress(OSError):
                    temporary.unlink(missing_ok=True)
            raise _environment_error(
                registry_path,
                f"atomic registry write failed without replacing the prior file: {error}",
            ) from error


def _entry_from_raw(raw: _RawEntry) -> ClaimRegistryEntry:
    identity = _identity_from_raw(raw.identity)
    link = _link_from_raw(identity.claim_id, raw.link) if raw.link is not None else None
    ignore = (
        IgnoreRecord(reason=IgnoreReason(raw.ignore.reason), note=raw.ignore.note)
        if raw.ignore is not None
        else None
    )
    migration = (
        RegistryMigrationRecord(
            status=ClaimMigrationStatus(raw.migration.status),
            method=ClaimMigrationMethod(raw.migration.method),
            score=raw.migration.score,
            previous_path=raw.migration.previous_path,
            current_path=raw.migration.current_path,
            evidence=tuple(raw.migration.evidence),
            conflicts=tuple(raw.migration.conflicts),
        )
        if raw.migration is not None
        else None
    )
    return ClaimRegistryEntry(
        identity=identity,
        status=ClaimRegistryStatus(raw.status),
        link=link,
        ignore=ignore,
        note=raw.note,
        migration=migration,
    )


def _identity_from_raw(raw: _RawIdentity) -> ClaimIdentitySnapshot:
    location = SourceLocation(**raw.location.model_dump())
    context = ClaimContext(**raw.context.model_dump())
    fingerprint = ClaimFingerprint(
        version=raw.fingerprint.version,
        digest=raw.fingerprint.digest,
        path=raw.fingerprint.path,
        structural_anchor=raw.fingerprint.structural_anchor,
        context_digest=raw.fingerprint.context_digest,
        semantic_digest=raw.fingerprint.semantic_digest,
        components=tuple((item[0], item[1]) for item in raw.fingerprint.components),
    )
    return ClaimIdentitySnapshot(
        claim_id=StableClaimId(raw.claim_id),
        fingerprint=fingerprint,
        location=location,
        raw_text=raw.raw_text,
        kind=ClaimKind(raw.kind),
        disposition=ClaimDisposition(raw.disposition),
        context=context,
    )


def _link_from_raw(
    claim_id: StableClaimId,
    raw: _RawDirectLink | _RawDerivedLink,
) -> ClaimLink:
    if isinstance(raw, _RawDirectLink):
        return DirectLink(
            claim_id=claim_id,
            metric=_metric_from_raw(raw.metric),
            confirmed_fingerprint=raw.confirmed_fingerprint,
            tolerance_override=_tolerance_from_raw(raw.tolerance_override),
            note=raw.note,
        )
    return DerivedLink(
        claim_id=claim_id,
        operation=DerivedOperation(raw.operation),
        operands=tuple(
            DerivedOperand(name=operand.name, metric=_metric_from_raw(operand.metric))
            for operand in raw.operands
        ),
        output_unit=NumericUnit(raw.output_unit),
        output_scale=LinkScale(raw.output_scale),
        confirmed_fingerprint=raw.confirmed_fingerprint,
        rounding=RoundingPolicy(
            decimal_places=raw.rounding.decimal_places,
            mode=RoundingMode(raw.rounding.mode),
        ),
        standard_deviation_mode=(
            StandardDeviationMode(raw.standard_deviation_mode)
            if raw.standard_deviation_mode is not None
            else None
        ),
        tolerance_override=_tolerance_from_raw(raw.tolerance_override),
        note=raw.note,
    )


def _metric_from_raw(raw: _RawMetricReference) -> MetricReference:
    return MetricReference(
        source_file=raw.source_file,
        run_id=raw.run_id,
        metric_name=raw.metric_name,
        source_selector=raw.source_selector,
        scale=LinkScale(raw.scale),
    )


def _tolerance_from_raw(raw: _RawTolerance | None) -> NumericTolerance | None:
    if raw is None:
        return None
    return NumericTolerance(absolute=Decimal(raw.absolute), relative=Decimal(raw.relative))


def _entry_payload(entry: ClaimRegistryEntry) -> dict[str, object]:
    payload: dict[str, object] = {
        "identity": _identity_payload(entry.identity),
        "status": entry.status.value,
    }
    if entry.link is not None:
        payload["link"] = _link_payload(entry.link)
    if entry.ignore is not None:
        payload["ignore"] = {"reason": entry.ignore.reason.value, "note": entry.ignore.note}
    if entry.note:
        payload["note"] = entry.note
    if entry.migration is not None:
        payload["migration"] = {
            "status": entry.migration.status.value,
            "method": entry.migration.method.value,
            "score": entry.migration.score,
            "previous_path": entry.migration.previous_path,
            "current_path": entry.migration.current_path,
            "evidence": list(entry.migration.evidence),
            "conflicts": list(entry.migration.conflicts),
        }
    return payload


def _identity_payload(identity: ClaimIdentitySnapshot) -> dict[str, object]:
    return {
        "claim_id": identity.claim_id.value,
        "fingerprint": {
            "version": identity.fingerprint.version,
            "digest": identity.fingerprint.digest,
            "path": identity.fingerprint.path,
            "structural_anchor": identity.fingerprint.structural_anchor,
            "context_digest": identity.fingerprint.context_digest,
            "semantic_digest": identity.fingerprint.semantic_digest,
            "components": [list(item) for item in identity.fingerprint.components],
        },
        "location": {
            "path": identity.location.path,
            "selector": identity.location.selector,
            "line": identity.location.line,
            "column": identity.location.column,
            "end_line": identity.location.end_line,
            "end_column": identity.location.end_column,
            "char_start": identity.location.char_start,
            "char_end": identity.location.char_end,
        },
        "raw_text": identity.raw_text,
        "kind": identity.kind.value,
        "disposition": identity.disposition.value,
        "context": {
            "summary": identity.context.summary,
            "structural_anchor": identity.context.structural_anchor,
            "prefix_anchor": identity.context.prefix_anchor,
            "suffix_anchor": identity.context.suffix_anchor,
            "syntactic_context": identity.context.syntactic_context,
            "occurrence_ordinal": identity.context.occurrence_ordinal,
            "table_anchor": identity.context.table_anchor,
            "table_row": identity.context.table_row,
            "table_column": identity.context.table_column,
        },
    }


def _link_payload(link: ClaimLink) -> dict[str, object]:
    if isinstance(link, DirectLink):
        payload: dict[str, object] = {
            "type": "direct",
            "metric": _metric_payload(link.metric),
            "confirmed_fingerprint": link.confirmed_fingerprint,
        }
        if link.tolerance_override is not None:
            payload["tolerance_override"] = _tolerance_payload(link.tolerance_override)
        if link.note:
            payload["note"] = link.note
        return payload
    payload = {
        "type": "derived",
        "operation": link.operation.value,
        "operands": [
            {"name": operand.name, "metric": _metric_payload(operand.metric)}
            for operand in link.operands
        ],
        "output_unit": link.output_unit.value,
        "output_scale": link.output_scale.value,
        "confirmed_fingerprint": link.confirmed_fingerprint,
        "rounding": {
            "decimal_places": link.rounding.decimal_places,
            "mode": link.rounding.mode.value,
        },
    }
    if link.standard_deviation_mode is not None:
        payload["standard_deviation_mode"] = link.standard_deviation_mode.value
    if link.tolerance_override is not None:
        payload["tolerance_override"] = _tolerance_payload(link.tolerance_override)
    if link.note:
        payload["note"] = link.note
    return payload


def _metric_payload(metric: MetricReference) -> dict[str, object]:
    return {
        "source_file": metric.source_file,
        "run_id": metric.run_id,
        "metric_name": metric.metric_name,
        "source_selector": metric.source_selector,
        "scale": metric.scale.value,
    }


def _tolerance_payload(tolerance: NumericTolerance) -> dict[str, object]:
    return {"absolute": str(tolerance.absolute), "relative": str(tolerance.relative)}


def _project_root(project_root: Path, registry_path: str) -> Path:
    try:
        return project_root.resolve(strict=True)
    except OSError as error:
        raise _environment_error(registry_path, f"project root is unavailable: {error}") from error


def _resolve_registry_path(root: Path, value: str, *, must_exist: bool) -> Path:
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        not value.strip()
        or posix.is_absolute()
        or windows.is_absolute()
        or ".." in posix.parts
        or "\\" in value
        or posix.suffix.casefold() not in {".yml", ".yaml"}
    ):
        raise _error(
            value or "claims.yml",
            "",
            "registry path must be a project-relative POSIX .yml or .yaml path",
            "use a path such as .metricproof/claims.yml",
        )
    candidate = root.joinpath(*posix.parts)
    try:
        if candidate.exists() or candidate.is_symlink():
            resolved = candidate.resolve(strict=True)
            if not _is_within(resolved, root):
                raise _error(
                    value,
                    "",
                    "registry path escapes the project root through a link",
                    "store claims.yml inside the project root",
                )
        elif must_exist:
            raise _environment_error(value, "registry file does not exist")
        if candidate.parent.exists():
            parent = candidate.parent.resolve(strict=True)
            if not _is_within(parent, root):
                raise _error(
                    value,
                    "",
                    "registry parent escapes the project root through a link",
                    "store claims.yml inside the project root",
                )
    except OSError as error:
        raise _environment_error(value, f"registry path is unavailable: {error}") from error
    return candidate


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _error(file: str, field: str, reason: str, remediation: str) -> ClaimRegistryError:
    return ClaimRegistryError(
        file=file,
        field=field,
        reason=reason,
        remediation=remediation,
    )


def _environment_error(file: str, reason: str) -> ClaimRegistryError:
    return ClaimRegistryError(
        file=file,
        field="",
        reason=reason,
        remediation="check local path permissions and retry",
        exit_code=ExitCode.ENVIRONMENT_ERROR,
    )
