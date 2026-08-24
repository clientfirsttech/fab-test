---
name: aidd-python
description: Python best practices for this project — simplicity budgets, the ruff contract, and the review lens for spotting over-engineering. Use when writing, reviewing, or refactoring Python.
---

# Python guide

Act as a top-tier software engineer with serious Python discipline. The job is
working code that the next reader can hold in their head — not code that
demonstrates what the language can do.

## Before Writing Code

- Read the ruff configuration in `pyproject.toml`. It is the contract, not a suggestion.
- Read the surrounding module. Match its idiom before importing a new one.
- Conform to existing style and patterns unless directed otherwise. These
  instructions count as "directed otherwise" unless the user overrides them.

## Principles

- **YAGNI** — build for the caller in front of you.
- **KISS** — the boring version is the one that survives.
- **DRY, second time** — two similar blocks are a coincidence; three are a pattern.
- **Simplicity is removing the obvious and adding the meaningful.** What varies
  becomes a parameter; what never varies becomes a default and disappears.

Constraints {
  Be concise.
  One job per function; keep IO at the edges and logic pure in the middle.
  Prefer comprehensions and generators over append-in-a-loop.
  Prefer immutability; return new values rather than mutating arguments.
  Prefer plain functions and dataclasses over classes with behavior.
  Prefer the standard library over a dependency, and a dependency over a fork.
  Use pathlib for paths, f-strings for formatting, and `|` unions for types.
  Type public functions. Skip annotations that only restate the obvious.
  Catch the exception you can handle; blind `except Exception` belongs only at a
  process boundary, and carries a `# noqa: BLE001` saying which boundary.
  Obey the projects lint rules. Do not silence a rule you could satisfy.
  (a `# noqa` has no reason after it) => it is unjustified; fix the code instead
  (a parameter is unused) => delete it, or say in a comment which interface pins it
  (an abstraction has one caller) => inline it
  (a candidate abstraction cannot be named) => it is not an abstraction yet
  (a flag would do) => do not add a subsystem
}

## Simplicity Budgets

These are the thresholds in `[tool.ruff.lint.mccabe]` and `[tool.ruff.lint.pylint]`.
Crossing one is a signal to split the function, not to raise the number.

| Signal | Budget | What it usually means |
|--------|--------|----------------------|
| Cyclomatic complexity (`C901`) | 15 | The function is several functions sharing a name |
| Arguments (`PLR0913`) | 8 | A parameter object or a dataclass is waiting to be named |
| Branches (`PLR0912`) | default | Dispatch logic wants a mapping, not an `if` chain |
| Statements (`PLR0915`) | default | Setup, work, and reporting are fused together |

Raising a budget is a decision. Say why in the commit message.

These are all function-level. File-level budgets — module and test-module length,
and where to split — live in [aidd-module-budgets](../aidd-module-budgets/SKILL.md).

## The Over-Engineering Lens

When reviewing, look for these before looking at style:

1. **Dead parameters** — an argument nothing reads. It is either a leftover or a
   bug where the value was meant to be used. Check which before deleting.
2. **Single-caller indirection** — a helper, wrapper, or base class with exactly
   one use. Inline it and see if anything is lost.
3. **Configuration nobody sets** — a flag, env var, or config key with one value
   in every caller and every test.
4. **Speculative generality** — plugin points, registries, and hooks added for a
   second implementation that never arrived.
5. **Duplicated modules** — the same file in two trees. One of them is stale, and
   the stale one is what someone will read next.
6. **Swallowed errors** — a broad `except` that turns a bug into a silent empty
   result.

## Naming

NamingConstraints {
  Functions are verbs: `resolve_tool()`, `build_command()`.
  Predicates read as yes/no questions: `is_ready`, `has_findings`.
  Private helpers take a single leading underscore; there is no second level.
  Avoid noun-heavy restatements: `group_by_artifact(files)` not `artifact_grouping_helper(files)`.
  Say what it is, not what type it is: `artifact_path` not `path_str`.
  Module-level constants are UPPER_SNAKE; nothing else is.
}

## Comments

Comments {
  Docstrings on public functions and modules; one line when one line is enough.
  A comment explains why, never what — the code already says what.
  Write for a reader who has never seen the epic or the task plan.
  A `# noqa` without a reason is a defect.
}

## Commands

```bash
ruff check .                  # the gate — must be clean before commit
ruff check . --fix            # safe autofixes only
pytest -m <marker>            # narrow first when a test fails (see vision.md)
pytest -q                     # full suite at review and commit checkpoints

# The over-engineering lens, mechanised:
ruff check src --select C901,PLR0911,PLR0912,PLR0913,PLR0915,ARG,ERA --statistics
```

> This project is a facade over external analyzers. Wrapping a tool is the job;
> reimplementing one is not. See `vision.md`.
