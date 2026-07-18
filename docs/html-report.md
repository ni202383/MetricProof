# Offline HTML report

`metricproof report` renders the same immutable `CheckResult` used by `metricproof check`. The report adapter does not reload inputs or repeat rule logic.

## Generate a report

```text
metricproof report --format html --output reports/metricproof.html --no-timestamp
metricproof report --format json --output reports/metricproof.json --no-timestamp
```

Output paths must be project-relative and remain inside the project after path and symlink resolution. Parent directories are created only within that boundary. The writer uses a same-directory temporary file, flush/fsync, and atomic replacement.

`--no-timestamp` omits generated time metadata and makes repeated output byte-stable for unchanged inputs. The report still records deterministic input facts such as project, scanned-file count, registry counts, rule execution summaries, and stable diagnostic IDs.

## Contents

The HTML report includes:

- summary counts by severity and registry state;
- one execution card for each selected rule, including zero-finding and skipped states;
- each finding's code, severity, confidence, location, and subject;
- observed and expected facts;
- evidence items and related source locations;
- uncertainty and remediation text;
- input/link diagnostics and rule limitations;
- a persistent notice that findings are consistency risks, not scientific verdicts.

Clear runs remain useful: the report explicitly shows zero findings and the execution status of every selected rule rather than producing an empty page.

## Offline and security contract

The generated HTML is a single UTF-8 file:

- all CSS is inline;
- no JavaScript or script element is emitted;
- no image, font, stylesheet, or other network resource is referenced;
- all project-controlled and diagnostic text is HTML-escaped;
- no raw LaTeX is interpreted by the browser;
- no input file is modified.

The report can be opened directly from disk in a modern browser. It does not require MetricProof, Python, a server, or network access after generation.

## Exit codes

Report writing and check status are separate facts. When a valid report contains findings meeting `--fail-on`, the file is written and the command exits `1`.

- `0`: report written; no selected rule met the threshold;
- `1`: report written; selected rule findings met the threshold;
- `2`: invalid CLI/configuration/output request;
- `3`: blocking input, parse, or link diagnostic.

The Demo intentionally returns `1`; this is not a report-generation failure.

## Schema relationship

HTML and JSON reports are projections of CheckResult schema version `2`. JSON is suitable for deterministic local tooling. HTML is for human review. Neither format adds or removes rule decisions, and neither format is a scientific audit certificate.

## Current limitations

- There is no Git evidence chain in the report.
- There is no SARIF, GitHub Actions integration, PDF/Word renderer, or Web service.
- Report files are local artifacts and are not uploaded or published by MetricProof.
- The embedded source snippets are evidence excerpts, not a full paper rendering.
