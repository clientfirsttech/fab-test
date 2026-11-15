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

## SampleModel-DefaultState test bed

`SampleModel-DefaultState.Report` binds to `SampleModel-PQLAssert.SemanticModel` and holds one preselected example per slicer kind for the [PBIR Slicer Default State epic](../tasks/pbir-slicer-default-state-epic.md). Each selection lives in `visual.objects.general[0].properties.filter` of the named `visual.json`. `Fiscal Calendar` (July fiscal years named by their end year) and the `Chart Measure` field parameter were added to the model for it; `Fiscal Calendar` is disconnected, so its slicers filter nothing.

**Provenance** says where a selection's JSON shape comes from. *Desktop* means the same shape Power BI Desktop wrote in `SampleModel-PQLAssert.Report`; *hand* means authored from `powerbi-report-author` metadata and only rendered. A *hand* shape is not canonical until a Desktop save confirms it: select the value in Desktop, save, and diff.

| Page | Visual | Kind | Preselected | Provenance | Rendered (before refresh) |
|---|---|---|---|---|---|
| Standard Slicers | `ce885ceced4291ade64c` | `slicer` Dropdown | Alignment = Good | Desktop (`In`) | Good |
| Standard Slicers | `9eded2e3c22f3f38a082` | `slicer` Basic, multi | Eye Color = Blue, Brown | Desktop (`In`, extended to two values) | Blue, Brown ticked |
| Standard Slicers | `012e790c5b0c7c36c739` | `slicer` Dropdown, calendar-driven | Fiscal Semester = FY27-S1 (as of 2026-11-14) | Desktop (`In`) | FY27-S1 |
| Standard Slicers | `0799761abbc17c80e032` | `slicer` Dropdown, single select, second label format | Half Year = 2026 H2 | Desktop (`In`) | 2026 H2 |
| Standard Slicers | `bfe1bd2eb570a144b258` | `slicer` Dropdown, near-miss | none (All) | n/a | All |
| Standard Slicers | `b84126137973afa03196` | `slicer` Basic, field parameter | Chart Measure = Running Total | hand (`In` on the display column) | **not ticked**, though the chart applies it |
| Date Between | `e18dbfac55c555c788cc` | `slicer` Between | First appearance 1961-01-01 to 1969-12-31 | hand (`And` of `>=` / `<` on `datetime'…'`) | empty until refresh |
| Date Relative | `a60f5852c086b26d86a4` | `slicer` Relative | Last 20 years, including today | Desktop (copied verbatim) | Last 20 Years, 11/16/2006 - 11/15/2026 |
| Date Picker | `77017c2b4495f8869386` | `slicer` RelativeDatePicker | Last 20 years from today | hand (Relative filter, new mode) | 11/16/2006 - 11/15/2026 |
| Input Slicer | `4939c433554061c20080` | `textSlicer`, Contains any | Character name contains "Spider" | hand (`Contains`, `dropdown.filterMode`) | Spider pill |

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
