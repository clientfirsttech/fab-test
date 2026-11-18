# Agents

Two directions, with different questions: an agent that acts for a person, and software whose caller is an agent. fab-test is mostly the second: an AI agent is one of its three callers. The first covers the Fabric Data Agents fab-test tests and the coding agents that work in this repo. Review a surface in both directions when it's both.

The first direction draws on Amershi et al., "Guidelines for Human-AI Interaction" (CHI 2019), and Cooper's considerate-assistant idea; the second on fab-test's vision.md.

## An agent acting for a person

The polite agent is a good assistant: it does what was asked, says what it's about to do when it matters, and never leaves the person to discover a surprise.

- **Stays in scope.** Does what was asked, not adjacent work it thinks is helpful; proposes extras rather than doing them.
- **Shows its plan before acting** when the work is long, touches many files, or is hard to undo.
- **Asks once before the irreversible:** deleting, publishing, sending, pushing, spending. Routine, reversible steps go ahead without asking.
- **Asks only what it can't find out.** It checks the code, config, or docs first; a question names what it found and why that wasn't enough.
- **Reports faithfully:** what it did, what it skipped, what failed, with the output. It never claims a success it didn't verify.
- **Stops when blocked** rather than retrying the same failing step, and says what it tried.
- **Remembers stated preferences** within the session and, where it can, across sessions; it doesn't make the person repeat a correction.
- **Keeps a small footprint:** no stray files, no settings changed on the side, temporary work cleaned up.
- **Speaks in the person's terms,** not its internal process: the outcome first, then the detail.

Probes: give it a task with an obvious adjacent fix (does it stay in scope?), one with an irreversible step (does it ask, once?), one that will fail (does it stop and report honestly?), and a correction early in the session (does it hold later?).

## Software an agent calls

An agent can't squint at a screen, ask a colleague, or guess what a vague message meant. Everything it needs has to be in the output. Each gap costs a retry, wasted tokens, or a wrong edit.

- **Capability is discoverable.** `--help`, `list`, `explain`, and the agent's skill name every command, flag, exit code, and output shape, and they match the installed version.
- **Output is parseable and stable.** One JSON document on stdout with `--format json`; field names don't drift between versions; narration stays on stderr.
- **Exit codes separate the cases an agent acts on differently:** findings in the artifact (fix the artifact), a missing tool or credential (fix the environment), bad arguments (fix the call), an unsupported platform (stop).
- **A finding carries what an agent needs to fix it:** the rule id, the file and element, the expected and actual values, and the remediation.
- **Remediation can be acted on as written:** an exact flag, env var, config key, or command, not "check your configuration".
- **Nothing makes it guess or retry blind.** Errors say whether a retry could help; a timeout says it was a timeout.
- **Cheap to ask first.** A small first answer (`-q`), with more detail on request, so a passing run costs few tokens.
- **No prompt without a flag.** An agent usually has no TTY; an unanswered prompt is a hang.
- **The skill is the agent's `--help`.** When it's wrong, the agent is wrong: a stale flag or exit code in the skill is a High finding.

Probes: drive it as an agent would. Read only the skill, then make the call it suggests; parse the JSON; provoke each exit code; run a remediation exactly as printed; check that `-q` alone is enough to decide what to do next.
