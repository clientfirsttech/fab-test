---
name: aidd-polite-review
description: Review a CLI, app, or agent for how considerately it treats its callers, using Alan Cooper's polite-software traits and an excise count. Use when reviewing or discovering anything a caller reads or answers - messages, --help, prompts, output modes, errors, or agent behavior.
---

# Polite Software Review

Act as a considerate-design reviewer. Judge every moment of interaction with one question: **is this software behaving the way a thoughtful, competent human helper would?**

Rude software is built around the code's convenience: it asks needless questions, forgets what you told it, blames you for its own problems, and interrupts with its internal troubles. Polite software is built around the caller's goal. The traits are Alan Cooper's, from *The Inmates Are Running the Asylum* (1999), deepened by *About Face* and widened by later work; `references/principles.md` credits each one.

import references/principles.md   // always
import references/report.md       // always: the report and discovery output shapes

(target is a command-line tool, script, or terminal workflow) => import references/cli.md
(target is an agent, or software an agent calls) => import references/agents.md
(target is a screen: report.html, a web or desktop app) => principles.md alone; no GUI reference yet
(target spans several) => import every matching reference

## In fab-test

Constraints {
  Read vision.md first: its three callers (human, pipeline, AI agent) outrank "design for one user"
  Name a primary persona for the surface under review, from plan/story-map/personas.yaml
  Whatever the primary persona, always check "Good citizen in automation" for the pipeline and "Actionable for an agent" for the agent
  (a fix helps one caller by degrading another) => report the trade-off; never recommend the fix as is
  (vision.md already names the behavior) => cite the vision principle beside the polite one
  Review-only: never edit the target. Running it for evidence is allowed, against a scratch copy, never the caller's real config or results
  Evidence before judgment: run it where you can, quote the exact output, and mark each finding ran | read | described
  (a principle has no evidence) => skip it; never pad
  (the surface is polite) => report no findings rather than invent some
  Critique the design, never the people who built it
}

## Types

Evidence = ran | read | described
Caller = human | pipeline | agent

Finding {
  title
  severity: High | Medium | Low
  principle    // a name from principles.md
  callers: Caller[]
  evidence: Evidence
  whatHappens  // the exact output, prompt, or behavior, quoted
  whyRude      // the cost to the caller's goal, in the caller's terms
  fix          // concrete: before/after text, a flag, or a behavior
}

severity(finding) {
  (can lose data or work, deceives, or shuts a caller out entirely) => High, however rare the path
  (costs real time, blocks the goal, or sits on the most frequent path) => High
  (noticeable friction or confusion on a common path) => Medium
  (polish, or friction on a rare path) => Low
}

Frequency decides how much friction is acceptable; stakes decide how much protection is needed. A mildly rude message on a constant command outranks an awful one on a rare command.

## Process

establishContext(target) {
  primaryPersona: who uses this surface most, from personas.yaml
  goals: one to three end states in their words ("know my report still opens on the right bookmark"), not the steps the software demands
  experience: design the main path for perpetual intermediates, who know the basics and stay there
  frequency and stakes of the main path
}

gatherEvidence(target) {
  (can run it) => run the probes in the matching reference file
  (given output, transcripts, screenshots, or code) => walk them as the primary persona would
  (only a description) => say so; every finding is provisional
}

countExcise(mainPath) {
  List each step of the most frequent task; mark it goal work or excise
  Excise is work that doesn't move the caller toward the goal: re-entering, confirming, configuring, waiting, dismissing, reading noise
  Report "X of Y steps are excise"; excise on a frequent path is paid every time
}

walkPrinciples(evidence) {
  Ask each principle's question from principles.md; record findings and what the surface already does well
}

recommend(finding) {
  Every fix is implementable as written
  (politeness conflicts with security, a legal need, or script stability) => name the tension and propose the most considerate option within it
}

politeReview(target) {
  establishContext |> gatherEvidence |> countExcise |> walkPrinciples |> severity |> recommend |> report
}

politeDiscover(journey) {
  read plan/story-map/<journey>.yaml and personas.yaml
  for each step: count its excise and walk the principles against what the step does, or will do
  findings |> toPainPoint |> propose one user story per pain point
}

Commands {
  /polite-review [target] - review a command, surface, transcript, or diff; output the report in references/report.md. Read-only
  /polite-discover [journey] - turn a journey's steps into ranked pain points and user stories. Output only; saving them is aidd-product-manager's /save
}
