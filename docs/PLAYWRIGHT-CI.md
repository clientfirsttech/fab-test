# Running `fab-test playwright` against a Fabric workspace

`fab-test playwright` opens each published report in a real browser, page by page, and fails the run when a visual doesn't render. It is the one analyzer that needs a **service principal**: it has to generate an embed token, and an `az login` session can't do that.

This guide takes you from nothing to a passing local run. Do these steps in order. Each step is a prerequisite for the next, and the local run at the end is how you know the setup is right before you involve CI.

| Step | Where | Who usually does it |
|------|-------|---------------------|
| [1. Register the service principal](#1-register-the-service-principal) | Entra ID (Azure portal) | Entra app admin |
| [2. Allow service principals in the tenant](#2-allow-service-principals-in-the-tenant) | Fabric admin portal | Fabric admin |
| [3. Give it a workspace role](#3-give-it-a-workspace-role) and enable XMLA | Fabric workspace and capacity | Workspace and capacity admins |
| [4. Deploy the reports you want to test](#4-deploy-the-reports-you-want-to-test) | Fabric workspace | You |
| [5. Run it locally](#5-run-it-locally) | Your machine | You |

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

By default every page, each page's bookmarks, and (when RLS is on) every role is tested. Add `--pages none --roles none` for a quick single-case smoke test.

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

## Exit codes

| Exit | Meaning | What to do |
|------|---------|------------|
| `0` | Every case rendered | Nothing |
| `1` | A case failed to render, **or** setup is incomplete: missing credentials, no environment, or a report name that isn't in the workspace | Read the line under `▶ fab-test playwright`. A setup problem names the variable or flag to set; a render failure names the visual |

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
| `fab-test auth status` says the workspace isn't reachable, but runs succeed | Without `--env-file`, `auth status` checks reachability with your Azure sign-in, not the service principal | Pass `--env-file .fab-test/.env` |

## Next: run it in GitHub Actions

Once the local run passes, the same variables go into a GitHub Environment's secrets, and a workflow installs the browser and runs the same command. That workflow and its setup are documented in the next section of this guide.
