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

from typing import Any

from tabulate import tabulate

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


def truncate(text: Any, width: int) -> str:
    """Flatten ``text`` onto one line and cut it to ``width`` with an ellipsis."""
    text = str(text).replace(chr(10), " ").replace(chr(13), "")
    if len(text) <= width:
        return text
    return text[: width - 3] + "..." if width > 3 else text[:width]


_SEVERITY_ORDER = {"error": 0, "warning": 1}


def findings_table(findings: list[dict[str, Any]], terminal_width: int) -> str:
    """Render rule-shaped findings (rule/severity/object/message) as a table.

    Errors first, then by rule and object. The message takes whatever width
    the other columns leave, so a narrow terminal truncates prose rather
    than the rule ID or the offending object.
    """
    if not findings:
        return ""
    ordered = sorted(
        findings,
        key=lambda f: (
            _SEVERITY_ORDER.get(str(f.get("severity")).lower(), 2),
            str(f.get("rule") or "").lower(),
            str(f.get("object") or "").lower(),
        ),
    )
    rows = [
        (
            str(f.get("rule") or ""),
            str(f.get("severity") or "").capitalize(),
            str(f.get("object") or ""),
            str(f.get("message") or ""),
        )
        for f in ordered
    ]
    # tabulate pads every header by two, so a column is never narrower than that.
    rule_w = min(max(len("Rule") + 2, *(len(r[0]) for r in rows)), 25)
    sev_w = min(max(len("Severity") + 2, *(len(r[1]) for r in rows)), 10)
    obj_w = min(max(len("Object") + 2, *(len(r[2]) for r in rows)), 40)
    # Keep room for a readable message: shrink the object column before it.
    while obj_w > 20 and terminal_width - rule_w - sev_w - obj_w - table_padding(4) < 40:
        obj_w -= 1
    msg_w = max(20, terminal_width - rule_w - sev_w - obj_w - table_padding(4))
    widths = (rule_w, sev_w, obj_w, msg_w)
    return tabulate(
        [tuple(truncate(cell, w) for cell, w in zip(row, widths)) for row in rows],
        headers=("Rule", "Severity", "Object", "Message"),
        tablefmt=TABLE_FORMAT,
        stralign="left",
    )
