# Telemetry Context Epic

**Status**: 📋 PLANNED
**Goal**: Ensure analyzer telemetry always carries repository, branch, actor, and run context.

## Overview
Telemetry payloads today gather git context from `GITHUB_*` environment variables, but local runs and self-hosted runners often leave these fields empty. Missing branch and actor makes it impossible to correlate findings with the developer or pipeline that produced them, undermining trend analysis and incident triage. This epic hardens context collection so telemetry is useful regardless of where `fab-test` runs.

---

## Collect Branch and Actor Locally ✅

Use local git configuration as a fallback when GitHub Actions environment variables are absent.

**Requirements**:
- Given `fab-test` runs outside of GitHub Actions, then the telemetry payload still includes the current branch from `git rev-parse --abbrev-ref HEAD`.
- Given the local git user email is configured, then the telemetry payload includes it as the actor when `GITHUB_ACTOR` is not set.
- Given `git` is not available or the command fails, then telemetry still sends with empty context fields rather than crashing.

---

## Distinguish Local vs Pipeline Origin ✅

Add an explicit `origin` field to telemetry so dashboards can filter by run environment.

**Requirements**:
- Given `GITHUB_ACTIONS` is set, then the telemetry payload sets `origin` to `github-actions`.
- Given `GITLAB_CI`, `CIRCLECI`, or `AZURE_DEVOPS` is set, then `origin` reflects the matching CI system.
- Given no known CI environment variables are present, then `origin` is set to `local`.

---

## Capture Machine Context ✅

Include enough non-sensitive machine context to diagnose environment-specific failures.

**Requirements**:
- Given telemetry is enabled, then each payload includes `platform` (e.g., `win32`, `linux`), `python_version`, and `fab-test` version.
- Given the OS platform cannot be determined, then the field is omitted rather than causing a send failure.
- Given personally identifiable information would be included, then it is redacted before transmission.

---

## Validate Telemetry Payload Schema ✅

Reject malformed payloads before transmission so incomplete records don't corrupt downstream analytics.

**Requirements**:
- Given a telemetry payload is built, then required fields (`analyzer`, `artifact_name`, `status`, `timestamp`) are validated before sending.
- Given a required field is missing, then telemetry logs a warning and skips the record without failing the analyzer run.
- Given an optional field is present but malformed, then it is dropped and the rest of the payload is still sent.

---

## Add Telemetry Dry-Run Inspection ✅

Let users preview what telemetry would send without actually transmitting it.

**Requirements**:
- Given `fab-test <subcommand> --telemetry --dry-run`, then the telemetry payload is printed to stdout instead of being sent.
- Given `fab-test <subcommand> --telemetry` with `ENABLE_EVENTHOUSE_LOGGING=true`, then the payload is sent as it is today.
- Given `--no-telemetry` is set, then no payload is built or printed even with `--dry-run`.

---

## Regression Tests for Telemetry Context

Cover local, CI, and missing-git scenarios with unit tests that do not require a real Eventhouse endpoint.

**Requirements**:
- Given a mocked local git environment, then `_git_context()` returns the branch and actor from git commands.
- Given GitHub Actions environment variables are set, then `_git_context()` prefers those values over local git output.
- Given telemetry sending fails with a network error, then the analyzer run still exits with its own status code.
