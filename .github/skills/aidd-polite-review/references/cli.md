# Command-line surfaces

For commands, flags, prompts, `--help`, stdout and stderr, exit codes, and terminal workflows. The general idea comes from the *Command Line Interface Guidelines* (clig.dev); fab-test's own contract is in `.github/skills/fab-test/SKILL.md` (Agent Contract) and vision.md, and where it already says what polite looks like, a probe checks against it.

## Run safely

Constraints {
  Run probes from a scratch copy of the inputs, with --output-dir in scratch; never against the caller's real config, contracts, or results
  Prefer --dry-run, --plan-only, and read-only commands; when a probe must write, write to scratch
  Record each probe's exact command, exit code, and stdout and stderr separately (2>stderr.txt)
  Before a long run, check no earlier run is still going
}

## Probes

Run the ones that apply to the surface under review. Each line is the probe, then what polite looks like.

- **Bare command, no arguments** → does the common thing or says in a few lines what it needs; no wall of usage; exit 2 only when it truly can't proceed.
- **`--help`** → the common path first, with an example; fits 80 columns; defaults and env vars shown beside each flag; no internal names.
- **A typo in a flag or subcommand** → exit 2, the closest valid name suggested, nothing run.
- **A missing prerequisite** (tool not installed, no credentials, no artifacts found) → a fast, specific failure naming the flag, env var, or config key that fixes it (fab-test: exit 127, or 126 for an unsupported platform); `doctor` reports the same thing before a run.
- **A non-interactive run** (`< /dev/null`, `CI=true`, piped output) → never waits on a prompt; each question has a flag; fails fast naming that flag when an answer is missing.
- **`--format json`** → exactly one JSON document on stdout, with progress, warnings, and subprocess output on stderr; `| jq .` works.
- **`-q`** → on a pass, one line per artifact and nothing else; on a failure, the reason is still shown.
- **`-v`** → adds detail without changing results or files on disk.
- **A failing run** → which artifact, which rule, where, and the fix, in the caller's terms; the traceback only at `-v`; the result path named once.
- **A long run** → a sign of life within a second; past ten seconds, progress and what is running.
- **Ctrl-C mid-run** → stops promptly, no traceback, no half-written result left looking complete, and says what was kept.
- **A rerun after success** → same result, nothing re-asked that was answered and saved; files it wrote earlier are appended to or left alone, not clobbered.
- **An overwriting or destructive action** → refused without `--force` (and the message names it), or the old version kept and its path printed.
- **`NO_COLOR=1`, a narrow terminal, a pipe** → no color codes in a pipe; meaning never carried by color alone; tables wrap or truncate cleanly.
- **The exit code against the docs** → the same meaning as fab-test's skill and `explain` say, for every path probed.

## Interactive prompts

A question is excise unless only the caller can answer it. Ask of each prompt:

- **Could it be inferred?** From a file already read, the folder name, the artifact, or the last run. Then don't ask; show what was inferred.
- **Could it be defaulted?** Show the default in the prompt and accept Enter.
- **Could it be remembered?** Save the answer where the next run reads it, and say where.
- **Is it in the caller's terms?** Display names, not internal ids; dates in words, not serials; choices named by what they do.
- **Can the caller skip it?** A `skip` answer, or a way to leave an item out without abandoning the rest.
- **Does a non-interactive run have a flag for it?** If not, the command can't serve a pipeline.

Asking can be the polite choice: when a wrong guess would be silent and costly (a company's fiscal year, which item a contract should pin), one clear question beats a confident wrong answer. Then the question should say why it's asked and what the answer changes.

## Output

- **Each fact once.** A path, count, or remedy repeated in banner, body, and summary is noise; fab-test's analyzer contract asks for each fact once.
- **stdout is data, stderr is narration**, in every mode, so a pipe never breaks.
- **Silence on success is fine** at `-q`; at default verbosity, a one-line result and where the detail is.
- **Remediation printed once per run**, not once per artifact, when it is the same.
- **Severity is visible without color**: `error`, `warning`, counts by level.

## Excise to look for

Flags that must be passed on every run; paths retyped that a config or the working directory could supply; a confirmation before a recoverable action; a setup step before the first useful result; reading a banner to find the one line that matters; rerunning with `-v` to learn which artifact failed.
