# Credentials

**`fab-test` stores no credentials of its own** — no token, no cache, no credential file anywhere. It reads whatever the environment already provides, and delegates sign-in to the tool that owns the credential. There is no `fab-test` token cache to look for.

## `fab-test auth status`

Reports which identity would be used, and unlike `doctor` it verifies for real — this is the one command allowed to acquire a token.

```bash
fab-test auth status                      # readable table
fab-test auth status --format json        # one JSON document on stdout
fab-test auth status --workspace <name-or-id>  # also check that workspace is reachable
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

Service-mode runs (`bpa`/`pbir`/`a11y`/`rdl` against a workspace) use the one chain above with the Fabric REST scope `https://api.fabric.microsoft.com/.default`; the identity needs read access to the item and Fabric API access. Order: environment service principal → `--env-file`/`.fab-test/.env`/`./.env` → `DefaultAzureCredential` → `--interactive`. A partial service principal is an error, never a silent fallback. Nothing resolvable exits `127` naming the variables and `fab-test auth status`. The run names the credential it resolved once on stderr, after the mode banner — `auth=service-principal (.fab-test/.env)`, `auth=ambient:DefaultAzureCredential`, or `auth=interactive` — never a secret, and silent under `-q` and `--format json`. A service principal in `.fab-test/.env` wins over `az login`; for Data Agent runs, `--auth az` reverses that.

## Data Agent credentials

`fab-test data-agent` asks a deployed agent questions as a **service principal or your `az login`**, with the scope `https://analysis.windows.net/powerbi/api/.default` (`FABRIC_SCOPE` overrides it). It follows the chain every service command uses: a full service principal (environment → `--env-file` → `PLAYWRIGHT_ENV_FILE` → `.fab-test/.env` → `./.env`, client-credentials flow), else `az login`. Part of a principal exits `127` naming what is missing before promptfoo starts. `--auth az` uses `az login` even when a principal is set: the way out when the principal is throttled (`RequestBlocked`), rejected, or not set up for this agent. `--auth service-principal` never falls back, and exits `127` when none is set. The az token comes from the Azure CLI only (`AzureCliCredential`, not the whole `DefaultAzureCredential` chain); the tenant is the one `az login` chose, so use `az login --tenant <id>` for another. `az` not installed or not signed in is final and says to run `az login`. No `--interactive` and no managed identity (Fabric doesn't support one for Data Agents). In CI, `--auth az` after the pipeline's own `az login` (GitHub `azure/login` with OIDC, Azure DevOps `AzureCLI@2`) runs as that pipeline's principal with no client secret in the job. `tests init` and `tests lint` need no credentials.

The identity, a person or a principal, needs what [Microsoft Learn](https://learn.microsoft.com/fabric/data-science/data-agent-service-principal) lists:
- for a service principal, the tenant setting **Service principals can use Fabric APIs**, for it or a group it's in;
- **Member** or **Contributor** in the agent's workspace;
- **read access to every data source** the agent uses. The agent queries under the caller's identity, so sharing only the agent isn't enough. KQL-database sources don't support service principals yet.

A 401 after one token refresh, a 403, `"isRetriable": false`, `CapacityNotActive`, any other 4xx, a DNS failure and an untrusted certificate are final, not retried, and each names its fix. A 5xx, a timeout or a dropped connection is retried with capped backoff. The provider is the only layer that retries (promptfoo's own retries are off), and a server's `Retry-After` is a floor: a `RequestBlocked` agent is waited for once, then asked no more that run, and the envelope's `retry_after` says when to come back. No secret or token enters promptfoo's environment (under `--auth az` the provider asks `az` itself): the wrapper strips every service-principal spelling and the Azure SDK secrets, and the provider reads the principal from a private temp file that is deleted after the run. The token goes only to `https` Fabric and Power BI hosts, plus exact hosts in the caller's `FAB_TEST_DATA_AGENT_ALLOWED_HOSTS`. A suite can't widen that.

`--interactive` signs in through the browser with the token held in memory only — no device code, no cache on disk. It never prompts in CI (`CI`/`GITHUB_ACTIONS`/`TF_BUILD`; exit `2`), and `interactive_auth: off` in `fab-test.yml` or `FAB_TEST_INTERACTIVE_AUTH=0` turns it off fleet-wide (exit `2` naming the flag). `doctor` reports a per-analyzer service-readiness line without acquiring a token.
