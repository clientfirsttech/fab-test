# Pipeline Deletion Dead-Code Audit Epic

**Status**: ✅ COMPLETED
**Goal**: Remove the modules stranded by the nine-workflow Fabric pipeline deletion that have no real caller left, without deleting `detect_changes.py`'s still-consumed output contract.

## Overview

Removing the nine Fabric pipeline workflows left eight modules under `src/fab_test/scripts/` with tests but no production caller: `detect_changes.py`, `deploy.py`, `check_promotion_safety.py`, `generate_fabric_cicd_config.py`, `compare_baseline.py`, `scan_credentials.py`, `scan_entropy.py`, and `aggregate_security_findings.py`. Each was invoked only by a workflow that no longer exists, so a green suite proves only that dead code still parses. Deliberately deferred at the time of the pipeline-workflow deletion, since a wrong call here deletes something a consumer reaches through a path nobody grepped for.

**Audit, checked against every real code path** (`[project.scripts]` entries, cross-module imports in `src/`, and every surviving workflow — `build.yml`, `check-tool-updates.yml`, `copilot-setup-steps.yml`, `publish*.yml`):

- **`deploy.py`, `check_promotion_safety.py`, `generate_fabric_cicd_config.py`, `compare_baseline.py`, `scan_credentials.py`, `scan_entropy.py`, `aggregate_security_findings.py`** — zero production callers found: no console-script entry, no import from anywhere else in `src/`, no surviving workflow reference. Each is CI/CD deployment or repo-wide security-scan glue, which vision.md's Non-Goals already excludes ("Being a general-purpose Fabric deployment tool — deployment lives in `fabric-cicd-deployment`"). Confirmed dead, not merely unused.
- **`detect_changes.py`** — the one exception. Its `changed-artifacts.json` output shape is still consumed by `playwright_validation/impact.py`. The specific concern that made it "not fully dead" (a fourth duplicate artifact-map loader) was already resolved by the Environments Metadata Layers epic — it now calls the shared `_artifact_types.load_artifact_map`. Kept: it's an orphaned producer for a still-real consumer contract, not dead code.

---

## Delete the seven dead modules and their orphaned tests

**Requirements**:
- Given `deploy.py`, `check_promotion_safety.py`, `generate_fabric_cicd_config.py`, `compare_baseline.py`, `scan_credentials.py`, `scan_entropy.py`, and `aggregate_security_findings.py`, should be deleted from `src/fab_test/scripts/`.
- Given `detect_changes.py`, should be left untouched — it is not part of this deletion.
- Given a test file dedicated entirely to a deleted module (`test_deploy.py`, `test_check_promotion_safety.py`, `test_compare_baseline.py`, `test_security_scans.py`), should be deleted with it.
- Given a test file that mixes coverage of a deleted module with coverage of still-live code (`test_environments_config.py`'s `TestGenerateFabricCicdConfig`, `test_environments_layers.py`'s `deploy.py`/`generate_fabric_cicd_config.py`/`check_promotion_safety.py` sections), should have only the dead-module tests removed — the still-live sections (`validate_environments_yaml`, `validate_environments_schema`, the Playwright resolver) must keep passing unchanged.
- Given `fabric_cicd` was imported nowhere except `deploy.py`, should have the now-unused `fabric-cicd` dependency removed from `pyproject.toml`'s `dependencies` — an unused mandatory dependency is shipped to every `pip install fab-test` user for no reason.
- Given `pyproject.toml`'s `[tool.ruff.lint.per-file-ignores]` names `scan_credentials.py`/`scan_entropy.py` specifically, should have those two entries removed once the files are gone.
- Given `_metadata.py`'s `resolve_environments_yml` and `validate_environments_yaml.py`'s module docstring both name the three deleted CLI scripts as callers, should be updated to name only the callers that remain (the two schema validators, the Playwright resolver).
- Given `README.md`/`docs/RELEASE.md` cite `fabric-cicd`'s outdated TestPyPI version as a reason `--extra-index-url` is required, should drop that reasoning once `fabric-cicd` is no longer a dependency, keeping only the still-true `pql-test` reasoning.
- Given `tests/test_complexity_budget.py`'s `COMPLEXITY_CEILING` was deliberately held at 6 because `deploy.py`/`check_promotion_safety.py` findings were left unaddressed pending this audit, should be re-measured and lowered to the new real count once those files are gone.
- Given the full test suite and `ruff check src/`, should both pass after every deletion and edit above.
