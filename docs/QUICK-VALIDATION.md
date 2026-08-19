# Quick validation guide

Validate the `fab-test` package and its analyzers on your local machine before pushing changes to CI.

## Prerequisites

- Python 3.12 or later
- A clone of this repository
- (Optional) External analyzer tools such as Tabular Editor or PBIR Inspector if you plan to run `fab-test` against real artifacts

## Virtual environments used by this project

This repository uses several local virtual environments. They are all ignored by `.gitignore` and can be recreated at any time.

| Environment | Purpose |
|-------------|---------|
| `.venv`     | General development environment with the package installed in editable mode (`pip install -e .`). |
| `.venv-test`| Fresh, throwaway environment used to install and validate the locally built wheel exactly as a consumer would. |
| `.venv-pkg` | Development/test environment with dev dependencies such as `pytest`, `coverage`, and `playwright`. |
| `.venv-smoke`| Environment used by the GitHub Actions smoke-test helpers (`smoke-test-orchestrator`, `smoke-test-pql-test`). |

All of these are optional. The only one the walkthrough below depends on is `.venv-test`.

## Build the wheel locally

The project is packaged with `setuptools` and `pyproject.toml`. Build a wheel into `dist/`:

```bash
pip install build
python -m build
```

After the build completes, `dist/` contains both a wheel and a source distribution:

```text
dist/
  fab_test-1.0.0-py3-none-any.whl
  fab_test-1.0.0.tar.gz
```

## Install the wheel in a virtual environment

Create a fresh virtual environment to test the packaged distribution exactly as a consumer would install it:

```bash
python -m venv .venv-test
source .venv-test/bin/activate  # Windows: .venv-test\Scripts\activate
pip install dist/fab_test-*.whl
```

Verify the console scripts are registered:

```bash
fab-test --help
```

## Run wrapper contract tests with pytest

`pytest` validates the analyzer wrappers using mocks and fixtures, so it does not require external tools. Make sure the virtual environment is activated so the installed console scripts are on `PATH`, then install `pytest` and run the test suite from the repository root:

```bash
# Windows
.venv-test\Scripts\activate
# macOS/Linux
# source .venv-test/bin/activate

pip install pytest
pytest
```

Run a subset of tests by marker:

```bash
pytest -m fab_test      # fab-test CLI surface
pytest -m analyzers     # all contract-tier analyzer tests
pytest -m bpa           # BPA wrapper only
pytest -m pbir          # PBIR Inspector wrapper only
pytest -m pql_test      # pql-test wrapper only
pytest -m pql_lint      # Power Query lint wrapper only
```

> **Note:** Some wrapper contract tests launch the installed console scripts (`tabular-editor-bpa`, `fab-test`, etc.) as subprocesses. Those scripts must be on `PATH`, so always activate the virtual environment before running `pytest`.

## Run artifact analyzers with fab-test

`fab-test` exercises the actual analyzers against `.fabric/artifacts`. Each analyzer has its own tool requirements.

### Discover artifacts without running anything

```bash
fab-test bpa --dry-run
fab-test pbir --dry-run
fab-test pql-test --dry-run
```

### Run a single analyzer

```bash
fab-test bpa --tabular-editor-path "/path/to/TabularEditor.exe"
fab-test pbir --inspector-path "/path/to/PBIRInspectorCLI"
fab-test pql-test --env DEV
fab-test pql-lint
```

### Isolate one artifact

```bash
fab-test bpa --artifact SampleModel-PQLAssert
fab-test pql-test --artifact SampleModel-PQLAssert --env DEV
```

### Run the default analyzer set

```bash
fab-test all
```

The default set is configured in `.github/metadata/analyzers.json`.

### Check readiness before running (doctor)

Before running any analyzer, ask whether its tool or credentials are actually in place:

```bash
fab-test doctor
fab-test doctor --analyzer bpa --format json
```

### Pipeline snippet: doctor as a gate, run.json as the artifact

A copy-pasteable step for a CI job — gate on readiness, run with `--format json`, upload the manifest instead of globbing result directories:

```yaml
- name: Check fab-test readiness
  run: fab-test doctor --format json

- name: Run bpa
  run: fab-test bpa --format json --artifact-dir .fabric/artifacts

- name: Upload run manifest
  uses: actions/upload-artifact@v4
  with:
    name: fab-test-run-manifest
    path: analyzer-results/run.json
```

`run.json` records `schema_version`, `fab_test_version`, `origin` (`"local"` locally, the detected CI system in a pipeline), the invoked command (credentials redacted), per-artifact status, envelope paths, totals, and the final exit code — see the [Agent Contract](../.github/skills/fab-test/SKILL.md#agent-contract) for the full schema.

### Running the local-Desktop analyzer set in CI

`fab-test local` (see [QUICKSTART-LOCAL.md](QUICKSTART-LOCAL.md)) isn't only for a laptop — it runs the same in a pipeline, since it never requires a workspace ID or service principal:

```yaml
- name: Check local-workflow readiness
  run: fab-test doctor --local --format json

- name: Run the local-Desktop analyzer set
  run: fab-test local --format json

- name: Upload run manifest
  uses: actions/upload-artifact@v4
  with:
    name: fab-test-run-manifest
    path: analyzer-results/run.json
```

The difference from running it on a laptop: no Power BI Desktop instance is open in CI, so `pql-test`'s DAX tests connect to nothing and degrade to a `skipped` status on that artifact (never a failure — see vision.md's "platform gaps degrade to skips") rather than binding to a `desktop` port. `pql-lint`, BPA, and PBIR Inspector are unaffected — they don't depend on Desktop at all.

## Clean up

When finished, deactivate the virtual environment:

```bash
deactivate
```

Remove the test environment and build artifacts if desired:

```bash
rm -rf .venv-test dist
```

On Windows:

```powershell
Remove-Item -Recurse -Force .venv-test, dist
```

## Full reference

- [`fab-test` CLI reference](../.github/skills/fab-test/SKILL.md)
- [`pytest.ini`](../pytest.ini) for test markers and configuration
