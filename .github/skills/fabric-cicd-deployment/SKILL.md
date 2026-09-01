---
name: fabric-cicd-deployment
description: "RETIRED — do not route commands here. See the retirement note below."
---

# Fabric CI/CD Deployment — RETIRED

**This skill is retired.** `deploy.py`, `check_promotion_safety.py`, and
`generate_fabric_cicd_config.py` — the scripts this skill documented as the
live deployment interface — were deleted by the Pipeline Deletion Dead-Code
Audit epic (2026-08-31): the nine Fabric pipeline workflows that invoked
them were already removed, leaving all three with zero production callers
anywhere in this repository. Deployment automation for this project does
not currently exist.

This also matches [vision.md](../../../vision.md)'s own Non-Goals, which
already scoped deployment out of `fab-test`: *"Being a general-purpose
Fabric deployment tool — deployment lives in `fabric-cicd-deployment`."*
The three scripts living inside `src/fab_test/scripts/` were a holdover
from before that boundary was drawn, not a deliberate design.

Nothing below this note describes working tooling. It is kept only as a
historical reference for the `environments.yml` schema and promotion-chain
shape, in case a future deployment effort wants a starting point — not as
an instruction for an agent to act on. No command routes here any more
(see `aidd.agent.md`/`aidd-workflow/SKILL.md`'s command maps).

---

Metadata-driven deployment pattern using `environments.yml` as the single source of truth.
All deployment logic flows through `scripts/deploy.py` → `python -m fabric_cicd deploy`.

## Architecture

```
.fab-test/metadata/environments.yml        ← single source of truth
        │
        ├─ scripts/deploy.py               ← reads yml, generates temp config, invokes fabric-cicd
        ├─ scripts/check_promotion_safety.py ← validates promotion eligibility
        └─ scripts/generate_fabric_cicd_config.py ← standalone config generator
                │
                └─ python -m fabric_cicd deploy --config <temp-config> --artifact <path>
```

## environments.yml Schema

```yaml
promotion_chain: [testbed, dev, test, prod]

defaults:
  repository_directory: ".fabric/artifacts"
  item_type_in_scope: ["*"]

environments:
  <name>:
    description: String
    workspace_id: String          # supply via FABRIC_WORKSPACE_ID at runtime
    allowed_branches: [String]
    promotion_target: String
    previous_environment: String  # omit for first in chain
    requires_validation: bool     # static analyzers must pass
    requires_security_scan: bool  # credential + entropy scan
    requires_ai_validation: bool  # AI governance (testbed only)
    allows_rollback: bool
```

Constraints {
  workspace_id must be empty in the file — supply at runtime via FABRIC_WORKSPACE_ID or --workspace-id
  Never commit a workspace_id value to environments.yml
  environments.yml is the only supported environment configuration file — do not recreate environments.json or fabric-cicd-config.yml
}

## Promotion Chain

```
testbed → dev → test → prod
```

Each environment defines `promotion_target` and `previous_environment`.
`check_promotion_safety.py` validates that the previous stage passed its gates before allowing promotion.

## Deployment Ordering

Artifacts are deployed in dependency order using a topological sort. Reports that
reference a local SemanticModel via `definition.pbir` `byPath` are scheduled in
a later phase than the SemanticModel. The workflow enforces this with GitHub
Actions `needs` edges between `deploy-phase-N` jobs.

```
prepare-matrix  ──►  deploy-phase-0  ──►  deploy-phase-1  ──►  deploy-phase-2 ...
                         (SemanticModels)       (Reports)
```

The per-artifact `fabric-cicd` invocation deploys **only** the named artifact;
dependencies are guaranteed by phase ordering, not by `items_to_include`.

## deploy.py Interface

Deploy a single artifact:

```bash
python scripts/deploy.py \
  --artifact <path-to-artifact-folder> \
  --environment <environment-name> \
  [--workspace-id <workspace-id>]
```

Generate a deployment plan for a set of changed artifacts:

```bash
python scripts/deploy.py \
  --plan \
  --environment <environment-name> \
  --terse \
  < changed-artifacts.json
```

The plan input JSON must be an object with a `changed_artifacts` list:

```json
{
  "changed_artifacts": [
    {"name": "Model.SemanticModel", "type": "SemanticModel", "path": ".fabric/artifacts/Model.SemanticModel"},
    {"name": "Report.Report", "type": "Report", "path": ".fabric/artifacts/Report.Report"}
  ]
}
```

Reads `environments.yml`, merges defaults + environment block, writes a temporary
`fabric-cicd` config, then invokes:

```bash
python -m fabric_cicd deploy --config <temp-config> --artifact <path>
```

## Dependency Rules

- A `Report` may reference a `SemanticModel` via `definition.pbir` `byPath`.
- If the referenced SemanticModel is in the same changed set, it is added to the
dependency graph and scheduled in an earlier deployment phase.
- If the referenced SemanticModel is **not** in the changed set, it is assumed to
already exist in the target workspace. The Report is scheduled without a local
dependency edge.
- Circular local dependencies raise an error during plan generation.

## Validation Gates per Environment

| Environment | Static validation | Security scan | AI validation |
|-------------|------------------|---------------|---------------|
| testbed | ✅ required | ✅ required | ✅ required |
| dev | ✅ required | ✅ required | — |
| test | ✅ required | ✅ required | — |
| prod | ✅ required | ✅ required | — |

## Adding a New Environment

addEnvironment(name) {
  1. Add block under `environments:` in environments.yml
  2. Set promotion_target and previous_environment
  3. Set requires_* flags
  4. Leave workspace_id empty — add the value to GitHub Secrets as FABRIC_WORKSPACE_ID_<NAME>
  5. Add the branch → environment mapping in the workflow inputs if needed
}

## Common Failure Modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `workspace_id is empty` | Not set in secrets | Add `FABRIC_WORKSPACE_ID` secret for the environment |
| `Environment not found` | Name mismatch | Check spelling against `environments.yml` keys |
| `Missing required key` | Schema violation | Add missing `defaults` or `environments` block |
| `Circular dependency detected` | Local artifact references form a cycle | Remove the circular `byPath` reference |
| `Report deployed before SemanticModel` | Dependency not discovered or old workflow | Confirm the Report uses `byPath` and the orchestrator is using phased deploy jobs |
| Promotion blocked | Previous stage gates not met | Run validation for `previous_environment` first |
