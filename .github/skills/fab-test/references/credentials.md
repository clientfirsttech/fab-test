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