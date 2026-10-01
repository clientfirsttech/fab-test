# RDL Finding Clarity Epic

**Status**: ✅ COMPLETED (2026-09-30)
**Goal**: A person reading `fab-test rdl` output can tell which dataset, field or object broke which rule, and the terminal output looks like every other analyzer's.

## Overview

A review of `fab-test rdl --verbose` against `QRY-02.rdl` found two problems. The verbose run prints three lines and no findings table, where PBIR Inspector and BPA print a banner, context lines and a table. And a finding's `object` is a bare leaf name (`Test`, `DataSet1`) with a generic message: QRY-02 doesn't say which dataset the calculated field is in or what its expression is, DS-05 doesn't show the `SELECT *`, and the report's Results table keeps only the first hit per rule. DS-02 is the one rule that reads well, because it puts the dataset name in its message.

---

## Shared findings table

**Status**: ✅ DONE (2026-09-30)

`_table_style.py` already owns the house table format (`TABLE_FORMAT`, `table_padding`); `_truncate` and the findings table are copied between the BPA and PBIR wrappers, and PBIR alone still draws `simple` instead of the house format.

**Requirements**:
- Given `fab-test rdl --verbose` with findings, should print the same banner, Artifact/Rules/Envelope/Native JSON lines and finding count as PBIR Inspector, then a Rule/Severity/Object/Message table in `TABLE_FORMAT`
- Given the table helper, should live in `_table_style.py` (no CLI-layer imports), be used by `rdl` and PBIR Inspector, and replace the duplicated `_truncate` in BPA
- Given PBIR Inspector's verbose table, should now draw in `TABLE_FORMAT` and keep its sort order and columns
- Given `invoke_rdl_lint.py`, should be covered by the wrapper layering test

---

## Breadcrumbs

**Status**: ✅ DONE (2026-09-30). Also fixed QRY-04, which looked for SortExpressions inside Group; Report Builder writes them beside Group in TablixMember and under Tablix, so it never fired on a real file.

**Requirements**:
- Given a finding on a dataset-scoped item (field, filter, query), should set `object` to a path such as `DataSet1 › Test`, so a name reused across datasets is unambiguous
- Given QRY-02, should quote the field's expression in the message
- Given DS-05, DS-07 and QRY-01, should quote the offending fragment (the `SELECT *` text, the DAX table, the filter expression), truncated
- Given any rule that fires, should follow DS-02: the message alone, as shown in a CI annotation, identifies the offender
- Given an unnamed element, should fall back to its element path rather than `?`

---

## Every hit in the Results table

**Status**: ✅ DONE (2026-09-30)

`build_test_results` keeps only the first hit per rule.

**Requirements**:
- Given a rule that fires on several elements, should show every offender in the report's Results table, not only the first
- Given a rule that passes or is skipped, should still produce one row

---

## Documentation

**Status**: ✅ DONE (2026-09-30)

**Requirements**:
- Given the README, `docs/RDL-RULES.md`, QUICK-VALIDATION and the fab-test skill, should show the verbose table and the path-style `object`
