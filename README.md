# fab-test

Metadata-driven CI/CD and validation framework for Microsoft Fabric artifacts.

This package provides the `fab-test` CLI and supporting analyzer wrappers used by the [fabric-ci-cd-dataops](https://github.com/kerski/fabric-ci-cd-dataops) reference implementation.

## Install

### From PyPI

```bash
pip install fab-test
```

### From source in editable mode (developers)

Editable mode links the package source into the active environment so code changes are reflected immediately.

```bash
git clone https://github.com/kerski/fabric-ci-cd-dataops.git
cd fabric-ci-cd-dataops
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

### From a locally built wheel

Build the wheel into `dist/`:

```bash
pip install build
python -m build
```

Create a fresh virtual environment, activate it, and install the wheel:

```bash
python -m venv .venv-test
source .venv-test/bin/activate  # Windows: .venv-test\Scripts\activate
pip install dist/fab_test-*.whl
```

Verify the console scripts are registered:

```bash
fab-test --help
```

## Run manual tests locally

### Wrapper contract tests with pytest

`pytest` exercises the analyzer wrappers without requiring external tools such as Tabular Editor or Power BI Desktop. To run the contract tests against the installed wheel, stay in the repository root and run the following inside the same virtual environment:

```bash
# Windows
.venv-test\Scripts\activate
# macOS/Linux
# source .venv-test/bin/activate

pip install pytest
pytest
```

To run a subset of tests by marker:

```bash
pytest -m fab_test
pytest -m analyzers
```

> **Note:** Some wrapper contract tests launch the installed console scripts (`tabular-editor-bpa`, `fab-test`, etc.) as subprocesses. Those scripts must be on `PATH`, so always activate the virtual environment before running `pytest`.

### Artifact validation with fab-test

`fab-test` runs analyzers against your actual `.fabric/artifacts`. It requires the corresponding external tools for each analyzer.

```bash
# Discover which artifacts would be analyzed
fab-test bpa --dry-run

# Run BPA against SemanticModel artifacts
fab-test bpa --tabular-editor-path "/path/to/TabularEditor.exe"

# Run PBIR Inspector against Report artifacts
fab-test pbir --inspector-path "/path/to/PBIRInspectorCLI"

# Run pql-test DAX tests
fab-test pql_test --env DEV

# Run Playwright visual validation (requires service-principal credentials)
fab-test playwright --artifact "Not Working Visuals" --env dev --env-file .env

# Discover reports that depend on a deployed semantic model
fab-test dependencies --semantic-model SalesModel --env dev --env-file .env
```

Full CLI reference: [`.github/skills/fab-test/SKILL.md`](.github/skills/fab-test/SKILL.md).

See [`docs/QUICK-VALIDATION.md`](docs/QUICK-VALIDATION.md) for a complete local build-and-test workflow.

## Usage

`fab-test` runs analyzers against your `.fabric/artifacts`. It is the local equivalent of the CI artifact validation gate. See the [Run manual tests locally](#run-manual-tests-locally) section above for common commands, and [`.github/skills/fab-test/SKILL.md`](.github/skills/fab-test/SKILL.md) for the full CLI reference.

## AI agent guidance

The package ships the AIDD agent instructions and skills used by the reference repository. After install, locate them under the installed package path:

```python
import fabric_ci_cd_dataops
import importlib.resources as resources

print(resources.files("fabric_ci_cd_dataops").joinpath("agents/aidd.agent.md"))
```

## License

MIT. See [LICENSE](LICENSE).
