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
| Fires on | `workflow_dispatch`, or a pre-release tag (`v1.0.0.0.dev1`, `v1.0.1rc2`, `v1.0.1b3`) | A final tag only (`v1.0.0` or `v1.0.0.0`) |
| Guard | — | `check_release_target.py` reads the version out of the built wheel and refuses a pre-release or a tag that disagrees with it |

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
| PyPI Project Name | `fab-test` |
| Owner | `kerski` |
| Repository name | `fab-test` |
| Workflow name | `publish-testpypi.yml` |
| Environment name | `testpypi` |

### PyPI

Same form at <https://pypi.org/manage/account/publishing/>, one workflow filename
and one environment name different:

| Field | Value |
|---|---|
| PyPI Project Name | `fab-test` |
| Owner | `kerski` |
| Repository name | `fab-test` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

Trusted publishing resolves by **distribution name**, not repository name. The
distribution is `fab-test`; the repository this grew out of was
`fabric-ci-cd-dataops`. Registering the latter would authorize a project nobody
is publishing.

Also create both GitHub environments (Settings → Environments) with the names
`testpypi` and `pypi`. A workflow naming an environment that does not exist fails
before it reaches the upload step.

---

## Cutting a pre-release

### 1. Bump the version — one file

`src/fabric_ci_cd_dataops/__init__.py` is the only place the version is written.
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
  "fab-test==1.0.0.0.dev2"

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
  `pql-test` 0.1.11 and `fabric-cicd` 0.1.7; this project requires
  `pql-test==0.1.12` and a current `fabric-cicd`. Without the production index
  alongside it the install fails to resolve, which reads as a broken package and
  is not one.
- **The exact pin** — `1.0.0.0.dev1` is a PEP 440 dev release. pip skips
  pre-releases unless you name a version exactly or pass `--pre`, so a bare
  `pip install fab-test` finds no acceptable version even once the project
  exists.

---

## Cutting a final release

1. Set `__version__` to the final value (`1.0.0.0`) — no `dev`, `a`, `b`, or `rc`.
2. Tag it and push:

   ```bash
   git tag v1.0.0.0
   git push origin v1.0.0.0
   ```

3. `publish.yml` fires, runs the same build and metadata checks, then
   `check_release_target.py` before the upload — it refuses a pre-release version
   and refuses a tag that disagrees with the wheel. A guard that ran after the
   upload would guard nothing.
4. On success it publishes to PyPI and creates a GitHub Release with generated
   notes.
5. Update the README's install section: once the project exists on PyPI,
   `pip install fab-test` is true for the first time and the "not yet" wording
   has to go.

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
      "fab-test==1.0.0.0.dev1"

- name: Check readiness
  run: fab-test doctor --format json

- name: Run analyzers
  run: fab-test all --format json --artifact-dir .fabric/artifacts

- name: Upload run manifest
  uses: actions/upload-artifact@v4
  if: always()
  with:
    name: fab-test-run-manifest
    path: analyzer-results/run.json
```

After the first final release, drop both index flags and pin normally
(`pip install "fab-test==1.0.0.0"`).

Keep `--artifact-dir` explicit in CI, and see
[QUICK-VALIDATION.md](QUICK-VALIDATION.md#pipeline-snippet-doctor-as-a-gate-runjson-as-the-artifact)
for why, plus what `run.json` carries when a build goes red.

---

## For the agent

The same install commands and the metadata resolution order live in
[`.github/skills/fab-test/SKILL.md`](../.github/skills/fab-test/SKILL.md), so an
agent reads them from its skill rather than from this file.

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
