# Stage 4B2a CLI and configuration audit

- `metricproof scan` currently accepts `--json`, `--show-all`,
  `--show-tables`, and `--file`. Default filtering is syntactic-context based,
  hiding command arguments and unknown candidates.
- The objective changes the primary human display semantics: the default summary
  must include classification counts; `--show-claims` should show likely and
  possible classifications; `--show-all` may include ambiguous,
  non-experiment, and existing raw-debug information.
- Current JSON schema version is `2`, with raw candidates and tables. Stage
  4B2a needs an explicit new version while retaining raw candidates and adding
  classification references and evidence.
- The CLI already has a single `_load_paper_scan` composition path. It should
  call an application classifier after scanning and pass both results to
  renderers, without moving rules into CLI code.
- Current `_scan_payload` receives a display-filtered candidate tuple. The new
  schema should preserve all raw candidates independent of human display
  filters, or otherwise document exact compatibility; classification references
  must not depend on omitted candidates.
- The raw Pydantic config already accepts `metric_aliases`, but
  `YamlConfigurationRepository.load` currently discards that field when
  constructing adapter-neutral `ProjectConfiguration`.
- A minimal, strictly validated application configuration extension can carry
  normalized metric aliases. Unknown fields remain forbidden by the existing
  strict Pydantic model.
- Built-in classification weights and thresholds should remain code-owned.
  Configuration should extend recognized metric terms only, not expose a
  user-programmable rule/weight system.
- `PaperScanner` remains the only I/O port needed for scan; the classification
  service can be a pure application/domain function and needs no new filesystem
  port.

