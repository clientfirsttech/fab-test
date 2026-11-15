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

Every selection below was last saved by Power BI Desktop (2026-11-14), so each shape is what Desktop writes. Each rendered as listed in Desktop screenshots after a refresh.

| Page | Visual | Kind | Saved selection |
|---|---|---|---|
| Standard Slicers | `ce885ceced4291ade64c` | `slicer` Dropdown | Alignment = Bad |
| Standard Slicers | `9eded2e3c22f3f38a082` | `slicer` Basic, multi-select | Eye Color = Black, Compound |
| Standard Slicers | `012e790c5b0c7c36c739` | `slicer` Dropdown, calendar column | Fiscal Semester cleared (All) |
| Standard Slicers | `0799761abbc17c80e032` | `slicer` Dropdown, single select, calendar column | Half Year = 2025 H2, a year behind the current 2026 H2 |
| Standard Slicers | `bfe1bd2eb570a144b258` | `slicer` Dropdown | Year = 1940 (its header still reads "no default") |
| Standard Slicers | `b84126137973afa03196` | `slicer` Basic, field parameter | Chart Measure = Number of Characters |
| Date Between | `e18dbfac55c555c788cc` | `slicer` Between | First appearance up to 2026-10-28 (start left at the earliest date) |
| Date Relative | `a60f5852c086b26d86a4` | `slicer` Relative | Last 20 calendar months |
| Date Picker | `77017c2b4495f8869386` | `slicer` RelativeDatePicker | 1939-10-01 to 1951-08-27, picked on the calendar |
| Input Slicer | `4939c433554061c20080` | `textSlicer`, Contains any | Character name contains "Wolverine" |

### Selection shapes Desktop writes

- **Value slicers** store `In` with one `[[{"Literal": ...}]]` row per selected value, as DAX literals (`'Bad'`, `1940L`).
- **A field parameter** stores `In` on the hidden `Chart Measure Fields` column with the field reference as the value (`'''MarvelFact''[Number of Characters]'`). The display name appears only in `Where[].Annotations.filterExpressionMetadata.valueMap`. A visual bound to the parameter keeps only the selected field in its projections (`fieldParameters[].length` follows the selection).
- **No selection** has two forms: no `general` object at all (never set), or `general: [{"properties": {}}]` (cleared in Desktop).
- **Between** stores `data.startDate`/`data.endDate` and a filter of `>=` start and `<` end plus one day (`ComparisonKind` 2 and 3). A bound left at the column's earliest or latest date is dropped, so the filter can be a single comparison.
- **Relative** stores a `Between` of `DateSpan(DateAdd(Now, n, TimeUnit))`; `TimeUnit` 0 is day, 2 is month, 3 is year. A calendar period ends at the previous whole period (`-1`).
- **Date picker** (`RelativeDatePicker`) stores either the relative shape or, for a range picked on the calendar, the same `And` of `>=` / `<` as Between.
- **Input slicer** (`textSlicer`) stores `Contains` per typed value, with the operator in `dropdown.filterMode`; no `selectedValues`.
- On save Desktop adds `"active": true` to slicer projections, and gives the list, date and input slicers an empty `Categorical` `filterConfig` entry for their own field. The packaged `NO_VISUAL_LEVEL_FILTERS_*` rules flag that entry (see plan.md).

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
