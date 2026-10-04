# Third-party notices

`fab-test` is MIT-licensed (see [LICENSE](LICENSE)), and does not vendor or
redistribute the binaries below — none of them ship inside the wheel. Each is
downloaded (or, for pbir-a11y, built from source; for promptfoo, installed as a
cached npm package) at runtime by
`_analyzer_tool_bootstrap.py` and cached under `.fab-test-tools/`, from the
URL/repository declared in `analyzers.json`'s `tool_install` block for that
analyzer. `fab-test` calls each one as an external process (or, for
pbir-a11y, requires and re-exports none of its code); it does not link
against, embed, or modify any of them.

`pql-test` is different: it is a regular pinned `pip` dependency in
`pyproject.toml` (not a `tool_install`-bootstrapped tool), so it **is**
installed alongside `fab-test` for every `pip install cft-fab-test` — it is the
one tool in this file that actually reaches every installer's environment.
`invoke_pql_test.py` still calls its installed console-script entry point
(`pql-test.exe`) as an external process rather than importing its code.

| Tool | Analyzer | License | License text |
|---|---|---|---|
| [Tabular Editor 2](https://github.com/TabularEditor/TabularEditor) | `bpa` | MIT | [TabularEditor/TabularEditor license](https://github.com/TabularEditor/TabularEditor/blob/master/LICENSE) |
| [fab-inspector](https://github.com/NatVanG/fab-inspector) (PBIR Inspector) | `pbir` | MIT | [NatVanG/fab-inspector license](https://github.com/NatVanG/fab-inspector/blob/main/LICENSE) |
| [pbir-a11y](https://github.com/Juls-BI/pbir-a11y) | `a11y` | PolyForm Shield 1.0.0 | [Juls-BI/pbir-a11y license](https://github.com/Juls-BI/pbir-a11y/blob/main/LICENSE) |
| [promptfoo](https://github.com/promptfoo/promptfoo) | `data_agent` | MIT | [promptfoo/promptfoo license](https://github.com/promptfoo/promptfoo/blob/main/LICENSE) |
| [pql-test](https://pypi.org/project/pql-test/) | `pql_test` | Business Source License 1.1 | Bundled at `pql_test-<version>.dist-info/licenses/LICENSE.txt` in any `fab-test` install |

## pbir-a11y: PolyForm Shield 1.0.0

Unlike Tabular Editor 2 and fab-inspector's MIT terms,
[PolyForm Shield 1.0.0](https://polyformproject.org/licenses/shield/1.0.0/)
is a source-available, non-permissive license. Its full text is at the link
above and at pbir-a11y's own
[LICENSE](https://github.com/Juls-BI/pbir-a11y/blob/main/LICENSE) file.

`fab-test` wraps pbir-a11y as an external tool call (`invoke_pbir_a11y.py`
spawns its built CLI as a subprocess) and does not redistribute it: nothing
under this license is vendored into the `fab-test` wheel, checked into this
repository, or shipped to anyone who installs `fab-test`.

## pql-test: Business Source License 1.1

pql-test's [LICENSE.txt](https://pypi.org/project/pql-test/) (bundled at
`pql_test-<version>.dist-info/licenses/LICENSE.txt` in any `fab-test`
install) names Client First Technologies as Licensor and states:

- **Additional Use Grant:** None
- **Change Date:** four years from the date each version is first published
- **Change License:** GNU Affero General Public License v3.0

The full [Business Source License 1.1](https://mariadb.com/bsl11/) text
governs what those terms mean. Unlike the other three tools in this file,
pql-test is installed as a regular pinned `pip` dependency in
`pyproject.toml`, not fetched on demand by `_analyzer_tool_bootstrap.py` —
it is present in every `fab-test` install. `invoke_pql_test.py` still calls
its installed console-script entry point (`pql-test.exe`) as an external
process rather than importing its code.

Questions about what either license permits for a specific use are a legal
question for that license's text and your own counsel, not something this
file interprets.

## Recording a newly wrapped tool

When a future analyzer wraps another external tool, add a row to the table
above (tool, analyzer, license, link to the license text) in the same
commit that adds its `tool_install` entry to `analyzers.json` — and, if its
license is anything other than a short permissive one (MIT, Apache-2.0,
BSD), add a dedicated section stating its key terms as written, the way the
PolyForm Shield and Business Source License sections above do. The same
applies to a new pinned `pip` dependency added to `pyproject.toml`, not
just a `tool_install`-bootstrapped one — pql-test above is the precedent
for that case.
