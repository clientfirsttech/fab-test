# Analyzer touch points

Every place a new analyzer must be registered, surveyed 2026-09-26 against
`a11y` (the most recent addition), `bpa`, and `pql_test`. Symbols are named
instead of line numbers, which drift. **Guard** names the test that catches an
omission; `none` means nothing does and you have to check it yourself.

## Wrapper: `src/fab_test/scripts/invoke_<name>.py`

| Item | Guard |
|---|---|
| Flags `--artifact-path`, `--output-path` (default `envelope_path(name, stem)`), `--verbose`, plus a tool-path flag if external | per-wrapper test only |
| `build_envelope(EnvelopeIdentity(...))` + `write_envelope`; keys in `ENVELOPE_REQUIRED_KEYS` | per-wrapper test only |
| `Timer` for `duration_ms` and `started_at` | none |
| Findings shaped `rule`/`severity`/`object`/`message`; severity `error`/`warning`/`info` | `severity_counts` treats unknown as error |
| `test_results` in a shape `normalize_findings` recognizes, so the HTML table renders | none |
| `attach_report(env, output_path)` before `write_envelope` | per-wrapper test only |
| `log()` to stderr under `ANALYZER_OUTPUT_MODE=json`; `ANALYZER_VERBOSITY` | per-wrapper test only |
| `::error::`/`::warning::` on stderr; error envelope before exit 1 | none |
| `native.<ext>` via `native_output_path`, recorded only if written | none |

## Registration: `fab_test_registry.py`

| Item | Guard |
|---|---|
| `ANALYZER_REGISTRY[name] = (glob, description)`; the glob also drives type routing | `test_target.py` (glob is a known type) |
| `ANALYZER_SCOPES[name]` | `test_target_scopes.py` (every analyzer declares scopes, accepts `path`, only API analyzers take `workspace`) |
| `HIDDEN_ANALYZERS` if not advertised | `test_hidden_analyzers.py` |
| `build_<name>_command` in `_COMMAND_BUILDERS`, writing to `output_dir/<key>/<stem>/envelope.json` | none for key parity |
| Default tool path constant; `_BOOTSTRAPPED_ANALYZERS`, `_BOOTSTRAP_REGISTRY_NAME`, `_TOOL_FLAG_HINTS` | none for parity |
| `_CLOUD_ANALYZERS`, `_DESKTOP_CAPABLE_ANALYZERS`, `_REPOSITORY_SCOPED_ANALYZERS` | none |
| Explicit-path branches in `resolve_tool` and `_readiness_without_version` | none |
| `check_readiness` returns the common shape | `test_readiness.py` (iterates the registry) |
| `_resolve_<name>_rules_path` if the analyzer has rules | none |

## Registration: elsewhere

| Item | Where | Guard |
|---|---|---|
| `_add_<name>_subparser` calling `_add_common_flags`; entry in `_SUBPARSER_BUILDERS` | `fab_test_parser.py` | `test_fab_test_output_contract.py` (parser-driven) |
| Aliases in `_SUBCOMMAND_ALIASES`, `_CANONICAL_TO_REGISTRY_KEY` | `fab_test_parser.py` | `test_fab_test_subcommand_names.py` (hardcoded) |
| `_TOOL_DISPLAY_NAMES` (`list`), explain's default rules map, `_ruleset_rows` (`config --show`) | `fab_test_admin.py` | none |
| `init` template comments for a rules overlay | `fab_test_admin.py` | none |
| `_LOCAL_ANALYZERS`, `_local_readiness` | `fab_test_local.py` | `test_local_command.py` (against itself) |
| `analyzer_registry.<key>`, `artifact_analyzers.<Type>`, `fab_test_all` | `metadata/analyzers.json` | none against the registry |
| `tool_install.release_source` so update checks see it | `analyzers.json`, `tools/check_tool_updates.py` | none; silently skipped |
| `_telemetry_table` for a dynamic analyzer | `fab_test_telemetry.py` | none |
| `_RULE_OVERLAY_ANALYZERS`; `rules.properties`; overlay apply fn | `_config.py`, `schemas/fab-test.schema.json`, `_rule_overlay.py` | none for parity |
| `THIRD-PARTY.md` row; `_WRAPPED_TOOLS` | repo root, `tests/test_third_party_notices.py` | the test (hardcoded) |

## Consumers that come for free once the envelope path is right

Exit code (`_artifact_exit_code`), CI annotations and PR review comments
(`_finalize_artifact_run`), telemetry payload (`_build_telemetry_payload`), run
manifest, summary tables and the run index (`fab_test_summary.py`,
`_report_html.render_index`), `--dry-run`.

## Tests and budgets

| Item | Guard |
|---|---|
| Marker in `pytest.ini` and `tests/conftest.py` `_ANALYZER_MARKERS`/`_MARKER_SUFFIX` | none between the two |
| `test_module_budget.py`: `fab_test_registry.py` and `fab_test_parser.py` sit at their exemption ceilings, so any new analyzer needs a split or a recorded exemption | the test |
| Coverage floor 80% over `src/fab_test` | CI |

## Documentation

README, `docs/QUICK-VALIDATION.md`, `.github/skills/fab-test/SKILL.md` and its
`references/` (flags, reports, targeting-and-discovery), copied byte-for-byte to
`src/fab_test/skill/` (`test_skill_resource.py`). A doc test in the shape of
`test_a11y_documentation.py`.
