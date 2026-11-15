# Checking what a report's slicers open with

A customer agrees what a report shows when it opens: which alignment, which eye colours, which semester. Every edit risks saving a working selection over that agreement, and a default that follows the calendar goes stale at rollover with no commit to notice it. A **slicer contract** writes the agreement down once; `fab-test pbir` checks it on every run.

This guide uses the test bed in `fabric-artifacts/`: `SampleModel-DefaultState.Report` and its contract, `SampleModel-DefaultState.Report.odcs.yaml`.

## 1. Build the contract

From the repository root:

```bash
fab-test pbir contract init fabric-artifacts/SampleModel-DefaultState.Report
```

`init` finds every slicer, shows what it opens with today, and asks how to check it:

```
Standard Slicers: 'AlignmentDim'[Alignment] opens with Bad. Keep checking that, follow the calendar, or skip it?
  [keep/calendar/skip] default keep:
Standard Slicers: 'Fiscal Calendar'[Fiscal Semester] opens with FY27-S1. ... (format FY{fiscal_year_short}-S{fiscal_semester})
  [keep/calendar/skip] default calendar:
```

- **keep** checks today's selection exactly.
- **calendar** checks a value that follows the calendar. When the current value matches a known pattern for today, `init` suggests it: `FY27-S1` becomes `FY{fiscal_year_short}-S{fiscal_semester}`, which will expect `FY27-S2` from January.
- **skip** leaves the slicer out.

Calendar answers also ask when your fiscal year starts and whether it is named by the year it starts or ends in. `init` suggests the answer that reproduces today's values; several months can, so check it.

Enter takes the suggestion. The contract is written beside the report, never inside it: Fabric deletes files inside a report folder that aren't part of the report.

Run `init` again after adding slicers: it adds rules for the new ones and leaves yours alone (`--force` replaces a rule's check, keeping anything else you added to it). `--dry-run` shows the file without writing it, and nothing is written unless the result is a contract `fab-test pbir` accepts.

Some selections can't be checked, and `init` only offers to skip them: "Select all" then untick some values, a hierarchy slicer, or two slicers on one page bound to the same column with different selections.

## 2. Check it

```bash
fab-test pbir --artifact SampleModel-DefaultState
```

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

The other checks are `range: {from: 2026-01-01, to: 2026-06-30}` (Between slicers and date pickers), `relative: {range: Last, duration: 20, period: Calendar Months}` and `contains: [Wolverine]` (input slicers). `selected: []` means the slicer should open with nothing selected. The fields a calendar value can use are `year`, `year_short`, `half`, `quarter`, `month`, `fiscal_year`, `fiscal_year_short`, `fiscal_semester`, `fiscal_quarter` and `fiscal_month`.

A fixed value containing `{` or `}` is written `{{` or `}}`, because braces mark calendar fields. A comment in the file is yours to keep: `init` won't rewrite a contract containing `#` without `--force`.

## 4. Catch the rollover on a schedule

A semester changes with no commit, so a pipeline that only runs on push never notices. Run `fab-test pbir` on a schedule as well; see [`examples/github-actions/slicer-defaults.yml`](examples/github-actions/slicer-defaults.yml) and [`examples/azure-devops/slicer-defaults.yml`](examples/azure-devops/slicer-defaults.yml).

The full reference, including the agent workflow, is [`.github/skills/fab-test/references/slicer-contracts.md`](../.github/skills/fab-test/references/slicer-contracts.md).
