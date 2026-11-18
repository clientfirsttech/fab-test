# Checking what a report's slicers open with

A customer agrees what a report shows when it opens: which alignment, which eye colours, which semester. Every edit risks saving a working selection over that agreement, and a default that follows the calendar goes stale at rollover with no commit to notice it. A **slicer contract** writes the agreement down once, along with the bookmark each bookmark navigator highlights; `fab-test pbir` checks it on every run.

Setting one up on your own report for the first time? Start with the [walkthrough](SLICER-CONTRACTS-WALKTHROUGH.md). This guide uses the test bed in `fabric-artifacts/`: `SampleModel-DefaultState.Report` and its contract, `SampleModel-DefaultState.Report.odcs.yaml`.

## 1. Build the contract

From the repository root:

```bash
fab-test pbir contract init fabric-artifacts/SampleModel-DefaultState.Report
```

`init` finds every slicer, shows what it opens with today, and asks how to check it:

```
Standard Slicers: 'AlignmentDim'[Alignment] opens with Bad. Keep checking that or skip it?
  [keep/skip] default keep:
Standard Slicers: 'Fiscal Calendar'[Fiscal Semester] opens with FY27-S1, which looks like the current period (FY{fiscal_year_short}-S{fiscal_semester}). Keep FY27-S1 always, follow the current period, or skip it?
  [keep/current/skip] default current:
```

- **keep** checks today's selection exactly.
- **current** checks that the slicer opens on the current period, whatever the date. It's offered only when `init` recognises today's value as one: `FY27-S1` becomes `FY{fiscal_year_short}-S{fiscal_semester}`, which will expect `FY27-S2` from January.
- **skip** leaves the slicer out.

A slicer that follows a fiscal period (`FY27-S1`, `FY26`) also needs your company's fiscal year, so answering current for it asks when your fiscal year starts and what it's called. There's no default: nothing in a report says which fiscal year it uses, and on any one day several fit (on 30 September 2026, `FY26` fits a January or an October start alike). Once your contract has a fiscal year, `init` offers it as the default. A calendar period (`2026 H2`, `2026-11`) asks nothing more. If a slicer isn't on today's period under the fiscal year you give, `init` says so and writes nothing: either the answer or the report is wrong.

| Your fiscal year | Start month | Named by | Last day of FY26 → first day of FY27 |
|---|---|---|---|
| Calendar year | 1 | end | 31 Dec 2026 → 1 Jan 2027 |
| October start (e.g. US federal) | 10 | end | 30 Sep 2026 → 1 Oct 2026 |
| July start (e.g. Microsoft, Australia) | 7 | end | 30 Jun 2026 → 1 Jul 2026 |
| April start (e.g. India) | 4 | end | 31 Mar 2026 → 1 Apr 2026 |
| April start, named by the year it starts (e.g. Japan) | 4 | start | 31 Mar 2027 → 1 Apr 2027 |

Preview a rollover with `--as-of` on its first day. A contract has one fiscal calendar, and a label naming both years (`2026-27`) can't follow the current period, so keep it and update it at rollover.

Type a choice or its first letter; Enter takes the suggestion. The contract is written beside the report, never inside it: Fabric deletes files inside a report folder that aren't part of the report.

Run `init` again after adding slicers: it adds rules for the new ones and leaves yours alone (`--force` replaces a rule's check, keeping anything else you added to it). `--dry-run` shows the file without writing it, and nothing is written unless the result is a contract `fab-test pbir` accepts.

Some selections can't be checked, and `init` only offers to skip them: "Select all" then untick some values, a hierarchy slicer, or two slicers on one page bound to the same column with different selections.

## 2. Check it

```bash
fab-test pbir --artifact SampleModel-DefaultState
```

The run says which contract paired with the report and splits its findings between the PBIR rules every report gets and the contract's `CONTRACT.*` rules:

```
📜 Slicer contract: fabric-artifacts\SampleModel-DefaultState.Report.odcs.yaml (12 slicer checks, 3 bookmark navigators)
📊 1 finding(s) (1 error(s), 0 warning(s)): 0 from the PBIR rules, 1 from the slicer contract
```

A report pairs with the contract whose `fabTestReport` matches its `.platform` `logicalId`, wherever the file is under `--artifact-dir`; with none, the 📜 line says `none` and names the id. In the envelope, each finding and test result carries `source`: `rules` or `contract`.

A slicer that drifted is a finding on its page:

```
CONTRACT.half-year-current  error  Standard Slicers  'Fiscal Calendar'[Half Year] opens with ['2025 H2']; the contract expects 2026 H2
```

A slicer that was deleted, or a page that was renamed, is a finding too; nothing passes by going missing. To see what a calendar-driven rule will expect on another day, pass `--as-of`:

```bash
fab-test pbir --artifact SampleModel-DefaultState --as-of 2027-01-15
```

## 3. Edit the contract by hand

The contract is plain YAML. Each rule sits on the slicer's column and names its page:

```yaml
- id: half-year-current
  type: custom
  engine: fab-test
  severity: error            # or warning
  implementation:
    page: Standard Slicers
    selected: ["{year} H{half}"]
```

The other checks are `range: {from: 2026-01-01, to: 2026-06-30}` (Between slicers and date pickers), `relative: {range: Last, duration: 20, period: Calendar Months}` and `contains: [Wolverine]` (input slicers). `selected: []` means the slicer should open with nothing ticked, and `selected: all` with "Select all" ticked. Both show every row, but they look different on open, so neither passes for the other. The fields a calendar value can use are `year`, `year_short`, `half`, `quarter`, `month`, `fiscal_year`, `fiscal_year_short`, `fiscal_semester`, `fiscal_quarter` and `fiscal_month`.

`schema` lists only the tables and columns that have rules, never the whole model, and can be left out when there are none. `pql-test contract lint <contract> <model>` validates the file as ODCS and checks that every name resolves in the model.

A fixed value containing `{` or `}` is written `{{` or `}}`, because braces mark calendar fields. A comment in the file is yours to keep: `init` won't rewrite a contract containing `#` without `--force`.

### Bookmark navigators

A bookmark navigator isn't bound to a column, so its entry sits in the contract's `customProperties`, named by page and by the bookmark's display name:

```yaml
customProperties:
  - property: fabTestBookmarkNavigators
    value:
      - id: page-1-navigator
        page: Page 1
        selected: Bookmark 2     # null: nothing preselected
```

`init` asks about each page's navigator (keep or skip) and writes these for you. A navigator that drifted is a finding:

```
CONTRACT.page-1-navigator  error  Page 1  the bookmark navigator opens with [Bookmark 1]; the contract expects Bookmark 2
```

Renaming or deleting the bookmark fails too ("the report has no bookmark by that name"), and so does removing the navigator from the page.

### How the contract maps to PBIR

The contract names things the way Power BI shows them, not the way the saved files store them. Where PBIR has a readable name, the contract keeps it:

| Contract | PBIR (enhanced report format) |
|---|---|
| `schema[].name`, `properties[].name` | the slicer's bound field: `SourceRef.Entity`, `Property` |
| `relative: {range, duration, period}` | `relativeRange`, `relativeDuration`, `relativePeriod` |
| `relative` values `Last`, `20`, `Calendar Months` | the same literals: `'Last'`, `20D`, `'Calendar Months'` |
| `contains: [Wolverine]` | the input slicer's `Contains` condition |

Where PBIR stores state as a filter expression or an internal id, the contract uses what's on screen:

| Contract | PBIR stores | Why |
|---|---|---|
| `selected: [Bad]` | `filter.Where[].Condition.In.Values` (`'Bad'`) | a selection has no PBIR name, only an `In` filter |
| `selected: all` | `isInvertedSelectionMode` `true`, with no filter or a `Not In []` | "Select all" is what you see |
| `selected: []` | no `Where` rows | |
| `range: {from, to}` | `Comparison`, `ComparisonKind` 2 (≥) and 3 (<) | `to` is **inclusive**, as Desktop shows it; PBIR stores the next day, exclusive |
| field parameter `selected: [Number of Characters]` | the hidden Fields column's value; the name is in `filterExpressionMetadata.valueMap` | the name you see |
| `page: Standard Slicers` | the page folder's id, with `displayName` in `page.json` | ids change when a page is copied |
| navigator `selected: Bookmark 2` | `selectedBookmark` = `'9c65f6aa324d70ac0e33'`, the bookmark's `name` | display name, as for pages |

The slicer's `mode` (`'Basic'`, `'Dropdown'`, `'Between'`, `'Relative'`, `'RelativeDatePicker'`) isn't in the contract: a dropdown and a list with the same selection open the same way, so they pass the same rule.

## 4. Catch the rollover on a schedule

A semester changes with no commit, so a pipeline that only runs on push never notices. Run `fab-test pbir` on a schedule as well; see [`examples/github-actions/slicer-defaults.yml`](examples/github-actions/slicer-defaults.yml) and [`examples/azure-devops/slicer-defaults.yml`](examples/azure-devops/slicer-defaults.yml).

The full reference, including the agent workflow, is [`.github/skills/fab-test/references/slicer-contracts.md`](../.github/skills/fab-test/references/slicer-contracts.md).
