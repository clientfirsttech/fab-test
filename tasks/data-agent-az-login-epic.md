# Data Agent az login Epic

**Status**: ✅ IMPLEMENTED 2026-11-22 (live run pending az login to the workspace's tenant) on `feature/data-agent-testing`
**Goal**: run Data Agent suites as the developer's `az login` identity, not only as a service principal.

## Why

On 2026-11-22 Fabric started answering every Data Agent request from the service principal with 429 `RequestBlocked`. It started at 16:19 UTC and was still happening at 20:54 UTC. Moving the workspace to two other capacities, including an F2, didn't clear it. The same agent answered the user in the portal in 9–14 s. The provider accepts only a service principal, so the suite couldn't run at all.

The rest of fab-test already uses an ambient Azure credential when no service principal is set (`build_fabric_service_client`, `SIGN_IN_REMEDIATION`). The Data Agent path was the exception.

## Decisions

1. **`--auth az|service-principal` on `fab-test data-agent`.** The default is the chain every other command uses: the service principal when one is fully set, `az login` when none is set, and an error when one is half set. `--auth az` uses `az login` even when a service principal is set, which is what a blocked service principal needs. `--auth service-principal` refuses to fall back.
2. **The token comes from `AzureCliCredential`, not `DefaultAzureCredential`.** The flag says az login, so the run doesn't probe managed identity or VS Code first. The process timeout is 30 s, because a cold `az` on Windows takes several seconds. One helper in `_credentials.py`, `azure_cli_token`, serves both the URL resolution and the provider.
3. **The provider acquires its own token from az.** The wrapper hands promptfoo no token: an `az` token in the environment would reach `{{ env.* }}` templating (decision 19 of the Data Agent Testing epic). Instead it sets `FAB_TEST_DATA_AGENT_AUTH=az` and writes no service-principal file. Tokens are cached per process and redacted as before.
4. **A failed az sign-in is final, with the fix** (aidd-polite-http): "az login gave no token for Fabric: … Run `az login` (add `--tenant <id>` for the workspace's tenant)." It is said once, at run level, like every other cause. The tenant is whichever one `az login` chose.
5. **401 and 403 name the identity in use**: the service principal, or your az login.

## Tasks

### Shared az token

Given az is signed in, should return the token and its expiry for the scope. Given az is not signed in or not installed, should raise one sentence naming `az login`. Given az reports an authentication error, should raise it redacted with the same fix.

**Status**: ✅ `azure_cli_token`, `data_agent_auth` and the `_cli_credential` seam in `_credentials.py`. A conftest guard refuses the real `az` in every test, because with no principal a test would quietly sign in as the developer (it did, once).

### Provider

Given `FAB_TEST_DATA_AGENT_AUTH=az`, should take its token from az even when a service principal is set, and send no request to the token endpoint. Given no service principal and no mode, should use az. Given a half-set principal, should still refuse. Given az fails, should be final, one sentence, no retry. Given 401 or 403 under az, should name the az login identity.

**Status**: ✅ `_auth_mode`, `_az_token`, and identity-aware 401/403 messages in the provider.

### Wrapper and CLI

Given `--auth az`, the wrapper should write no service-principal file and pass the mode, and the run should resolve the agent URL with an az token. Given `--auth service-principal` and nothing set, should exit 127 without starting promptfoo. Given nothing set and no `--auth`, should use az. The command builder should forward `--auth`.

**Status**: ✅ `--auth` on `fab-test data-agent` and the wrapper; `_client` signs in with az for URL resolution; the command builder forwards it.

### Documentation

`flags.md` and `credentials.md` (both copies), the walkthrough's troubleshooting, and `CHANGELOG.md`.

**Status**: ✅ Both skill copies (SKILL.md: who asks, when to rerun with `--auth az`, CI with OIDC), `credentials.md`, `flags.md`, the walkthrough, CHANGELOG.

### Quality gates

ruff, ratchets, full suite, then one live run with `--auth az`.

**Status**: ⚠️ ruff clean, ratchets pass, 3816 passed + 2 skipped (parallel half). Live: `--auth az` signed in and listed workspaces, but `az login` is in another tenant than the workspace; rerun after `az login --tenant <workspace tenant>`. Playwright half not run (the principal is blocked).
