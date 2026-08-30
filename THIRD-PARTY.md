# Third-party notices

`fab-test` is MIT-licensed (see [LICENSE](LICENSE)), and does not vendor or
redistribute the binaries below — none of them ship inside the wheel. Each is
downloaded (or, for pbir-a11y, built from source) at runtime by
`_analyzer_tool_bootstrap.py` and cached under `.fab-test-tools/`, from the
URL/repository declared in `analyzers.json`'s `tool_install` block for that
analyzer. `fab-test` calls each one as an external process (or, for
pbir-a11y, requires and re-exports none of its code); it does not link
against, embed, or modify any of them.

| Tool | Analyzer | License | License text |
|---|---|---|---|
| [Tabular Editor 2](https://github.com/TabularEditor/TabularEditor) | `bpa` | MIT | [TabularEditor/TabularEditor license](https://github.com/TabularEditor/TabularEditor/blob/master/LICENSE) |
| [fab-inspector](https://github.com/NatVanG/fab-inspector) (PBIR Inspector) | `pbir` | MIT | [NatVanG/fab-inspector license](https://github.com/NatVanG/fab-inspector/blob/main/LICENSE) |
| [pbir-a11y](https://github.com/Juls-BI/pbir-a11y) | `a11y` | PolyForm Shield 1.0.0 | [Juls-BI/pbir-a11y license](https://github.com/Juls-BI/pbir-a11y/blob/main/LICENSE) |

## pbir-a11y and PolyForm Shield 1.0.0

Unlike Tabular Editor 2 and fab-inspector's permissive MIT terms,
[PolyForm Shield 1.0.0](https://polyformproject.org/licenses/shield/1.0.0/)
is **source-available with a non-compete restriction**, not permissive. In
plain terms, per the license itself and pbir-a11y's own README:

- You **can** use it for personal projects, in your day job or freelance
  work, run it in your own or your employer's dev/CI pipelines (paid work
  included), and modify or fork it.
- You **cannot** use it to build or offer a product or service that
  competes with the licensor's own commercial offering ([PBIX
  A11y](https://www.pbiaudits.com), the browser tool pbir-a11y is a CLI
  translation of).

`fab-test` **wraps pbir-a11y as an external tool call, and does not
redistribute it**: nothing under this license is vendored into the `fab-test`
wheel, checked into this repository, or shipped to anyone who installs
`fab-test`. `invoke_pbir_a11y.py` spawns pbir-a11y's built CLI as a
subprocess and reads its JSON output over stdout, the same arm's-length
relationship `fab-test` has with Tabular Editor 2 and fab-inspector. Using
`fab-test`'s `a11y` analyzer to check your own Power BI reports — including
inside a commercial pipeline — is exactly the permitted use above; it does
not make `fab-test` itself, or a report checked with it, a product built on
pbir-a11y in the sense the license restricts.

## Recording a newly wrapped tool

When a future analyzer wraps another external tool, add a row to the table
above (tool, analyzer, license, link to the license text) in the same
commit that adds its `tool_install` entry to `analyzers.json` — and, if its
license is anything other than a short permissive one (MIT, Apache-2.0,
BSD), add a dedicated section explaining what it does and does not permit,
the way the PolyForm Shield section above does.
