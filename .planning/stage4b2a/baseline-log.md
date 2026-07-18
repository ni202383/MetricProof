# Stage 4B2a pre-change baseline log

## Environment

- `python --version`: Python 3.13.9.
- Initial Git status: clean on `main...origin/main`.

## Test gate

- First `python -m pytest` attempt failed during fixture setup because pytest's
  default `C:\Users\HUAWEI\AppData\Local\Temp\pytest-of-HUAWEI` directory is
  inaccessible inside the restricted Windows sandbox.
- No repository assertion failure was observed in that attempt.
- Rerun with controlled `--basetemp C:\tmp\metricproof-stage4b2a-baseline`:
  220 passed, 2 skipped in 4.21 seconds.
- The two skips are the existing Windows symlink-capability skips.
- Coverage rerun with controlled basetemp: 220 passed, 2 skipped; total branch
  coverage 90.07%, satisfying the configured 90% threshold.

## Pending baseline commands

- Ruff lint
- Ruff format check
- Pyright strict
- compileall
- build

