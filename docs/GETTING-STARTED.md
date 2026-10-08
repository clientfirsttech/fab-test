# Getting started: install to first Playwright run

This guide takes a new machine from nothing to a passing `fab-test playwright` run from the console. It goes in order: prerequisites, install, `fab-test init`, a service principal created with the Azure CLI, then the run.

Do the steps in order. Each step ends with a **Check** that tells you it worked before you go on.

> Only need static analysis (BPA, PBIR Inspector, DAX tests against Power BI Desktop)? That needs no service principal. See [QUICKSTART-LOCAL.md](QUICKSTART-LOCAL.md). For the same setup through the portal instead of the CLI, and the GitHub Actions setup that comes after it, see [PLAYWRIGHT-CI.md](PLAYWRIGHT-CI.md).

| Step | What you get | Who usually does it |
|------|--------------|---------------------|
| [0. Prerequisites](#0-prerequisites) | Tools and roles in place | You and your admins |
| [1. Install fab-test](#1-install-fab-test) | `fab-test` on `PATH` | You |
| [2. Initialize the repository](#2-initialize-the-repository) | `fab-test.yml` and `.fab-test/` | You |
| [3. Create the service principal](#3-create-the-service-principal-azure-cli) | App registration, API permissions, client secret in `.fab-test/.env` | Entra app admin |
| [4. Allow service principals in the tenant](#4-allow-service-principals-in-the-tenant) | Fabric tenant settings enabled for the service principal | Fabric admin |
| [5. Add the service principal to your workspaces](#5-add-the-service-principal-to-your-workspaces) | Member role on each workspace | Workspace admin |
| [6. Run Playwright from the console](#6-run-playwright-from-the-console) | A passing run | You |

The commands below are for bash (Linux, macOS, Git Bash, or WSL). Steps that differ in PowerShell show both versions.

## 0. Prerequisites

### Tools

| Tool | Version | Check |
|------|---------|-------|
| Python | 3.12 or later | `python --version` |
| Azure CLI | Recent 2.x | `az version` |
| Git | Any | `git --version` |

### Access

| What | Needed for |
|------|------------|
| Permission to create app registrations in Microsoft Entra ID | [Step 3](#3-create-the-service-principal-azure-cli) |
| A role that can grant tenant-wide admin consent (Global Administrator, Privileged Role Administrator, or Cloud Application Administrator) | [Step 3](#3-create-the-service-principal-azure-cli), admin consent |
| Fabric administrator | [Step 4](#4-allow-service-principals-in-the-tenant), tenant settings |
| **Admin** role on each workspace you want to test | [Step 5](#5-add-the-service-principal-to-your-workspaces) |
| Workspaces on a Fabric, Premium, or Premium Per User capacity | Embedding, and XMLA for `fab-test pql-test` |
| The reports you want to test, already published to the workspace | [Step 6](#6-run-playwright-from-the-console). fab-test does not deploy reports |

You don't need to hold every role yourself. Give each admin the step that matches their role.

## 1. Install fab-test

The package is `cft-fab-test`. The command it installs is `fab-test`. Work in your Power BI project repository, not in a clone of fab-test.

```bash
cd <your-power-bi-repo>
python -m venv .venv
source .venv/bin/activate            # PowerShell: .venv\Scripts\Activate.ps1

pip install "cft-fab-test==1.9.0b5"  # or: pip install --pre cft-fab-test
```

Playwright needs a browser and some pytest plugins. The plugins come with the `playwright` extra; the browser is a separate download:

```bash
pip install "cft-fab-test[playwright]"
playwright install chromium           # Linux: playwright install --with-deps chromium
```

If you skip this, the run fails with a raw pytest error (`unrecognized arguments: --html=...`) instead of a fab-test remediation message.

**Check:**

```bash
fab-test --version
```

## 2. Initialize the repository

```bash
fab-test init
```

This writes three files and never overwrites one that already exists:

| File | Purpose | Commit it? |
|------|---------|------------|
| `fab-test.yml` | Commented settings: workspace, environment, and analyzer options | Your choice. Keep it out of Git if it holds personal values like `playwright_user_name` |
| `.fab-test/.gitignore` | Keeps `.fab-test/.env` out of Git | Yes |
| `.fab-test/.env.example` | Template for the credentials file | Yes |

Add `--dry-run` to see what it would write without writing anything.

**Check:**

```bash
fab-test config --show
```

## 3. Create the service principal (Azure CLI)

Playwright needs a service principal because it generates an embed token. An `az login` session can't generate one. This step creates the app registration and its service principal, adds the Power BI API permissions, grants admin consent, creates a client secret, and saves the credentials to `.fab-test/.env`.

Run this as the Entra app admin. Use one shell session for all of step 3, because later commands reuse the variables set by earlier ones.

### 3a. Sign in and create the app

```bash
az login                               # add --tenant <tenant-id> if you belong to more than one tenant
TENANT_ID=$(az account show --query tenantId -o tsv)

APP_NAME="fab-test-playwright"
APP_ID=$(az ad app create \
  --display-name "$APP_NAME" \
  --sign-in-audience AzureADMyOrg \
  --query appId -o tsv)

SP_OBJECT_ID=$(az ad sp create --id "$APP_ID" --query id -o tsv)

echo "Tenant:    $TENANT_ID"
echo "Client ID: $APP_ID"
echo "SP object: $SP_OBJECT_ID"
```

`APP_ID` is the **application (client) ID**, which is the value fab-test reads. `SP_OBJECT_ID` is the **service principal object ID**, which Fabric needs when you assign workspace roles in step 5. They're different GUIDs, so don't mix them up.

### 3b. Add the Power BI API permissions and grant consent

The permissions are scopes on the Power BI Service API (`00000009-0000-0000-c000-000000000000`). The loop looks up each permission's ID from your tenant, so no GUIDs are hard-coded:

| Permission | Used for |
|------------|----------|
| `App.Read.All` | Reading Power BI apps |
| `Dataset.Read.All` | Reading semantic models (datasets) |
| `SemanticModel.Read.All` | Discovering a model's RLS roles |
| `Report.Read.All` | Discovering a report's pages and bookmarks |
| `Workspace.Read.All` | Finding the workspace and its items |

```bash
PBI_API="00000009-0000-0000-c000-000000000000"

for SCOPE in App.Read.All Dataset.Read.All SemanticModel.Read.All Report.Read.All Workspace.Read.All; do
  SCOPE_ID=$(az ad sp show --id "$PBI_API" \
    --query "oauth2PermissionScopes[?value=='$SCOPE'].id | [0]" -o tsv)
  if [ -z "$SCOPE_ID" ]; then
    echo "Skipped $SCOPE: not found on the Power BI Service API in this tenant"
    continue
  fi
  az ad app permission add --id "$APP_ID" --api "$PBI_API" --api-permissions "$SCOPE_ID=Scope"
done

az ad app permission admin-consent --id "$APP_ID"
```

If `admin-consent` fails right after the app is created, wait a minute and run it again, since new apps take a moment to replicate. If your account can't grant consent, send the client ID to someone who can, or have them use **Grant admin consent** on the app's **API permissions** page in the portal.

If a permission is missing, discovery doesn't fail the run. It logs a warning and tests only the default page and role, so you get fewer test cases instead of a red build.

### 3c. Create a client secret and save it to `.fab-test/.env`

```bash
CLIENT_SECRET=$(az ad app credential reset \
  --id "$APP_ID" \
  --display-name "fab-test" \
  --years 1 \
  --append \
  --query password -o tsv)

mkdir -p .fab-test
(
  umask 077
  cat > .fab-test/.env <<EOF
FABRIC_TENANT_ID=$TENANT_ID
FABRIC_CLIENT_ID=$APP_ID
FABRIC_CLIENT_SECRET=$CLIENT_SECRET
EOF
)
unset CLIENT_SECRET
```

`--append` adds a secret without removing the app's existing ones. The secret is only returned once, and this script writes it straight to the file without printing it. Put a calendar reminder before the expiry date, because an expired secret causes a `401` error on every call.

PowerShell:

```powershell
$clientSecret = az ad app credential reset --id $APP_ID --display-name "fab-test" --years 1 --append --query password -o tsv
New-Item -ItemType Directory -Force .fab-test | Out-Null
@"
FABRIC_TENANT_ID=$TENANT_ID
FABRIC_CLIENT_ID=$APP_ID
FABRIC_CLIENT_SECRET=$clientSecret
"@ | Set-Content -Encoding utf8 .fab-test/.env
Remove-Variable clientSecret
```

(In PowerShell, set `$TENANT_ID` and `$APP_ID` the same way as in 3a. The `az` commands are the same; only variable syntax changes.)

fab-test finds this file without a flag. It checks `--env-file`, then `PLAYWRIGHT_ENV_FILE`, then `.fab-test/.env`, then `./.env`. It never prints the secret, writes it to results, or sends it in telemetry.

**Check:** confirm that Git ignores the file. The command should print the path:

```bash
git check-ignore .fab-test/.env
```

If it prints nothing, step 2 didn't run in this repository. Don't commit until it prints the path.

### 3d. Put the service principal in a security group

The tenant settings in step 4 are granted to a security group, not to an individual app:

```bash
GROUP_NAME="sg-fabric-service-principals"
GROUP_ID=$(az ad group create \
  --display-name "$GROUP_NAME" \
  --mail-nickname "$GROUP_NAME" \
  --query id -o tsv)

az ad group member add --group "$GROUP_ID" --member-id "$SP_OBJECT_ID"
```

If the group already exists, skip `create` and get its ID with `az ad group show --group "$GROUP_NAME" --query id -o tsv`.

**Check:**

```bash
az ad group member check --group "$GROUP_ID" --member-id "$SP_OBJECT_ID" --query value
```

## 4. Allow service principals in the tenant

A Fabric administrator enables these settings in the **Fabric admin portal → Tenant settings**, scoped to the security group from 3d:

| Setting | Section | Needed for |
|---------|---------|------------|
| **Service principals can use Fabric APIs** (older tenants: *Allow service principals to use Power BI APIs*) | Developer settings | Every API call. Without it, every call gets `401`/`403`. This is the most common silent blocker |
| **Embed content in apps** | Developer settings | Rendering each report through the embedding SDK |
| **Dataset Execute Queries REST API** | Integration settings | Only for paginated reports that have parameters |

Changes can take up to about 15 minutes to take effect.

**Check (Fabric admin only):** list the relevant settings and which groups they're scoped to:

```bash
az rest --method get \
  --resource "https://api.fabric.microsoft.com" \
  --url "https://api.fabric.microsoft.com/v1/admin/tenantsettings" \
  --query "tenantSettings[?contains(title, 'ervice principal') || contains(title, 'Embed content') || contains(title, 'Execute Queries')].{title:title, enabled:enabled, groups:join(', ', enabledSecurityGroups[].name || \`[]\`)}" \
  -o table
```

### Enable XMLA

A capacity admin turns on **Admin portal → Capacity settings → (your capacity) → Power BI workloads → XMLA Endpoint**. Playwright doesn't need it. `fab-test pql-test` uses the same service principal and does need it.

## 5. Add the service principal to your workspaces

Run this as a workspace **Admin**. First, find the workspace IDs:

```bash
az rest --method get \
  --resource "https://api.fabric.microsoft.com" \
  --url "https://api.fabric.microsoft.com/v1/workspaces" \
  --query "value[].{name:displayName, id:id}" -o table
```

Then give the service principal the **Member** role on each workspace you test. Use the **service principal object ID** from 3a, not the client ID:

```bash
for WORKSPACE_ID in <workspace-guid-1> <workspace-guid-2>; do
  az rest --method post \
    --resource "https://api.fabric.microsoft.com" \
    --url "https://api.fabric.microsoft.com/v1/workspaces/$WORKSPACE_ID/roleAssignments" \
    --headers "Content-Type=application/json" \
    --body "{\"principal\": {\"id\": \"$SP_OBJECT_ID\", \"type\": \"ServicePrincipal\"}, \"role\": \"Member\"}"
done
```

To grant access to the whole group instead, use `"id": "$GROUP_ID", "type": "Group"`. Don't use Viewer.

If you get `409`, the principal already has a role on that workspace. If you get `401` or `403`, you aren't a workspace Admin, or step 4 hasn't applied yet.

**Check:**

```bash
fab-test auth status --env-file .fab-test/.env --workspace-id <workspace-guid>
```

Exit `0` means the service principal signed in and can reach the workspace. Exit `1` means the credentials work but the workspace can't be reached, so recheck this step and step 4. Exit `127` means the credentials didn't resolve or couldn't get a token, so recheck step 3c.

## 6. Run Playwright from the console

Set the workspace and an environment label as real environment variables. Putting them in `.fab-test/.env` doesn't work.

```bash
export FABRIC_WORKSPACE_ID=<workspace-guid>
export FABRIC_ENVIRONMENT=dev
```

```powershell
$env:FABRIC_WORKSPACE_ID = "<workspace-guid>"
$env:FABRIC_ENVIRONMENT  = "dev"
```

To skip exporting these every time, set `workspace:` and `environment:` in `fab-test.yml` instead.

**Check readiness:**

```bash
fab-test doctor
```

Look for this line:

```text
✅ playwright: workspace configured, credentials from .fab-test/.env
```

If the line shows ❌, the `→` line under it names what's missing.

**Preview the plan without a browser or token:**

```bash
fab-test playwright --artifact "<Report Name>" --plan-only
```

This writes the page × bookmark × role matrix to `test-cases.csv` and stops.

**Run a quick smoke test (one case):**

```bash
fab-test playwright --artifact "<Report Name>" --pages none --roles none
```

**Run the full matrix with an HTML report:**

```bash
fab-test playwright --artifact "<Report Name>" --report
```

`<Report Name>` is the report's name **in the workspace**. If it doesn't match, the run lists the closest names. A passing run ends with `✅  <Report Name>  — no findings` and exits `0`. A render failure exits `1` and names the case that failed.

Results are written to `fab-test-results/playwright/<report>/`:

| Path | Contents |
|------|----------|
| `envelope.json` | One row per case: status, page, and a link back to the page in `app.powerbi.com` |
| `report.html` | Written with `--report`. Links each case to its screenshot |
| `test-cases/<case>/screenshot.png` | What the page looked like |
| `test-cases/<case>/console.json`, `network.json`, `event_log.json` | Evidence when a case fails |

If the model uses RLS, set `PLAYWRIGHT_USER_NAME` (or `playwright_user_name` in `fab-test.yml`) to a user in your tenant. Without it, the run stops before getting a token instead of testing the default identity.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `Playwright runs need pytest, ...` | the `playwright` extra isn't installed | [Step 1](#1-install-fab-test) |
| `missing: FABRIC_CLIENT_ID ... FABRIC_CLIENT_SECRET` | `.fab-test/.env` is incomplete or not found | [Step 3c](#3c-create-a-client-secret-and-save-it-to-fab-testenv) |
| `AADSTS7000215: Invalid client secret` | The secret has expired, or the secret **ID** was saved instead of its value | Run 3c again |
| `401` / `403` in `console.json` | A tenant setting hasn't applied, or the service principal has no workspace role | [Step 4](#4-allow-service-principals-in-the-tenant), [step 5](#5-add-the-service-principal-to-your-workspaces) |
| `doctor`: *no workspace or credentials resolved* | `FABRIC_WORKSPACE_ID` isn't exported in this shell | [Step 6](#6-run-playwright-from-the-console) |
| *No environment given...* | `FABRIC_ENVIRONMENT` isn't set and `--env` wasn't passed | [Step 6](#6-run-playwright-from-the-console) |
| *No Report matching '...'* | The report isn't published, or it has a different name | Publish it, or use the name the error suggests |
| Only one case ran | Page or role discovery is missing a permission (a warning was logged) | Recheck 3b consent and the step 5 role |

For more symptoms and the evidence files, see [PLAYWRIGHT-CI.md → Troubleshooting](PLAYWRIGHT-CI.md#troubleshooting).

## Next

- **CI:** put the same three values in a GitHub Environment's secrets and use [`examples/github-actions/playwright-live.yml`](examples/github-actions/playwright-live.yml). See [PLAYWRIGHT-CI.md → Run it in GitHub Actions](PLAYWRIGHT-CI.md#next-run-it-in-github-actions).
- **AI agents:** run `fab-test skill --install claude` or `fab-test skill --install copilot` so your agent has the full CLI reference.
- **Cleanup:** to remove everything from step 3, run `az ad app delete --id "$APP_ID"` (this also deletes the service principal), then `az ad group delete --group "$GROUP_ID"` if the group was created only for this.
