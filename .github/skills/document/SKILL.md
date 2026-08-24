---
name: document
description: Keeps project documentation in sync with the codebase. Updates README.md, docs/QUICK-VALIDATION.md, and .github/skills/fab-test/SKILL.md to reflect the current state of scripts/fab_test.py and all invoke_*.py wrappers. Trigger with "document".
---

# document

Keeps the three user-facing documentation surfaces in sync with the codebase.

Four more files carry the same result-location literal but are outside this skill's
three named targets: `docs/RELEASE.md`, `docs/QUICKSTART-LOCAL.md`,
`.github/skills/pql-test/SKILL.md`, and `.github/skills/fab-inspector/SKILL.md`. The
Results Directory Rename epic found these drifted out of sync with a single `document`
run in 2026-08 — when a change touches the default output directory or result-path
shape, check these four by hand too.

## When to invoke

User says: **document**, **update docs**, **sync docs**, **update readme**, **update quick-validation**

## Files to read first

Before writing anything, read these source-of-truth files:

```
scripts/fab_test.py                         ← subcommands, flags, arg parser
scripts/invoke_tabular_editor_bpa.py        ← BPA wrapper interface
scripts/invoke_pbir_inspector.py            ← PBIR wrapper interface
scripts/invoke_pql_test.py                  ← pql-test wrapper (CLI args, venv lookup)
scripts/invoke_pqlint.py                    ← pqlint wrapper interface
scripts/_analyzer_envelope.py               ← envelope schema keys
.github/metadata/rules/BPARules.json        ← BPA rules file path (for default reference)
```

Also read the current state of the three target files before editing:

```
README.md
docs/QUICK-VALIDATION.md
.github/skills/fab-test/SKILL.md
```

## Target Files and What to Update

### 1. `.github/skills/fab-test/SKILL.md`

Full reference for the `fab-test` CLI. Regenerate the entire content to match `fab_test.py`'s current argument parser. Key sections:

- **Distinction from pytest** table — one row per subcommand showing pytest vs fab-test split
- **Installation** — `pip install -e .`
- **Subcommands** — derived from `_ANALYZER_REGISTRY` in `fab_test.py`
- **Global flags** — from `_add_common_flags()`: `--artifact`, `--artifact-dir`, `--output-dir`, `--dry-run`
- **Subcommand-specific flags** — from each `subs.add_parser()` block
- **pql_test `--env` flag** — document that it maps to `PQL_TEST_ENV` env var
- **Result locations** — `fab-test-results/<analyzer>/<stem>/envelope.json` and `native.json`
- **Envelope schema keys** — from `ENVELOPE_REQUIRED_KEYS` in `_analyzer_envelope.py`
- **Source files table** — map each script to its purpose

### 2. `README.md`

Update only the **"Test your Fabric artifacts locally (fab-test)"** section. Do not touch other sections. The section should:

- Show the pytest vs fab-test distinction table
- Show install command
- Show all subcommand examples including `--artifact` isolation and `--env` for pql_test
- Reference the skill file for full docs: `.github/skills/fab-test/SKILL.md`

### 3. `docs/QUICK-VALIDATION.md`

Update only the **"Run analyzers locally before pushing"** section. Do not touch CI/CD workflow sections or quick test scenarios. The section should:

- Keep pytest marker reference (pytest is the framework contract layer)
- Add a `fab-test` subsection below pytest that shows how to run analyzers against real `.fabric` artifacts
- Include `--env DEV` example for pql_test
- Include `--artifact` isolation example
- Reference `.github/skills/fab-test/SKILL.md` for full CLI reference

## Rules

- Edit only the sections identified above — do not rewrite or restructure other content
- Derive all flag names, defaults, and env vars from the source scripts, not from memory
- Keep examples concrete: use `SampleModel-PQLAssert` as the artifact stem in examples
- Do not add speculative features — only document what exists in the code
- After updating all three files, confirm what changed in a short summary
