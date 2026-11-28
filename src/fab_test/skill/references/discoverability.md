# Discoverability: doctor → list → explain

What each command checks, and what `fab-test doctor --format json` and `doctor --local --format json` print.

```
Discoverability {
  fn doctor()          // is each analyzer's tool/credential ready?
  fn doctor(--local)   // readiness for the local Desktop workflow specifically
  fn list()            // what subcommands exist, and how many artifacts match?
  fn explain(analyzer) // what command would `fab-test ANALYZER` actually run?
}

Constraints {
  doctor and list both support --format json
  doctor --analyzer NAME checks exactly one analyzer
  doctor --workspace NAME_OR_ID checks service readiness against that workspace, as FABRIC_WORKSPACE_ID would
  doctor marks each row ✅ ready, ⚠ warning (one setting away, e.g. credentials but no workspace), ℹ info (not set up, or a tool fetched on first run), or ❌ error (set up, and the run would fail); JSON rows carry it as `status`
  doctor exits 1 on any ❌ (--strict: any ⚠ too), else 0 -- a CI gate for one analyzer uses doctor --analyzer NAME
  doctor compares the az login account with `pql-test auth status` for pql_test (❌ when they differ, as the run would refuse)
  list's matched-artifact counts respect --artifact-dir
  explain ANALYZER never spawns a subprocess — it only shows the resolved command, tool path, rules path, and output path
}
```

```bash
fab-test doctor                       # is each analyzer's tool/credential ready?
fab-test doctor --local               # readiness for the local Desktop workflow specifically
fab-test doctor --workspace "Sales Dev"  # readiness for a service run against this workspace
fab-test list                         # what subcommands exist, and how many artifacts match?
fab-test explain bpa                  # what command would `fab-test bpa` actually run?
```

Plain `fab-test doctor --format json` gives every analyzer entry the same shape:

```
DoctorAnalyzerEntry {
  analyzer: String
  ready: Boolean
  resolved_path: String | null
  reason: String
  remediation: String | null
  version: String | null   // null for an analyzer with no wrapped tool of its own (pql_test, playwright, dependencies, telemetry); the resolved pinned version from analyzers.json for one that bootstraps a binary
}

Constraints {
  Every analyzer entry carries all five keys, version included, regardless of readiness
  The download cache is keyed by version, so bumping the pin in a fab-test upgrade downloads the new binary rather than reusing whatever an older checkout cached
  (a local override — an env var or a default_path file — shadows the declared pin) => reason names the variable or file and states the resolved tool will not receive automatic updates, a state a user in it can't fix by upgrading fab-test alone
}
```

See [docs/RELEASE.md](https://github.com/clientfirsttech/fab-test/blob/main/docs/RELEASE.md#bumping-a-wrapped-tools-pin) for how a pin gets bumped and delivered.

```bash
fab-test doctor --format json
```
```json
{
  "analyzers": [
    {"analyzer": "bpa", "ready": true, "resolved_path": "C:\\...\\TabularEditor.exe", "reason": "resolved via cached download (version 2.29.0)", "remediation": null, "version": "2.29.0"},
    {"analyzer": "pbir", "ready": true, "resolved_path": "C:\\...\\fab-inspector.exe", "reason": "resolved via cached download (version 4.0.1)", "remediation": null, "version": "4.0.1"},
    {"analyzer": "pql_test", "ready": false, "resolved_path": null, "reason": "no workspace, credentials, or running Desktop instance", "remediation": "Set FABRIC_WORKSPACE_ID ...", "version": null}
  ]
}
```

`doctor --local` checks Python version, whether a Desktop instance is running, the Desktop Bridge CLI's presence (path only — never invoked), and each of `fab-test local`'s four analyzers, then states exactly which ones would run:

```
DoctorLocalCheck {
  check: String            // "python" | "desktop" | "bpa" | "pbir" | ...
  ready: Boolean
  reason: String
  resolved_path: String | null
  remediation: String | null
  version                  // present only for the bootstrapped checks (bpa, pbir) — absent, not null, for python/desktop/desktop-bridge/pql_test, which have no tool version of their own
}

Constraints {
  Only the bootstrapped checks (bpa, pbir) carry version here
  The plain (non --local) doctor above is the one with the uniform five-key shape
}
```

```bash
fab-test doctor --local --format json
```
```json
{
  "checks": [
    {"check": "python", "ready": true, "reason": "3.12.10", "resolved_path": "/usr/bin/python3.12", "remediation": null},
    {"check": "desktop", "ready": false, "reason": "no running instance detected", "resolved_path": null, "remediation": "Open a .pbip file in Power BI Desktop"},
    {"check": "bpa", "ready": true, "reason": "resolved via cached download (version 2.29.0)", "resolved_path": "C:\\...\\TabularEditor.exe", "remediation": null, "version": "2.29.0"}
  ],
  "would_run": ["bpa", "pbir", "pql_test"]
}
```
