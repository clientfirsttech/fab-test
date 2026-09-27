# aidd-analyzer-contract

The minimum requirements a fab-test analyzer must meet to behave like every other
check: the same envelope, exit codes, HTML report, telemetry, CI annotations, and
reach through `all`, `local`, `list`, `explain`, and `doctor`.

## Why

The contract is spread across about twenty registration points, and most of them
are not tested against each other. A new analyzer can pass its own tests and
still be missing from `fab-test local`, produce no `report.html`, or report the
wrong telemetry type. This skill turns "make it behave like the others" into a
list you can plan against.

## Commands

`/analyzer-contract plan rdl` lists every touch point the `rdl` analyzer needs
and drafts the epic requirements for them.

`/analyzer-contract review a11y` checks an existing analyzer against the
contract and reports each gap.

## Files

`SKILL.md` holds the contract and process. `references/checklist.md` lists every
touch point and the test that guards it, if any. `references/known-gaps.md`
lists existing analyzers that currently deviate.
