---
name: aidd-graphify
description: Use shared local EXTRACTED-only graph context for reviews, epic refreshes, dependency lookup, and measured Claude/Copilot savings.
---

# Shared Local Graph Skill

## Process

fn loadSharedSkill() {
  Resolve the absolute repository root
  Read "$root/.github/skills/aidd-graphify/SKILL.md"
  Follow that canonical skill's constraints, commands, and benchmark protocol
  Do not run stock /graphify, install hooks, or bypass required network isolation
}

loadSharedSkill()
