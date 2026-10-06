# Release runbook

Everything the publish workflows cannot do for themselves, in the order it has to
happen. The workflows handle build, metadata checks, upload, and post-upload
verification; what is left is the part that needs a human with the account, and
the one-line version bump that starts it.

Two indexes, two workflows, and they never overlap:

| | Rehearsal | Production |
|---|---|---|
| Index | TestPyPI | PyPI |
| Workflow | [`.github/workflows/publish-testpypi.yml`](../.github/workflows/publish-testpypi.yml) | [`.github/workflows/publish.yml`](../.github/workflows/publish.yml) |
| GitHub environment | `testpypi` | `pypi` |
| Fires on | `workflow_dispatch`, or a dev tag (`v1.0.0.0.dev1`, `v1.8.1b1.dev2`) | A final tag (`v1.0.0`, `v1.0.0.0`) or a public pre-release tag (`v1.8.1b1`, `v2.0.0a1`, `v1.0.1rc2`) |
| Guard | — | `check_release_target.py` reads the version out of the built wheel and refuses a dev release or a tag that disagrees with it |

A publish cannot be undone. Both indexes refuse a second upload of a version, so
a wrong file is the file everyone installs, permanently. That is why the
rehearsal path exists and why the production guard reads the wheel rather than
trusting the tag.

---

## One-time setup: register the trusted publishers

**Only a human with the account can do this**, and neither workflow can succeed
until it is done — trusted publishing exchanges the workflow's OIDC token for an
upload token, so there is no secret to add and nothing to fall back on.

Do it *before* the first publish, using each index's **pending** publisher form
(the project does not exist yet, which is what "pending" means).

### TestPyPI

Sign in as **`jkerski`** at <https://test.pypi.org/manage/account/publishing/> and
add a pending publisher with exactly these values:

| Field | Value |
|---|---|
| PyPI Project Name | `cft-fab-test` |
| Owner | `clientfirsttech` |
| Repository name | `fab-test` |
| Workflow name | `publish-testpypi.yml` |
| Environment name | `testpypi` |

### PyPI

Same form at <https://pypi.org/manage/account/publishing/>, one workflow filename
and one environment name different:

| Field | Value |
|---|---|
| PyPI Project Name | `cft-fab-test` |
| Owner | `clientfirsttech` |
| Repository name | `fab-test` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

Trusted publishing resolves by **distribution name**, not repository name. The
distribution is `cft-fab-test`; the repository is `fab-test`, and the one this
grew out of was `fabric-ci-cd-dataops`. Registering either repository name
would authorize a project nobody is publishing.

Why the prefix: PyPI refuses `fab-test` as too similar to the unrelated
[`fabtest`](https://pypi.org/project/fabtest/) (it compares names with `-`,
`_`, and `.` stripped). TestPyPI does not run that check, which is why an older
`fab-test` project exists there; it is abandoned, and nothing publishes to it.
Only the distribution name changed -- the `fab-test` console script and the
`fab_test` import package did not.

The owner is the GitHub organization the workflow runs in
(`clientfirsttech`), not a personal account. A publisher registered under the
wrong owner fails with `invalid-publisher` even though every other field
matches.

Also create both GitHub environments (Settings → Environments) with the names
`testpypi` and `pypi`. A workflow naming an environment that does not exist fails
before it reaches the upload step.

---

## Cutting a pre-release

### 1. Bump the version — one file

`src/fab_test/__init__.py` is the only place the version is written.
`pyproject.toml` reads it through `[tool.setuptools.dynamic]`, so there is no
second place to keep in step.

```python
__version__ = "1.0.0.0.dev2"
```

TestPyPI refuses a repeat upload of a version, so **every rehearsal needs a fresh
one**. Bump the `devN` suffix, not the release part.

### 2. Rehearse without a tag

Run **Publish to TestPyPI** from the Actions tab (`workflow_dispatch`). Prefer
this to tagging: a tag is a claim about a commit, and needing to move one to
retry a release is how a tag ends up describing the wrong tree.

The workflow builds, asserts the wheel's contents, runs `twine check --strict`,
uploads, and then installs what it just published into a clean venv and runs the
console script. That last step is the point — a wheel that builds is not evidence
that a wheel an index serves installs.

### 3. Or tag, once the dispatch is green

```bash
git tag v1.0.0.0.dev2
git push origin v1.0.0.0.dev2
```

### 4. Verify by hand

```bash
python -m venv /tmp/verify
/tmp/verify/bin/pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple \
  "cft-fab-test==1.0.0.0.dev2"

/tmp/verify/bin/fab-test --version
/tmp/verify/bin/fab-test doctor --local
/tmp/verify/bin/fab-test config --show     # names the layer each metadata file came from
```

Run it from a directory that is **not** a checkout of this repository. Inside the
checkout, `.github/metadata/` satisfies every lookup, so a wheel that ships no
rulesets at all would still appear to work.

The index can lag a minute or two behind a successful upload; the workflow
retries for that reason, and a manual install may need the same patience.

### Why the install command looks like that

- **`--extra-index-url https://pypi.org/simple`** — TestPyPI carries
  `pql-test` 0.1.11; this project requires `pql-test==0.1.17`. Without the
  production index alongside it the install fails to resolve, which reads
  as a broken package and is not one.
- **The exact pin** — `1.0.0.0.dev2` is a PEP 440 dev release. pip skips
  pre-releases unless you name a version exactly or pass `--pre`, so a bare
  `pip install cft-fab-test` finds no acceptable version even once the project
  exists.

---

## Cutting a public beta (alpha, beta, rc)

A beta goes to **production PyPI**, where pip hides it from a bare
`pip install cft-fab-test` and serves it to `--pre` or an exact pin. Only a dev
release (`.devN`) is refused there.

1. Set `__version__` to the beta (`1.8.1b1`). PEP 440 spelling: no dot or dash
   before `b1`.
2. Rehearse it on TestPyPI first by dispatching **Publish to TestPyPI** -- a
   `b`/`rc` tag no longer reaches that workflow, so dispatch is the only way in.
3. Tag and push from `main`:

   ```bash
   git tag v1.8.1b1
   git push origin v1.8.1b1
   ```

4. `publish.yml` fires, uploads to PyPI, and creates a GitHub Release marked as
   a **pre-release**, so it never becomes the repository's "Latest release".
5. A fix to a beta is the next beta (`1.8.1b2`): PyPI never accepts the same
   version twice.

---

## Cutting a final release

1. Set `__version__` to the final value (`1.0.0.0`) — no `dev`, `a`, `b`, or `rc`.
2. Tag it and push:

   ```bash
   git tag v1.0.0.0
   git push origin v1.0.0.0
   ```

3. `publish.yml` fires, runs the same build and metadata checks, then
   `check_release_target.py` before the upload — it refuses a dev release
   and refuses a tag that disagrees with the wheel. A guard that ran after the
   upload would guard nothing.
4. On success it publishes to PyPI and creates a GitHub Release with generated
   notes.
5. Update the README's install section: after the first final release a bare
   `pip install cft-fab-test` works, so the "beta" wording and the `--pre`
   advice have to go.
6. Leave the logo's `raw.githubusercontent.com` URL in the README as an
   absolute link, not a relative one. README.md is the literal
   `long_description` uploaded to both indexes (`readme = "README.md"` in
   `pyproject.toml`); a relative image path renders on GitHub but shows as a
   broken image on PyPI/TestPyPI, which have no repository context.

---

## For a pipeline that consumes `fab-test`

Copy-pasteable, pinned to the pre-release, with the extra index that makes it
resolvable:

```yaml
- name: Install fab-test (TestPyPI pre-release)
  run: |
    pip install \
      --index-url https://test.pypi.org/simple/ \
      --extra-index-url https://pypi.org/simple \
      "cft-fab-test==1.9.0b3"

- name: Check readiness
  run: fab-test doctor --format json

- name: Run analyzers
  run: fab-test all --format json --artifact-dir fabric-artifacts

- name: Upload run manifest
  uses: actions/upload-artifact@v4
  if: always()
  with:
    name: fab-test-run-manifest
    path: fab-test-results/run.json
```

After the first final release, drop both index flags and pin normally
(`pip install "cft-fab-test==1.0.0.0"`).

The optional telemetry extras resolve from the same indexes and need the same
`--extra-index-url` while the package lives on TestPyPI, because their Azure SDK
dependencies (`azure-kusto-data`/`azure-kusto-ingest` for Eventhouse,
`azure-storage-file-datalake` for Lakehouse) are only on production PyPI. Install
either extra alone, or both together for both destinations:

```bash
pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple \
  "cft-fab-test[telemetry]==1.4.2.dev1"

pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple \
  "cft-fab-test[telemetry,telemetry-lakehouse]==1.4.2.dev1"
```

Keep `--artifact-dir` explicit in CI, and see
[QUICK-VALIDATION.md](QUICK-VALIDATION.md#pipeline-snippet-doctor-as-a-gate-runjson-as-the-artifact)
for why, plus what `run.json` carries when a build goes red.

### Stay current on tool pins (`tool-currency.yml`)

A wrapped tool's pin (Tabular Editor, PBIR Inspector) travels inside
`analyzers.json`, so the only way a consuming pipeline receives a bump is by
installing a newer `fab-test`. This job checks weekly and opens an issue when
one is available, mirroring
[`.github/workflows/check-tool-updates.yml`](../.github/workflows/check-tool-updates.yml)
in this repository but scoped to the package itself rather than its
dependencies:

```yaml
name: fab-test tool currency

on:
  schedule:
    - cron: "0 6 * * 1"
  workflow_dispatch:

permissions:
  contents: read
  issues: write

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - name: Compare the installed pin against the index
        id: check
        run: |
          current=$(pip show fab-test | grep '^Version:' | cut -d' ' -f2)
          latest=$(pip index versions fab-test 2>/dev/null | head -1 | grep -oE '[0-9][0-9a-zA-Z.]*' | head -1)
          echo "current=$current" >> "$GITHUB_OUTPUT"
          echo "latest=$latest" >> "$GITHUB_OUTPUT"

      - name: Open an issue if a newer fab-test is available
        if: steps.check.outputs.current != steps.check.outputs.latest
        uses: actions/github-script@v7
        with:
          script: |
            const title = `fab-test update available: ${{ steps.check.outputs.current }} -> ${{ steps.check.outputs.latest }}`;
            const open = await github.rest.issues.listForRepo({
              owner: context.repo.owner, repo: context.repo.repo,
              state: "open", labels: "tool-update",
            });
            if (open.data.some((issue) => issue.title === title)) return;
            await github.rest.issues.create({
              owner: context.repo.owner, repo: context.repo.repo,
              title,
              body: "A newer fab-test release may carry an updated tool pin. See https://github.com/clientfirsttech/fab-test/blob/main/docs/RELEASE.md",
              labels: ["tool-update"],
            });
```

---

## For the agent

The same install commands and the metadata resolution order live in
[`.github/skills/fab-test/SKILL.md`](../.github/skills/fab-test/SKILL.md), so an
agent reads them from its skill rather than from this file.

---

## Bumping a wrapped tool's pin

`fab-test` wraps four external tools (`pbir_inspector`, `tabular_editor_bpa`,
`pql_test`, and whichever others `analyzers.json` lists), each pinned by a
`tool_install.version` field so `doctor` and the cache can tell a stale binary
from a current one. [`.github/workflows/check-tool-updates.yml`](../.github/workflows/check-tool-updates.yml)
runs weekly, and opens an issue labeled `tool-update` naming any tool whose
upstream has moved past the pin — that issue is normally what starts this
procedure, though `python tools/check_tool_updates.py` can be run by hand too.

1. **Edit the pin** in
   [`src/fab_test/metadata/analyzers.json`](../src/fab_test/metadata/analyzers.json):
   bump `tool_install.version` to the new release.
2. **Record a fresh checksum per platform.** Download each platform's asset for
   the new version and hash it:

   ```bash
   sha256sum <downloaded-asset>
   ```

   Write the result into `tool_install.install_sha256` (one hash) or
   `install_sha256s` (`{"linux": ..., "win32": ..., "darwin": ...}`), matching
   whichever key the tool's existing entry already uses. A pin without a
   matching hash is worse than no pin — it lets a corrupted or substituted
   download through silently.
3. **Verify locally**, from a checkout with the analyzer's old cache still on
   disk, that `fab-test doctor` reports the tool as not-yet-downloaded (the
   version-keyed cache directory means the new pin cannot resolve the old
   binary), then let it download and confirm the new version resolves cleanly:

   ```bash
   fab-test doctor --local
   ```
4. **Run the full test suite** — `analyzers.json` changes are covered by
   `tests/test_fab_test_tool_bootstrap.py` and `tests/test_readiness.py`, among
   others.
5. **Commit** the `analyzers.json` change with a message naming the tool and
   the version, e.g. `chore(tools): bump tabular_editor_bpa to 2.29.0`.

`pql_test`'s entry deliberately carries no `version` field — it tracks the
`pql-test==` pin in `pyproject.toml` instead, via `release_source.version_source
== "pyproject.toml"`, so that version has exactly one place to change (see
"Bump the version" above; the same file, different reason).

---

## When a publish fails

| Symptom | Cause |
|---|---|
| `invalid-publisher` / OIDC rejected at upload | The pending publisher was never registered, or one of its five fields does not match — most often the workflow filename or the environment name |
| `File already exists` on PyPI | That version is spent. Bump `__version__` and cut a new tag; it cannot be overwritten |
| TestPyPI job green but nothing uploaded | `skip-existing: true` is deliberate — re-running a dispatch on an unchanged tree should not fail the job. Bump the `devN` suffix to actually publish |
| `check_release_target.py` refuses the release | Either the version is a pre-release (send it to TestPyPI) or the tag disagrees with the built wheel. Fix `__version__` or the tag; do not bypass the check |
| Clean-venv install cannot resolve dependencies | The `--extra-index-url` is missing, or you dropped the exact pin |
| Analyzers fail on a fresh install with a missing `BPARules.json` | The wheel shipped without its metadata. `check_wheel_contents.py` asserts those files by name and runs in both publish workflows — check whether it was made to pass by weakening it |
