# TestPyPI Release Epic

**Status**: ✅ COMPLETED — 9 of 9 tasks done. `fab-test==1.0.0.0.dev4` is published on TestPyPI and the install verified from a clean venv outside this checkout (see the last task below).
**Goal**: Publish `fab-test` 1.0.0.0.dev1 to TestPyPI as an installable package, and document the install for all three callers.

## Overview

Today a reader is told `pip install fab-test` works, and it does not — the name is
unregistered on both indexes, and `publish.yml` has never fired because no tag has
ever been cut. Publishing as-is would ship something broken: the wheel carries no
rulesets, so `bpa` and `pbir` resolve `BPARules.json` under the caller's own
`.github/metadata/` and fail validation outside this checkout. This epic packages the
metadata the analyzers need, gives consumers `.fab-test/metadata/` to override it,
publishes to TestPyPI, and proves the result by running the installed console script
from a clean venv.

Publishing target is `kerski/fab-test` under the TestPyPI account `jkerski`.

---

## One Version, One Place  ✅ (a53e36c)

Make `__init__.py` the only place the version is written, and set it to `1.0.0.0.dev1`.

**Requirements**:
- Given a version bumped only in `__init__.py`, should build a wheel whose distribution metadata reports that version
- Given `fab-test --version`, the telemetry `fab_test_version` field, and the installed distribution metadata, should all report the same string
- Given `1.0.0.0.dev1` sorts below `1.0.0` as a PEP 440 dev release, should not be selected by a plain `pip install fab-test` — every documented install pins it exactly or passes `--pre`
- Given TestPyPI rejects re-uploading a version, should make the next rehearsal a one-line edit rather than two files that can drift

---

## Rules Ship With The Package  ✅ (a53e36c)

Package the rulesets and `analyzers.json` so an install outside a checkout can run.

**Requirements**:
- Given `pip install fab-test` and no checkout, should run `bpa` and `pbir` against packaged rulesets — `_DEFAULT_BPA_RULES` currently points into the caller's own `.github/metadata/rules/` and `validate_path` makes the miss a hard error
- Given `_rule_overlay.py` documents overlays applied to "a packaged ruleset", should actually ship the ruleset it describes
- Given `analyzers.json` is read from `REPO_ROOT/.github/metadata/`, should resolve like the rulesets rather than remain the one metadata file that still requires a checkout
- Given `package-data` declares `agents/*` and `skills/*/*` and no such directories exist under `src/`, should drop the dead entries and correct the README section that tells a reader to find them after install
- Given the wheel is the only artifact a consumer sees, should assert its data files by name in a test, since the entries above were declared and silently never shipped

---

## Repo-Local Metadata Overrides  ✅ (`_metadata.py` layer chain)

Give a consumer `.fab-test/metadata/` to override packaged metadata, without a new config key.

**Requirements**:
- Given a repo with `.fab-test/metadata/rules/BPARules.json`, should prefer it over the packaged copy
- Given a repo with no override, should use the packaged copy silently — an absent override is a default, not a missing file worth warning about
- Given this repository's existing `.github/metadata/rules/`, should keep working: `.fab-test/` is the name a consumer is told, `.github/metadata/` the one already in the field and in every workflow
- Given `.github/` belongs to GitHub, should not instruct a consumer to create this project's layout inside it
- Given a packaged ruleset and a repo copy that have drifted, should fail a test asserting they agree — a fallback that answers confidently and wrongly is worse than none
- Given `fab-test config --show`, should name which layer the effective ruleset came from, matching the origin tracking the flag/env/config/default chain already reports

---

## Deferred From Metadata Packaging  ✅ (closed by the Environments Metadata Layers epic)

Two more copies of the same pattern, found after tasks 2-3 landed. Both are
invoked by workflows inside a checkout rather than as console scripts, so
neither is a blocker for a `pip install` consumer -- which is why they were
out of scope above, and why they are recorded rather than silently skipped.

**Requirements**:
- Given `detect_changes.py` holds a fourth copy of the artifact-map loader that exits 1 when the file is absent, should resolve through the shared metadata layers like the other three
- Given `run_analyzer.py` defaults `--metadata-path` to a relative `.github/metadata/analyzers.json`, should resolve to a path that can exist in a wheel
- Given `environments.yml` carries workspace GUIDs and branch policy, should never fall back to a packaged copy — a baked-in GUID would aim a deployment at the wrong workspace silently, so its resolution needs repo layers only

---

## Pre-Release Tags Never Reach PyPI  ✅ (56e22f3)

Separate the rehearsal path from the production path in the publish workflows.

**Requirements**:
- Given a tag like `v1.0.0.0.dev1`, should publish to TestPyPI and never to PyPI — today's `v[0-9]+.[0-9]+.[0-9]+*` glob matches pre-release tags and would send them to production
- Given the `pypi` environment names project `fabric-ci-cd-dataops`, should name `fab-test`, since trusted publishing resolves by distribution name
- Given no tag at all, should publish to TestPyPI on `workflow_dispatch`, so a release can be rehearsed without moving a tag

---

## Install From TestPyPI Is Verified, Not Assumed  ✅

Prove the published artifact installs and runs, rather than trusting that it uploaded.

**Requirements**:
- Given a clean venv and only the TestPyPI index, should fail to resolve — `pql-test==0.1.12` and current `fabric-cicd` exist only on production PyPI, which carries 0.1.11 and 0.1.7
- Given the documented install command, should carry `--extra-index-url https://pypi.org/simple` so those dependencies resolve
- Given a fresh install from TestPyPI, should verify through the real entry point: `fab-test --help`, `fab-test doctor --local`, and a `bpa` run reaching the packaged rules — from the installed console script, outside any checkout

Verified 2026-08-28 against `fab-test==1.0.0.0.dev4` in a clean venv outside this
checkout (`%TEMP%\fab-test-verify`): install resolved with both index flags,
`--version`/`--help`/`doctor --local` all ran correctly, `config --show` named
`rules.bpa`/`rules.pbir` as resolved from the **packaged** copies under
`site-packages` (not a checkout path), and a real `bpa` run invoked Tabular
Editor against real `.SemanticModel` artifacts using the packaged
`BPARules.json`, producing genuine pass/fail counts. An empty directory ran
`bpa` cleanly with a "no artifacts found" warning rather than erroring on a
missing rules file.

---

## Package Metadata Points At The Right Repository  ✅ (56e22f3)

The project page is the first thing a reader sees, and every URL on it is currently wrong.

**Requirements**:
- Given the repository is `kerski/fab-test`, should not point Repository, Documentation, Changelog, and Issues at `kerski/fabric-ci-cd-dataops`
- Given the README's relative links (`docs/QUICKSTART-LOCAL.md`, `../README.md`), should resolve on the project page rather than 404 against the index host
- Given `twine check --strict`, should pass before any upload step runs
- Given setuptools>=77, should declare the license as an SPDX expression rather than `{ text = "MIT" }` plus a `License ::` classifier, both now deprecated

---

## The README Stops Claiming PyPI  ✅ (this commit)

Say what a reader can actually run today.

**Requirements**:
- Given `fab-test` is unregistered on both indexes, should not tell a reader `pip install fab-test` works — in the README and in `docs/QUICKSTART-LOCAL.md`, which opens with that command
- Given a reader who wants the pre-release, should find the TestPyPI command with its extra index and its exact pin, and know why a bare install will not find it
- Given a reader tuning rules, should find `.fab-test/metadata/rules/` documented as the override and the packaged copy as the default

---

## A Release Runbook For All Three Callers  ✅ (this commit)

One document per the Definition of Done, covering the steps a workflow cannot take.

**Requirements**:
- Given only a human with the `jkerski` account can create it, should record the TestPyPI pending-trusted-publisher fields verbatim: owner `kerski`, repo `fab-test`, the publish workflow filename, and the environment name
- Given a pipeline that consumes `fab-test`, should have a copy-pasteable snippet installing the pinned pre-release from TestPyPI with its extra index
- Given the agent, should read the same install commands and rules-resolution order from `.github/skills/fab-test/SKILL.md` that the human reads from the README
