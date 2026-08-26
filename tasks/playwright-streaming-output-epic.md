# Playwright Streaming Output Epic

**Status**: ✅ COMPLETED
**Goal**: A long-running `fab-test playwright` invocation never looks hung, and a
default (non-verbose) run stays terse instead of dumping a full pytest -v transcript.

## Overview

`_run_pytest` used to buffer the pytest subprocess's output entirely and only
print it after the child exited, and only when `--verbose` was passed. Each
Playwright case can take up to a minute in a real browser, so a caller with no
`--verbose` flag saw nothing at all until the whole run finished -- indistinguishable
from a hang. `_stream_subprocess` (commit `ff78deb`) fixed the silent case by
streaming every line as it arrived, but did so unconditionally, which traded
"looks hung" for "floods every default run with the full pytest -v transcript."

---

## Stream subprocess output without an assert that ruff's S101 forbids

`_stream_subprocess` narrowed `proc.stdout is not None` with a bare `assert`,
which is banned by the project's `S101` lint rule outside `tests/**` and is
stripped entirely under `python -O`.

**Requirements**:
- Given `Popen(..., stdout=PIPE)` unexpectedly returns a process with no
  `stdout` stream, should raise a `RuntimeError` naming the cause instead of
  relying on an `assert`

## Keep default output terse while still showing progress

**Requirements**:
- Given `verbose=True`, should log every line of subprocess output as it
  arrives, unchanged from the streaming behavior introduced in `ff78deb`
- Given `verbose` left at its default (`False`), should log only pytest's
  per-test outcome lines (`PASSED`/`FAILED`/`ERROR`/`SKIPPED`/`XFAIL`/`XPASS`)
  and suppress setup/collection noise, so a caller still sees progress without
  the full pytest -v transcript on every default run
