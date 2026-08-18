---
name: fab-inspector
description: PBIR Inspector (fab-inspector) CLI reference for static analysis of Power BI PBIR report artifacts. Use when invoking, configuring, or troubleshooting the PBIR Inspector tool locally or in CI. Covers all CLI flags, authentication modes, output formats, and integration with this project's invoke_pbir_inspector.py wrapper.
---

# fab-inspector (PBIR Inspector)

Static analysis CLI for Power BI PBIR report artifacts. Validates reports against configurable JSON rule sets.

Source: https://github.com/NatVanG/fab-inspector

## CLI Reference

```
PBIRInspectorCLI [options]
```

### Input Options

| Flag | Description | Required |
|------|-------------|----------|
| `-fabricitem <path>` | Path to a single PBIR report folder (`.Report`) | One of these |
| `-fabricworkspace <guid>` | Workspace ID — analyzes all reports in the workspace | One of these |

### Rules

| Flag | Description | Default |
|------|-------------|---------|
| `-rules <path-or-url>` | Path or URL to custom rules JSON | Built-in base rules |

### Authentication (workspace mode only)

| Flag | Values | Description |
|------|--------|-------------|
| `-authmethod` | `interactive`, `serviceprincipal`, `azurecli` | Auth method for Fabric API |
| `-tenantid <guid>` | | Azure AD tenant |
| `-clientid <guid>` | | Service principal app ID |
| `-clientsecret <secret>` | | Service principal secret |

### Output

| Flag | Description |
|------|-------------|
| `-output <path>` | Directory where result files are written (created as a folder) |
| `-formats <list>` | Comma-separated: `JSON`, `HTML`, `Console` (e.g. `JSON,HTML`) |
| `-verbose true` | Include PASSED rules in output (not just failures). **Always use this.** |

### Examples

```bash
# Local report — JSON + HTML output with all rules shown
PBIRInspectorCLI \
  -fabricitem ".fabric/artifacts/SalesReport.Report" \
  -rules ".github/metadata/rules/pbi-inspector-custom-rules.json" \
  -output "./analyzer-results/pbir/SalesReport/native.json" \
  -formats JSON,HTML \
  -verbose true

# Workspace mode — interactive auth
PBIRInspectorCLI \
  -fabricworkspace "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" \
  -rules "./rules/custom-rules.json" \
  -authmethod interactive \
  -formats Console

# Service principal auth
PBIRInspectorCLI \
  -fabricworkspace "<workspace-guid>" \
  -rules "./rules.json" \
  -authmethod serviceprincipal \
  -tenantid "<tenant-guid>" \
  -clientid "<app-guid>" \
  -clientsecret "<secret>" \
  -output "./results" \
  -formats JSON
```

## Output Behavior

OutputDirectory {
  // -output specifies a DIRECTORY, not a file
  // The CLI creates the directory and writes files inside it:
  //   TestRun_<guid>_<HHMMSS>.json   (when JSON in -formats)
  //   TestRun_<guid>_<HHMMSS>.html   (when HTML in -formats)
  // Console format prints to stdout only
}

Constraints {
  `-verbose true` must always be passed so PASSED rules appear in output
  `-formats JSON,HTML` is a single flag with comma-separated values — one CLI call produces both
  `-output` path becomes a directory; the CLI names files with TestRun_<guid>_<timestamp>.<ext>
  (workspace mode) => requires -authmethod
  (local -fabricitem mode) => no auth needed
}

## Integration in This Project

```
fab-test pbir                          ← runs invoke_pbir_inspector.py with --emit-html
scripts/invoke_pbir_inspector.py       ← Python wrapper
```

### Wrapper flags

| Flag | Description |
|------|-------------|
| `--artifact-path` | Path to .Report folder |
| `--rules-path` | Rules JSON |
| `--inspector-path` | Path to PBIRInspectorCLI binary |
| `--output-path` | Envelope output path |
| `--emit-html` | Pass `-formats JSON,HTML` (default via fab-test) |

### Output layout

```
analyzer-results/pbir/<artifact-stem>/
├── envelope.json                          ← standardized envelope
└── native.json/                           ← directory created by CLI
    ├── TestRun_<guid>_<HHMMSS>.json       ← raw JSON results
    └── TestRun_<guid>_<HHMMSS>.html       ← HTML report (when --emit-html)
```

The envelope includes `native_html_output_path` pointing to the first discovered `.html` file inside `native.json/` when HTML output is present.

## Rules File Format

Rules are defined in JSON with the structure:

```json
{
  "Rules": [
    {
      "id": "RULE_ID",
      "name": "Human readable name",
      "description": "What the rule checks",
      "disabled": false,
      "logType": 1,
      "itemType": "report_deprecated",
      "parameters": { "paramName": "value" }
    }
  ]
}
```

RuleLogTypes {
  0 => Warning (informational, non-blocking)
  1 => Error (test failure)
}

### Disabling a rule

Set `"disabled": true` in the rules JSON to skip evaluation.

### Rule parameters

Rules accept parameter overrides (e.g. `paramMaxVisualsPerPage`, `paramMaxTopNFilteringPerPage`).

## Test Result Schema

Each result object in the TestRun JSON:

```
TestResult {
  Id: GUID
  RuleId: String           // e.g. "REDUCE_VISUALS_ON_PAGE"
  RuleName: String
  RuleDescription: String
  LogType: 0 | 1          // 0=Warning, 1=Error
  RuleItemType: String
  RuleSetName: String
  RuleSetPath: String
  ItemPath: String         // relative path inside the report
  ParentName: String | null
  ParentDisplayName: String
  Pass: Boolean
  Expected: Any
  Actual: Any
  Message: String
}
```
