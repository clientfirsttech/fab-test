# fabric-cicd-deployment

Documents the metadata-driven Fabric artifact deployment pattern for this project.

## Why

This project uses a single `environments.yml` file to define the promotion chain
(testbed → dev → test → prod), workspace IDs, validation gates, and branch
mappings. The skill captures the schema, the `deploy.py` interface, and common
failure modes so agents can reason about deployments without reading scattered
workflow files.

## When to use

- Deploying a Fabric artifact to a specific environment
- Configuring a new environment or workspace
- Understanding the promotion chain and gate requirements
- Diagnosing deployment failures (workspace ID missing, promotion blocked, etc.)
- Generating a standalone fabric-cicd config from `environments.yml`
