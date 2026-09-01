# Fabric CI/CD Deployment Skill Retirement

**Status**: ✅ COMPLETED
**Goal**: Stop routing "deploy"/"fabric deploy" to a skill that documents scripts this repository no longer contains.

## Overview

The Pipeline Deletion Dead-Code Audit epic deleted `deploy.py`, `check_promotion_safety.py`, and `generate_fabric_cicd_config.py` — confirmed to have zero production callers anywhere in `src/`, `tests/`, or a surviving workflow. It missed one caller class: `.github/skills/fabric-cicd-deployment/SKILL.md` and its `README.md` document all three as the live deployment interface, with worked CLI examples. That skill is still wired into `.github/agents/aidd.agent.md` and `.github/skills/aidd-workflow/SKILL.md`'s command maps under "deploy, fabric deploy", so following it today tells an agent to run a file that does not exist.

Deeper than a stale doc: vision.md's own Non-Goals already say deployment is out of scope for this package ("Being a general-purpose Fabric deployment tool — deployment lives in `fabric-cicd-deployment`"), naming it as a separate concern. The three deleted scripts living inside `src/fab_test/scripts/` were themselves a holdover from before that boundary was drawn. Nothing in this repository implements the pattern the skill describes any more, so the honest fix is retiring the skill — not rewriting it to describe a pattern with no working implementation, and not silently deleting a skill a future deployment effort might want as a reference.

---

## Retire the skill and its command-map routing

**Requirements**:
- Given `.github/skills/fabric-cicd-deployment/SKILL.md`, should state plainly near the top that it is retired, why (the scripts it documented were deleted; deployment automation for this repository no longer exists), and that its schema/architecture content is kept only as historical reference — not an instruction an agent should act on.
- Given `.github/skills/fabric-cicd-deployment/README.md`, should carry the same retirement note.
- Given `.github/agents/aidd.agent.md`'s Command Map and `.github/skills/aidd-workflow/SKILL.md`'s Command Map, should no longer route "deploy"/"fabric deploy" to `fabric-cicd-deployment` — neither should silently keep pointing at a retired skill.
- Given a skill under `.github/skills/` (other than one explicitly named as retired) references `scripts/<name>.py`, should have that file exist under `src/fab_test/scripts/` — a new regression test enforces this so the same class of drift (a script deleted, its skill left undated) fails the suite instead of requiring another manual review to catch it.
