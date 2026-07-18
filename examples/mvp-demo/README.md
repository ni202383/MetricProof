# MetricProof MVP demo

This fully fictional local project exercises the Stage 5 loop without executing
LaTeX or user code. It contains six current Claims:

- consistent baseline accuracy `70.0\%` linked to fraction `0.70`;
- stale proposed accuracy `80.0\%` linked to `0.90`;
- wrong displayed gain `25.0` linked to a `20.0` percentage-point subtraction;
- consistent F1 `0.750` linked to `0.75`;
- recall `60.0\%` intentionally left unlinked;
- timeout `10.0` explicitly ignored as a run setting, not a result.

From this directory run:

```text
metricproof experiments validate
metricproof scan --show-claims
metricproof link --non-interactive --json
metricproof check
metricproof check --json
```

The link suggestion command and both check renderers are read-only. `check`
intentionally exits `1` with one `STALE_VALUE`, one `WRONG_DELTA`, and one
`MISSING_PROVENANCE`; the consistent and ignored cases remain quiet. The checked-in
`.metricproof/claims.yml` makes the result immediately reproducible. Use a copy of
this directory for interactive `metricproof link` experiments if you want to alter
the registry.