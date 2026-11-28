# The run manifest (`fab-test-results/run.json`)

```
RunManifest {
  schema_version: Integer
  fab_test_version: String
  origin: "local" | "github-actions" | "gitlab-ci" | "circleci" | "azure-devops"
  target: Target | null
  command: String[]        // sanitized — see Constraints below
  artifacts: ArtifactResult[]
  totals { errors: Integer, warnings: Integer }
  telemetry_error: String | null
  exit_code: Integer
  started_at: String       // UTC ISO 8601, when the invocation began
  finished_at: String      // UTC ISO 8601, when run.json was written
  wall_ms: Integer         // what the caller waited, end to end
  execution: Execution | null
}

Execution {                 // present only when the run included playwright
  backend: "local" | "azure"
  execution_config: String | null        // the selected execution YAML's path
  execution_config_origin: String        // "flag" | "env:PLAYWRIGHT_CONFIG_PATH" | "config:playwright_config" | "default"
  workers: Integer | null                // xdist workers per report (capped by its case count)
  workers_origin: "flag" | "env:PLAYWRIGHT_XDIST_WORKERS" | "execution_config" | "default"
  jobs: Integer                          // reports run at once
  jobs_origin: "flag" | "execution_config" | "config" | "default"
}

Target {
  raw: String
  scope: "path" | "desktop" | "workspace"
  name: String
  type: String | null
  workspace: String | null
  workspace_id: String | null   // the GUID resolved from a workspace name; names a workspace and grants access to nothing, so it is safe to record
  path: String | null
}

ArtifactResult {
  analyzer: String
  artifact: String
  status: "passed" | "failed" | "skipped" | "timeout" | "preflight_failed"
  envelope_path: String | null
  errors: Integer
  warnings: Integer
  detail: String | null
  duration_ms: Integer | null   // the analyzer subprocess's wall time; null when it never ran (preflight_failed)
}

Constraints {
  Every analyzer invocation (a single subcommand or `all`) writes exactly one run.json under --output-dir (default fab-test-results/), so a caller reads one file instead of globbing result directories
  ("timeout" or "preflight_failed") => the run was aborted without producing a result to report
  (the run ended without a result to report) => detail carries the human-readable reason: the resolved remediation message for preflight_failed, the exceeded duration for timeout, or the analyzer's own error message when it exited non-zero before writing an envelope (status "failed"; envelope_path points at the envelope fab-test wrote in its place, whose message is that same error and whose findings are empty -- never an earlier run's envelope)
  (the analyzer did write an envelope, however it failed) => detail is null; the findings are the reason, and envelope_path points at them
  run.json alone is always enough to learn what to fix — a caller never has to fall back to stderr, which matters when run.json is the only file a pipeline uploads
  (no CI environment variable is detected) => origin = "local"
  (a CI system is detected) => origin = its name ("github-actions" | "gitlab-ci" | "circleci" | "azure-devops")
  The envelope schema, status values, and result layout are identical whether origin is local or CI — origin is the only field that differs between a local run and a CI run
  (target is null) => the run discovered artifacts instead of being pointed at one
  Branch on target.scope ("path" | "desktop" | "workspace") rather than parsing target.raw
  Where origin distinguishes local from CI, target.scope distinguishes whether the run read files on disk, a running Desktop instance, or a deployed workspace item — a distinction origin alone never answers
  command has every known credential flag (--client-secret, --password, --token, --secret, --api-key) and any key=value-shaped token redacted before the file is written — no credential ever appears in the manifest
  (this run's telemetry was delivered to every configured destination, or none was asked for) => telemetry_error = null
  (telemetry failed) => telemetry_error names why: an unreachable cluster, an unreachable OneLake endpoint, a missing install extra, a missing permission grant. One destination's failure never blocks the other's delivery; if both fail, telemetry_error names both, prefixed by destination
  telemetry_error never changes exit_code — telemetry is diagnostic and must not fail a build. See [Telemetry](references/configuration.md#telemetry)
  doctor, list, explain, auth, and clean-tools never write a manifest — they don't run an analyzer
  sum(artifacts[].duration_ms) / wall_ms => how much the run gained from parallelism (about 1 with jobs 1); compare runs only with their execution blocks, and only when they tested the same artifacts
  execution never holds the service URL, a token, or any credential
}
```

```json
{
  "schema_version": 1,
  "fab_test_version": "1.0.0",
  "origin": "local",
  "target": {
    "raw": "local/SampleModel-PQLAssert",
    "scope": "desktop",
    "name": "SampleModel-PQLAssert",
    "type": null,
    "workspace": null,
    "workspace_id": null,
    "path": null
  },
  "command": ["fab-test", "bpa", "--format", "json"],
  "artifacts": [
    {
      "analyzer": "bpa",
      "artifact": "SampleModel-PQLAssert",
      "status": "passed",
      "envelope_path": "fab-test-results/bpa/SampleModel-PQLAssert/envelope.json",
      "errors": 0,
      "warnings": 21,
      "detail": null,
      "duration_ms": 8412
    }
  ],
  "totals": {"errors": 0, "warnings": 21},
  "telemetry_error": null,
  "exit_code": 0,
  "started_at": "2026-10-09T20:04:12+00:00",
  "finished_at": "2026-10-09T20:04:21+00:00",
  "wall_ms": 9105,
  "execution": null
}
```

The case a pipeline meets most is a `detail` populated on an aborted run: `fab-test playwright --artifact ThinReport` with no `--env` aborts before authenticating, and `detail` carries `No environment given, so there is nothing to resolve 'ThinReport' against. Pass --env, ...`.
