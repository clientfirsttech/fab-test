# Tool Version Currency Epic

**Status**: 🚧 IN-PROGRESS — 3 of 5 tasks done
**Goal**: Notice when a wrapped tool ships a new release, and make a released pin
bump actually reach the machines running it.

## Overview

WHY: `fab-test` is a facade over four upstream tools, and nothing in the repository
watches any of them. `pql-test` is pinned at `0.1.12` while PyPI carries `0.1.13`;
nobody noticed, because there is no mechanism that could. There is no
`.github/dependabot.yml` either, so the packaged dependencies are unwatched for the
same reason.

Worse, the delivery path for a fix is broken in a way that is invisible. The pins
live in `analyzers.json`, which ships inside the wheel, so the intended remedy is
"edit the URL, cut a fab-test release, users get it on upgrade." That does not work
today: `resolve_executable` consults the `.fab-test-tools` cache marker *before* the
install URL, and the cache is keyed by analyzer and platform but **not by version**.
Ship `analyzers.json` pointing at a new release and every existing checkout keeps
running the old binary, silently and forever. A version bump that reaches nobody is
worse than no bump at all, because the release notes claim otherwise.

This epic is deliberately small on shipped code. Task 3 is the only one that touches
the wheel; the rest is maintainer machinery that lives outside `src/`. An earlier
draft proposed a `fab-test update` command and a `fab-test check-updates`
subcommand — both were cut. `analyzers.json` already controls the URLs and the wheel
already distributes it, so a download-orchestration subsystem would have been a
second delivery mechanism competing with the one that works, and a subcommand whose
only real caller is a weekly cron job is surface in a file already 2,956 lines over
its 800-line budget. Per the simplicity constraint in [vision.md](../vision.md):
no abstraction until the second caller.

### What discovery found

| Finding | Consequence |
|---------|-------------|
| `pql-test` pinned `0.1.12`, PyPI has `0.1.13` | One pin is stale today |
| `tool_install` has no `version` field — the version is a substring of the URL | Nothing can compare "have" against "available" without regex-parsing a URL; `doctor` cannot report a version |
| Cache marker outranks the install URL, and is not version-keyed | A shipped pin bump does not reach an existing checkout |
| `.fab-test-tools/pbir_inspector/resolved-executable.txt` (no platform segment) points at a **Linux** binary on a Windows box | Orphan from before the cache was platform-keyed; nothing invalidates it |
| `_verify_checksum` exists but neither tool declares `install_sha256` | Checksum verification is dead code; a 19 MB executable is downloaded unverified |
| `default_path` outranks both cache and URL | A user with `./TabularEditor/TabularEditor.exe` never receives an update and is never told one exists |
| fab-inspector publishes three tag flavors per version (`-Winform`, `-AvaloniaUI`, plain); only the plain tag carries `*-FabInspCLI.zip` | `GET /releases/latest` returns `v3.4.0-Winform`, whose assets contain no CLI at all — a naive checker proposes a URL that 404s |
| Every fab-inspector release ≥ `v3.5.0` is a prerelease | Under the stable-only policy this epic adopts, fab-inspector reports "current" at `v3.4.0` indefinitely. That quiet is deliberate, not a bug |
| `v3.4.0` ships **four** CLI assets including `osx-arm64`; we declare three platforms | Apple Silicon resolves the `osx-x64` build |
| Tabular Editor's URL is a CDN template, not a GitHub asset, and TE3 is a different (commercial) product | The checker needs a version-*line* constraint (`2.x`) and a third source shape |
| `pql-test==0.1.12` appears in six files | A bump has a documentation blast radius nothing tracks |

Upstream state at planning time (2026-08-28): `pql-test` 0.1.13 available;
Tabular Editor 2.28.0 current; fab-inspector newest *stable* release carrying CLI
assets is `v3.4.0` — matching the current pin — with `v3.5.0` prerelease-only.

---

## Record version provenance in `analyzers.json`  ✅

`tool_install` describes where to download a tool but not *what version* that URL
points at, and not where newer versions are announced. Both are needed before
anything can compare, and both are additive — an entry without them resolves
exactly as it does today, per the backward-compatibility constraint.

Adds `version`, `install_url_template` (so a bump derives URLs rather than
string-replacing them), and a `release_source` block naming the upstream feed and
how to read it. Also backfills `install_sha256s` for the current pins, so
`_verify_checksum` stops being unreachable code.

**Requirements**:
- Given a `tool_install` entry with no `release_source` or `version`, should resolve
  the executable exactly as it does today, with no warning and no behavior change
- Given `pbir_inspector`, should declare `version: "3.4.0"`, a `github_release`
  source for `NatVanG/fab-inspector`, an asset pattern matching
  `{platform}-FabInspCLI.zip`, and `allow_prerelease: false`
- Given `tabular_editor_bpa`, should declare `version: "2.28.0"`, a `url_template`
  source against the CDN, and `version_line: "2"` so TE3 releases are never proposed
- Given `pql_test`, should declare a `pypi` source for the `pql-test` package,
  reading its pinned version from `pyproject.toml` rather than duplicating it
- Given any tool with a recorded `install_sha256`, should verify the download and
  delete the archive on mismatch — exercising the path `_verify_checksum` already
  implements but nothing reaches
- Given the packaged copy and a `.fab-test/metadata/` override, should read the new
  fields through the existing metadata layers, not a second lookup

Done: `pbir_inspector` declares `version: "3.4.0"` and a `release_source` of
`{type: github_release, repo: NatVanG/fab-inspector, asset_prefixes:
{linux: linux-x64, win32: win-x64, darwin: osx-x64}, asset_suffix:
-FabInspCLI.zip, allow_prerelease: false}` — the prefix/suffix split (rather
than one `{platform}` token) matches the real asset names
(`win-x64-FabInspCLI.zip`), which don't have a single substitutable
`{platform}` segment. `tabular_editor_bpa` declares `version: "2.28.0"`, an
`install_url_template` (`.../TabularEditor.{version}.zip`) alongside the
existing concrete `install_url` (kept for zero behavior change), and a
`release_source` of `{type: url_template, version_line: "2"}`. `pql_test`
declares `release_source: {type: pypi, package: pql-test, version_source:
pyproject.toml}` with **no** `version` field — the pin lives only in
`pyproject.toml`, per the requirement not to duplicate it.

`install_sha256s` (plural, platform-keyed) backfilled for `pbir_inspector`
and `install_sha256` (singular, one platform) for `tabular_editor_bpa` --
both read by the existing `_platform_specific()` helper with no code change.
Verified for real, not just computed: downloaded the actual `v3.4.0` win32/
linux/darwin assets and the actual `TabularEditor.2.28.0.zip` and hashed each
with `sha256sum`; a first manual transcription of the fab-inspector digests
was silently one character short per string (64-char hex truncated to 63) --
caught by a script asserting `len() == 64` against the recomputed digests
before trusting them, not by inspection. Cleared the local `.fab-test-tools`
cache and called `resolve_executable` directly for both `pbir_inspector` and
`tabular_editor_bpa` on this Windows machine: both re-downloaded for real and
passed `_verify_checksum` against the win32 entries, proving those two
digests are correct (the linux/darwin ones were computed the same way but
can't be exercised on this OS). No metadata-layer code changed -- these
fields resolve through `load_analyzer_config`'s existing single lookup, same
as every other `tool_install` key. `pytest -m fab_test` on
`test_fab_test_tool_bootstrap.py` and `test_readiness.py`: 33 passed,
confirming the additive fields caused no behavior change.

## Check upstream releases from a repository-internal script  ✅

The comparison logic itself: read the declared `release_source` for each tool, ask
the upstream feed what the newest eligible release is, and report drift. Lives in
`tools/check_tool_updates.py`, **outside `src/`**, so it is not packaged into the
wheel that every user installs and never runs.

Note the trade this makes: outside `src/fabric_ci_cd_dataops`, the script is outside
the coverage denominator, so its tests are not enforced by the 80% floor. That is
accepted for maintenance tooling and should not be extended to shipped code.

**Requirements**:
- Given `NatVanG/fab-inspector`, should select the newest **non-prerelease** release
  whose assets include a `*-FabInspCLI.zip` for every declared platform, and should
  ignore the `-Winform` and `-AvaloniaUI` tag flavors entirely
- Given the fab-inspector feed as it stands today, should report `v3.4.0` as current
  and should **not** propose the `v3.5.0` prerelease
- Given `tabular_editor_bpa`, should consider only `2.x` releases, so a TE3 tag is
  never proposed as an upgrade to a free CLI
- Given `pql_test`, should compare the PyPI latest against the pin read from
  `pyproject.toml` and report `0.1.12 → 0.1.13`
- Given `GITHUB_TOKEN` in the environment, should send it — the unauthenticated
  GitHub API allows 60 requests/hour
- Given no network, a timeout, or a non-200 response, should report the tool's status
  as unknown and exit 0; a flaky upstream must never fail a build
- Given `--format json`, should emit one machine-readable record per tool with
  current version, available version, and the release URL
- Given every pin current, should exit 0 with no drift reported; given
  `--fail-on-update` and any drift, should exit non-zero

Done: `tools/check_tool_updates.py` reads `analyzer_registry.*.tool_install.
release_source` from the packaged `analyzers.json` and dispatches to one of
three checkers by `type`. `github_release` (fab-inspector) filters out
drafts and, unless `allow_prerelease`, prereleases; among what remains, only
a release whose asset names include `{prefix}{asset_suffix}` for *every*
declared platform is a candidate, so a `-Winform`/`-AvaloniaUI`-flavored tag
or one missing even one platform's asset is skipped outright, and the
newest candidate by parsed version wins. `url_template` (Tabular Editor)
consults a GitHub repo for version discovery only -- `install_url_template`
still supplies the real download URL -- filtered to tags starting with
`{version_line}.`, so a `3.x` TE3 tag can never be proposed as an upgrade to
the free TE2 CLI this wraps. `pypi` (pql-test) reads the pin straight out of
`pyproject.toml`'s `dependencies` list (never duplicating it into
analyzers.json) and compares it against the PyPI JSON API's `info.version`.
A tiny `_parse_version` turns a dotted string into a tuple of ints for
comparison (`2.10.0 > 2.9.0`, unlike a plain string compare), stopping at
the first non-numeric component rather than guessing an ordering it
doesn't need. `GITHUB_TOKEN`, when set, is sent as a bearer token on every
`api.github.com` call. Every checker's failure (`URLError`, `HTTPError`,
`TimeoutError`, a missing/malformed JSON field) is caught per-tool in
`check_all()` and downgraded to `status: "unknown"` rather than raising, so
one flaky upstream or one unexpected API shape never stops the other tools
from being checked or fails the run -- confirmed by actually simulating a
network outage (`_get_json` monkeypatched to raise) and watching every tool
degrade to unknown while `main(["--fail-on-update"])` still returned 0, not
a `try/except` I only read.

Verified against the **real, live upstream feeds** (not just mocked
fixtures) before writing a single test: ran the finished script directly
and it reported exactly what the epic's own "What discovery found" table
predicted -- `pbir_inspector` current at `3.4.0` with the `v3.5.0`
prerelease correctly invisible, `tabular_editor_bpa` current at `2.28.0`
with no TE3 tag proposed, and `pql_test` reporting the real
`0.1.12 → 0.1.13` drift. Also caught live: the default Windows console
encoding (cp1252) crashed the ✓/↑ status symbols in text-format output --
the same class of pre-existing defect already on record for
`validate_environments_schema.py` -- fixed by reconfiguring stdout to UTF-8
the same way `fab_test.py` already does, not by downgrading to ASCII.

Added `"repo": "TabularEditor/TabularEditor"` to `tabular_editor_bpa`'s
`release_source` in `analyzers.json` (for version discovery only) --
TabularEditor/TabularEditor turned out to have real GitHub releases tagged
by plain version number (`2.28.0`, no `v` prefix), confirmed by querying
the live API before assuming it, not by guessing from the CDN URL alone.

26 new tests in `tests/test_check_tool_updates.py`, importing the script via
`importlib.util.spec_from_file_location` (the same pattern
`test_publish_workflows.py` already uses for `.github/scripts/`, since
`tools/` is not a package either); deliberately unmarked, matching this
repo's existing convention for repo-internal-tooling tests
(`test_check_promotion_safety.py` and siblings) rather than forcing a fit
into a marker meant for the fab-test CLI contract. No test touches the
network -- every upstream call goes through `_get_json`, monkeypatched to a
fixture or a raising stub.

## Key the tool cache by version so a shipped bump lands  ✅

The task that makes the rest matter. `resolve_executable` returns a cached marker
before it ever looks at the install URL, and the cache path carries no version, so
upgrading `fab-test` cannot replace a downloaded binary. This also removes the
orphan marker left over from before the cache was platform-keyed.

**Blast radius** — `resolve_executable` and `probe_executable` are shared by both
paths that resolve a tool. Enumerate before editing, run each afterwards through the
real CLI: `fab-test bpa`, `fab-test pbir`, `fab-test all`, `fab-test local`,
`fab-test doctor`, `fab-test doctor --local`, `fab-test clean-tools --dry-run`,
`fab-test clean-tools`, and both `invoke_*` wrappers directly.

**Requirements**:
- Given a `tool_install` declaring a `version`, should cache under
  `.fab-test-tools/<analyzer>/<platform>/<version>/` and write the marker there
- Given a cache populated at one version and `analyzers.json` subsequently declaring
  a newer one, should ignore the old cache and download the new version — this is the
  defect the epic exists to fix
- Given a cache populated at the currently declared version, should reuse it without
  network access, exactly as today
- Given a `tool_install` with no `version`, should use the existing unversioned cache
  path, so an override that predates this epic keeps resolving
- Given the pre-platform orphan marker
  `.fab-test-tools/pbir_inspector/resolved-executable.txt`, should remove it and
  should never resolve a marker whose recorded executable is for another platform
- Given `clean-tools`, should remove superseded versions and report each by name;
  given `--dry-run`, should list them and delete nothing
- Given `doctor`, should report the resolved version for each tool alongside its
  readiness
- Given a `default_path` file or an env-var path shadowing the cache, should say so
  in `doctor` output and name the variable — a user in that state cannot receive a
  pin bump and is currently never told

Done: `_analyzer_tool_bootstrap.py` gained one seam, `_cache_dir(repo_root,
analyzer_name, platform, tool_install)`, used by both `resolve_executable`
and `probe_executable` in place of the old `<analyzer>/<platform>` path.
When `tool_install` declares a `version` it appends a `<version>` segment;
when it doesn't, the path is unchanged from today. Proved live, not just
under test: bumped `tabular_editor_bpa`'s `version` from `2.28.0` to
`2.28.1` in the real `analyzers.json` with the real populated cache still on
disk, ran `fab-test doctor`, watched it correctly report "not yet
downloaded" instead of the stale cached binary, then restored the file —
this is the exact defect (`analyzers.json` ships a bump, existing checkouts
never see it) the epic exists to fix, reproduced and confirmed fixed against
the real cache and the real CLI rather than only a synthetic tmp_path.

`probe_executable` now returns a `version` key on every branch (cache hit:
the declared version; local-candidate/no-URL/unsupported-platform branches:
`None`), which meant giving `check_readiness`, `_cloud_readiness`, and
`_telemetry_readiness`'s row builder a uniform key set too, or `doctor
--format json` would emit different shapes for a bootstrapped-tool row vs.
a cloud or telemetry row. Rather than touching `_cloud_readiness`'s five
return statements for a field that never applies to them, `check_readiness`
wraps the whole dispatch in one `result.setdefault("version", None)`.

A local candidate (env var or `default_path`) that shadows a declared pin
now gets a note in the same `reason` string doctor already prints —
"resolved via env var TABULAR_EDITOR_PATH (shadows pinned 2.28.0; won't
receive automatic updates)" — plus a `remediation` naming the variable to
unset (or the file to move, for `default_path`). A CLI `--tabular-editor-
path` argument deliberately gets no note: it is a per-invocation choice, not
a silent trap. Verified live with a real shadowing env var against the real
CLI, not only the unit tests.

`clean-tools` was widened to name each cached `analyzer/platform/version`
it removes (derived from wherever a `resolved-executable.txt` marker or an
`extracted/` directory actually sits, so it works for both the old
unversioned layout and the new one) rather than one generic ".fab-test-
tools removed" line — while keeping the full-wipe behavior completely
unchanged (asked the user rather than guessed: a "prune only stale
versions, keep current" reading was also plausible from the requirement's
wording, but changes clean-tools' semantics and would have broken its
existing full-wipe tests; the user chose "keep full-wipe, improve
reporting").

Investigated and cleaned up the epic's own named orphan while working in
this file: `.fab-test-tools/pbir_inspector/resolved-executable.txt` (no
platform segment, pointing at a **linux** binary) turned out to be tracked
in git from the repository's very first commit, predating both the
platform-keyed cache and the `.gitignore` rule that would otherwise exclude
it. An early `rm -rf .fab-test-tools` (to force fresh downloads for
verification) deleted these tracked files before that was noticed;
`git status` caught it immediately, `git checkout --` restored them, and
they were then removed properly with `git rm --cached` (staged, not
committed) since nothing in the codebase or its history since that first
commit ever referenced them.

`tests/test_fab_test_tool_bootstrap.py` gained 8 tests: version-keyed cache
path, a version bump ignoring the old cache and downloading the new one, a
same-version cache hit never touching the network (`_download` patched to
raise if called), no-version preserving the pre-epic path, and the
`probe_executable` version/shadow-note reporting including the CLI-argument
exception. `tests/test_fab_test_config.py` gained 2 for `clean-tools`'s new
per-entry labels (dry-run and real). `tests/test_readiness.py` and
`tests/test_doctor.py`'s stable-key-set contracts were updated from four
keys to five. `tests/test_module_budget.py`: `fab_test_registry.py`'s
exemption ceiling raised from 817 to 829 (the `setdefault` wrapper added 12
lines). Full suite: **1448 passed, 3 skipped, coverage 86%** (floor 80%,
held); every Blast Radius entry point re-verified through the real CLI
after the change, not just the one that prompted it: `doctor`,
`doctor --local`, `clean-tools --dry-run`, `clean-tools`, `bpa --dry-run`,
`pbir --dry-run`, `all --dry-run`, `local --dry-run`, all confirmed correct
before and after a real cache clear/rebuild cycle.

## Watch upstream on a schedule, and write the bump down

The command nobody remembers to run is not a process. A weekly job turns drift into
an issue, and `dependabot.yml` covers the packaged dependencies that
`check_tool_updates.py` deliberately does not.

The bump procedure itself belongs in [docs/RELEASE.md](../docs/RELEASE.md), because
"edit the URL, record the checksum, cut a release" is three steps that are easy to
do two of.

**Requirements**:
- Given the weekly schedule, should run `tools/check_tool_updates.py --format json`
  and open an issue naming each drifted tool, its available version, and
  `analyzers.json` as the file to edit
- Given no drift, should open no issue and leave no failed run in the history
- Given an upstream outage, should not fail the workflow
- Given the workflow is ever deleted, `tools/check_tool_updates.py` should be deleted
  with it — its only caller. A script whose workflow was removed is how eight modules
  under `scripts/` became untestable dead code (see Standalone Tasks in
  [plan.md](../plan.md)); a header comment should say so
- Given `.github/dependabot.yml`, should cover both `pip` and `github-actions`
- Given [docs/RELEASE.md](../docs/RELEASE.md), should carry the pin-bump procedure
  including recording `install_sha256` per platform

## Stop the pin from being duplicated, and document all three callers

`pql-test==0.1.12` is written in six places. Five of them are prose that a bump will
miss, and nothing fails when they disagree.

**Requirements**:
- Given `pyproject.toml` declares a `pql-test` pin, should fail a test if any
  documented occurrence in `README.md`, `docs/RELEASE.md`,
  `.github/skills/fab-test/SKILL.md`, or `.github/workflows/publish-testpypi.yml`
  names a different version
- Given the test fails, should name every file and line that disagrees, not just the
  first
- Given the AI-agent caller, `.github/skills/fab-test/SKILL.md` should document the
  new `doctor` version column and the shadowing warning
- Given the human caller, `README.md` and `docs/` should explain that tool versions
  are pinned in `analyzers.json` and delivered by upgrading `fab-test`
- Given the pipeline caller, `docs/` should carry a copy-pasteable
  `tool-currency.yml` snippet
- Given all three, should be changed together via the `document` skill so they cannot
  drift

---

## Follow-up (not in this epic)

Bump the stale pins **through** the new checker, once it exists, so the first real
bump proves the mechanism: `pql-test` to `0.1.13`, and fab-inspector whenever
upstream promotes a stable release carrying CLI assets. Separately, consider
declaring `osx-arm64` so Apple Silicon stops resolving the x64 build.

If a consumer ever begins maintaining their own URLs in
`.fab-test/metadata/analyzers.json`, they become a genuine second caller and a
`fab-test check-updates` subcommand earns the surface this epic denied it.
