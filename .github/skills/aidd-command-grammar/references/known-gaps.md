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
| `fab-test pbir contract init` | `<Report>.Report.odcs.yaml`, beside the report | Grammar and placement conform; gaps below. Exits 0, 2 (refusal or unreadable), 130 (interrupted) |
| `validate-environments-yaml` | `environments.yml` (Playwright's label → workspace map) | Gap: a second console script outside `fab-test`; exit 1 for both a schema error and an unreadable file |
| `pql-test contract lint` (upstream) | the slicer contract | Gap: the walkthrough's lint step leaves fab-test |

## `pbir contract init`

- **Not discoverable.** `fab_test.py`'s `main` catches `argv[1:3] == ["pbir", "contract"]` before argparse, so `fab-test help`, `list` and `explain` don't know it exists; only `fab-test pbir --help`'s epilog names it.
- **No `lint` verb.** People are sent to `pql-test contract lint CONTRACT MODEL`, which takes the contract file and the model rather than the report.
- Fixed 2026-11-19 (Authoring Command Grammar epic): TARGET takes a name as the run's does, `--artifact`'s metavar and help match the run's, `--artifact-dir` and `--format` default from `fab-test.yml`, `-q` prints one result line, and flags.md lists `-q`/`-v`.

## Planned

- **Data Agent Testing epic, decision 3:** `promptfooconfig.yaml` inside `NAME.DataAgent/`. Fabric's Commit to Git deletes files in an item folder that aren't part of its definition; the suite belongs beside the folder.
- **Data Agent Testing epic, decision 10:** `fab-test data-agent init` puts a verb in the analyzer's TARGET position and names no noun. Under the grammar it is `fab-test data-agent tests init`, with `tests lint` beside it.
- **`fab-test playwright init` (plan.md standalone task):** no noun yet. If it scaffolds the execution YAML that `--playwright-config` reads, the noun names that file.

## Authored inputs with no verb (not gaps)

A verb is added only when a flow needs one (decision 4). These are listed so a
future epic starts from them:

- `*.Tests.dax` under `<Model>.SemanticModel/DAXQueries/`, run by `pql-test`. Upstream `pql-test contract generate` writes tests from an ODCS contract (ODCS Contract Analyzer epic).
- The Playwright execution YAML (`--playwright-config`) and `.env` files (`--env-file`, `--playwright-env-file`).
- T-TEST procedures for `sqldb-test`: part of the SQL database's own definition, so inside the item folder is correct. Decision 7 covers only files outside an item's definition.
