"""Shared table styling for every surface that renders one.

Split out of `fab_test_summary` because the analyzer wrappers need it too,
and they run as a subprocess per artifact. Importing the summary module to
reach two constants pulled in `fab_test_registry` and, through it,
`_credentials`, `_desktop`, `_target`, and `_rule_overlay` — measured at
roughly 59 ms of import on every spawn.

Deliberately holds nothing but styling: no envelope knowledge, no
discovery, no analyzer names. That is what lets both the CLI and a wrapper
import it without either dragging the other along.
"""

from __future__ import annotations

# Boxed borders make column boundaries unambiguous, which matters most
# where a cell holds a long path. `tabulate` is already a dependency, so
# this costs nothing; `rich` would look better still but is a runtime
# dependency for presentation alone.
TABLE_FORMAT = "rounded_outline"


def table_padding(col_count: int) -> int:
    """Return the non-content characters a table of ``col_count`` costs.

    Column widths are budgeted against the terminal, so this has to match
    whatever `TABLE_FORMAT` actually draws or wide cells overflow and wrap
    — which looks worse than the truncation the budget exists to produce.

    A boxed format spends ``"│ "`` on the left edge, ``" │ "`` between each
    pair, and ``" │"`` on the right: ``3 * col_count + 1``. A borderless
    one spends two spaces between columns and nothing at the edges.
    """
    if "outline" in TABLE_FORMAT or "grid" in TABLE_FORMAT:
        return 3 * col_count + 1
    return 2 * (col_count - 1)
