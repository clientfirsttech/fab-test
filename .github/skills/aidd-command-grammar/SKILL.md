---
name: aidd-command-grammar
description: The shape every fab-test command that authors or checks a test file follows - words, flags, file placement, exit codes, output modes. Use when planning, adding, reviewing, or changing a subcommand, verb, noun, or flag a person types.
---

# Command Grammar

fab-test's value is one contract (vision.md). `aidd-analyzer-contract` keeps the
commands that *run* checks to it; this skill keeps the commands that *author*
the files those checks read — a contract, a test suite — to one shape, so a
person, pipeline, or agent that learned one flow already knows the next.

This skill decides a command's shape: its words, flags, files, exit codes and
output modes. `aidd-polite-review` judges how it talks: wording, questions,
interruptions. Neither restates the other.

import references/checklist.md
import references/known-gaps.md

## Grammar

```
fab-test <analyzer> [TARGET]                 run: checks, never writes source files
fab-test <analyzer> <noun> <verb> [TARGET]   author: creates or checks a file a person keeps
fab-test <init|config|doctor|list|explain|skill|help|auth> ...   self: about fab-test itself
```

Verb = init | lint            // closed; see Constraints
Noun = contract | tests       // the file a person authors; one format per noun
ExitCode {
  0    done, or lint found nothing
  1    lint findings: any problem in the file lint checks, unreadable YAML included
  2    nothing to do or check: usage error, no item or paired file, a refused flag, init's unreadable
       existing file, or an answer missing off a terminal
  127  a wrapped tool is missing
  130  interrupted
}

## Constraints

Constraints {
  // Words
  A verb is init or lint. init creates the authored file from the artifact or appends to it; lint checks it against the artifact without running anything, and needs no service
  (a flow needs a third verb) => add it to this skill when a second analyzer needs it too, never in one command alone
  A noun names one file format everywhere: contract is always ODCS; a promptfoo suite is tests
  The noun word is reserved in the analyzer's TARGET position; an item with that name is passed as ./contract
  Never put a verb straight after the analyzer (`fab-test data-agent init`): it collides with TARGET and names no file
  Never add a top-level verb about an artifact's files (`fab-test lint`); top-level verbs are about fab-test, and `fab-test init` stays the config scaffold
  Register the noun as an argparse subparser of its analyzer, so `--help`, `help`, `list` and `explain` know it

  // Inputs: what the run takes, the verbs take the same way
  TARGET is the item (`Sales.Report`), never the authored file; fab-test finds the paired file
  TARGET, --artifact, --artifact-dir, --as-of and --<noun> FILE have the run's name, metavar, help and default on every verb
  Every default resolves flag → env → fab-test.yml or pyproject.toml → packaged, as the run's do; never a literal default that skips the config
  --<noun> FILE overrides the pairing, on every verb and on the run

  // Files
  An authored file lives beside the item folder as <Item>.<Type>.<suffix>, because Fabric's Commit to Git deletes non-definition files inside it
  (the tests are part of the item's own definition, like T-TEST procedures) => they stay inside the folder
  Pair the file with its item by a stable identity recorded in the file (pbir: the report's logicalId), not by name alone
  init appends new entries and keeps existing ids; changing or replacing one needs --force

  // init without a person
  --questions prints every question with its suggested answer and needs_human, then stops; with --format json, one document
  --answers FILE applies answers by question id; an unanswered question takes its suggestion unless needs_human
  (no TTY, CI, or --format json, and an answer is missing) => exit 2 before asking anything, naming --questions and --answers; never prompt, never guess
  --dry-run means the same on every verb: show what would be written or run, write nothing

  // Output: the vision's modes, with the run's meanings
  -q prints one result line per item (`✓ Sales.Report.odcs.yaml written`); the default adds what a person acts on, including the next step; -v adds per-item detail; --format json keeps stdout one document
  Verbosity resolves -q/-v → ANALYZER_VERBOSITY → fab-test.yml; --format resolves like any input default
  Name the next step: init → `<noun> lint` → the run → the CI snippet; in text as a line, in JSON as `next`
  Refuse a run-only flag (--report, --open-report, --telemetry, and --output-dir unless the verb writes under fab-test-results/) with exit 2 naming the command that takes it, never argparse's "unrecognized arguments"
  (lint wraps an upstream linter) => run it with fab-test's own interpreter or pin, add fab-test's own checks (the file reads as the run reads it, and pairs with an item), and map the result to ExitCode; the caller never needs the upstream command
  lint writes nothing and no envelope: results are the run's job. With no TARGET it checks every authored file under --artifact-dir, as the run checks every item, and its JSON is one shape either way: {ok, <files>: [...], next}
  Credentials never reach stdout, an authored file, or JSON output

  // Discoverable and documented, for all three callers
  List each verb in the analyzer's --help, `fab-test help`, and the fab-test skill's flags.md (both copies)
  Give each flow one flag table — a row per flag, a column each for init, lint and the run — in the fab-test skill reference and the guide
  Give each flow a walkthrough: save the artifact, init, lint, run, break it, CI, opening with an init-to-CI flowchart (docs/SLICER-CONTRACTS-WALKTHROUGH.md is the model)
  Run every verb under -q, the default, -v, --format json, --dry-run, and a refused run-only flag, through the installed console script, before review passes
}

## Process

planCommand(analyzer, noun) {
  1. Read references/known-gaps.md; never copy a listed deviation
  2. Choose the noun: reuse one only if the file format is the same, else name the new file
  3. Walk references/checklist.md; write one Given/should line per row that applies into the epic
  4. (the run changes too) => also load aidd-analyzer-contract; (wording, prompts or questions) => aidd-polite-review
  5. TDD it (aidd-tdd), then verify every mode through the installed console script
}

reviewCommand(diff) {
  For each command, verb, noun or flag the diff adds or changes:
    check every Constraint |> report each unmet one with its checklist row and the fix
  (the deviation is already in known-gaps.md) => note it; it is a finding only if the diff extends it or copies it to a new command
  (the diff fixes a known gap) => require its entry removed from known-gaps.md
}

Commands {
  /command-grammar plan [analyzer noun] - the checklist rows and the epic's Given/should lines for a new or changed authoring command
  /command-grammar review [diff | command] - check a command against the grammar; review-only
}
