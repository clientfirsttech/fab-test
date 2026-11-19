# Principles

Each principle has the question to ask, what rude and polite look like, and where the idea comes from. Skip any principle the evidence doesn't touch. Name findings by the principle's heading so reports and pain points use the same words.

## fab-test's vision, in these terms

vision.md already asks for several of these. When a finding breaks one, cite both, so the fix is argued from the project's own commitments:

- **One contract, three callers** → Good citizen in automation, Actionable for an agent, Trustworthy
- **Local first** → Instant gratification, My data is mine
- **Tell the caller how to fix it** → Errors are design failures, Forthcoming, Quiet about its own problems
- **A change that serves one caller by degrading another is not aligned** → the trade-off rule in SKILL.md

## Cooper's traits

From Alan Cooper, *The Inmates Are Running the Asylum* (1999), where he argues that software should behave like a considerate human assistant.

### Interested in me
- **Ask:** Does it remember my choices, recent items, and preferences?
- **Rude:** asks for the same path, workspace, or answer on every run; forgets a choice the moment the command exits.
- **Polite:** reuses the last answer as the default, reads a config file, appends to what exists rather than starting over.

### Deferential
- **Ask:** Does it suggest and let me decide, or override and lecture?
- **Rude:** silently rewrites my input; refuses a valid choice because it prefers another; explains at length why I'm wrong.
- **Polite:** offers a default and accepts a different answer; warns once, then does what I asked.

### Forthcoming
- **Ask:** Does it volunteer what I'll obviously need next?
- **Rude:** "Done." with no path to the result; a failure with no next step.
- **Polite:** names where the result is, the next command to run, and the flag that fixes a failure.

### Common sense
- **Ask:** Are frequent actions easy, dangerous ones separated, and obvious questions not asked?
- **Rude:** a destructive flag one letter from a common one; a question whose answer is in a file it already read.
- **Polite:** the frequent path needs no flags; destructive actions need an explicit, distinct flag.

### Anticipates needs
- **Ask:** Does it prepare likely next steps and sensible defaults?
- **Rude:** blank defaults when one answer covers most cases; downloads a tool only at the moment it's needed, mid-run.
- **Polite:** sensible defaults shown in the prompt; readiness checked up front (`doctor`) so a run doesn't fail halfway.

### Responsive
- **Ask:** Does it notice the context I'm in and adapt?
- **Rude:** colors and spinners written into a pipe; the same prompt in CI as on a laptop.
- **Polite:** detects a TTY, CI, `NO_COLOR`, terminal width, and adapts its output.

### Quiet about its own problems
- **Ask:** Does it keep stack traces and internals out of my way?
- **Rude:** a Python traceback for a missing file; internal names (`_run_analyzer`, `KeyError: 'x'`) in a message meant for a person.
- **Polite:** one line in the caller's terms; the traceback only at `-v` or in a log, and the message says where.

### Keeps me informed
- **Ask:** Can I see status and what just happened at a glance?
- **Rude:** a long silent run; a summary that hides which artifact failed.
- **Polite:** progress within a second; a summary that names what passed, what failed, and where the detail is.

### Perceptive
- **Ask:** Does it notice patterns in how I work and make them easier?
- **Rude:** the same three flags typed on every run with no way to save them.
- **Polite:** a config key for every repeated flag, and `config --show` to see where a value came from.

### Self-confident
- **Ask:** Does it act and offer undo, instead of "Are you sure?" every time?
- **Rude:** confirms routine, recoverable actions until the caller answers "y" without reading.
- **Polite:** acts, keeps what it replaced, and says how to restore it; confirms only what can't be undone.

### Stays focused
- **Ask:** Does it avoid tangents, nags, and wizards nobody asked for?
- **Rude:** update nags, tips, and banners on every run; a setup wizard before the command I typed runs.
- **Polite:** does the one thing asked; anything extra is opt-in or printed once.

### Fudgable
- **Ask:** Can I bend the process the way a sensible clerk would let me?
- **Rude:** all-or-nothing input: one bad entry rejects the whole file; no way to skip a question.
- **Polite:** a `skip` answer, a partial run that keeps the good results, an override flag for an edge case.

### Instant gratification
- **Ask:** Can I get something useful done right away?
- **Rude:** account, workspace, and config needed before the first useful result.
- **Polite:** a first run that works on what's on disk, with no setup, and says what more setup would unlock.

### Trustworthy
- **Ask:** Is it consistent, and does it never lose my work?
- **Rude:** overwrites a hand-edited file; the same flag means different things on different commands; exit codes that lie.
- **Polite:** never overwrites without `--force`; one meaning per flag and exit code everywhere.

## Expanded principles

### Minimal excise
- **Ask:** How much of the work is tax rather than progress?
- **Rude:** steps that only serve the software: re-entering, confirming, navigating, waiting, dismissing.
- **Polite:** the most frequent task is mostly goal work. Count it; see `countExcise` in SKILL.md.
- **Source:** Cooper, Reimann, Cronin and Noessel, *About Face* (4th ed., 2014), on excise.

### Designed for intermediates
- **Ask:** Is the main path built for people who know the basics, not only for first-timers or experts?
- **Rude:** `--help` that is a tutorial, or a wall of every flag with the common one buried.
- **Polite:** the common path first with an example, beginners pointed to a walkthrough, experts given shortcuts.
- **Source:** *About Face*, on perpetual intermediates.

### Undo over confirmation
- **Ask:** Are confirmations rare enough that people still read them?
- **Rude:** a confirmation on every run trains the caller to say yes, so it protects nothing when it matters.
- **Polite:** reversible by default (backups, `--dry-run`, write-new-then-replace); confirmation kept for the irreversible.
- **Source:** Jef Raskin, *The Humane Interface* (2000), on habituation.

### Errors are design failures
- **Ask:** Does it prevent slips and mistakes instead of scolding afterward?
- **Rude:** accepts input it can't use, then fails late; an error that names the symptom, not the cause or the fix.
- **Polite:** validates early, suggests the closest valid value, and names the flag, env var, or config key that fixes it.
- **Source:** Don Norman, *The Design of Everyday Things* (revised 2013), on slips, mistakes, and feedback.

### Few modes
- **Ask:** Can the same action mean different things depending on hidden state?
- **Rude:** a default that silently changes from local to service because an env var is set somewhere.
- **Polite:** state that changes meaning is visible: printed once at the start of the run, and recorded in the result.
- **Source:** Raskin, *The Humane Interface*, on modes.

### Respects attention
- **Ask:** Does it inform in the periphery and interrupt only for what matters now?
- **Rude:** every warning at the same volume as an error; the same advice printed once per artifact.
- **Polite:** errors stand out; repeated advice is printed once per run; detail is one flag away.
- **Source:** Mark Weiser and John Seely Brown, "Designing Calm Technology" (1995).

### Fast enough to keep flow
- **Ask:** Does it respond quickly enough that I don't lose my train of thought?
- **Rude:** seconds of silent startup; a slow step with no sign of life.
- **Polite:** feedback within about 0.1 s feels instant, within 1 s keeps flow; past 10 s, show progress and what is running.
- **Source:** Jakob Nielsen, *Usability Engineering* (1993), on response-time limits.

### My data is mine
- **Ask:** Can I get my data out, work offline where sensible, and control what's collected?
- **Rude:** telemetry on by default with no notice; results only viewable in a service.
- **Polite:** plain files on disk in an open format; telemetry opt-in and inspectable before sending (`--dry-run`).
- **Source:** Kleppmann, Wiggins, van Hardenberg and McGranaghan, "Local-first software" (Ink & Switch, 2019).

### Honest
- **Ask:** Are there dark patterns: tricks, hidden costs, guilt, forced continuity?
- **Rude:** a "pass" that hides skipped checks; a warning count that omits suppressed rules; a default that opts the caller into something.
- **Polite:** skipped and suppressed work is reported as such; a pass means the checks ran.
- **Source:** Harry Brignull, who named "dark patterns" in 2010; *Deceptive Patterns* (2023).

### Usable by everyone
- **Ask:** Does it work with assistive tech, without color alone, at different sizes and abilities?
- **Rude:** pass and fail told apart only by red and green; tables that break at 80 columns; an HTML report with no headings or alt text.
- **Polite:** a word or symbol beside every color; `NO_COLOR` honored; output readable at 80 columns and by a screen reader.
- **Source:** W3C, *Web Content Accessibility Guidelines* (WCAG) 2.2 (2023).

### Good citizen in automation
- **Ask:** Does it behave predictably for scripts, CI, and other programs?
- **Rude:** prompts in a non-interactive run; data and chatter mixed on stdout; exit 0 on failure; output that changes shape between versions.
- **Polite:** never prompts without a TTY and has a flag for every answer; stdout is the data, stderr the narration; exit codes are documented and stable; silent when there's nothing to say.
- **Source:** Eric S. Raymond, *The Art of Unix Programming* (2003), on the Rules of Silence and Repair; Prasad, Firshman, Tashian and Parish, *Command Line Interface Guidelines* (clig.dev, 2020).

### Considerate agency
- **Ask:** When it acts for me, does it stay in scope, show its plan, and ask before irreversible steps?
- **Rude:** does more than asked; acts first and explains later; reports success it didn't verify.
- **Polite:** states the plan, asks once before the irreversible, reports what it did and did not do.
- **Source:** Amershi et al., "Guidelines for Human-AI Interaction" (CHI 2019). See references/agents.md.

### Actionable for an agent
- **Ask:** Can an agent calling this tell what happened and what to do next without guessing?
- **Rude:** prose-only failures; one exit code for every kind of failure; remediation that needs a human to interpret.
- **Polite:** parseable output, exit codes that separate "your artifact failed" from "the tool is missing" from "bad arguments", and a fix the agent can run as written.
- **Source:** fab-test's vision.md (the AI agent caller and "Tell the caller how to fix it"). See references/agents.md.
