"""Deterministic JSON and single-file offline HTML rendering for CheckResult."""
# ruff: noqa: E501 -- inline offline HTML/CSS is intentionally kept literal and auditable.

from __future__ import annotations

import html
import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path, PureWindowsPath
from tempfile import NamedTemporaryFile

from metricproof.domain.diagnostics import CheckDiagnostic, CheckResult, RuleExecutionSummary
from metricproof.domain.models import Evidence, ScalarValue, SourceLocation

REPORT_FORMATS = frozenset({"html", "json"})
RULE_DESCRIPTIONS = {
    "MISSING_PROVENANCE": "Experimental Claim candidates without a confirmed local source or ignore decision.",
    "STALE_VALUE": "Confirmed direct links whose current local metric no longer matches the displayed value.",
    "UNFAIR_COMPARISON": "User-declared controlled configuration fields that differ between two runs.",
    "WRONG_BEST_MARK": "Best and second-best table formatting under explicit column semantics.",
    "WRONG_DELTA": "Confirmed derived Claims whose displayed value differs from deterministic recomputation.",
}


def check_result_payload(result: CheckResult) -> dict[str, object]:
    return {
        "schema_version": result.schema_version,
        "command": "check",
        "tool_version": result.tool_version,
        "project": result.project,
        "summary": {
            "checked_claim_count": result.summary.checked_claim_count,
            "scanned_file_count": result.summary.scanned_file_count,
            "registry": dict(result.summary.registry_counts),
            "migrations": dict(result.summary.migration_counts),
            "diagnostics_by_code": dict(result.summary.diagnostic_counts),
            "diagnostics_by_severity": dict(result.summary.severity_counts),
            "diagnostic_count": len(result.diagnostics),
            "rules": [
                {
                    "code": item.code,
                    "status": item.status,
                    "diagnostic_count": item.finding_count,
                    "diagnostics_by_severity": {
                        "info": item.info_count,
                        "warning": item.warning_count,
                        "error": item.error_count,
                    },
                    "limitation_count": item.limitation_count,
                    "skip_reason": item.reason or None,
                }
                for item in result.summary.rule_summaries
            ],
        },
        "diagnostics": [_diagnostic_payload(item) for item in result.diagnostics],
    }


def render_json_report(result: CheckResult, *, generated_at: str | None) -> str:
    payload = check_result_payload(result)
    payload["command"] = "report"
    payload["generated_at"] = generated_at
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_html_report(result: CheckResult, *, generated_at: str | None) -> str:
    registry = dict(result.summary.registry_counts)
    severity = dict(result.summary.severity_counts)
    generated = generated_at or "omitted for deterministic output"
    overall = "REVIEW" if result.diagnostics else "CLEAR"
    cards = "".join(_rule_card(item) for item in result.summary.rule_summaries)
    diagnostics = "".join(_diagnostic_html(item) for item in result.diagnostics)
    if not diagnostics:
        diagnostics = '<p class="empty">No diagnostics were produced.</p>'
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MetricProof report - {_h(result.project)}</title>
<style>
:root{{--ink:#18211f;--muted:#61706b;--paper:#f4f1e9;--card:#fffdf7;--line:#d9d4c8;--accent:#0d766e;--warn:#b66a16;--error:#b13a3a;}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1180px;margin:auto;padding:40px 24px 72px}} header{{display:flex;justify-content:space-between;gap:24px;align-items:flex-end;border-bottom:2px solid var(--ink);padding-bottom:22px}}
h1{{font-size:44px;line-height:1;margin:0;letter-spacing:-.04em}} .eyebrow{{color:var(--accent);font-weight:800;letter-spacing:.12em;text-transform:uppercase}} .meta{{text-align:right;color:var(--muted)}}
.notice{{margin:24px 0;padding:14px 18px;border-left:4px solid var(--accent);background:#e7f1ed}} .stats,.rules{{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:12px;margin:24px 0}}
.stat,.rule,.diagnostic{{background:var(--card);border:1px solid var(--line);border-radius:12px;box-shadow:0 8px 24px #18211f0a}} .stat{{padding:18px}} .stat strong{{display:block;font-size:27px}} .stat span,.small{{color:var(--muted);font-size:13px}}
h2{{margin-top:40px;font-size:25px}} .rule{{padding:16px;border-top:4px solid var(--accent)}} .rule h3{{font-size:14px;margin:0 0 6px}} .pill{{display:inline-block;border-radius:999px;padding:2px 8px;background:#e7f1ed;font-size:12px;font-weight:700}}
.diagnostic{{margin:14px 0;overflow:hidden}} .diag-head{{display:flex;gap:12px;align-items:center;padding:14px 16px;border-bottom:1px solid var(--line)}} .diag-head code{{font-weight:800}} .severity-error{{color:var(--error)}} .severity-warning{{color:var(--warn)}} .diag-body{{padding:16px}}
.compare{{display:grid;grid-template-columns:1fr 1fr;gap:12px}} .value{{padding:12px;background:#f1eee5;border-radius:8px;overflow-wrap:anywhere}} dl{{display:grid;grid-template-columns:130px 1fr;gap:7px 14px}} dt{{font-weight:700}} dd{{margin:0;overflow-wrap:anywhere}} details{{margin-top:12px}} summary{{cursor:pointer;font-weight:700}} code{{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}} footer{{margin-top:48px;color:var(--muted);border-top:1px solid var(--line);padding-top:18px}}
@media(max-width:680px){{header{{display:block}}.meta{{text-align:left;margin-top:14px}}h1{{font-size:34px}}.compare{{grid-template-columns:1fr}}dl{{grid-template-columns:1fr}}}}
</style>
</head>
<body><main>
<header><div><div class="eyebrow">Local evidence review</div><h1>MetricProof</h1></div><div class="meta"><strong>{_h(result.project)}</strong><br>v{_h(result.tool_version)} | {_h(generated)}</div></header>
<div class="notice"><strong>{overall}</strong> - Diagnostics are representation-consistency checks and heuristic risks. They are not scientific conclusions or research-integrity judgments.</div>
<section class="stats">
{_stat("Files scanned", result.summary.scanned_file_count)}{_stat("Claims", result.summary.checked_claim_count)}{_stat("Active links", registry.get("active", 0))}{_stat("Ignored", registry.get("ignored", 0))}{_stat("Warnings", severity.get("warning", 0))}{_stat("Errors", severity.get("error", 0))}
</section>
<h2>Five-rule overview</h2><section class="rules">{cards}</section>
<h2>Diagnostics and evidence</h2><section>{diagnostics}</section>
<footer>Generated entirely from one MetricProof CheckResult. This file contains inline CSS, no external assets, no network requests, and remains readable without JavaScript.</footer>
</main></body></html>"""


def write_report(
    project_root: Path,
    output: str,
    report_format: str,
    result: CheckResult,
    *,
    no_timestamp: bool,
) -> Path:
    if report_format not in REPORT_FORMATS:
        raise ValueError(f"unsupported report format: {report_format}")
    destination = _safe_output(project_root, output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    generated_at = None if no_timestamp else datetime.now(UTC).replace(microsecond=0).isoformat()
    content = (
        render_html_report(result, generated_at=generated_at)
        if report_format == "html"
        else render_json_report(result, generated_at=generated_at)
    )
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return destination


def _safe_output(project_root: Path, output: str) -> Path:
    windows = PureWindowsPath(output)
    candidate = Path(output)
    if (
        not output.strip()
        or candidate.is_absolute()
        or windows.is_absolute()
        or ".." in candidate.parts
    ):
        raise ValueError("report output must be a non-empty project-relative path")
    root = project_root.resolve(strict=True)
    destination = (root / candidate).resolve(strict=False)
    try:
        destination.relative_to(root)
    except ValueError as error:
        raise ValueError("report output escapes the project root") from error
    return destination


def _stat(label: str, value: object) -> str:
    return f'<div class="stat"><strong>{_h(value)}</strong><span>{_h(label)}</span></div>'


def _rule_card(item: RuleExecutionSummary) -> str:
    description = RULE_DESCRIPTIONS.get(item.code, "Configured local consistency rule.")
    detail = item.reason or (
        f"{item.error_count} error(s), {item.warning_count} warning(s), "
        f"{item.info_count} info, {item.limitation_count} limitation(s)"
    )
    return f'<article class="rule"><span class="pill">{_h(item.status)}</span><h3>{_h(item.code)}</h3><p>{_h(description)}</p><div class="small">{_h(detail)}</div></article>'


def _diagnostic_html(item: CheckDiagnostic) -> str:
    evidence = "".join(_evidence_html(value) for value in item.evidence)
    uncertainties = "".join(f"<li>{_h(value)}</li>" for value in item.uncertainties)
    subject = item.subject_id or item.claim_id or "unavailable"
    chain = _evidence_chain(item)
    return f'''<article class="diagnostic" data-rule="{_h(item.code)}" data-severity="{_h(item.severity.value)}" data-file="{_h(item.location.path)}">
<div class="diag-head"><span class="pill severity-{_h(item.severity.value)}">{_h(item.severity.value)}</span><code>{_h(item.code)}</code><span class="small">{_h(subject)}</span></div>
<div class="diag-body"><p><strong>{_h(item.message)}</strong></p><div class="compare"><div class="value"><span class="small">Observed</span><br>{_h(_scalar(item.observed))}</div><div class="value"><span class="small">Expected</span><br>{_h(_scalar(item.expected))}</div></div>
<dl><dt>Location</dt><dd><code>{_h(item.location.display)}</code></dd><dt>Confidence</dt><dd>{_h(item.confidence)}</dd><dt>Remediation</dt><dd>{_h(item.remediation)}</dd></dl>
<details open><summary>Evidence</summary>{evidence or "<p>unavailable</p>"}</details>
<details><summary>Evidence chain</summary>{chain}</details>
{f"<details><summary>Uncertainty</summary><ul>{uncertainties}</ul></details>" if uncertainties else ""}</div></article>'''


def _evidence_html(item: Evidence) -> str:
    details = "".join(f"<li><code>{_h(value)}</code></li>" for value in item.details)
    location = item.location.display if item.location is not None else "unavailable"
    return f'<div class="value"><strong>{_h(item.kind)}</strong> - {_h(item.summary)}<br><span class="small">{_h(location)}</span>{f"<ul>{details}</ul>" if details else ""}</div>'


def _evidence_chain(item: CheckDiagnostic) -> str:
    steps = [
        item.location.display,
        item.claim_id or item.subject_id or "Stable Claim unavailable",
        "claims.yml link unavailable"
        if item.claim_id is None
        else "claims.yml decision represented",
        *(evidence.summary for evidence in item.evidence),
    ]
    return "<ol>" + "".join(f"<li>{_h(step)}</li>" for step in steps) + "</ol>"


def _diagnostic_payload(item: CheckDiagnostic) -> dict[str, object]:
    return {
        "diagnostic_id": item.diagnostic_id,
        "kind": item.kind.value,
        "code": item.code,
        "severity": item.severity.value,
        "message": item.message,
        "claim_id": item.claim_id,
        "subject_id": item.subject_id,
        "location": _location_payload(item.location),
        "observed": _json_scalar(item.observed),
        "expected": _json_scalar(item.expected),
        "confidence": str(item.confidence),
        "evidence": [_evidence_payload(value) for value in item.evidence],
        "related_sources": [_location_payload(value) for value in item.related_sources],
        "remediation": item.remediation,
        "uncertainties": list(item.uncertainties),
    }


def _evidence_payload(item: Evidence) -> dict[str, object]:
    return {
        "evidence_id": item.evidence_id,
        "kind": item.kind,
        "summary": item.summary,
        "location": _location_payload(item.location) if item.location else None,
        "details": list(item.details),
    }


def _location_payload(item: SourceLocation) -> dict[str, object]:
    return {
        "path": item.path,
        "selector": item.selector,
        "line": item.line,
        "column": item.column,
        "end_line": item.end_line,
        "end_column": item.end_column,
        "char_start": item.char_start,
        "char_end": item.char_end,
        "display": item.display,
    }


def _json_scalar(value: ScalarValue) -> ScalarValue:
    return str(value) if isinstance(value, Decimal) else value


def _scalar(value: ScalarValue) -> str:
    return "unavailable" if value is None else str(value)


def _h(value: object) -> str:
    return html.escape(str(value), quote=True)
