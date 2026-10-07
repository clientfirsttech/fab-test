# Running `fab-test playwright` against a Fabric workspace

`fab-test playwright` opens each published report in a real browser, page by page, and fails the run when a visual doesn't render. It is the one analyzer that needs a **service principal**: it has to generate an embed token, and an `az login` session can't do that.

This guide takes you from nothing to a passing local run, then to the same run in GitHub Actions. Prefer the Azure CLI to the portal? [GETTING-STARTED.md](GETTING-STARTED.md) scripts steps 1 and 3 below with `az`, including writing the client secret straight to `.fab-test/.env`. Do these steps in order. Each step is a prerequisite for the next, and the local run is how you know the setup is right before you involve CI.

| Step | Where | Who usually does it |
|------|-------|---------------------|
| [1. Register the service principal](#1-register-the-service-principal) | Entra ID (Azure portal) | Entra app admin |
| [2. Allow service principals in the tenant](#2-allow-service-principals-in-the-tenant) | Fabric admin portal | Fabric admin |
| [3. Give it a workspace role](#3-give-it-a-workspace-role) and enable XMLA | Fabric workspace and capacity | Workspace and capacity admins |
| [4. Deploy the reports you want to test](#4-deploy-the-reports-you-want-to-test) | Fabric workspace | You |
| [5. Run it locally](#5-run-it-locally) | Your machine | You |
| [Run it in GitHub Actions](#next-run-it-in-github-actions) | GitHub repository settings | You |

## 1. Register the service principal

1. In the Azure portal, go to **Microsoft Entra ID → App registrations → New registration**. Give it a name your admins will recognize (e.g. `fab-test-playwright`), leave it single-tenant, and register it.
2. On the app's **Overview** page, copy the **Directory (tenant) ID** and the **Application (client) ID**.
3. Under **API permissions → Add a permission → Power BI Service**, add these permissions, then choose **Grant admin consent**:

   | Permission | Used for |
   |------------|----------|
   | `App.Read.All` | Reading Power BI apps |
   | `Dataset.Read.All` | Reading semantic models (datasets) |
   | `SemanticModel.Read.All` | Discovering a model's RLS roles |
   | `Report.Read.All` | Discovering a report's pages and bookmarks |
   | `Workspace.Read.All` | Finding the workspace and its items |

4. Under **Certificates & secrets → Client secrets**, create a secret and copy its **Value** right away. The portal shows it only once.
5. Create an Entra **security group** (e.g. `sg-fabric-service-principals`) and add the app to it. The tenant setting in step 2 is granted to a group, not to an individual app.

Those three values map to the variables `fab-test` reads:

| Portal value | Variable |
|--------------|----------|
| Directory (tenant) ID | `FABRIC_TENANT_ID` |
| Application (client) ID | `FABRIC_CLIENT_ID` |
| Client secret value | `FABRIC_CLIENT_SECRET` |

`FABRIC_SERVICE_PRINCIPAL_ID` / `FABRIC_SERVICE_PRINCIPAL_SECRET` are accepted as aliases for the last two.

If page or role discovery can't list what it needs, the run logs a warning and tests only the default page and role instead of failing. A missing permission there shows up as fewer test cases, not a red build.

## 2. Allow service principals in the tenant

A Fabric administrator enables these in the **Fabric admin portal → Tenant settings → Developer settings**, scoped to the security group from step 1 rather than the whole organization:

- **Service principals can use Fabric APIs** (older tenants label it *Allow service principals to use Power BI APIs*). Without it, every API call gets `401`/`403`, however the rest is configured. This is the most common silent blocker.
- **Embed content in apps**. Playwright renders each report through the embedding SDK.
- **Dataset Execute Queries REST API** (under *Integration settings*). Only needed for paginated reports with parameters: fab-test runs each parameter's own valid-values query to pick the values it tests. Without it, those reports are tested with no parameters and a warning names this setting.

Tenant setting changes can take up to about 15 minutes to take effect.

## 3. Give it a workspace role

In the target workspace, choose **Manage access → Add people or groups**, add the app (or its security group), and give it the **Member** role. Do the same for every workspace you test. Don't use Viewer.

### Enable XMLA endpoint access

Each workspace you test must be on a capacity (Fabric, Premium, or Premium Per User) with the XMLA endpoint enabled. A capacity admin sets this under **Admin portal → Capacity settings → (your capacity) → Power BI workloads → XMLA Endpoint**. The same service principal can then also run `fab-test pql-test`, which queries the model over XMLA.

## 4. Deploy the reports you want to test

Playwright tests the **published** report in the workspace, not the `.Report` folder on disk. Your local folder name has to match the report's name in the workspace. If it doesn't, the run fails and lists the closest names that do exist, for example:

```text
No Report matching 'ThinReport' in workspace 798dfd00-…. Closest candidates: SampleModel-PQLAssert, Not Working Visuals, Report with Bookmarks - Broken Visuals.
```

Deploying is out of scope for `fab-test`. Use Git integration, deployment pipelines, or your own CI/CD for that step.

## 5. Run it locally

Install `fab-test` (see [Install](../README.md#install)), then the browser Playwright drives and the pytest plugins that run it. All are separate from the `fab-test` package itself -- `pytest`, `pytest-playwright`, and `pytest-html` are dev-only dependencies of the `fab-test` project, not something installing `fab-test` pulls in for you, and `pytest-xdist` is needed the moment more than one case runs, which is the default for any report with more than one page:

```bash
playwright install chromium
pip install pytest pytest-playwright pytest-html pytest-xdist
```

Skipping this step fails with a raw `pytest` usage error (`unrecognized arguments: --html=...`) rather than a `fab-test`-style remediation message -- if you see that, this is almost always why.

### Put the credentials in `.fab-test/.env`

```dotenv
# .fab-test/.env  -- never commit this file
FABRIC_TENANT_ID=<directory (tenant) id>
FABRIC_CLIENT_ID=<application (client) id>
FABRIC_CLIENT_SECRET=<client secret value>
```

`fab-test` finds this file without a flag. It checks `--env-file`, then `PLAYWRIGHT_ENV_FILE`, then `.fab-test/.env`, then `./.env`. `fab-test init` scaffolds `.fab-test/` with a `.gitignore` that keeps `.env` out of Git.

### Name the workspace and environment

Export these in your shell. They are the same variables the CI workflow sets, so what works here works there:

```bash
export FABRIC_WORKSPACE_ID=<workspace GUID>
export FABRIC_ENVIRONMENT=dev      # a label for the run; any value works when the workspace is set
```

On PowerShell:

```powershell
$env:FABRIC_WORKSPACE_ID = "<workspace GUID>"
$env:FABRIC_ENVIRONMENT  = "dev"
```

Set both as real environment variables. Putting them in `.fab-test/.env` does not work: `doctor` and workspace resolution read them from the process environment only.

### Check readiness, then run

```bash
fab-test doctor
```

Look for:

```text
✅ playwright: workspace configured, credentials from .fab-test/.env
```

If the row is ❌, its `→` line names exactly what's missing. Then run one report:

```bash
fab-test playwright --artifact "SampleModel-PQLAssert" --report
```

A passing run ends like this and exits `0`:

```text
  ✅  SampleModel-PQLAssert  — no findings
```

By default every page, each page's bookmarks, and (when RLS is in play) every role is tested -- one case per page, plus one per that page's own bookmark, repeated per role. Add `--pages none --roles none` for a quick single-case smoke test, or `--plan-only` to write the matrix to `test-cases.csv` and stop without minting a token or launching a browser.

A paginated report is tested with no parameters and, when it declares any, once more with a parameter set -- the first valid value of each single-value parameter, the first two of each multi-value one, applied at embed time. Reading those values runs the parameter's own dataset query through `executeQueries`, which needs the **Dataset Execute Queries REST API** tenant setting to allow the service principal; without it, the report is still tested with no parameters and the run logs a warning naming the setting.

Role discovery needs an effective-identity user. Set `PLAYWRIGHT_USER_NAME` (as the workflow below does, from a secret) or declare `playwright_user_name` in `fab-test.yml`; with neither, a model's roles are discovered and the run stops before any token is minted rather than silently testing the default identity.

### What a failure looks like

Against a report with a broken visual, the same command exits `1` and names only the case that failed:

```text
  ❌  Not Working Visuals
```

`fab-test-results/playwright/<report>/envelope.json` records each case's own result and a direct link to the page it tested:

```json
{
  "test_name": "Not Working Visuals_14c428845591d434b53c_no-bookmark",
  "page_name": "Page 1",
  "status": "error",
  "actual": "Power BI error event fired: {\"message\":\"Missing_References\",\"detailedMessage\":\"Something's wrong with one or more fields.. Could not render a report visual titled: Sum of Column B by Column A\"}",
  "report_link": { "label": "Page 1", "href": "https://app.powerbi.com/groups/…/reports/…/14c428845591d434b53c" }
}
```

`--report` writes `report.html` next to it, which links each case to its screenshot.

## Azure-hosted browsers

This optional backend runs only the browsers on Azure. Python Playwright,
pytest, and xdist run on your machine or CI runner; fab-test still generates
the same page/bookmark/role cases and writes the same verdicts and evidence.
No Node/npm runner, custom tests, cross-report sharding, or Azure portal
reporter is installed. The proof used Python Playwright 1.63.0 with
pytest-playwright 0.9.0; keep Playwright compatible with the workspace service.

1. Create or select an Azure Playwright workspace and enable **access-token
  authentication** in its authentication settings. This release uses a
  service access token, not Entra authentication for the browser service.
2. Copy its browser endpoint and create an access token. Store both locally
  in `.fab-test/.env`, never in committed YAML or a chat message:

  ```dotenv
  PLAYWRIGHT_SERVICE_URL=wss://<regional-host>/playwrightworkspaces/<workspace-id>/browsers
  PLAYWRIGHT_SERVICE_ACCESS_TOKEN=<service-access-token>
  ```

  Keep the three `FABRIC_*` credentials above: they generate Power BI embed
  tokens and are not substitutes for this browser-service token. Process
  environment values win over the selected env file. File selection is
  `--env-file` > `PLAYWRIGHT_ENV_FILE` > `.fab-test/.env` > `./.env`.
3. Install the Python pytest plugins from step 5. For Azure, skip the local
  Chromium download; Python connects to remote browsers instead.
4. Select the [credential-free example](examples/playwright/azure.yml):

  ```bash
  fab-test playwright --artifact "Not Working Visuals" --env DEV --report \
    --playwright-config docs/examples/playwright/azure.yml --workers 8
  ```

The selector resolves `--playwright-config` > `PLAYWRIGHT_CONFIG_PATH` >
`playwright_config` in fab-test config > local default. Flag/environment paths
are invocation-relative; config-key paths are relative to their owning file.
`fab-test config --show` shows the selection and origin. Set the environment
selector when using `doctor`; it checks credentials without connecting:

```powershell
$env:PLAYWRIGHT_CONFIG_PATH = "docs/examples/playwright/azure.yml"
fab-test doctor
fab-test config --show
```

Omitting a selector keeps local execution even if Azure credentials exist.
Use `backend: local` in YAML to customize local browsers without service
credentials. Supported keys are `backend`, positive `workers`, `launch`
(`headless`, string-list `args`, nonnegative `slow_mo`), `context` (`viewport`
width/height, `locale`, `timezone_id`, `color_scheme`, `ignore_https_errors`),
and Azure `connection` (`os`, `timeout_ms`, `expose_network`). Defaults are
Linux, 30000 ms connection timeout, and `<loopback>` exposure. Broader network
exposure is opt-in; choose it only when required for a trusted target.
`PLAYWRIGHT_TIMEOUT_SECONDS` still controls report rendering, not connection.
Arbitrary plugins, tests, reporters, and executable configurations are refused.

Workers resolve `--workers` > `PLAYWRIGHT_XDIST_WORKERS` > YAML > `4`.
Only cases within the current report are parallelized, capped by its case
count. Begin with a modest limit and respect your Azure service quota; more
workers do not guarantee faster reports. Contexts and browser sessions use
pytest-playwright's normal teardown.

For selected YAML, native pytest HTML and JUnit are written to
`<output-dir>/playwright/<report>/report/index.html` and `results.xml`.
The facade envelope, `report.html`, and `test-cases/` evidence keep their
existing locations. Connection/authentication failure becomes an execution
error, not a broken-visual finding; raw connection diagnostics are withheld
to avoid exposing authorization headers. There is no automatic local fallback.
Plan-only does not require the Azure token or launch a browser.

### Watching the browser locally

Browsers are hidden by default, which is what CI wants. For a live demonstration on a
developer machine, add `--headed` (optionally `--slow-mo 500` and `--workers 1`), or select
[`headed.yml`](examples/playwright/headed.yml). `PLAYWRIGHT_HEADLESS=false` also shows the window, at the
lowest precedence: YAML `launch.headless`, then `--headed`, override it. Do not use these in CI: a hosted runner has
no display, and Azure-hosted browsers ignore them with a warning.

### GitHub Actions and Azure DevOps

The [GitHub Actions example](examples/github-actions/playwright-azure.yml)
uses a protected Environment named `fabric-demo`. Add the existing Fabric
credential secrets plus `PLAYWRIGHT_SERVICE_ACCESS_TOKEN` to that Environment.
Store `PLAYWRIGHT_SERVICE_URL` and `FABRIC_WORKSPACE_ID` as Environment
variables; the example also accepts an existing endpoint secret. Configure
required reviewers and ensure the job's `environment:` name matches.

The [Azure DevOps example](examples/azure-devops/playwright-azure.yml) uses
an authorized variable group named `fabric-demo`. Mark
`FABRIC_CLIENT_SECRET` and `PLAYWRIGHT_SERVICE_ACCESS_TOKEN` secret, add the
tenant/client IDs, endpoint, workspace ID, and `PLAYWRIGHT_ARTIFACT`, and map
them explicitly into the test step's environment. Restrict group permissions.

Both examples build this repository's feature checkout with Python 3.12,
publish all result evidence after failure, and propagate fab-test's nonzero
exit code. For another repository, replace the source install with a pinned
fab-test release containing `--playwright-config` and the same Python pytest
plugins. These YAML examples were syntax-checked; live execution on either
CI platform is a separate validation, not implied by the local Azure proof.
Rotate tokens before expiry and immediately after accidental disclosure;
update local and CI stores together. Do not echo, commit, or pass tokens on
the command line. Browser offload does not upload results to the Azure portal.

## Exit codes

| Exit | Meaning | What to do |
|------|---------|------------|
| `0` | Every case rendered | Nothing |
| `1` | A case failed or an attempted run had an execution error | Read the envelope and remediation; browser-service errors are not visual findings |
| `2` | Invalid execution YAML or argument/configuration | Correct the named config path or setting |
| `127` | Missing credentials or other prerequisites | Set the named variables and run `doctor` again |

For example, an incomplete service principal names every missing variable:

```text
Playwright needs a full service principal to generate an embed token; missing: FABRIC_CLIENT_ID (or FABRIC_SERVICE_PRINCIPAL_ID), FABRIC_CLIENT_SECRET (or FABRIC_SERVICE_PRINCIPAL_SECRET). Set them in the environment, in a .env file, or pass --env-file.
```

Run `fab-test doctor` first in CI. It catches these setup problems before any browser starts.

## Troubleshooting

Every case writes its evidence to `fab-test-results/playwright/<report>/test-cases/<case>/`:

| File | Written when | Tells you |
|------|--------------|-----------|
| `screenshot.png` | Always | What the page looked like when the case finished |
| `console.json` | The browser logged errors | Failed requests (`400`/`401`/`403`) and script errors |
| `network.json` | There were failed network calls | Which API call failed |
| `event_log.json` | A render failed or timed out | The embed SDK's event history (`loaded`, `rendered`, `error`) |
| `embed_error_details.txt` | A timeout where Power BI showed an error panel | The panel's text, usually a permission or token-scope message |

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `doctor` shows ❌ *no workspace or credentials resolved* | `FABRIC_WORKSPACE_ID` isn't exported in this shell | [Name the workspace](#name-the-workspace-and-environment) |
| *ERROR: usage: python -m pytest …* / *unrecognized arguments: --html=…* | `pytest`, `pytest-playwright`, `pytest-html`, or `pytest-xdist` isn't installed | [Run it locally](#5-run-it-locally) -- `pip install` all four |
| *No environment given, so there is nothing to resolve…* | `FABRIC_ENVIRONMENT` isn't set and `--env` wasn't passed | Export `FABRIC_ENVIRONMENT` or add `--env dev` |
| *No Report matching '…'* | The report isn't deployed, or has a different name | [Step 4](#4-deploy-the-reports-you-want-to-test) |
| `401` / `403` in `console.json`, or a permissions message in `embed_error_details.txt` | Tenant setting not applied, or no workspace role | [Step 2](#2-allow-service-principals-in-the-tenant), [step 3](#3-give-it-a-workspace-role) |
| *did not render within 180000ms* | A slow page or a large model | Raise `PLAYWRIGHT_TIMEOUT_SECONDS` (default `180`) |
| Only one case ran when you expected several | Page or role discovery couldn't list them (a warning was logged) | Check `Report.Read.All` and `SemanticModel.Read.All` have admin consent ([step 1](#1-register-the-service-principal)) and the workspace role ([step 3](#3-give-it-a-workspace-role)) |
| A paginated report with parameters ran only its no-parameter case | Its valid-values query couldn't run (a warning names the parameter) | Enable **Dataset Execute Queries REST API** for the service principal's group ([step 2](#2-allow-service-principals-in-the-tenant)) |
| `fab-test auth status` says the workspace isn't reachable, but runs succeed | Without `--env-file`, `auth status` checks reachability with your Azure sign-in, not the service principal | Pass `--env-file .fab-test/.env` |

## Next: run it in GitHub Actions

Once the local run passes, the same values go into a GitHub Environment's secrets and variables, and a workflow installs the browser and its pytest plugins before running the same command.

### Create the GitHub Environment

1. In your repository, go to **Settings → Environments → New environment**, name it `fabric-demo` (or pick your own name and update the workflow's `environment:` key to match).
2. Optionally, under **Deployment protection rules**, add required reviewers -- a run against a real workspace then waits for approval before it starts.
3. Under **Environment secrets**, add:

   | Secret | Value |
   |--------|-------|
   | `FABRIC_TENANT_ID` | Directory (tenant) ID |
   | `FABRIC_CLIENT_ID` | Application (client) ID |
   | `FABRIC_CLIENT_SECRET` | Client secret value |

4. Under **Environment variables** (not secrets -- a workspace ID is metadata, not a credential), add:

   | Variable | Value |
   |----------|-------|
   | `FABRIC_WORKSPACE_ID` | The workspace GUID from [step 3](#3-give-it-a-workspace-role) |

### Copy the example workflow

[`docs/examples/github-actions/playwright-live.yml`](examples/github-actions/playwright-live.yml) is a complete workflow -- copy it into your own repository's `.github/workflows/`. It:

- Triggers only on `workflow_dispatch`, never `pull_request` -- a fork PR has no access to this Environment's secrets at all.
- Takes `artifact`, `dataset_id`, `dataset_workspace_id`, `pages`, and `roles` as dispatch inputs, so the one workflow covers all three ways of naming what to test (see [Targeting a report or a dataset](#targeting-a-report-or-a-dataset) below).
- Installs the published package, then the browser and its pytest plugins separately (see [Run it locally](#5-run-it-locally) for why those are separate).
- Runs `fab-test doctor` before the real command, so a misconfigured Environment fails fast with exit `127` naming what's missing.
- Uploads `fab-test-results/playwright/**` under `if: always()`, and writes a per-case pass/fail table to the job's step summary.

### Targeting a report or a dataset

The same three shapes from [`references/flags.md`](../.github/skills/fab-test/references/flags.md) work as dispatch inputs -- fill in exactly one when you run the workflow:

| Fill in | Runs |
|---------|------|
| `artifact` only | That one report |
| `dataset_id` (+ `dataset_workspace_id`) | Every report built on that dataset |
| `dataset_workspace_id` only | Every dataset in that workspace, each one's own dependent reports |

The last two need nothing local checked in -- they resolve entirely against Fabric, which is why a team with reports deployed straight from Power BI Desktop (no `.pbip` in the repository at all) can still run this workflow.

### Picking dev, test, or prod at dispatch time

The example workflow above reads one fixed `FABRIC_WORKSPACE_ID` per Environment -- simplest when you only ever run against one workspace from that Environment. A team that promotes through several workspaces (dev/test/prod) and wants to pick which one *at dispatch time*, without duplicating the Environment or the workflow, can do this instead:

1. Commit an `environments.yml` mapping each label to its workspace ID -- see [Configuration](.github/skills/fab-test/references/configuration.md#configuration) for the file's location and shape. Workspace IDs are metadata, not secrets, so this file is safe to check in.
2. Add an `environment` dispatch input (a `choice` of your labels), and pass it straight through as `--env ${{ inputs.environment }}` -- `fab-test` resolves the workspace from `environments.yml` itself, no `FABRIC_WORKSPACE_ID` Environment variable needed at all.
3. Add an optional `workspace_id` dispatch input too, passed as `--workspace-id` when non-empty. It wins over `--env`, so a workspace not yet in `environments.yml` -- or a one-off run against somewhere else entirely -- never needs a workflow edit.

`.github/workflows/playwright-demo.yml` in this repository is exactly this pattern, reading this repository's own `.fab-test/metadata/environments.yml`: `--env dev` already resolves to a real workspace with nothing else supplied, and `test`/`prod` fall back to the `workspace_id` override until their entries in that file carry a real workspace ID.


## Automated live CI

`.github/workflows/live-ci.yml` runs on every same-repository pull request, on
pushes to `main`/`dev`, and by hand. It uses the `fabric-demo` Environment's
service principal against the `visual-error-testing` workspace to check
`fab-test auth status`, a service-mode `rdl --workspace` run, and the live
parity tests (`pytest -m integration`). Fork and dependabot PRs are skipped
(they cannot read the secrets); the workflow never uses `pull_request_target`.
If the Environment requires reviewers, every run waits for approval.
