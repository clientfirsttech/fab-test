---
name: pql-test
description: pql-test PyPI analyzer wrapper for this project. Covers CLI interface, envelope contract, two-tier marker pattern, and file locations. Use when authoring, debugging, or extending the pql-test integration in scripts/invoke_pql_test.py, tests/test_invoke_pql_test.py, or the analyzers.json registry entry.
---

# pql-test Analyzer

Runs DAX/PQL tests defined inside a `.pbip` SemanticModel artifact using the `pql-test` PyPI package.
All execution flows through `scripts/invoke_pql_test.py`, which wraps the CLI and writes the shared JSON envelope.

## Architecture

```
pytest -m pql_test  /  pytest -m pql_test_integration
        │
        └─ scripts/invoke_pql_test.py          ← Python wrapper (entry point)
                │
                ├─ pql-test CLI  (shutil.which)
                │     fallback: python -m pql_test
                │
                ├─ analyzer-results/pql_test/<artifact-stem>/native.json   ← raw CLI output
                └─ analyzer-results/pql_test/<artifact-stem>/envelope.json ← shared envelope
```

## CLI Interface

The wrapper calls the installed `pql-test` entry point using the `run-tests` subcommand:

```
pql-test run-tests <MODEL_PATH> \
  [--env         <environment-label>]
  [--workspace-id  <workspace-guid>]
  [--output        <path-to-native-json>]
  [--log-format    github|azuredevops]
```

`MODEL_PATH` formats accepted by pql-test:

| Format | Used for |
|--------|----------|
| `local/<model_name>` | Locally-open Power BI Desktop instance |
| `<path/to/.SemanticModel>` | Filesystem PBIP directory (also connects to Desktop if open) |
| `<Workspace>.Workspace/<Model>.SemanticModel` | Fabric service via XMLA |

If `pql-test` is not on `PATH`, the wrapper falls back to:

```
python -m pql_test run-tests …
```

**Direct Python invocation**:

```
python scripts/invoke_pql_test.py \
  --artifact-path .fabric/artifacts/SampleModel-PQLAssert.SemanticModel \
  --artifact-name SampleModel-PQLAssert \
  [--env DEV]
```

**With fab-test**:

```
fab-test pql_test [--env DEV] [--workspace-id <guid>]
```

## Envelope Contract

Every run writes `envelope.json` using `_analyzer_envelope.build_envelope()`:

```json
{
  "schema_version": "1.0",
  "analyzer":            "pql_test",
  "artifact_path":       "<resolved absolute path>",
  "status":              "passed | failed | error | timeout",
  "message":             "<human-readable summary>",
  "findings":            [],
  "native_output_path":  "analyzer-results/pql_test/<stem>/native.json",
  "duration_ms":         <int>,
  "test_results":        []
}
```

`ENVELOPE_REQUIRED_KEYS` from `scripts/_analyzer_envelope.py` is imported and asserted in `tests/test_invoke_pql_test.py::test_envelope_shape`.

## Two-Tier Marker Pattern

| Command | Layer | Requires tools? | Expected result |
|---------|-------|-----------------|-----------------|
| `pytest -m pql_test` | Contract | No | Always green — tests wrapper logic, envelope shape, path validation |
| `pytest -m pql_test_integration` | Execution | `pql-test` installed + service principal | Real run; skips if unavailable |
| `pytest -m "pql_test or pql_test_integration"` | Both | — | Full suite |

Contract tests never call `subprocess`. They mock `invoke_pql_test.subprocess.run`.

## workspace_id Constraint

```
Constraints {
  workspace_id must never be committed to the repository
  Supply at runtime via --workspace-id CLI arg or FABRIC_WORKSPACE_ID env var
  Integration tests skip automatically when workspace_id is absent
}
```

## File Locations

| File | Purpose |
|------|---------|
| `scripts/invoke_pql_test.py` | Wrapper — build_command, parse_findings, run_pql_test, main |
| `scripts/_analyzer_envelope.py` | Shared envelope schema, Timer, write_envelope |
| `tests/test_invoke_pql_test.py` | Contract test suite (marker: pql_test) |
| `analyzer-results/pql_test/<stem>/envelope.json` | Shared envelope written on every run |
| `analyzer-results/pql_test/<stem>/native.json` | Raw pql-test JSON output |
| `.github/metadata/analyzers.json` | Registry entry for `pql_test` analyzer |

## analyzers.json Registry Pattern

```json
{
  "name": "pql_test",
  "type": "dynamic",
  "artifact_types": ["SemanticModel"],
  "command": "python scripts/invoke_pql_test.py --artifact-path {artifact_path} --artifact-name {artifact_name} --output-path {output_path}",
  "native_output": {
    "format": "json",
    "path_pattern": "analyzer-results/pql_test/{artifact_stem}/native.json"
  }
}
```

## Static vs Dynamic Classification

- **Static layer** (`pytest -m pql_test`): runs offline against repo files — no credentials, no network.
- **Dynamic layer** (`pytest -m pql_test_integration`): requires a deployed model and a service principal (`FABRIC_WORKSPACE_ID`).

Vision §2.7 hard constraint: the contract layer must always be locally verifiable.
