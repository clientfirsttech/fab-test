# Reports

Result envelopes are the machine contract. A person who wants to know *what actually failed* needs something else, so `fab-test` can write a readable HTML report per artifact.

**Generation is opt-in.** Nothing is written unless `--report` is passed (or `report: true` in `fab-test.yml`, or `ANALYZER_REPORT=1`), so no existing run gets slower and no pipeline collects artifacts it did not ask for.

```bash
fab-test all --report          # reports for every analyzer, plus an index
fab-test bpa --report          # one analyzer
fab-test all --report --no-report   # invalid: mutually exclusive, exits 2
```

## Where a report comes from

| Analyzer | Report | Why |
|----------|--------|-----|
| `pbir` | Upstream `native.json/TestRun.html` | PBIR Inspector produces its own, richer than anything rendered from the envelope. **Appears with or without `--report`.** |
| `bpa` | Generated `report.html` | Tabular Editor emits TRX (Visual Studio TeamTest XML); there is no HTML to wrap. |
| `pql-test` | Generated `report.html` | `pql-test` emits JSON and CI log annotations only. |

The generated report never overwrites an upstream one: `attach_report` is a no-op when the envelope already carries `native_html_output_path`. PBIR's own `TestRun.html` also has two upstream asset paths repaired in place, both by inlining as base64 data URIs rather than leaving a relative path for the browser to resolve: the favicon (`fix_favicon_link`) -- FabInspCLI ships it relative to the tool's *install* directory, which 404s once the report lands under `fab-test-results/` -- and each per-object screenshot (`fix_screenshot_images`) -- the template builds that `src` as `PBIInspectorPNG\<Id>.png`, a Windows-style relative path with the same problem. An object whose screenshot file genuinely isn't in that folder is left as it was; only the images that exist but couldn't resolve get fixed. Because `native_out` is reused run-over-run for the same artifact, a stale `PBIInspectorPNG` folder left from a prior run is removed before the inspector binary runs (whenever HTML output is requested) — FabInspCLI does not regenerate that folder against an already-populated one, while it does randomize every finding's `Id` each run, so a leftover folder would otherwise get inlined against the wrong run's ids.

Every report is a single self-contained file — no external stylesheet, script, or font ever fetches, links, or points off the page, so it opens from disk and survives being uploaded as a CI artifact. Rendering is deterministic: the same envelope always produces the same bytes, and the run time shown comes from the envelope's `started_at`, never from render time.

**A failure to render is a warning, never a failed build.** Exit codes belong to findings, not to presentation.

## The full test list and its filter

`findings` only ever holds violations — a passing run has always rendered as "No findings" with no evidence of what ran. An envelope may additionally carry `test_results`: every test or rule the analyzer evaluated, passed or failed. When it is present and non-empty, `render_report` shows that full list instead of the findings-only table, each row tagged `pass`/`warning`/`error`/`skip`, with an **All / Errors / Warnings / Passed** filter above the table — pure CSS (hidden radio inputs + sibling selectors). `bpa` and `pql_test` both populate `test_results` today; `pbir`'s own `TestRun.html` has its own filter UI and is untouched by this.

The full list also has a **search box and clickable, sortable column headers** (Search and Sort epic) — the one place the report emits an inline `<script>`. It never fetches, links, or references anything outside the page, so the self-contained-report guarantee still holds; only the stricter "no script at all" claim was relaxed. Typing in the search box hides any row whose text doesn't match, live; clicking a header sorts by that column (ascending, then descending on a second click), and appends a ▲/▼ arrow to that header so the active column and direction stay visible — clicking a different header moves the arrow, clearing the previous one (Sort Direction Indicator epic). Both search and sort compose with the status filter and with each other, and a "No matching rows" message appears if all three combine to nothing. None of this appears on the findings-only table or the per-run index — both have no full test list to search or sort, so neither gets the search box or the script.

**Extending this to a new analyzer**: populate `test_results` on the envelope with a list of dicts in either shape `normalize_findings` already recognizes (pql-test's `suite_name`/`test_name`/`passed`/`expected`/`actual`, or a rule shape with `rule`/`severity`/`object`/`message` plus a `status` key of `pass`/`error`/`warning`/`skip`) — the renderer, the filter, the search box, the column sort, and the status colouring all come for free. No new HTML to write.

## The per-run index

`fab-test all --report` also writes `fab-test-results/index.html` linking every report and envelope, so one run means one page to open rather than four. It is built from the same rows the terminal summary prints, so its counts cannot disagree with them. A single-analyzer command with more than one artifact (`fab-test a11y`, `bpa`, `pbir`, ...) gets the same treatment under `--report`: an index is written for that run too. Only a single analyzer against exactly one artifact skips the index, since that shape already has one report to point at.

The index header also shows **when the run happened and who ran it**: a UTC timestamp, plus branch/commit/actor sourced from `GITHUB_*` environment variables in CI, falling back to local `git` (branch, commit, `git config user.email`) outside CI, and to an em-dash (`—`) placeholder outside a git checkout entirely — it never raises. Per-analyzer `report.html` deliberately has no timestamp (see above): the index is scoped to one run, not a reusable artifact, which is why only it gained one.

## Finding the paths

The `all` summary lists one path per artifact beneath the table — the report where there is one, the envelope otherwise:

```
  ╭────────────┬───────────────────────┬──────────┬───────┬────────╮
  │ Analyzer   │ Artifact              │ Status   │   Err │   Warn │
  ├────────────┼───────────────────────┼──────────┼───────┼────────┤
  │ pbir       │ SampleModel-PQLAssert │ FAILED   │     4 │      1 │
  │ bpa        │ SampleModel-PQLAssert │ warning  │     0 │     21 │
  ╰────────────┴───────────────────────┴──────────┴───────┴────────╯

  pbir/SampleModel-PQLAssert
    fab-test-results/pbir/SampleModel-PQLAssert/native.json/TestRun.html
  bpa/SampleModel-PQLAssert
    fab-test-results/bpa/SampleModel-PQLAssert/report.html
```

Paths are relative to the working directory and never truncated, so they stay clickable in a terminal that linkifies them. Under `--format json` each artifact row carries `report_path` (null when absent) alongside `output_path`, which keeps its existing meaning.

## Open Report

`--open-report` closes the "find it in Explorer, double-click" gap after a local run: it opens the produced report/index in the default browser instead of leaving you to find the path yourself.

```bash
fab-test bpa --open-report          # runs bpa, opens report.html when it's done
fab-test all --open-report          # runs every configured analyzer, opens the run's index.html
fab-test bpa --no-report --open-report   # invalid: --open-report needs a report to open, exits 2
```

- **Implies `--report`.** Passing `--open-report` alone still turns report generation on for that run — it is never a silent no-op, and you never have to pass both flags.
- **Which path it opens** depends on the run shape, the same one [The per-run index](#the-per-run-index) and [Finding the paths](#finding-the-paths) already describe: the index for any run with more than one artifact (`fab-test all` across analyzers, or one analyzer across several artifacts), the single `report.html`/native report for a single-analyzer command against exactly one artifact. Every shape with more than one report to choose from opens the same kind of page, rather than only some of them opening anything.
- **A no-op under CI.** `--open-report` is suppressed whenever `GITHUB_ACTIONS` or `CI` is set: a build agent has no display to pop a browser onto, so it falls back to printing the path exactly like a run without `--open-report` would. Do not add it to a pipeline YAML — the guard means it does nothing there anyway.
- **Never fails a run.** No browser available, no display, `webbrowser.open()` raising — every one of these prints the path instead of raising, matching the report renderer's own "a failure to render is a warning, never a failed build" contract above.
- **Env var**: `ANALYZER_OPEN_REPORT=1` behaves like passing the flag, one level below the CLI flag in precedence (same chain as `ANALYZER_REPORT`).

## Colour

Status and non-zero error/warning counts are coloured in text output. Colour is **off** when stdout is not a terminal, **off** whenever `NO_COLOR` is set (any value), always **off** under `--format json`, and can be forced on with `FORCE_COLOR=1` for a CI job that renders ANSI.
