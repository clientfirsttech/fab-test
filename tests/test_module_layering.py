"""Layering invariants between the CLI and the analyzer wrappers.

Scope
-----
An analyzer wrapper runs as a subprocess *per artifact*. Anything it
imports is paid for on every spawn, so it must not reach into the CLI
orchestration layer — `fab_test`, `fab_test_summary`, or
`fab_test_registry` — however small the thing it wants.

That is not hypothetical: the table restyle once had
`invoke_tabular_editor_bpa` importing two formatting constants from
`fab_test_summary`, which pulled in the analyzer registry and through it
`_credentials`, `_desktop`, `_target`, and `_rule_overlay` — roughly 59 ms
of import on every spawn, for two strings.

Static checks on the source text, so they are fast and always pass.
"""

import ast
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "src" / "fab_test" / "scripts"

# Modules that orchestrate the CLI. A wrapper importing one of these drags
# the whole graph into a per-artifact subprocess.
_CLI_LAYER = {"fab_test", "fab_test_summary", "fab_test_registry"}

_WRAPPERS = [
    "invoke_tabular_editor_bpa.py",
    "invoke_pql_test.py",
    "invoke_pbir_inspector.py",
    "invoke_pqlint.py",
    "invoke_rdl_lint.py",
]


def _relative_imports(path: Path) -> list[tuple[str, list[str]]]:
    """Return ``(module, [names])`` for every `from .x import y` in ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        (node.module or "", [a.name for a in node.names])
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 1
    ]


@pytest.mark.fab_test
@pytest.mark.parametrize("wrapper", _WRAPPERS)
def test_a_wrapper_does_not_import_the_cli_layer(wrapper):
    """Per-artifact subprocesses must not pay for CLI orchestration."""
    path = _SCRIPTS / wrapper
    if not path.exists():
        pytest.skip(f"{wrapper} not present")

    offenders = [m for m, _ in _relative_imports(path) if m in _CLI_LAYER]

    assert not offenders, (
        f"{wrapper} imports the CLI layer: {offenders}. "
        "Move what it needs into a leaf module both sides can import."
    )


@pytest.mark.fab_test
@pytest.mark.parametrize("wrapper", _WRAPPERS)
def test_a_wrapper_imports_no_private_name_from_another_module(wrapper):
    """A leading underscore is a module's statement that it owes no promises.

    Reaching across a boundary for one turns a private detail into a
    contract that nothing records.
    """
    path = _SCRIPTS / wrapper
    if not path.exists():
        pytest.skip(f"{wrapper} not present")

    offenders = [
        f"{module}.{name}"
        for module, names in _relative_imports(path)
        for name in names
        if name.startswith("_")
    ]

    assert not offenders, f"{wrapper} imports private names: {offenders}"


@pytest.mark.fab_test
def test_the_shared_style_module_stays_a_leaf():
    """`_table_style` exists to be importable from anywhere; keep it that way.

    The moment it imports a sibling, it stops being safe for a wrapper and
    the dependency it was created to break comes back by another route.
    """
    imports = _relative_imports(_SCRIPTS / "_table_style.py")

    assert not imports, f"_table_style must import no sibling module: {imports}"
