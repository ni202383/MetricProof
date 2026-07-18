# Stage 4B2a final audit

## Verified results

- Python 3.13.9.
- Final plain suite: 247 passed, 2 existing Windows symlink skips.
- Final branch coverage: 90.26%, above the configured 90% threshold.
- Ruff lint and format check passed.
- Pyright strict passed with 0 errors, 0 warnings, 0 informations.
- compileall, isolated build, and `git diff --check` passed.
- Temporary acceptance project:
  - 15 raw candidates and 15 classifications;
  - 8 likely, 5 possible, 0 ambiguous, 2 non-experiment;
  - 1 parsed and 1 degraded table;
  - 1 non-blocking multirow limitation;
  - schema version 3;
  - scan, show-claims, show-all, JSON, doctor, experiments validate, and module
    help exited successfully.
- The focused 2,000-candidate generated classification call completed in about
  0.07 seconds on this machine and classified every candidate exactly once.

## Completion criteria audit

1. Pre-change Python 3.13 baseline passed after controlled-temp reruns.
2. Every raw candidate receives exactly one classification.
3. Results contain disposition, kind, score, confidence, review recommendation,
   and evidence.
4. Explicit reference, layout, structure, URL/version/date/year, and color
   contexts are excluded or strongly downgraded.
5. Epoch, batch size, seed, run count, and related quantities remain
   experiment quantities rather than direct performance results.
6. Parsed, degraded, and unsupported tables have different evidence semantics.
7. Mean ± std remains one compound summary-statistic candidate.
8. Classification is deterministic, stable, immutable, and uses one table
   indexing pass.
9. Human scan views and schema 3 JSON are usable.
10. Tests, coverage, Ruff, Pyright, compile, and build pass.
11. Documentation states heuristic limitations and reviewability.
12. No stable ID, claims.yml, link, DerivedLink, or consistency rule was added.
13. No network, remote resource, commit, push, release, or destructive action
    was performed.

## Known heuristic boundaries

- Bounded context can occasionally carry a nearby sentence's vocabulary into a
  candidate score.
- Complex table structure numbers such as a multirow span can remain possible
  when nearby metric text is strong.
- Unsupported and degraded structures are downgraded but cannot fully recover
  formal header semantics.
- Rare metric names require explicit `metric_aliases`.
- `LIKELY` is not confirmation of a paper conclusion, and `NON_EXPERIMENT` can
  still be wrong for unusual notation.

