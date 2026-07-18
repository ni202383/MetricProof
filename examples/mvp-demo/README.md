# MetricProof five-rule Demo

This fully fictional, read-only-input project exercises the complete local workflow without executing LaTeX, experiment code, or user expressions.

It contains 12 current numeric Claims and checked-in review decisions: 10 active links, one explicit ignore decision, and one intentionally unlinked Claim. Its three runs use separate local result and configuration files. The labeled table declares one higher-is-better and one lower-is-better metric, so the same run must be bold in both columns.

Run from this directory:

```text
metricproof experiments validate
metricproof scan --show-claims
metricproof link --non-interactive --json
metricproof check
metricproof check --json
metricproof report --format html --output metricproof-report.html --no-timestamp
```

Or use `./run-demo.sh` / `.\run-demo.ps1`. These scripts validate the expected code `1`, continue long enough to create the report, and finally return `1`; they do not mask findings.

Expected stable rule findings:

- `STALE_VALUE`: one displayed `80.0%` is linked to `0.90`.
- `WRONG_DELTA`: one displayed `25.0` differs from a `20.0` percentage-point subtraction.
- `MISSING_PROVENANCE`: one recall Claim has no link or ignore decision.
- `WRONG_BEST_MARK`: the ablation row is incorrectly bold for accuracy and underlined for error rate.
- `UNFAIR_COMPARISON`: `dataset.split` and `training.epochs` differ; `method.name` is quiet because the difference is explicitly allowed with a reason.

Consistent direct links, correct best marks, the declared method-name difference, and the ignored run-setting value remain quiet. Both `check` and `report` intentionally exit `1` because error-level findings meet the configured threshold. Terminal, JSON, and HTML are renderings of the same deterministic `CheckResult`.

`metricproof-report.html` is a generated artifact and can be deleted/recreated. The report is a single offline file with inline CSS, no JavaScript, and no external resources.