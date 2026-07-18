# MetricProof Stage 4B2a Plan

## Goal

Use deterministic, explainable heuristics to classify every existing
`RawNumericCandidate` as an experimental Claim candidate, expose the results
through the application service and `metricproof scan`, and verify the complete
Python 3.13 quality baseline without implementing persistent Claim identity,
links, checks, reports, remote features, or AI.

## Phase Gates

| Phase | Status | Objective | Expected completion state | Verification | Minimum meaningful cases |
|---|---|---|---|---|---:|
| 0. Recover and scope | complete | Load the attached objective, recover prior planning state, and preserve existing work | Clean worktree; Stage 4B2a has its own plan; prohibited scope recorded | Goal objective read as UTF-8; Git and planning state inspected | 13 completion criteria audited |
| 1. Baseline and architecture audit | complete | Read required files and establish the pre-change baseline | Interfaces, constraints, extension points, and baseline results documented | Python, pytest, coverage, Ruff, format, Pyright, build, inspection | Existing full suite plus static/build gates |
| 2. Classification model and rule design | complete | Define deterministic models, thresholds, evidence, ordering, and configuration use | Design covers required semantics within dependency boundaries | Focused tests, type checks, design review | 200 table-driven rule/model cases where feasible |
| 3. Core classification implementation | complete | Implement pure classification and application orchestration | One explainable result per candidate; deterministic, immutable, near-linear | Unit/integration/generated tests | 200 meaningful classification cases |
| 4. CLI and JSON integration | complete | Extend scan output and versioned JSON compatibly | Summary, show modes, JSON, help, and exit codes usable | CLI and schema tests | Existing matrix plus targeted combinations |
| 5. Edge cases and performance gate | complete | Close high-risk semantic and scaling gaps | Edge cases pass without rereads or quadratic behavior | Regressions and thousands-candidate run | 1000 generated final cases where feasible |
| 6. Documentation and status | complete | Update only directly relevant documentation | Docs match interfaces, limitations, schema, and status | Cross-document and command audit | All affected commands/interfaces |
| 7. Full validation and completion audit | complete | Run every specified command and audit all completion criteria | All gates pass truthfully; boundaries recorded; no prohibited features | Full quality/CLI/temp-project/Git verification | Full suite plus 1000 generated cases where feasible |

## Boundaries

- Keep `CLI -> application -> domain`; adapters implement application ports.
- Consume existing domain objects and validated configuration without rereading
  or reparsing files.
- No network, AI, NLP models, embeddings, databases, services, plugins, or
  arbitrary code execution.
- Do not implement stable Claim IDs, context fingerprints, migration,
  `claims.yml`, interaction records, Claim-to-Metric matching, `DerivedLink`,
  checks, HTML reports, Git evidence, or paper rewriting.
- Treat classifications as reviewable heuristics, not confirmed errors or
  scientific conclusions.

## Verification discipline

- Do not advance a phase with a known gate failure.
- Log failures and add focused regression coverage for repository defects.
- Meet volume targets with meaningful table-driven, generated, or existing
  cases, not repetitive low-value fixtures.
- Reread this plan and `findings.md` before major design decisions.

## Errors encountered

| Error | Attempt | Resolution |
|---|---:|---|
| Initial objective output was mojibake | 1 | Re-read explicitly as UTF-8 |
| Placeholder goal already existed | 1 | Completed it and created the Stage 4B2a goal |
| Combined planning patch could not initialize Windows restricted-token sandbox | 1 | Retried as a narrower add-only patch |

