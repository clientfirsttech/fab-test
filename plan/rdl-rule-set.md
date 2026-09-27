# RDL / Paginated Report Rule Set

Source: rule set by John K, 2026-09-24. 44 rules checkable against a `.rdl` file's XML. Element names are unprefixed RDL elements in the report's default namespace.

- **Severity**: High = measurable performance or correctness risk; Medium = performance or maintenance cost; Low = readability or convention. In fab-test, High maps to `error` (fails the run) and Medium/Low map to `warning`.
- **Tier** (added during discovery, 2026-09-26): **A** = deterministic single-file check (RDL Static Analysis epic); **B** = heuristic; **C** = cross-file, service, network, or manual. B and C are backlog.
- Source hyperlinks were lost when the rule set was pasted; only the source names below survived. Fill in URLs before the catalog ships.

## Schema and structure

| ID | Rule | Check in the XML | Sev | Tier | Source |
|---|---|---|---|---|---|
| STR-01 | Report uses a current RDL schema | Default xmlns on `<Report>` older than `.../reporting/2016/01/reportdefinition`. Power BI accepts SSRS 2016+. Fix: open and save in Report Builder. | Medium | A | MS Learn: Find schema version; What are paginated reports |
| STR-02 | Built from a common template | PageHeader has logo, `Globals!ExecutionTime`, page number; PageFooter has standard notice. Compare against template. | Low | C | MSSQLTips #3659 r1 |
| STR-03 | Field names are friendly | `Fields/Field/@Name` has no auto-generated underscores or cryptic names. | Low | B | MS Learn: Data retrieval guidance |

## Data sources and datasets

| ID | Rule | Check in the XML | Sev | Tier | Source |
|---|---|---|---|---|---|
| DS-01 | Use shared data sources | `DataSource` has `DataSourceReference`, not embedded `ConnectionProperties/ConnectString`. Also flag credentials in the connect string. | Medium | A | MSSQLTips #3659 r2 |
| DS-02 | No unused datasets | Every `DataSet/@Name` appears in some `DataSetName`, `DataSetReference/DataSetName`, or expression. All datasets run even when unbound. | High | A | MS Learn: Data retrieval; MSSQLTips #3659 r3 |
| DS-03 | No datasets for fixed parameter lists | `ValidValues`/`DefaultValue` `DataSetReference` returning static values → use `ParameterValues`. | Medium | B | MSSQLTips #3659 r3 |
| DS-04 | Share one dataset across data regions | Near-identical `CommandText` feeding different regions. | Medium | B | MSSQLTips #3659 r3 |
| DS-05 | No SELECT * | Regex `SELECT\s+\*` in `Query/CommandText`. | High | A | MSSQLTips #3659 r4; MS Learn: Data retrieval |
| DS-06 | No orphan query columns | Select-list columns with no matching `Field/DataField`. | Medium | B | MS Learn: Data retrieval |
| DS-07 | Prefer stored procedures for relational sources | `Query/CommandType = StoredProcedure` rather than inline text. | Medium | A | MS Learn: Data retrieval; DMC 2023 |

## Query pushdown

| ID | Rule | Check in the XML | Sev | Tier | Source |
|---|---|---|---|---|---|
| QRY-01 | Filter in the query, not the report | `DataSet/Filters` or `Tablix/Filters` present. | High | A | MS Learn: Performance; MSSQLTips #3659 r6 |
| QRY-02 | No report-level calculated fields | `Field` with a `Value` child instead of `DataField`. | Medium | A | MS Learn: Data retrieval; MSSQLTips #3659 r7 |
| QRY-03 | Aggregate in the query | `Sum(`, `Count(`, `Avg(` in textbox `Value`s over detail datasets. | High | A | MS Learn: Performance; MSSQLTips #4006 |
| QRY-04 | Sort in the query | `SortExpressions` on tablix groups duplicating an order that could be `ORDER BY`. | Medium | A | MSSQLTips #3659 r10 |
| QRY-05 | Convert types in the query | `CDate(`, `CInt(`, `CDec(`, `CStr(` repeated on the same field. | Medium | A | MSSQLTips #3659 r9 |
| QRY-06 | Join in the query, not with Lookup | `Lookup(`, `LookupSet(`, `MultiLookup(` in expressions. | High | A | MSSQLTips #4006; MS Learn: Data retrieval |
| QRY-07 | Move complex SQL into views or procs | Long `CommandText` (e.g. >50 lines or multiple CTEs). | Low | A | MSSQLTips #3659 r8 |

## Parameters

| ID | Rule | Check in the XML | Sev | Tier | Source |
|---|---|---|---|---|---|
| PRM-01 | Every parameter has a sensible default | Each `ReportParameter` has a `DefaultValue`. | Medium | A | MSSQLTips #3659 r13 |
| PRM-02 | Parameter types match the source column | `DataType` matches the SQL column type; dates use `DateTime`, not `String`. | High | B | MSSQLTips #3659 r14 |
| PRM-03 | Keep the parameter count low | Count `ReportParameter`; flag separate Year/Month/Day parameters. | Low | A | MSSQLTips #3659 r12 |
| PRM-04 | No MultiValue + Nullable | `MultiValue = true` with `Nullable = true` isn't supported. | High | A | MS Learn: Power BI Report Builder |
| PRM-05 | Show selected parameter values on the report | Each parameter appears as `Parameters!Name.Value`/`.Label` in a `Textbox`. | Low | A | MSSQLTips #4006 |
| PRM-06 | Choose filter vs query parameter deliberately | Parameter in `DataSet/Filters` vs `Query/QueryParameters`. | Medium | B | MS Learn: Data retrieval |

## Layout and rendering

| ID | Rule | Check in the XML | Sev | Tier | Source |
|---|---|---|---|---|---|
| LAY-01 | Body fits the page | `ReportSection/Width + Page/LeftMargin + Page/RightMargin ≤ Page/PageWidth`. | High | A | DataTaal 2026; MSSQLTips #3659 r11, r18 |
| LAY-02 | Avoid TotalPages | `Globals!TotalPages` in expressions. | Medium | A | MSSQLTips #3659 r15 |
| LAY-03 | Avoid subreports inside data regions | `Subreport` nested in a `Tablix`. Same detection as SUB-01. | High | A | MSSQLTips #3659 r19 |
| LAY-04 | Use interactive sort only when needed | `UserSort` elements on textboxes. | Low | A | MSSQLTips #3659 r17 |
| LAY-05 | Large reports have page breaks | Tablixes have a `Group/PageBreak/BreakLocation`. | Medium | A | MSSQLTips #3659 r16, r20 |
| LAY-06 | Avoid embedded images | `EmbeddedImages/EmbeddedImage`, or `Image/Source = Embedded`. | Medium | A | MS Learn: Image guidance |
| LAY-07 | External images are reachable and small | `Image/Source = External`: no sign-in, under 4 MB. | Medium | C | MS Learn: Image guidance |

## Subreports

| ID | Rule | Check in the XML | Sev | Tier | Source |
|---|---|---|---|---|---|
| SUB-01 | Prefer nested regions or drillthrough over a subreport in a tablix | `Subreport` inside a `Tablix` runs once per row. | High | A | MS Learn: Add a subreport; Subreports (SSRS) |
| SUB-02 | Stay under 50 subreports per main report | Count `Subreport` elements. | High | A | MS Learn: Troubleshoot subreports |
| SUB-03 | Passed parameters match the child's | Each `Subreport/Parameters/Parameter/@Name` exists in the child RDL; required child params are passed. | High | C | MS Learn: Troubleshoot; Subreports in Power BI |
| SUB-04 | ReportName resolves to one uniquely named report | `Subreport/ReportName` matches exactly one published report in the workspace. | High | C | MS Learn: Subreports in Power BI; Troubleshoot |
| SUB-05 | Share subreports with the same audience | Deployment check, not XML. | Medium | C | MS Learn: Subreports in Power BI |
| SUB-06 | Migrate subreports first | SSRS migration ordering. | Low | C | MS Learn: Subreports in Power BI |

## Accessibility

| ID | Rule | Check in the XML | Sev | Tier | Source |
|---|---|---|---|---|---|
| ACC-01 | Every object has alt text | Each `Image`, `Chart`, `Tablix`, `GaugePanel`, `Map` has a non-empty `ToolTip`. | High | A | MS Learn: Accessibility features |
| ACC-02 | Chart alt text describes the insight | `Chart/ToolTip` isn't a default name like "Chart1". | High | A | MS Learn: Accessibility features |
| ACC-03 | Tables have a caption or summary | `Tablix/ToolTip` present. | Medium | A | MS Learn: Accessibility features |
| ACC-04 | Titles are tagged as headings | Heading H1–H6 structure type on title textboxes; saved element name unconfirmed. | Medium | B | MS Learn: Accessibility features |
| ACC-05 | Header rows are tagged as column headers | Column-header structure type on tablix header rows. | Medium | B | MS Learn: Accessibility features |
| ACC-06 | Text contrast is at least 4.5:1 | `Style/Color` vs effective `BackgroundColor` (item → container → body). | High | B | MS Learn: Accessibility features; overview |
| ACC-07 | Alt text and headers are clear | Manual review for abbreviations/codes. | Low | C | MS Learn: Accessibility features |
| ACC-08 | HTML links carry alt text | `TextRun` with `MarkupType = HTML` rendering a link has a `ToolTip`. | Low | A | MS Learn: Accessibility features |

## Notes outside the XML

- Number/date textboxes should be wide enough not to wrap (MSSQLTips #4006). Preview in each export format, since HTML and PDF paginate differently (MS Learn: Pagination).
- Export with Accessible PDF (standard PDF is untagged) and validate with the PDF Accessibility Checker; non-wizard tables tag headers as TD (MS Learn: Accessibility features).
