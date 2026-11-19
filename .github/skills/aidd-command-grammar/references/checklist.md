# Authoring command touch points

Every place an authoring verb (`fab-test <analyzer> <noun> <verb>`) has to
agree with its siblings and with the run, surveyed 2026-11-19 against
`pbir contract init`. Symbols are named instead of line numbers, which drift.
**Guard** names the test that catches an omission; `none` means nothing does
and you have to check it yourself.

## Words and dispatch

| Item | Where | Guard |
|---|---|---|
| The noun is a subparser of its analyzer, and each verb a subparser of the noun | `fab_test_parser.py` (pbir: `fab_test.py`'s `main` hands `argv[1:3] == ["pbir", "contract"]` to `contract_main`, a known gap) | none |
| The verb is `init` or `lint`; a third is added to the skill first | the verb's parser | none |
| The noun names one file format across analyzers | the skill's Grammar | none |
| The analyzer's `--help` epilog names the verbs (`add_contract_flags` sets pbir's) | the analyzer's flag helper | none |
| `fab-test help` names the verbs | `fab_test_admin.py`'s `_print_help` | none |

## Inputs

| Item | Where | Guard |
|---|---|---|
| TARGET is the item; `--artifact` + `--artifact-dir` find it as on the run (metavar, help, deprecation note) | the verb's parser vs `_add_common_flags` | none |
| `--artifact-dir` and `--format` defaults resolve from config (`_PYPROJECT_CONFIG`, `merged_file_config` + `resolve_setting`) | the verb's parser or its `main` | none |
| `--as-of`, `--<noun> FILE` shared with the run where the run has them | `add_contract_flags` (pbir) | none |
| The file is found by the run's pairing (`_contract_files`, `_pair` for pbir), not a second lookup | `_slicer_contract_run.py` (pbir) | per-verb tests |

## Files

| Item | Where | Guard |
|---|---|---|
| `<Item>.<Type>.<suffix>` beside the item folder (`_contract_path` for pbir) | the verb module | per-verb tests |
| Paired by an identity in the file (`fabTestReport` = the report's `logicalId`) | the file format | per-verb tests |
| Append, keep ids, `--force` to change (`_merge`) | the verb module | per-verb tests |

## init without a person

| Item | Where | Guard |
|---|---|---|
| `--questions` with `suggested` and `needs_human` per question; one JSON document with `--format json` | `build_questions`, `print_payload` | per-verb tests |
| `--answers FILE` by question id | `_answers` | per-verb tests |
| Refuse with exit 2 before asking when no one can answer (`can_ask`) | the verb's `main` | per-verb tests |
| `--dry-run` writes nothing | the verb's write step | per-verb tests |

## Output

| Item | Where | Guard |
|---|---|---|
| `-q`/`-v` mutually exclusive, resolved flag → `ANALYZER_VERBOSITY` → `fab-test.yml` (`add_output_flags`, `level`) | `_slicer_init_output.py` | per-verb tests |
| `-q` prints one result line per item | the verb's printer | none |
| The next step named in text and as `next` in JSON | the verb's printer | none |
| Run-only flags refused with exit 2 naming the run (`pbir_refusal`) | `_slicer_init_output.py` | per-verb tests |
| An upstream linter's result mapped to the grammar's exit codes | the lint verb | per-verb tests |

## Callers

| Item | Where | Guard |
|---|---|---|
| The verbs and their flags in flags.md, both copies | `.github/skills/fab-test/references/`, `src/fab_test/skill/references/` | `test_skill_resource.py` (copies match) |
| One flag table per flow: rows per flag, columns init / lint / run | flags.md and the flow's guide | none |
| A walkthrough with save, init, lint, run, break it, CI, and a flowchart | `docs/<FLOW>-WALKTHROUGH.md` | none |
| A CI snippet that runs lint before the run | the walkthrough | none |
| Every mode run through the installed console script before review | the epic's verification notes | none |
