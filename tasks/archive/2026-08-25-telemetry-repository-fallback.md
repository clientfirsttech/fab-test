# Telemetry Repository Fallback Epic

**Status**: ✅ COMPLETED (2026-08-25)
**Goal**: `repository` in the telemetry payload resolves locally, the same way `branch`, `commit`, and `actor` already do.

## Overview

The [Telemetry Context](archive/2026-08-18-telemetry-context-epic.md) epic gave
`branch`, `commit`, and `actor` a local-git fallback so telemetry stays useful
outside GitHub Actions, but `repository` was left out of that fallback — it is
read only from `GITHUB_REPOSITORY` in [`_git_context.py`](../src/fabric_ci_cd_dataops/scripts/_git_context.py).
A local run or a self-hosted runner without that env var set ships every
telemetry record with `repository: ""`, even though the same `.git` checkout
that already supplies `commit`/`branch`/`actor` also has an `origin` remote
naming the repository. Nothing else in the payload correlates a record back
to which project it came from once `repository` is empty.

---

## Resolve `repository` From The Local Git Remote

**Requirements**:
- Given `fab-test` runs outside GitHub Actions with an `origin` remote configured, should record `repository` as `owner/repo` parsed from that remote's URL
- Given `GITHUB_REPOSITORY` is set, should prefer it over the local remote — the existing precedence every other field in `git_context()` already follows
- Given an HTTPS remote (`https://github.com/kerski/fab-test.git`) or an SSH remote (`git@github.com:kerski/fab-test.git`), should parse `owner/repo` from either form
- Given no `origin` remote, or `git` unavailable, or the URL does not parse, should record `repository` as `""` rather than raise — the same silent-empty contract every other field in `git_context()` already keeps
