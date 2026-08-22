# CLI Global Options Epic

**Status**: ✅ COMPLETED
**Goal**: Add `--help` and `--version` global options to the `fab-test` CLI for a polished, discoverable user experience.

## Overview

Users and CI pipelines need a quick way to discover what `fab-test` can do and which version is installed. Adding standard `--help` and `--version` global flags makes the CLI self-documenting, reduces onboarding friction, and aligns the tool with common POSIX/Unix conventions.

---

## Enhance `--help` output

> **Overcome by events**: argparse already provides `-h`/`--help` for the top-level parser and every subcommand, and [tests/test_fab_test.py](tests/test_fab_test.py) already covers exit codes, subcommand listing, and the pytest distinction.
>
> Remaining work is a small polish task, not a full implementation.

Ensure the top-level `fab-test --help` output includes the current version string and a link to documentation, and verify per-subcommand help remains accurate as flags evolve.

**Requirements**:
- Given a user runs `fab-test --help`, then the help message already lists all subcommands and global flags.
- Given a user runs `fab-test <subcommand> --help`, then help specific to that subcommand is already printed.
- Given the help output, then it should include the version string and a link to documentation.

---

## Implement `--version` global option

Add a top-level `--version` flag that prints the current `fab-test` version and exits with code `0`. The version should be sourced from the single source of truth (`__init__.py` or `pyproject.toml`).

**Requirements**:
- Given a user runs `fab-test --version`, then the output should print `fab-test <version>` and exit `0`.
- Given a user runs `fab-test -V`, then it should behave the same as `--version` if the short flag does not conflict with existing options.
- Given the version is updated in one location, then the CLI should reflect that change without manual duplication.

---

## Add tests for `--version`

Write tests that exercise the new `--version` option and guard against regressions. `--help` tests already exist in [tests/test_fab_test.py](tests/test_fab_test.py).

**Requirements**:
- Given `fab-test --version` is executed, then a test should assert the exit code is `0` and the output contains the expected version.
- Given `fab-test -V` is executed, then a test should assert it behaves identically to `--version`.
- Given `fab-test --version` is executed after a version bump, then the test should still pass using the single source of truth.
