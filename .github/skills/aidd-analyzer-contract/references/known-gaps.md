# Known contract deviations

Existing analyzers that break the contract, surveyed 2026-09-26. These are
backlog, not precedent: don't copy them into a new analyzer. Remove an entry
when it's fixed.

- **a11y**: drops `Timer.started_at`; missing from `artifact_analyzers.Report.static`,
  `_LOCAL_ANALYZERS`, the conftest marker maps, and has no `release_source`.
- **pbir**: no `attach_report`, so there's no `report.html` unless FabInspCLI
  writes its own HTML; no `started_at`.
- **pqlint**: no `attach_report`; no `started_at`; writes a non-standard
  `"timeout"` status; missing from `artifact_analyzers.SemanticModel.static`.
- **prompt_lint**: in `analyzers.json` but not `ANALYZER_REGISTRY`, so no
  subcommand; no `attach_report`, `--verbose`, or JSON-mode logging; findings
  carry no severity; records a `native.json` it never writes.
- **playwright**: dynamic, but its telemetry lands in `fabric_static_analysis`.
- **Envelope `analyzer` field vs registry key**: `pbir_a11y`/`a11y`,
  `pbir_inspector`/`pbir`, `tabular_editor_bpa`/`bpa`, `pqlint`/`pql_lint`. This
  is the name telemetry, annotations, and reports show.
- **All wrappers**: `native_output_path` resolves from the working directory, not
  beside `--output-path`, so `--output-dir` doesn't move `native.*` (only bpa
  takes `--native-output-path`).
- **dependencies**: no `analyzers.json` entry and no pytest marker.

Registration parity (`_COMMAND_BUILDERS`, the subparsers, `analyzers.json`,
`_LOCAL_ANALYZERS`, `_TOOL_DISPLAY_NAMES`, the marker maps) is checked against
`ANALYZER_REGISTRY` by `tests/test_analyzer_contract_parity.py`. Its
`_KNOWN_GAPS` must match the registration entries above: fixing one fails the
test until it's removed there too.
