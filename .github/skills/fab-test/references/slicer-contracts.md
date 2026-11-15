# Slicer contracts (`fab-test pbir`)

A slicer contract states what a PBIR report's slicers open with: the values preselected when the report loads. `fab-test pbir` checks it alongside the packaged PBIR Inspector rules; `fab-test pbir contract init` builds it. Read this when a user wants a report's landing state checked, a default that follows the calendar (the current semester or quarter), or a finding whose rule starts with `CONTRACT.`.

## The file

An ODCS v3 data contract named `<Report>.Report.odcs.yaml`, beside the report folder. Never inside it: Fabric's Commit to Git deletes files inside an item folder that aren't part of its definition. It pairs with the report whose `.platform` `logicalId` equals its `fabTestReport` custom property.

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
schema:
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

`implementation` holds `page` and exactly one check:

| Check | Slicer | Example |
|---|---|---|
| `selected` | value slicers and field parameters (by display name); `[]` means no selection | `[Bad]`, `[1940]`, `[Number of Characters]` |
| `range` | Between, or a date picker range picked on the calendar; `to` is inclusive; either bound may be left open | `{from: 1939-10-01, to: 1951-08-27}` |
| `relative` | Relative date slicer | `{range: Last, duration: 20, period: Calendar Months}` |
| `contains` | input slicer (`textSlicer`); `[]` means nothing typed | `[Wolverine]` |

A check reads one shape: a plain list of values on one column, an input slicer's text, a from/to date range, or a relative period. A slicer whose selection is in any other shape ("Select all" then untick, several columns, a hierarchy) fails its check with "a selection this check can't read" rather than passing, and `init` offers it only `skip`. A rule matches every slicer on its column on its page, so two slicers there with different selections can't be checked (`init` offers `skip`).

Rule ids must be unique, and `page.` is reserved. An `engine: fab-test` rule must be `type: custom`. A fixed value containing `{` or `}` is written `{{` / `}}`, since braces mark calendar fields (`init` escapes them for you).

pql-test reads the same file and skips `engine: fab-test` rules; fab-test skips everyone else's. fab-test never calls pql-test. A `*.odcs.yaml` that isn't valid YAML and mentions no `fab-test` rule is skipped with a warning.

## Calendar-driven values

A `selected` or `contains` string with `{fields}` is resolved for the run's date (`--as-of`, default today) under the contract's `fabTestCalendar` (`fiscal_year_start_month` 1-12, default 1; `fiscal_year_named_by` `start` | `end`, default `end`).

Fields: `year`, `year_short`, `half`, `quarter`, `month`, `fiscal_year`, `fiscal_year_short`, `fiscal_semester`, `fiscal_quarter`, `fiscal_month`. `*_short` are two-digit text (`09`). A format spec is allowed (`{month:02}`). A value that is one bare field (`"{year}"`) keeps its type, so it matches a whole-number column (`2026L`). Nothing is evaluated: attribute or index access, conversions and nested placeholders are refused.

## Running the check

```bash
fab-test pbir                                   # every report; each pairs with its contract
fab-test pbir --artifact Sales --as-of 2027-01-15   # reproduce a run on a given day
fab-test pbir --artifact Sales --contract path/to/contract.yaml   # skip pairing
```

`--contract FILE` applies to every report in the run, so use it with one report (a deployed report exported for `--workspace` has no `logicalId` to pair on). `all`, `local` and `explain pbir` pair contracts too.

## Building a contract

```
ContractInit {
  (on a terminal) => fab-test pbir contract init REPORT        // asks per slicer; Enter takes the suggestion
  (an agent) => {
    1. fab-test pbir contract init REPORT --questions --format json
    2. ask the user every question with needs_human: true; take `suggested` for the rest
    3. write {question id: answer} to a JSON file
    4. fab-test pbir contract init REPORT --answers FILE [--dry-run]
  }
  (no terminal and no --answers) => exit 2 naming --questions and --answers   // never waits for input
  answer per slicer = keep | calendar | skip | {"calendar": "<format>"}
  answer for calendar.fiscal_year_start_month = 1..12; calendar.fiscal_year_named_by = start | end
  (an existing contract) => adds rules for uncovered slicers; keeps every rule it has; --force replaces a differing rule's implementation only (severity and other keys stay)
  (its fabTestCalendar differs from the answers) => kept and reported (`calendar: kept`); --force replaces it
  (the contract contains '#') => exit 2 unless --force, because rewriting drops comments
  (the result wouldn't read back as fab-test pbir reads it, or the report has no .platform logicalId) => exit 2; nothing written
  (on a terminal) => prompts go to stderr, so --format json stdout stays one document
}
```

Each question carries `current` (what the slicer opens with), `choices`, `suggested`, and for a single value that a calendar format reproduces today, `calendar_format`. `calendar.fiscal_year_start_month` lists the start months that reproduce every calendar suggestion (`reproduces`); more than one means the user must say which. `contract` is reserved in pbir's TARGET position: a report named `contract` is reached with `--artifact contract`.

## Findings and the envelope

One rule per expectation (`CONTRACT.<id>`) and one per page (`CONTRACT.page.<display name>`), with the contract's severity. A finding's `object` is the page; its `message` names the field, what the slicer opens with and what the contract expects, e.g. `'Fiscal Calendar'[Half Year] opens with ['2025 H2']; the contract expects 2026 H2`. A missing slicer or a renamed page is a finding, never a silent pass. The envelope gains `contract`: `file`, `as_of`, `report_logical_id`, and each rule's resolved `expected`.

A malformed contract, an unknown calendar field, a bad calendar setting, or two contracts pairing with one report: exit `2` before any analyzer starts, one message naming each problem by its path in the file.

Selection shapes Desktop writes, which the rules read, are listed in `fabric-artifacts/README.md` (SampleModel-DefaultState test bed).
