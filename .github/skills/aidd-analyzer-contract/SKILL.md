---
name: aidd-analyzer-contract
description: Minimum requirements every fab-test analyzer subcommand and invoke_*.py wrapper must meet so the facade stays one contract. Use when planning, adding, reviewing, or changing an analyzer, its wrapper, or its registration.
---

# Analyzer Contract

fab-test's value is one contract across every tool it wraps (vision.md). That
contract is spread over roughly twenty registration points, and most of them are
not checked against each other: an analyzer can pass its own tests and still
produce no HTML report, send the wrong telemetry type, or be missing from
`fab-test local`. This skill is the list of what "behaves like the other
checks" means, so parity is planned up front instead of found in review.

import references/checklist.md
import references/known-gaps.md

## Contract

Finding {
  rule: String          // stable rule ID, e.g. "DS-02"
  severity: "error" | "warning" | "info"   // missing or unknown counts as error
  object: String        // the offending item's name, or its path when unnamed
  message: String       // what is wrong and how to fix it: the flag, key, or edit
}

Envelope {
  ...ENVELOPE_REQUIRED_KEYS   // _analyzer_envelope.py, via build_envelope(EnvelopeIdentity)
  status: "passed" | "warning" | "failed" | "error" | "skipped"
  findings: Finding[]
  test_results?             // rule shape (rule/severity/object/message/status) or
                            // test shape (suite_name/test_name/passed/expected/actual)
  duration_ms, started_at   // from Timer; keep started_at, don't discard it
  native_output_path?       // only if native.<ext> was actually written
}

Constraints {
  // Output — what every caller reads
  Write the envelope to <output_dir>/<registry key>/<artifact stem>/envelope.json with write_envelope
  (the run fails for any reason) => still write an error envelope before exiting 1
  Exit 0 for pass or warnings only; exit 1 for any error finding or tool failure
  (a wrapper-level threshold like --fail-on) => express it as finding severity, since
    _artifact_exit_code decides from findings, not from the wrapper's exit code
  Call attach_report(envelope, output_path) before write_envelope, so --report/--open-report work
  (ANALYZER_OUTPUT_MODE=json) => log() goes to stderr; stdout stays pure JSON
  Honor ANALYZER_VERBOSITY and --verbose; verbosity never changes files on disk
  (ANALYZER_VERBOSITY=summary) => print nothing to stdout on a passing run: `-q` prints its one line per artifact from the envelope, so any banner, path, or result line the wrapper adds is a token the caller pays for twice
  (default verbosity) => name each fact once: the envelope and native paths in the banner or after the run, never both; the rules and tool paths only at verbose, since they are the same for every artifact and already in the envelope
  (the wrapper explains a failure) => write it to stderr, and write an envelope whenever findings exist: `-q` hides stderr when findings account for the exit code and shows it when they do not
  Never write credentials to stdout, the envelope, the manifest, or telemetry

  // Identity — one name everywhere
  The registry key, the results folder, and the envelope's analyzer field agree
  Telemetry artifact_type is the Fabric type name (Report, PaginatedReport), not a file suffix
  (analyzer is dynamic) => route it to fabric_dynamic_analysis in _telemetry_table

  // Reach — discoverable like its siblings
  Register in ANALYZER_REGISTRY, ANALYZER_SCOPES, _COMMAND_BUILDERS, the parser, and analyzers.json
  (static and needs no service) => add to artifact_analyzers.<Type>.static and _LOCAL_ANALYZERS
  (should run by default) => add to fab_test_all
  (has rules) => rules.<name> overlay in _config.py, fab-test.schema.json, and _rule_overlay.py
  (wraps an external tool) => tool_install with release_source, a THIRD-PARTY.md row,
    _WRAPPED_TOOLS, and doctor readiness via requires_runtime/requires_platform
  (in-house, pure Python) => doctor reports it ready with no install step

  // Proof
  Add a pytest marker in pytest.ini and in conftest's _ANALYZER_MARKERS/_MARKER_SUFFIX
  (the change grows a file at its test_module_budget ceiling) => split on the module's seam
    or record the growth in its exemption; never let the suite fail on it
  Run the analyzer alone, via `all`, and via `local` through the installed console script
  Document all three callers with the `document` skill before the epic is done
}

## Process

addAnalyzer(name) {
  1. Read references/checklist.md and list every touch point this analyzer needs
  2. Read references/known-gaps.md; do not copy a sibling's known deviation
  3. Write the requirements into the epic as Given/should lines (one per contract
     group above that applies), including the module-budget plan
  4. TDD the wrapper first (aidd-tdd), then registration, then aggregate wiring
  5. Verify through the real CLI: `fab-test <name>`, `all`, `local`, `list`,
     `explain`, `doctor`, `--report`, `--open-report`, `--output-format json`,
     `--telemetry --dry-run`
  6. Close with the vision's Definition of Done: ruff, document, skill sync
}

reviewAnalyzer(diff) {
  Check the diff against every Constraint above |> report each unmet one with its checklist row
}

Commands {
  /analyzer-contract plan [name] — produce the touch-point list and epic requirements for a new analyzer
  /analyzer-contract review [name] — check an existing analyzer against the contract
}
