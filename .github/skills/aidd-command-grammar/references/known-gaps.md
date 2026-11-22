# Known grammar deviations

Commands that author or check a file a person writes, surveyed 2026-11-19 on
`origin/dev` (1.10.0b4) against the Authoring Command Grammar epic's decisions.
These are backlog, not precedent: don't copy them into a new command. Remove an
entry when it's fixed.

## Built

| Command | Authors or checks | Verdict |
|---|---|---|
| `fab-test init` | `fab-test.yml`, `.env.example` | Conforms: a top-level verb about fab-test itself. `--format` and `--dry-run` resolve from config like the run's |
| `fab-test config --validate` / `--show` | `fab-test.yml` (incl. `rules.<name>` overlays) | Conforms: fab-test's own config |
| `fab-test pbir contract init` | `fab-tests/pbir/<Report>.Report.odcs.yaml` | Grammar and placement conform; gaps below. Exits 0, 2 (refusal or unreadable), 130 (interrupted) |
| `validate-environments-yaml` | `environments.yml` (Playwright's label → workspace map) | Gap: a second console script outside `fab-test`; exit 1 for both a schema error and an unreadable file |
| `fab-test pbir contract lint` | the slicer contract, paired by logicalId | Conforms (2026-11-19); wraps `pql-test contract lint`, which the docs now name only as its upstream half |
| `fab-test data-agent tests init` | `fab-tests/data-agent/<Item>.DataAgent.promptfoo.yaml` | Grammar and placement conform; one deliberate departure below. Exits 0, 2, 130 |
| `fab-test data-agent tests lint` | the suite, paired by logicalId | Conforms (2026-11-21): offline checks first, then `promptfoo validate`; exits 0, 1, 2, 127 |

## `pbir contract init`

- Fixed 2026-11-21 (Data Agent Testing epic): the noun is a real argparse subparser, so a global flag first parses. `fab-test help`, `list --format json` (`authoring`) and `explain` (`Author:`) name the verbs. Near misses (`pbir lint`, `pbir init Sales`, `pbir contracts init`) exit 2 with `did you mean:` the exact command. Only an item folder (its suffix, or a `.platform`) counts as a TARGET named like a verb.
- Fixed 2026-11-19 (Authoring Command Grammar epic): `contract lint` exists; TARGET takes a name as the run's does, `--artifact`'s metavar and help match the run's, `--artifact-dir` and `--format` default from `fab-test.yml`, `-q` prints one result line, flags.md lists `-q`/`-v`, every flag of the run is refused naming the run, and `--artifact`/`--artifact-dir`/`--format` share the run's help text (`_cli_utils`). `--as-of`'s help differs on init on purpose: there it dates the `current` suggestion.

## `data-agent tests init`

- **Questions are the caller's, not fab-test's (deliberate, 2026-11-21).** The grammar's `--questions` lists questions with `suggested`/`needs_human` and `--answers` answers them by question id. A Data Agent suite is the person's own questions, so `--questions` lists *suggestions* plus the `--answers` shape, and `--answers` is `{"tests": [{query, expect, match, follow_ups, id?, replace?}], "replace_all"?}`, matched to existing tests by question text (or `id`). The user corrected the first design: "I'm not asking the questions". Don't copy this into a flow whose questions fab-test asks.

## Planned

- **`fab-test playwright init` (plan.md standalone task):** no noun yet. If it scaffolds the execution YAML that `--playwright-config` reads, the noun names that file.

## Authored inputs with no verb (not gaps)

A verb is added only when a flow needs one (decision 4). These are listed so a
future epic starts from them:

- `*.Tests.dax` under `<Model>.SemanticModel/DAXQueries/`, run by `pql-test`. Upstream `pql-test contract generate` writes tests from an ODCS contract (ODCS Contract Analyzer epic).
- The Playwright execution YAML (`--playwright-config`) and `.env` files (`--env-file`, `--playwright-env-file`).
- T-TEST procedures for `sqldb-test`: part of the SQL database's own definition, so inside the item folder is correct. Decision 7 covers only files outside an item's definition.
