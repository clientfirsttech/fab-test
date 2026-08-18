# CLI Quality Backlog Epic

**Status**: 📋 PLANNED
**Goal**: Harden `fab-test` into a predictable, fast, and CI-friendly CLI.

## Overview
Users rely on `fab-test` inside CI pipelines and local dev loops. As the analyzer surface grows, small usability gaps (unclear exit codes, missing validation, unbounded timeouts, no cache control) compound into friction. This epic bundles focused, non-breaking improvements that make the CLI more reliable, observable, and operable without changing existing analyzer contracts.

---

## Document Exit-Code Contract ✅

Define and surface explicit exit codes so CI pipelines can branch on the failure reason.

**Requirements**:
- Given `fab-test --help` is run, then the help epilog lists every exit code and its meaning.
- Given a platform-only analyzer runs on an unsupported OS, then the process exits with code `126` and prints the supported platform.
- Given an analyzer finds rule violations, then the process exits with code `1` while warnings remain non-fatal.
- Given invalid CLI arguments, then the process exits with code `2` before invoking any analyzer.

---

## Fail Fast on Unsupported Platforms ✅

Move platform checks into preflight so Windows-only analyzers stop cleanly before downloading or invoking binaries.

**Requirements**:
- Given `fab-test bpa` runs on Linux or macOS, then it exits with a clear "not supported on this platform" message before Tabular Editor resolution starts.
- Given `fab-test pbir` runs on a supported platform, then resolution proceeds exactly as it does today.
- Given the preflight failure, then the output points the user to `env_var` override documentation.

---

## Validate CLI Inputs Up Front ✅

Catch malformed arguments before spawning subprocesses or touching artifacts.

**Requirements**:
- Given `--workspace-id abc`, then the CLI rejects it because it is not a GUID.
- Given `--artifact-dir /missing/path`, then the CLI exits early with a message that the directory does not exist.
- Given `--format yaml`, then the CLI exits early with the allowed format list.

---

## Verify Downloaded Tool Archives ✅

Protect the tool bootstrap flow from corrupted or tampered downloads by validating checksums declared in the registry.

**Requirements**:
- Given `analyzers.json` declares `install_sha256` for the current platform, then `_analyzer_tool_bootstrap.py` verifies the digest after download and before extraction.
- Given the digest does not match, then the download is removed and a clear `RuntimeError` is raised.
- Given no `install_sha256` is declared, then the existing download-and-extract behavior is preserved.

---

## Configurable Subprocess Timeout ✅

Make the per-artifact timeout user-tunable instead of hard-coded at 120 seconds.

**Requirements**:
- Given `--timeout 300`, then long-running analyzers are allowed up to 300 seconds.
- Given no `--timeout`, then the default remains 120 seconds.
- Given `ANALYZER_TIMEOUT` is set in the environment, then it overrides the default but not the CLI flag.

---

## Parallelize Per-Artifact Runs ✅

Allow independent artifact validations to run concurrently and reduce total wall-clock time.

**Requirements**:
- Given `--jobs 4`, then up to four artifacts for the same analyzer run in parallel.
- Given `--jobs 1` or no flag, then artifacts run sequentially exactly as they do today.
- Given parallel execution, then each artifact still writes its own `envelope.json` and the aggregate summary waits for all tasks.

---

## Add Configuration File Support ✅

Let teams commit per-project defaults in `pyproject.toml` instead of relying solely on env vars.

**Requirements**:
- Given a `[tool.fab-test]` section in `pyproject.toml`, then its values are loaded as defaults for matching flags.
- Given both a config file and a CLI flag, then the CLI flag takes precedence.
- Given `FABRIC_ENVIRONMENT` is set, then it still overrides the config file default.

---

## Add Tool-Cache Management Command

Give users a first-class way to inspect and clear the `.fab-test-tools` cache.

**Requirements**:
- Given `fab-test clean-tools`, then the `.fab-test-tools` directory is removed and a confirmation message is printed.
- Given `fab-test clean-tools --dry-run`, then the command lists what would be deleted without deleting it.
- Given the cache does not exist, then the command exits cleanly with a "nothing to clean" message.

---

## Generate Shell Completions

Reduce typos and speed up artifact selection with tab completion.

**Requirements**:
- Given `fab-test --print-completion bash`, then a bash completion script is written to stdout.
- Given `fab-test --print-completion zsh`, then a zsh completion script is written to stdout.
- Given the completion script is installed, then tab completion lists subcommands, flags, and artifact stems from the current directory.

---

## Normalize Subcommand Aliases

Accept common hyphenated spellings without breaking existing underscore usage.

**Requirements**:
- Given `fab-test pql-test`, then it behaves identically to `fab-test pql_test`.
- Given `fab-test pql-lint`, then it behaves identically to `fab-test pql_lint`.
- Given `fab-test playwright-impact`, then it remains the canonical form and `playwright_impact` is also accepted.

---

## Show Per-Artifact Progress

Improve observability for long analyzer runs without adding noise in CI.

**Requirements**:
- Given a non-CI terminal and multiple artifacts, then `fab-test` shows a progress indicator (e.g., `artifact 3 of 7`).
- Given `GITHUB_ACTIONS` is set, then progress is emitted as `::notice::` annotations instead.
- Given `--verbose` is passed, then artifact names continue to be printed as they start.
