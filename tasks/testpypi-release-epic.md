# TestPyPI Release Epic

**Status**: 📋 PLANNED
**Goal**: Publish `fab-test` to TestPyPI and document the install for all three callers.

## Overview

Today a reader is told `pip install fab-test` works, and it does not — the name is
unregistered on both PyPI and TestPyPI, and `publish.yml` has never fired because no
tag has ever been cut. Worse, its tag filter `v[0-9]+.[0-9]+.[0-9]+*` matches
`v1.0.1rc1`, so the first attempt at a rehearsal release would land on *production*
PyPI. This epic makes TestPyPI the rehearsal target, proves the install works by
running the installed console script from a clean venv, and fixes the documentation
that currently promises a package nobody can get.

---

## One Version, One Place

Make `__init__.py` the only place the version is written.

**Requirements**:
- Given a version bumped only in `__init__.py`, should build a wheel whose distribution metadata reports that version
- Given `fab-test --version`, the telemetry `fab_test_version` field, and the installed distribution metadata, should all report the same string
- Given TestPyPI rejects re-uploading a version, should make a rehearsal bump a one-line edit rather than two files that can drift

---

## Pre-Release Tags Never Reach PyPI

Separate the rehearsal path from the production path in the publish workflows.

**Requirements**:
- Given a tag like `v1.0.1rc1`, should publish to TestPyPI and never to PyPI — today's glob matches it and would send it to production
- Given the `pypi` environment, should name the project `fab-test`, not `fabric-ci-cd-dataops`, since trusted publishing resolves by distribution name
- Given no tag at all, should still publish to TestPyPI on `workflow_dispatch`, so a release can be rehearsed without moving a tag

---

## Install From TestPyPI Is Verified, Not Assumed

Prove the published artifact installs and runs, rather than trusting that it uploaded.

**Requirements**:
- Given a clean venv and only the TestPyPI index, should fail to resolve — `pql-test==0.1.12` and current `fabric-cicd` exist only on production PyPI (TestPyPI has 0.1.11 and 0.1.7)
- Given the documented install command, should carry `--extra-index-url https://pypi.org/simple` so those dependencies resolve
- Given a fresh install from TestPyPI, should verify through the real entry point — `fab-test --help` from the installed console script, not a source-tree run

---

## Package Metadata Renders On The Project Page

The project page is the first thing a reader sees; it has to be readable.

**Requirements**:
- Given the README's relative links (`docs/QUICKSTART-LOCAL.md`, `../README.md`), should resolve on the project page rather than 404 against the index host
- Given `twine check --strict`, should pass before any upload step runs
- Given setuptools>=77, should declare the license as an SPDX expression rather than `{ text = "MIT" }` plus a `License ::` classifier, both now deprecated

---

## The README Stops Claiming PyPI

Say what a reader can actually run today.

**Requirements**:
- Given `fab-test` is unregistered on both indexes, should not tell a reader `pip install fab-test` works until it does — in the README and in `docs/QUICKSTART-LOCAL.md`, which opens with that command
- Given a reader who wants the pre-release, should find the TestPyPI command with its extra index, and know pre-release versions carry an `rc` or `.dev` suffix

---

## A Release Runbook For All Three Callers

One document per the Definition of Done, covering the steps a workflow cannot take.

**Requirements**:
- Given a maintainer publishing for the first time, should find the TestPyPI pending-trusted-publisher fields recorded (owner, repo, workflow filename, environment name), since only a human with the account can set them
- Given a pipeline that consumes `fab-test`, should have a copy-pasteable snippet installing a pinned TestPyPI pre-release
- Given the agent, should read the same install commands from `.github/skills/fab-test/SKILL.md` that the human reads from the README
