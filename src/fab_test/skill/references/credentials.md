# Credentials

**`fab-test` stores no credentials of its own** — no token, no cache, no credential file anywhere. It reads whatever the environment already provides, and delegates sign-in to the tool that owns the credential. There is no `fab-test` token cache to look for.

## `fab-test auth status`

Reports which identity would be used, and unlike `doctor` it verifies for real — this is the one command allowed to acquire a token.

```bash
fab-test auth status                      # readable table
fab-test auth status --format json        # one JSON document on stdout
fab-test auth status --workspace-id <id>  # also check that workspace is reachable
```

| Code | Meaning |
|------|---------|
| `0` | An identity resolved and was verified |
| `1` | Credentials are fine, but the named workspace is not reachable with them |
| `127` | Nothing resolvable, or an ambient credential that failed to acquire a token |

Resolution order matches what actually authenticates: environment variables → `.env` file → ambient Azure credential (`az login`, managed identity, VS Code sign-in). A *partially* configured service principal is reported as a mistake rather than silently falling through to ambient auth.

`doctor` uses the same chain but never acquires a token, so it reports an ambient credential as `unverified` and points here. That is expected, not a failure.

## `fab-test auth login`

Mints nothing. It runs the underlying tool's login, printing the exact command first so you can reproduce it without `fab-test`:

```bash
fab-test auth login                # delegates to `pql-test auth login`
fab-test auth login --cloud USGov  # sovereign cloud
```

With no delegable tool on PATH it exits `127` naming `az login` and the service-principal variables.

> **`--env` is not `--cloud`.** In `fab-test`, `--env` is the *test environment label* (`DEV`, `PROD`, `ANY`) and exists on the analyzer subcommands. `--cloud` selects the *Azure cloud* and exists only on `auth login`. `pql-test` spells its cloud flag `--environment`; the names are deliberately kept apart here so the two never collide.

## Azure-hosted browsers (`playwright`)

The optional Azure browser backend needs two more values, separate from the Fabric service principal above: `PLAYWRIGHT_SERVICE_URL` (a credential-free `wss://` endpoint) and `PLAYWRIGHT_SERVICE_ACCESS_TOKEN`. They resolve process environment > `--env-file` > `PLAYWRIGHT_ENV_FILE` > `.fab-test/.env` > `./.env`, and are required only when an execution YAML selects `backend: azure`. A missing value exits `127` naming the variable; a rejected token is an `error` envelope (`playwright_execution_error`), never a visual finding or a local fallback. Never put either in YAML, and rotate the token on exposure.
## Service mode credentials

Service-mode runs (`bpa`/`pbir`/`a11y`/`rdl` against a workspace) use the one chain above with the Fabric REST scope `https://api.fabric.microsoft.com/.default`; the identity needs read access to the item and Fabric API access. Order: environment service principal → `--env-file`/`.fab-test/.env`/`./.env` → `DefaultAzureCredential` → `--interactive`. A partial service principal is an error, never a silent fallback. Nothing resolvable exits `127` naming the variables and `fab-test auth status`.

`--interactive` signs in through the browser with the token held in memory only — no device code, no cache on disk. It never prompts in CI (`CI`/`GITHUB_ACTIONS`/`TF_BUILD`; exit `2`), and `interactive_auth: off` in `fab-test.yml` or `FAB_TEST_INTERACTIVE_AUTH=0` turns it off fleet-wide (exit `2` naming the flag). `doctor` reports a per-analyzer service-readiness line without acquiring a token.

## `data-agent` credentials

`fab-test data-agent` is stricter than the export analyzers and stricter than
`playwright` in one specific way: it is **service principal only**. Set
`FABRIC_TENANT_ID`, `FABRIC_CLIENT_ID`, and `FABRIC_CLIENT_SECRET` (plus
optional `FABRIC_SCOPE` when you need something other than
`https://analysis.windows.net/powerbi/api/.default`). There is no
`--interactive` escape hatch and no ambient `az login` fallback.

The local `.DataAgent/.env.example` scaffold is there to name the variables,
not to change the resolution order. At runtime the wrapper reads the effective
environment, refuses a partial service principal with the existing incomplete-SP
remediation, and exits `127` naming all three required variables plus
`fab-test auth status`. The service principal also needs workspace access and
any downstream data-source access the deployed Data Agent itself depends on.
