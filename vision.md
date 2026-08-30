# Vision

**A unified CLI for running tests on Microsoft Fabric artifacts — for the human, the pipeline, and the AI agent.**

## Why

Fabric artifact quality tooling is fragmented across Tabular Editor, PBIR Inspector, pql-test, pqlint, and Playwright — each with its own invocation, output shape, and failure semantics. `fab-test` is a facade: the value it adds is not new analysis, it is **one contract**. One way to discover what can run, one way to check readiness, one result envelope, one meaning per exit code.

That contract must serve three callers equally:

| Caller | Needs |
|--------|-------|
| **Human** | Readable output, obvious next step when something is missing, works on a laptop with no cloud access |
| **Pipeline** | Deterministic exit codes, stable result paths, no interactive prompts |
| **AI agent** | Parseable stdout, discoverable capability, remediation hints it can act on without guessing |

A change that serves one caller by degrading another is not aligned with this vision.

## Principles

1. **One contract, three callers** — same envelope schema, same exit codes, same result layout whether run locally, in CI, or by an agent.
2. **Local first** — a developer with a `.pbip` open in Power BI Desktop gets real findings without a workspace or service principal.
3. **Facade, not fork** — wrap upstream tools and rulesets; never fork what upstream maintains.
4. **Tell the caller how to fix it** — every failure names the flag, environment variable, or config key that resolves it.

## Constraints

```
Constraints {
  (test coverage) => keep line coverage above 80% over src/, measured on the full suite
                     at review and commit checkpoints and enforced in CI. A task is not
                     complete until its new code is covered
  (troubleshooting) => when a test fails, narrow before re-running: pytest -m <marker>,
                     then the single test file, then -k <expr> on the failing test.
                     Never re-run the full suite to iterate on one failure — it spends
                     tokens re-reading output you already have
  (validating)    => full suite at review and commit checkpoints, and in CI
  (coverage != gate on granular runs) => never fail a narrowed run on coverage; a marker
                     run legitimately covers a fraction of src/
  (simplicity)    => keep it simple where possible; prefer one flag over a subsystem,
                     one file over a format, and no abstraction until the second caller
  (backward compat) => existing commands, env vars, and result paths released in
                       1.0.0 and later keep working; new surfaces are additive
                       and optional
  (secrets)       => credentials are never written to stdout, result envelopes, the run
                     manifest, or telemetry
  (documentation) => an epic is not done until all three callers are documented: the
                     agent has a skill, the human has updated docs, and the pipeline
                     has YAML that is easy to produce. Any one missing => not done
  (blast radius)  => a change to code with more than one caller is unverified until
                     every caller is exercised through the real CLI, not only the one
                     that prompted the change. Enumerate them before editing, and run
                     each afterwards
}
```

Markers available for granular runs are declared in [`pytest.ini`](pytest.ini): `fab_test`, `analyzers`, `bpa`, `pbir`, `pql_test`, `pql_lint`, `prompt_lint`, `playwright`, `integration`.

## How Coverage Is Measured

The coverage floor and the granular-test constraint pull in opposite directions — a `pytest -m bpa` run covers a fraction of `src/` by design. They are reconciled by separating *when* coverage is measured from *how* tests are run:

| Moment | Command | Coverage |
|--------|---------|----------|
| Edit loop | `pytest -m <marker>` / one file / `-k <expr>` | Not measured, never gates |
| Review / commit checkpoint | Full suite with coverage | Reported; below 80% blocks the commit |
| CI | Full suite with `--cov-fail-under=80` | Enforced; build fails below the floor |

Rules: coverage is scoped to `src/fabric_ci_cd_dataops` (tests are excluded from the denominator), the 80% floor is a ratchet that does not go down, and the threshold lives in the CI invocation — **not** in `pytest.ini`, where it would fail every granular run and defeat the token-saving constraint.

One module is omitted from the denominator, by explicit path in `[tool.coverage.run]`: `validate_fabric_service_client.py`. It needs a live service to execute at all, so a unit test could only assert that its argument parser accepts flags — which would inflate the figure rather than improve it. `eventhouse_logger.py` was listed too until it earned a seam (Eventhouse Shipping §5): the ingest needs a cluster, but the validators deciding what reaches the wire never did, and being omitted is how they went untested entirely. Exclusions are single files, never patterns, so library code added later cannot fall into the gap; `tests/test_coverage_config.py` fails if an entry goes stale or if a core CLI module is ever listed.

Complexity is ratcheted the same way, by count rather than per function: `tests/test_complexity_budget.py` fails if the report grows. Gating each function would block a PR over one extra branch, which is a gate people route around; leaving it unwatched is how the report went from 36 findings to 45 across two epics before anyone looked.

## Blast Radius

`fab-test` is small enough that most helpers have several callers and large enough
that it is easy to forget which. Five defects reached the CLI in a single session,
all the same shape: shared code changed, one caller verified.

| Defect | Shared code | Callers exercised |
|--------|-------------|-------------------|
| `all --artifact X` raised `AttributeError` | `discover_artifacts` | 2 of 3 |
| Summary table overflowed the terminal | the column width budget | 1 of 3 |
| `pql-test` output crashed the reader thread | the subprocess arguments | 1 of 2 wrappers |
| `--report` wrote a file and never said so | report surfacing | `all` only |
| `all` then named every report twice | report surfacing | one analyzer only |

A green suite reported none of them. Each was found by running the CLI — which is
what "verify through the real entry point" already asks for, and was still not
enough, because one entry point was run and the change had touched several.

The callers worth enumerating for the surfaces that keep biting:

| Surface | Callers |
|---------|---------|
| Per-artifact summary and its paths | one analyzer, `fab-test all`, `fab-test local` |
| Artifact discovery | `_run_analyzer`, `list`, `explain`, the aggregate summary |
| Table widths | the summary, the findings tables, the analyzer wrappers |
| Envelope writing | every `invoke_*` wrapper |

Before editing one of these, list its callers. After editing, run each. "It worked for
the command I was asked about" is the failure mode, not the verification.

## Definition of Done — Documentation

Before documenting, run `ruff check` over `src/` and fix anything it flags. A build that fails lint after the code is "done" is not done — catching it here is cheaper than catching it in CI.

Documentation follows the same three callers as the CLI itself. Shipping for one and not the others leaves the epic incomplete.

| Caller | Deliverable | Where |
|--------|-------------|-------|
| **AI agent** | Skill created or updated with the new commands, flags, exit codes, and output shapes | `.github/skills/<name>/SKILL.md` |
| **Human** | README and walkthrough updated so a reader can run the new capability without reading source | [README.md](README.md), [docs/](docs/) |
| **Pipeline** | A copy-pasteable workflow snippet, or generation/scaffolding, so the YAML is not hand-derived | [docs/](docs/), workflow examples |

Use the `document` skill to make these changes together, so the three never drift apart.

## Non-Goals

- Replacing the analyzers it wraps, or reimplementing their rules.
- Being a general-purpose Fabric deployment tool — deployment lives in `fabric-cicd-deployment`.
- Requiring a Fabric workspace or service principal for local static analysis.

## Current Plan

See [plan.md](plan.md) for active epics and their sequence.
