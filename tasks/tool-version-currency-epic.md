# Tool Version Currency Epic

**Status**: 📋 PLANNED
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

## Record version provenance in `analyzers.json`

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

## Check upstream releases from a repository-internal script

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

## Key the tool cache by version so a shipped bump lands

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
