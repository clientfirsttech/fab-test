# Output shapes

One finding serves both AIDD flows: review ranks it like `aidd-review`, and discovery turns it into an `aidd-product-manager` pain point. Neither flow invents its own scale.

```
toReview(finding) {
  (High, and it can lose data or work or deceives) => blocking
  (High | Medium) => should-fix
  Low => nit
}

toPainPoint(finding) => PainPoint {
  name: finding.title
  description: finding.whatHappens + " " + finding.whyRude
  impact: 1..10       // from stakes: High 7..10, Medium 4..6, Low 1..3
  frequency: 1..10    // from how often the path runs: every run 8..10, most runs 5..7, rare 1..4
}
// aidd-product-manager ranks a story by impact * frequency

toStory(painPoint, persona) => "As a $persona, I want $jobToDo, so that $benefit"
```

Keep a report proportionate: a small command might have three findings, a whole CLI fifteen. Never fill a section to fill it.

## /polite-review report

```markdown
# Politeness review: [surface]

**Primary persona:** [from personas.yaml] — **Goals:** [1–3, in their words]
**Other callers checked:** [pipeline: …; agent: …]
**Evidence:** [ran / read / described, and against what]

## Summary
[2–4 sentences: its character as a helper, the biggest problems, what it already does well.]

## Excise on the main path
1. [step] — goal work
2. [step] — excise ([what kind: confirming, re-entering, waiting…])
…
X of Y steps are excise.

## Scorecard
| Principle | Rating | Note |
|---|---|---|
| [principle] | Polite / Mixed / Rude | [one line] |

[Only principles with evidence.]

## Findings

### [High · should-fix] [Short title]
- **Principle:** [principle] (vision: [vision principle], when one applies)
- **Callers:** [human, pipeline, agent]
- **Evidence:** [ran | read | described]
- **What happens:**
  ```
  [the exact output or prompt]
  ```
- **Why it's rude:** [the cost to the caller's goal]
- **Fix:** [concrete change; before/after when it helps]

[High → Medium → Low]

## What it already does well
[Polite behavior worth keeping, so fixes don't regress it.]

## Quick wins
[3–5 changes with the best payoff for the least effort.]
```

## /polite-discover output

```yaml
# For plan/story-map/<journey>.yaml; aidd-product-manager's /save writes it
painPoints:
  - name: [finding title]
    description: [what happens and why it costs the caller]
    impact: [1..10]
    frequency: [1..10]
    principle: [principle]
stories:
  - name: [short name]
    story: As a [persona], I want [job], so that [benefit]
    painPoint: [pain point name]
    priority: [impact * frequency]
```

Present the stories ranked by priority, then the excise count for each journey step that has any.
