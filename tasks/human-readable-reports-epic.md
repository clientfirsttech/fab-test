# Human-Readable Reports Epic

**Status**: 🚧 IN-PROGRESS (2/7)
**Goal**: Every analyzer produces a report a person can open and read, and the summary points at it.

## Overview

When `fab-test all` finishes, the Output column points at `envelope.json` — the machine contract. A human who wants to know *what actually failed* has to open a JSON file and read findings by hand, or re-run with `-v`. PBIR Inspector is the exception: it emits `TestRun.html`, a real report, and the envelope even records the path — but nothing surfaces it, so the one readable artifact in the tree is invisible. Meanwhile Tabular Editor emits TRX (Visual Studio TeamTest XML) and `pql-test` emits JSON; neither upstream tool can produce HTML at all, so for those analyzers a readable report is one `fab-test` has to render. This epic adds a Report column, promotes the HTML path to a real envelope key, and builds **one** renderer that serves every analyzer.

One renderer, not three. The envelope already normalizes findings, and [`fab_test_summary.py`](../src/fabric_ci_cd_dataops/scripts/fab_test_summary.py) already knows how to format the two shapes they come in — rule/severity/object/message for BPA and PBIR, suite/test/expected/actual for `pql-test`. The renderer is an HTML backend for formatting that already exists, which is why this is a bounded change rather than a reporting subsystem, and why an analyzer added later gets a report for free.

**On "facade, not fork"** ([vision.md](../vision.md)): rendering findings we already normalized is not reimplementing analysis. No rule is re-authored, no analyzer is reimplemented, and PBIR keeps its own upstream HTML because it is richer than anything generated from the envelope. The line held here is that `fab-test` never *computes* a finding — it only presents one it was given.

---

## 1. Add a Report Column to the Aggregate Summary ✅

Surface the readable artifact that already exists before generating any new ones.

**Done (2026-08-20)**: the `all` summary gains a `Report` column, populated from the envelope's optional HTML key. Both path columns are relative and untruncated, so both stay clickable. The column is omitted entirely when nothing in the run produced a report — a header over nothing but blanks is noise. JSON gains `report_path` as a separate field, always present and null when absent, so a consumer tests one thing; `output_path` keeps its meaning.

**Requirements**:
- Given an analyzer whose envelope records an HTML report, then the `all` summary shows that path in a `Report` column.
- Given an analyzer with no report, then the cell is empty rather than repeating the envelope path.
- Given the text format, then both `Output` and `Report` paths are relative to the working directory and never truncated, so both stay clickable.
- Given `--format json`, then the report path is a separate field and `output_path` keeps its current meaning.
- Given no analyzer in the run produced a report, then the column is omitted entirely rather than printed empty.

**Files**: `fab_test_summary.py`
**Tests**: `pytest -m fab_test tests/test_summary_paths.py -k report`

---

## 2. Make the HTML Path a Real Envelope Key ✅

Turn an ad-hoc field into part of the contract, so the Report column reads a documented key rather than a PBIR implementation detail.

**Done (2026-08-20)**: `ENVELOPE_OPTIONAL_KEYS` joins `ENVELOPE_REQUIRED_KEYS` in `_analyzer_envelope.py`, with `native_html_output_path` its first member and a test asserting the two sets never overlap. `build_envelope` takes `native_html_output_path_str` and **omits the key entirely when empty** rather than writing an empty string — optional means absent, so a consumer tests presence and a key is never a promise pointing nowhere. Purely additive: existing envelopes without it stay valid.

`native_html_output_path` is currently set only in [`invoke_pbir_inspector.py`](../src/fabric_ci_cd_dataops/scripts/invoke_pbir_inspector.py#L140) and appears in no schema.

**Requirements**:
- Given the envelope schema, then `native_html_output_path` is a documented *optional* key, absent rather than null when there is no report.
- Given an existing envelope without the key, then every consumer still reads it without error — the key is additive.
- Given the key, then a test asserts the schema and the writer agree, matching the drift guards already used for the config schema and the run manifest.

**Files**: `_analyzer_envelope.py`, `invoke_pbir_inspector.py`
**Tests**: `pytest tests/test_analyzer_report.py -k html`

---

## 3. Build the Envelope-to-HTML Renderer

One renderer, driven by the envelope, reusing the finding formatters that already exist.

**Requirements**:
- Given any envelope, then a self-contained HTML file is produced with no external CSS, JS, or font requests — it must open from disk and survive being uploaded as a CI artifact.
- Given findings in the rule/severity/object/message shape, then they render as a sortable table grouped by severity.
- Given findings in the suite/test/expected/actual shape, then they render with expected and actual side by side.
- Given an envelope with no findings, then the report still renders and says so plainly rather than showing an empty table.
- Given a finding containing HTML characters, then they are escaped — a rule name or DAX expression must never inject markup.
- Given the renderer, then it computes no finding of its own: every value shown traces to a field in the envelope.

**Files**: new `_report_html.py`
**Tests**: `pytest tests/test_report_html.py`

---

## 4. Generate Reports for BPA and pql-test

Wire the renderer into the analyzers whose upstream tools cannot emit HTML.

`pql-lint` is **out of scope for this version**: it is hidden from the advertised CLI surface (see `HIDDEN_ANALYZERS`), so generating a report nobody is pointed at would be work with no reader. The renderer is analyzer-agnostic, so if `pql-lint` is unhidden later it gains a report by being added to one list.

**Requirements**:
- Given a BPA run, then a report is written and its path recorded in `native_html_output_path`.
- Given a `pql-test` run, then the same, with test-level pass/fail detail.
- Given `pql-lint`, then no report is generated and nothing about its current behavior changes.
- Given PBIR, then its upstream `TestRun.html` is still used and no report is generated over it.
- Given any analyzer, then a failure to render is reported as a warning and never changes the run's exit code — a broken report must not fail a passing build.

**Files**: `fab_test_registry.py`, `_report_html.py`, `_analyzer_envelope.py`
**Tests**: `pytest -m bpa` then `pytest -m pql_test`

---

## 5. Decide When Reports Are Generated

Rendering on every run costs time and clutters CI artifacts; never rendering makes the feature invisible.

**Requirements**:
- Given no flag, then the default behavior is settled and documented, with the reasoning recorded here.
- Given `--report` / `--no-report`, then generation is forced on or off regardless of the default.
- Given a `report` key in `fab-test.yml`, then it resolves through the existing precedence chain (CLI > env > config > default).
- Given `--dry-run`, then no report is written.

**Files**: `fab_test.py`, `_config.py`, `schemas/fab-test.schema.json`
**Tests**: `pytest tests/test_config_loader.py -k report`

---

## 6. Add a Per-Run Index Page

`fab-test all` produces one report per analyzer per artifact. Opening four files to review one run is worse than opening one.

**Requirements**:
- Given a completed `all` run, then `analyzer-results/index.html` links every report and envelope produced.
- Given the index, then it shows each analyzer's status and error/warning counts, matching the aggregate summary exactly.
- Given the summary, then it names the index once so a reader knows where to start.
- Given a single-analyzer run, then no index is written — there is nothing to index.

**Files**: `_report_html.py`, `fab_test_summary.py`
**Tests**: `pytest -m fab_test tests/test_report_html.py -k index`

---

## 7. Document for All Three Callers

Per the documentation constraint in [vision.md](../vision.md). Use the `document` command so the three cannot drift apart.

**Requirements**:
- Given the `fab-test` skill, then it documents the `Report` column, the `native_html_output_path` envelope key, and the generation policy with its flag and config key.
- Given README and QUICK-VALIDATION, then a reader learns where to find a readable report without reading source.
- Given a pipeline author, then a snippet shows uploading `analyzer-results/index.html` as the reviewable build artifact.
- Given the docs, then they state which analyzers use an upstream report and which use the generated one, so nobody wonders why PBIR looks different.

**Files**: `.github/skills/fab-test/SKILL.md`, `README.md`, `docs/QUICK-VALIDATION.md`
**Tests**: `pytest` (full suite with coverage before commit)

---

## Deferred — A Report for `pql-lint`

Cut when `pql-lint` was hidden from the advertised CLI surface: a report nobody is pointed at is work with no reader. The renderer is analyzer-agnostic, so unhiding `pql-lint` and adding it to task 4's list is all this would take.

## Open Question — Should `fab-test local` Still Run `pql-lint`?

`_LOCAL_ANALYZERS` still includes it, and the `local` subcommand's help text names it, which is accurate but sits oddly against hiding it everywhere else. Left as-is deliberately: dropping it from `local` changes what a documented workflow *does*, which is a behavior change rather than the visibility change that was asked for. Worth an explicit decision before this epic closes.

## Deferred — Playwright Report Integration

Playwright has its own HTML reporter, so `playwright` should eventually populate `native_html_output_path` from it rather than use the generated report. Left out because `playwright` is not in the default `all` set and needs a workspace plus credentials to produce anything, making it the hardest to verify and the least often seen. Task 2's envelope key is what it will use when wired.

## Deferred — Trend and Baseline Views

Comparing a run against a previous one is a different feature from rendering a run, needs somewhere to store history, and duplicates [`compare_baseline.py`](../src/fabric_ci_cd_dataops/scripts/compare_baseline.py). Revisit only if reading two reports side by side proves genuinely insufficient.
