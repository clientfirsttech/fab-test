# Slicer contracts (`fab-test pbir`)

A slicer contract states what a PBIR report's slicers open with (the values preselected when the report loads) and which bookmark each bookmark navigator highlights (its preselection; it doesn't apply that bookmark on open). `fab-test pbir` checks it alongside the packaged PBIR Inspector rules; `fab-test pbir contract init` builds it. Read this when a user wants a report's landing state checked, a default that follows the calendar (the current semester or quarter), or a finding whose rule starts with `CONTRACT.`.

## The file

An ODCS v3 data contract named `<Report>.Report.odcs.yaml`, in `fab-tests/pbir/` at the repository root (`--tests-dir` moves it). Never inside the report folder: Fabric's Commit to Git deletes files inside an item folder that aren't part of its definition. A contract under `--artifact-dir` still pairs. It pairs with the report whose `.platform` `logicalId` equals its `fabTestReport` custom property.

```yaml
apiVersion: v3.1.0
kind: DataContract
id: sales-slicer-defaults
version: 1.0.0
status: active
customProperties:
  - property: fabTestReport                  # the report's .platform logicalId
    value: b3cba6e7-ddfc-4bcd-b4b1-5f2a3d5297fc
  - property: fabTestCalendar                # only needed for calendar-driven values
    value: {fiscal_year_start_month: 7, fiscal_year_named_by: end}
  - property: fabTestBookmarkNavigators      # only needed for bookmark navigators
    value:
      - {id: overview-navigator, page: Overview, selected: Home}   # bookmark display name; null = none
schema:                                      # only the tables your slicers use; omit when there are none
  - name: Fiscal Calendar                    # the slicer's table
    properties:
      - name: Fiscal Semester                # the slicer's column
        quality:
          - id: semester-default
            type: custom
            engine: fab-test
            severity: error                  # error (default) | warning
            implementation:
              page: Overview                 # the page's display name, never a visual ID
              selected: ["FY{fiscal_year_short}-S{fiscal_semester}"]
```

Check the file before running it with `fab-test pbir contract lint REPORT` (see [Linting a contract](#linting-a-contract)); `pql-test contract lint <contract> <Model>.SemanticModel` is the upstream half of that check.

`implementation` holds `page` and exactly one check:

| Check | Slicer | Example |
|---|---|---|
| `selected` | value slicers and field parameters (by display name); `[]` means nothing ticked, `all` means "Select all" ticked (each fails the other) | `[Bad]`, `[1940]`, `[Number of Characters]`, `all` |
| `range` | Between, or a date picker range picked on the calendar; `to` is inclusive; either bound may be left open | `{from: 1939-10-01, to: 1951-08-27}` |
| `relative` | Relative date slicer | `{range: Last, duration: 20, period: Calendar Months}` |
| `contains` | input slicer (`textSlicer`); `[]` means nothing typed | `[Wolverine]` |

A check reads one shape: a plain list of values on one column, an input slicer's text, a from/to date range, or a relative period. A slicer whose selection is in any other shape ("Select all" then untick, several columns, a hierarchy) fails its check with "a selection this check can't read" rather than passing, and `init` offers it only `skip`. A rule matches every slicer on its column on its page, so two slicers there with different selections can't be checked (`init` offers `skip`).

Rule ids must be unique, and `page.` is reserved. An `engine: fab-test` rule must be `type: custom`. A fixed value containing `{` or `}` is written `{{` / `}}`, since braces mark calendar fields (`init` escapes them for you).

pql-test reads the same file and skips `engine: fab-test` rules; fab-test skips everyone else's. fab-test never calls pql-test. A `*.odcs.yaml` that isn't valid YAML and mentions no `fab-test` rule is skipped with a warning.

## Bookmark navigators

A navigator has no column, so it is an entry in `fabTestBookmarkNavigators`, not a quality rule: `id`, `page` (display name), `selected` (the bookmark's display name as the report shows it, or `null` for nothing preselected) and optional `severity`. Never a bookmark's internal name or a visual ID: fab-test looks the display name up in `definition/bookmarks/*.bookmark.json` when it compiles. An entry checks every navigator on its page. Ids are shared with slicer rules, so they must be unique across both. A contract with only navigator entries is still a fab-test contract. Only bookmarks listed in `bookmarks.json` count, and a display name two bookmarks share matches neither (`init` offers only `skip`), so a name always says which bookmark.

It fails when the navigator preselects another bookmark, nothing (when one is expected), a bookmark since deleted, or anything (when `null` is expected); when the page has no navigator; and when the contract names a bookmark the report doesn't have (renamed or deleted).

## Calendar-driven values

A `selected` or `contains` string with `{fields}` is resolved for the run's date (`--as-of`, default today) under the contract's `fabTestCalendar` (`fiscal_year_start_month` 1-12, default 1; `fiscal_year_named_by` `start` | `end`, default `end`).

Fields: `year`, `year_short`, `half`, `quarter`, `month`, `fiscal_year`, `fiscal_year_short`, `fiscal_semester`, `fiscal_quarter`, `fiscal_month`. `*_short` are two-digit text (`09`). A format spec is allowed (`{month:02}`). A value that is one bare field (`"{year}"`) keeps its type, so it matches a whole-number column (`2026L`). Nothing is evaluated: attribute or index access, conversions and nested placeholders are refused.

### Fiscal years differ: always ask

`fabTestCalendar` is the user's company fiscal calendar, and nothing in the report says what it is. Ask the user; never infer it:

- "Which month does your fiscal year start in?"
- "Is the year that runs to <month before the start> 2027 called FY27 or FY26?" (the year it ends in is `end`; the year it starts in is `start`)

`init` asks the two fiscal questions only when an answer follows a fiscal field (`fiscal_year`, `fiscal_year_short`, `fiscal_semester`, `fiscal_quarter`, `fiscal_month`); `{year} H{half}` or `{year}-{month:02}` need no fiscal year, and no `fabTestCalendar` is written for them. The questions have no `suggested` answer unless the contract already holds a `fabTestCalendar` (a person's earlier answer), because on any one day several fiscal years produce the same label: on 2026-09-30, `FY26` fits start months 1, 10, 11 and 12 for a year named by the year it ends in, and 1 to 9 for one named by the year it starts in. `reproduces` lists the start months that fit today's values under either naming, and `applies_to` the slicer questions that need the answer. A January start needs no naming answer.

`init` refuses (exit 2, nothing written) a fiscal year under which a slicer answered `current` isn't on today's period, e.g. an April start for a report on `FY27-S1` in November 2026 (that would be `FY27-S2`). Either the answer is wrong or the report is stale: ask the user which, and fix the slicer in Desktop or answer `keep`.

| Fiscal year | `fiscal_year_start_month` | `fiscal_year_named_by` | Where the year turns over, as `FY{fiscal_year_short}` |
|---|---|---|---|
| Calendar year | 1 | `end` (either) | 2026-12-31 `FY26` / 2027-01-01 `FY27` |
| October start, named by end year (e.g. US federal) | 10 | `end` | 2026-09-30 `FY26` / 2026-10-01 `FY27` |
| July start, named by end year (e.g. Microsoft, Australia) | 7 | `end` | 2026-06-30 `FY26` / 2026-07-01 `FY27` |
| April start, named by end year (e.g. India) | 4 | `end` | 2026-03-31 `FY26` / 2026-04-01 `FY27` |
| April start, named by start year (e.g. Japan) | 4 | `start` | 2026-03-31 `FY25` / 2026-04-01 `FY26` |

`fiscal_quarter`, `fiscal_semester` and `fiscal_month` count from the start month (1 October is Q1 for an October start). Preview a rollover with `--as-of` on its first day (`--as-of 2026-10-01`); the scheduled run catches it for real.

Limits: one `fabTestCalendar` per contract, so a report whose slicers follow two different fiscal years can follow only one; check the other with `keep` or skip it. A label naming both years (`2026-27`, `FY2026/27`) can't be written as a format, since the fields name only one fiscal year; use `keep`, and update it at rollover.

## Running the check

```bash
fab-test pbir                                   # every report; each pairs with its contract
fab-test pbir --artifact Sales --as-of 2027-01-15   # reproduce a run on a given day
fab-test pbir --artifact Sales --contract path/to/contract.yaml   # skip pairing
```

`--contract FILE` applies to every report in the run, so use it with one report (a deployed report exported for `--workspace` has no `logicalId` to pair on). `all`, `local` and `explain pbir` pair contracts too.

## Linting a contract

```
ContractLint {
  fab-test pbir contract lint [TARGET] [--contract FILE] [--as-of DATE] [-q | -v] [--format json]
  TARGET => the report, as init and the run take it; none => every contract under --artifact-dir, each paired by logicalId
  checks => fab-test reads it as the run will (calendar as of --as-of) and it pairs with a report;
            pql-test validates ODCS and resolves table/column names in the model definition.pbir's byPath names
  (the model isn't in the folder, e.g. byConnection) => names not checked, said in the output; the rest still runs
  exit => 0 clean | 1 a problem in a file, unreadable YAML included | 2 nothing to check (no report, no paired
          contract, a run-only flag) | 127 pql-test missing
  --format json => one document: {ok, contracts: [{report, contract, model, as_of, ok, apiVersion, rules,
                   problems: [{source: fab-test | pql-test, message}]}], next}; `next` null unless ok
  -q => `contract lint passed|failed problems=N PATH` per contract; problems on stderr
  writes nothing; --report, --open-report, --no-report and --output-dir exit 2 naming the run
}
```

`init`, `lint` and the run take the same inputs and output flags:

| Flag | `contract init` | `contract lint` | `fab-test pbir` |
|---|---|---|---|
| `TARGET` / `--artifact` | the report; required | the report; none = every contract | the report; none = every report |
| `--artifact-dir`, `--format` | default from `fab-test.yml` | same | same |
| `--contract FILE` | refused | the contract to check | checked against every report |
| `--as-of` | suggests `current` for that date | resolves the calendar | resolves the calendar |
| `--dry-run` | show, write nothing | — | list, run nothing |
| `-q` | `contract written` (or `unchanged`) `added=N … PATH` | `contract lint passed problems=N PATH` | `pbir passed e=N w=N PATH` |
| `--format json` `next` | `fab-test pbir contract lint TARGET [--artifact-dir DIR]` | `fab-test pbir [TARGET] [--artifact-dir DIR]` | — |
| A flag of the run it doesn't take (`--telemetry`, `--timeout`, ...) | exit 2 naming the run | exit 2 naming the run | — |
| `--report`, `--open-report`, `--output-dir` | refused | refused | yes |

## Building a contract

```
ContractInit {
  (on a terminal) => fab-test pbir contract init REPORT        // asks per slicer; Enter takes the suggestion
                                                                 // the fiscal year has none: it must be typed
  (an agent) => {
    1. fab-test pbir contract init REPORT --questions --format json
    2. ask the user every question with needs_human: true; take `suggested` for the rest
       (the calendar.* questions, when listed: ask in the user's words, see Fiscal years differ;
        they're needed only if the user answers current for a question in their applies_to)
    3. write {question id: answer} to a JSON file
    4. fab-test pbir contract init REPORT --answers FILE [--dry-run]
  }
  (no terminal and no --answers) => exit 2 naming --questions and --answers   // never waits for input
  terminal = stdin and stderr both one; on Windows a real console (stdin on NUL, as agents run commands, isn't)
  answer per slicer = keep | current | skip | {"current": "<format>"}
  current is offered (choices) only when a known period format reproduces today's value; the question's
  calendar_format names it. A label init doesn't recognise can still take {"current": "<format>"}
  answer per bookmark navigator (question has kind: navigator) = keep | skip   // skip only when two on a page differ or one preselects a deleted bookmark
  answer for calendar.fiscal_year_start_month = 1..12; calendar.fiscal_year_named_by = start | end
  (a current answer follows a fiscal field, and no fiscal year answered or in the contract) => exit 2 naming it
  (under the answered fiscal year a current slicer isn't on today's period) => exit 2; nothing written
  (--force replaces the contract's fabTestCalendar) => every rule following a fiscal field is checked again; the same
  (current for a slicer with no values ticked: a range, relative, input, Select all or nothing ticked) => exit 2
  (an existing contract) => adds rules for uncovered slicers; keeps every rule it has; --force replaces a differing rule's implementation only (severity and other keys stay)
  (a rule or navigator already in the contract) => its question keeps that rule's id, even one renamed by hand; a new rule never takes an id the contract uses
  (its fabTestCalendar differs from the answers) => kept and reported (`calendar: kept`); --force replaces it
  (the contract contains '#') => exit 2 unless --force, because rewriting drops comments
  ('#' without --force, a file that isn't a YAML mapping, an id two rules share, or no contract and no .platform logicalId)
    => exit 2 before the first question, --questions included
  (the result wouldn't read back as fab-test pbir reads it, or the report has no .platform logicalId) => exit 2; nothing written
  (on a terminal) => prompts go to stderr, so --format json stdout stays one document
  -q / ANALYZER_VERBOSITY=summary / fab-test.yml verbosity: summary => one line on success,
                                     `contract written|unchanged added=N replaced=N kept=N unchanged=N PATH`; errors, --questions,
                                     --dry-run and --format json print as without -q
  TARGET => a path, or a report name found under --artifact-dir, as `fab-test pbir` takes it; --artifact is its alias
  --artifact-dir, --format => default from fab-test.yml (artifact_dir, format) when the flag isn't given
  -v => also every rule in the contract: id, page, field, what it expects, and added | kept | replaced | unchanged
  --report | --no-report | --open-report => exit 2 naming `fab-test pbir <name> --open-report`
  --contract | --output-dir => exit 2 naming `fab-test pbir <name> <flag> ...` (init writes to fab-tests/pbir/)
  any other flag of the run (--telemetry, --timeout, --jobs, ...) => exit 2 naming `fab-test pbir <name> <flag> ...`
  Ctrl-C at a prompt => exit 130; nothing written
}
```

Each question carries `current` (what the slicer opens with), `choices`, `suggested`, and for a single value that a calendar format reproduces today, `calendar_format`. The `calendar.*` questions are listed only when a suggested format uses a fiscal field; `calendar.fiscal_year_start_month` lists the start months that reproduce every such suggestion (`reproduces`), and both list the slicer questions that need them (`applies_to`). An answers file may give them even when unlisted, for a `{"current": "<format>"}` that uses a fiscal field. `contract` is reserved in pbir's TARGET position: a report named `contract` is reached with `--artifact contract`.

## Findings and the envelope

One rule per expectation (`CONTRACT.<id>`) and one per page (`CONTRACT.page.<display name>`), with the contract's severity. A finding's `object` is the page; its `message` names the field, what the slicer opens with and what the contract expects, e.g. `'Fiscal Calendar'[Half Year] opens with ['2025 H2']; the contract expects 2026 H2`, or for a navigator `the bookmark navigator opens with [Bookmark 2]; the contract expects Bookmark 1`. A missing slicer or a renamed page is a finding, never a silent pass. The envelope gains `contract`: `file`, `as_of`, `report_logical_id`, and each rule's resolved `expected`; `navigators` lists each navigator entry's `expected` bookmark and the internal `bookmarks` it resolved to.

Two rule sets run together: the PBIR rules (packaged or `--rules`) and the contract's `CONTRACT.*` rules. Every envelope finding and `test_results` row carries `source`: `rules` or `contract`; filter on it rather than the id prefix. A contract finding's `message` is what the rule found, without PBIR Inspector's `Rule "…" FAILED with result: [...]` wrapper. With `--report` / `--open-report`, the report is fab-test's page (as for `bpa`): a line naming the contract's path, its checks and how many failed (or why none paired) and how the PBIR rules did; one filterable table for both rule sets, whose `Source` column says `PBIR rules` or `Slicer contract (<file name>)`, a contract check being one row (its worst result across the pages it ran on; the message is what it found, or what it expects when it passed); and PBIR Inspector's TestRun.html collapsed in a frame at the bottom, where the contract's results are under ruleset `Slicer contract` instead of `Rules`. The run header names the paired contract (`📜 Slicer contract: <file> (<n> slicer checks, <n> bookmark navigators)`) or says `none` with the `logicalId` it looked for, and the count line splits findings by source (`… from the PBIR rules, … from the slicer contract`).

A malformed contract, an unknown calendar field, a bad calendar setting, or two contracts pairing with one report: exit `2` before any analyzer starts, one message naming each problem by its path in the file. Every contract under `--artifact-dir` is read, so a broken contract for another report stops an `--artifact` run too; the message says so.

Selection shapes Desktop writes, which the rules read, are listed in `fabric-artifacts/README.md` (SampleModel-DefaultState test bed).
