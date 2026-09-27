# Source Files

| File | Purpose |
|------|---------|
| `scripts/fab_test.py` | CLI entry point — argument parser, artifact discovery, subprocess dispatch |
| `scripts/fab_test_registry.py` | Analyzer registry, artifact discovery, and command builders |
| `scripts/invoke_tabular_editor_bpa.py` | BPA subprocess wrapper |
| `scripts/invoke_pbir_inspector.py` | PBIR Inspector subprocess wrapper |
| `scripts/invoke_pql_test.py` | pql-test subprocess wrapper (venv-aware lookup, native JSON parsing) |
| `scripts/invoke_pqlint.py` | pqlint subprocess wrapper |
| `scripts/invoke_rdl_lint.py` | `rdl` CLI wrapper — envelope, `attach_report`, malformed-file handling; the pure rule logic lives in `_rdl_lint.py` |
| `scripts/_rdl_lint.py` | `rdl`'s rule engine — namespace-agnostic XML parsing, the 28 Tier A rule check functions, the catalog loader, `test_results` builder |
| `scripts/invoke_playwright.py` | Playwright validation wrapper |
| `scripts/invoke_playwright_impact.py` | Playwright impact manifest builder |
| `scripts/invoke_playwright_dependencies.py` | Semantic-model dependency discovery wrapper |
| `scripts/playwright_validation/config.py` | `.env` / environment configuration loader |
| `scripts/playwright_validation/test_cases.py` | Report × page × bookmark case expansion |
| `scripts/playwright_validation/embed_config.py` | Power BI JavaScript embed config builder |
| `scripts/playwright_validation/power_bi_api.py` | Power BI REST API token helpers |
| `scripts/playwright_validation/fabric_service_client.py` | Azure Identity service client for Fabric/Power BI REST APIs |
| `scripts/playwright_validation/resolver.py` | Environment/workspace/report resolution |
| `scripts/playwright_validation/render_spec.py` | pytest-playwright spec that embeds reports (ships in the package; `tests/test_playwright_visual.py` holds its unit tests) |
| `scripts/_analyzer_envelope.py` | Shared envelope schema builder |
