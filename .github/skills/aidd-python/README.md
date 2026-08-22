# aidd-python

Python quality rules for `fab-test` — the counterpart to `aidd-javascript` in a
project that has no JavaScript.

## Why it exists

`aidd-review` and `aidd-fix` both defer to a language skill for what "good" means,
and `aidd-workflow` tells the agent to skip the JS/TS skills because this project
is Python. That left the language slot empty: reviews fell back to whatever the
agent assumed. This skill fills it.

It also gives the "is this over-engineered?" question a concrete answer. The
Over-Engineering Lens section lists the six shapes worth hunting for, and the
Simplicity Budgets section ties them to the ruff rules that detect them
automatically.

## What it covers

- Principles and constraints for writing Python here — one job per function,
  IO at the edges, standard library first, no abstraction until the second caller.
- Simplicity budgets: the complexity, argument, branch, and statement thresholds
  configured in `pyproject.toml`, and what crossing each one usually means.
- The over-engineering review lens: dead parameters, single-caller indirection,
  configuration nobody sets, speculative generality, duplicated modules,
  swallowed errors.
- Naming and comment rules, including the requirement that every `# noqa` carry
  a reason.

## When it loads

`aidd-workflow` loads it for the `review`, `fix bug`, and `task` commands. Load it
by hand any time you are writing or refactoring Python in this repository.

## Commands

Run the gate before committing:

```bash
ruff check .
```

Apply only the fixes ruff considers safe:

```bash
ruff check . --fix
```

Run the over-engineering lens over the source tree:

```bash
ruff check src --select C901,PLR0911,PLR0912,PLR0913,PLR0915,ARG,ERA --statistics
```

These rules are deliberately outside the CI gate. They report where code has
outgrown its shape; they do not block a pull request.
