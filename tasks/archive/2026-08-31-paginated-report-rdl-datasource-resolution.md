# Paginated Report RDL Data Source Resolution Epic

**Status**: ✅ COMPLETED — 3 of 3 tasks done
**Goal**: `fab-test playwright` resolves a paginated report's dataset ID and workspace automatically from its own local `.rdl` file, instead of requiring the caller to already know and supply those GUIDs by hand.

## Overview

A paginated report's `GenerateToken` request needs a dataset ID whenever the report queries a Power BI semantic model as a data source, but the Fabric REST API's report-metadata lookup does not reliably surface it (Paginated Report Testing epic). The report's own local `.rdl` file already carries this information in its `<DataSources>` block: `DataProvider=PBIDATASET` names the connection type, `Initial Catalog=sobe_wowvirtualserver-<GUID>` in `ConnectString` is the dataset's own ID, and `rd:PowerBIWorkspaceName` names the workspace it lives in (which may differ from the report's own workspace -- a shared dataset commonly does). The caller should never have to supply a GUID fab-test can read directly out of a file already checked into the repository.

---

## Parse a paginated report's own dataset reference from its .rdl file

**Requirements**:
- Given a local `.rdl` file with a `PBIDATASET` data source, parsing should extract the dataset ID from `ConnectString`'s `Initial Catalog=sobe_wowvirtualserver-<GUID>` pattern and the workspace name from `rd:PowerBIWorkspaceName`
- Given a local `.rdl` file whose only data source is not `PBIDATASET` (e.g. `PQO`/Power Query), parsing should return nothing rather than a false match -- not every paginated report has a bound Power BI dataset
- Given a malformed or unreadable `.rdl` file, parsing should return nothing rather than raising

---

## Resolve the dataset automatically when the artifact is discovered locally

**Requirements**:
- Given `fab-test playwright --artifact NAME --env ENV` (or local batch discovery) with no `--dataset-id`/`--dataset-workspace-id` given and a local `NAME.rdl` file exists with a parseable `PBIDATASET` source, the subprocess should be told the dataset ID and dataset workspace ID automatically
- Given an explicit `--dataset-id`/`--dataset-workspace-id`, that value should win over anything parsed from the `.rdl` file
- Given no local `.rdl` file exists at all (a purely remote target with nothing checked in), behavior should fall back to today's live metadata lookup / explicit-flag requirement unchanged

---

## Correct local discovery to the real RDL artifact convention

The Paginated Report Testing epic's local discovery extension assumed a `NAME.PaginatedReport/` folder convention that does not match how RDL reports are actually checked in -- they are flat `NAME.rdl` files.

**Requirements**:
- Given a repository with `NAME.rdl` files, `fab-test playwright` with no `--artifact` should discover and validate them as paginated reports
- Given no `NAME.PaginatedReport` folder convention exists in practice, the discovery/artifact-type-registry support added for it should be corrected or removed rather than left as dead, misleading code
