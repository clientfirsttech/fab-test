<!--
Source text for the Polite Software Review epic (tasks/polite-software-review-epic.md),
pasted by the user 2026-11-17. Kept verbatim as the starting draft; the skill built from it
lives at .github/skills/aidd-polite-review/. Delete this file when that epic is archived.
The four references/*.md files it names were not provided and do not exist yet.
-->

---
name: polite-software-review
description: Review an application, CLI, website, API, or AI agent for how considerately it treats the person using it. Built on Alan Cooper's "polite software" principles from The Inmates Are Running the Asylum, expanded with his later About Face work (excise, perpetual intermediates, considerate and smart products) and related thinking from Raskin, Norman, Nielsen, calm technology, dark-pattern research, local-first software, and modern CLI guidelines. Use this skill whenever the user asks to review, critique, audit, or give UX feedback on an app, a command-line tool, a terminal workflow, --help output, error messages, prompts, notifications, onboarding, settings, dialogs, or an AI assistant's or agent's behavior, even if they never mention Cooper or "politeness". Also use it when the user pastes CLI output, screenshots, transcripts, or source code for a user-facing interface and asks "is this good?", "how could this be friendlier?", or "what's annoying about this?".
---

# Polite Software Review

Alan Cooper argued that most software is rude: it is designed around the computer's and the programmer's convenience rather than the person's goals. It asks needless questions, forgets what you told it, blames you for its own problems, and interrupts you with its internal troubles. Polite software behaves like a considerate, competent human assistant.

This skill turns that idea into a repeatable review. The core lens is: **at each moment of interaction, is this software behaving the way a thoughtful human helper would?**

Cooper's original list of traits is the foundation. This skill expands it in two directions:

1. **Deeper**, using ideas Cooper and his co-authors developed later in *About Face* (excise, perpetual intermediates, considerate and smart products, goal-directed design), and ideas from others that explain *why* rude behavior hurts (Raskin on habituation and modes, Norman on slips and feedback).
2. **Wider**, covering territory that barely existed in 1999 but follows directly from "behave like a considerate helper": attention and notifications, speed, data ownership and privacy, honesty and dark patterns, accessibility, scripting and automation, and AI agents that act on the user's behalf.

## Which reference files to read

After reading this file, read the ones that apply:

- `references/principles.md`: the expanded principles with their sources and what to look for. **Always read this.**
- `references/cli.md`: command-line tools, scripts, TUIs, developer tooling.
- `references/gui.md`: desktop, mobile, and web apps.
- `references/agents.md`: AI assistants, chatbots, copilots, and agents that take actions.

A product that spans several (a CLI with an AI mode, a web app with an agent) gets all the relevant files.

## Workflow

### 1. Establish who the user is and what they are trying to do

Politeness is relative to a person and a goal. Before judging anything, write down (and ask only if you can't infer it):

- **Primary user**: who actually uses this (a developer in a hurry, an ops engineer at 3am, a first-time customer, a data analyst). Cooper's point is that designing for everyone pleases no one, so pick one and mention others only where their needs clearly diverge.
- **Their goals**: what they want, in their terms, not the software's ("deploy my change safely", not "invoke the deploy subcommand"). Distinguish goals (the end state) from tasks (the steps the software currently demands). Good design keeps the goals and questions the tasks.
- **Experience level over time**: *About Face* observes that most users are neither beginners nor experts for long. They become "perpetual intermediates" who know the basics and stay there. Judge mostly for them: beginners need a quick path to competence, experts need shortcuts, but intermediates are who you design the main path for.
- **Frequency and stakes**: a command typed fifty times a day, or a rare action with serious consequences? Frequency drives how much friction is acceptable; stakes drive how much protection is needed.

### 2. Gather real evidence

Base findings on what the software actually does.

- If you can run it, run it. Follow the probes in the relevant reference file.
- If the user provided screenshots, output, transcripts, code, or docs, walk through them as the primary user would.
- If you only have a description, say so in the report and keep findings provisional.

Show the exact message, prompt, or screen behind each finding so the reader can check it.

### 3. Count the excise on the main path

*About Face* calls "excise" any work the software demands that doesn't move the user toward their goal: navigating, configuring, confirming, re-entering, waiting, dismissing. It's like a tax.

For the primary user's most frequent task, list every step and mark each one as **goal work** (the thing they came to do) or **excise**. Report the ratio. This single exercise usually surfaces the highest-value findings, because excise on a frequent path is paid over and over.

### 4. Walk the interaction against the principles

Go through Cooper's original traits and the expanded principles in `references/principles.md`. Not every one applies; skip those with no evidence rather than padding. Note what the software does well as well as where it's rude.

Cooper's original traits, as a quick checklist:

| Trait | The question to ask |
|---|---|
| **Interested in me** | Does it remember my choices, recent items, and preferences? |
| **Deferential** | Does it suggest and let me decide, or override and lecture? |
| **Forthcoming** | Does it volunteer what I'll obviously need next? |
| **Common sense** | Are frequent actions easy, dangerous ones separated, obvious questions not asked? |
| **Anticipates needs** | Does it prepare likely next steps and sensible defaults, and use idle time? |
| **Responsive** | Does it notice how I work and the context I'm in, and adapt? |
| **Quiet about its own problems** | Does it keep stack traces and internals out of my way? |
| **Keeps me informed** | Can I see status and what just happened at a glance? |
| **Perceptive** | Does it notice patterns in my behavior and make them easier? |
| **Self-confident** | Does it act and offer undo, instead of "Are you sure?" every time? |
| **Stays focused** | Does it avoid tangents, nags, and unrequested wizards? |
| **Fudgable** | Can I bend the process the way a sensible human clerk would let me? |
| **Instant gratification** | Can I get something useful done right away? |
| **Trustworthy** | Is it consistent, and does it never lose my work? |

The expanded principles (detailed in `references/principles.md`):

| Principle | The question to ask |
|---|---|
| **Minimal excise** | How much of the work is tax rather than progress? |
| **Designed for intermediates** | Is the main path built for people who know the basics, not only for first-timers or experts? |
| **Undo over confirmation** | Are confirmations rare enough that people still read them? |
| **Errors are design failures** | Does it prevent slips and mistakes instead of scolding afterward? |
| **Few modes** | Can the same action mean different things depending on hidden state? |
| **Respects attention** | Does it inform in the periphery and only interrupt for what matters now? |
| **Fast enough to keep flow** | Does it respond quickly enough that I don't lose my train of thought? |
| **My data is mine** | Can I get my data out, work offline where sensible, and control what's collected? |
| **Honest** | Any dark patterns: tricks, hidden costs, guilt, forced continuity? |
| **Usable by everyone** | Does it work with assistive tech, without color alone, at different sizes and abilities? |
| **Good citizen in automation** | Does it behave predictably for scripts, CI, and other programs? |
| **Considerate agency** | When it acts for me, does it stay in scope, show its plan, and ask before irreversible steps? |

### 5. Prioritize

- **High**: costs real time, causes data loss or fear, blocks the goal, deceives the user, excludes some users entirely, or happens on the most frequent path.
- **Medium**: noticeable friction or confusion on a common path.
- **Low**: polish, or friction only on rare paths.

Frequency matters most for friction; stakes matter most for trust. A mildly rude message on a constant command outranks an awful one on a rare command, but any finding that can destroy data or deceive the user is High regardless of frequency.

### 6. Recommend concrete fixes

Every finding gets a specific, implementable fix, ideally with before/after text, flag names, or behavior. "Improve error messages" is not a fix; "Replace `Error: ENOENT` with `Can't find config.yaml in ./. Run 'tool init' to create one, or pass --config PATH`" is.

When politeness conflicts with another goal (security, legal requirements, script stability), name the tension and propose the most considerate option within the constraint rather than dropping the finding. For example, a security prompt can't be removed, but it can be rare, specific, and remembered.

## Report format

Keep it proportionate: a small tool might have five findings, a large app twenty. Don't invent issues to fill sections.

```markdown
# Politeness review: [product name]

**Primary user:** [who] — **Main goals:** [1–3 goals in their words]
**Evidence used:** [ran it / screenshots / transcript / code / description only]

## Summary
[2–4 sentences: the software's overall character as a helper, the biggest problems, and what it already does well.]

## Excise on the main path
[The most frequent task as numbered steps, each marked goal work or excise, then "X of Y steps are excise."]

## Scorecard
| Area | Rating | Note |
|---|---|---|
| [trait or principle] | Polite / Mixed / Rude | [one line] |
[Only areas with evidence.]

## Findings
### [High] [Short title]
- **Principle:** [trait or principle, e.g., "Undo over confirmation"]
- **What happens:** [exact behavior, with the message or output shown]
- **Why it's rude:** [the cost to the user, in terms of their goal]
- **Fix:** [concrete change, with before/after where useful]

[...repeat, ordered High → Medium → Low]

## What it already does well
[Genuinely polite behaviors worth keeping, so fixes don't regress them.]

## Quick wins
[The 3–5 changes with the best payoff for the least effort.]
```

## Tone of the review

Be direct and specific, but critique the design, not the people who built it. Cooper's argument is that rude software comes from process and incentives (building around the code rather than the user's goals), so frame fixes as design changes the team can make. Attribute principles to their sources when it helps the reader look further, but don't lecture: the findings and fixes are the point.
