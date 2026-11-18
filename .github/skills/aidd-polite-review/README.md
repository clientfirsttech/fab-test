# aidd-polite-review

Reviews a command, an app, or an agent for how considerately it treats the people and programs that use it. It asks one question at every step: is this software behaving the way a thoughtful, competent human helper would?

## Why

Code review checks that code is correct, safe, and tidy. It doesn't ask whether an error message names the fix, whether an `init` question could have been inferred, or whether a "pass" hides skipped checks. Those problems pass review and are found only when someone trips over them. This skill turns Alan Cooper's polite-software traits (*The Inmates Are Running the Asylum*), the excise count from *About Face*, and later work on attention, honesty, automation, and AI agents into a review you can repeat.

In fab-test it reviews for all three of the vision's callers at once: the person at a terminal, the pipeline, and the AI agent. A fix that helps one by hurting another is reported as a trade-off, not recommended.

## Commands

`/polite-review [target]` reviews a command, surface, transcript, or diff and writes a report: who the surface is for, how many steps on its main path are excise, findings with the exact output behind each one, and quick wins. It is read-only; running the target for evidence happens against a scratch copy.

```
/polite-review fab-test pbir contract init
/polite-review the diff on this branch
```

`/polite-discover [journey]` walks a user journey from `plan/story-map/` and turns what is rude about each step into ranked pain points and user stories, in the shapes `aidd-product-manager` uses. Saving them is that skill's `/save`.

```
/polite-discover pbir-slicer-default-state
```

## When it runs

The AIDD router loads it with `discover`, and with `review` when a diff changes what a caller reads or answers: messages, `--help`, prompts, `init` questions, `explain` or `doctor` output, the HTML report, or the fab-test skill.
