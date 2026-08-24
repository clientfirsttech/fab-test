# Fabric Artifacts

This directory contains Microsoft Fabric artifact definitions.

## Directory Structure

Each artifact is stored in its own subdirectory with a naming convention:

```
<ArtifactName>.<ArtifactType>/
```

### Examples

- `SalesModel.SemanticModel/` - A semantic model artifact
- `SalesReport.Report/` - A report artifact
- `CustomerAgent.Agent/` - An agent artifact
- `DataPipeline.Notebook/` - A notebook artifact

## Artifact Detection

The CI/CD pipeline automatically detects changes to artifacts in this directory using:

```bash
git diff --name-only HEAD~1 HEAD
```

Changed artifacts are published to `changed-artifacts.json` for downstream processing.

## Artifact Types

Artifact types are mapped in `artifact-map.json`, resolved via the metadata
layers (`.fab-test/metadata/` > `.github/metadata/` > packaged with the
distribution).

Each artifact type has:
- Static analyzers (run before deployment)
- Dynamic validators (run after deployment)

See `analyzers.json` (same metadata layers) for the complete analyzer matrix.

## Deployment

All artifacts are deployed using Fabric CI/CD Python:

```bash
python -m fabric_cicd deploy
```

Manual REST deployment is prohibited.
