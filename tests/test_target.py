"""Contract tests for the target grammar (Artifact Targeting and Auth §1).

Scope
-----
`_target.parse_target` turns one string into a `ResolvedTarget`. Parsing
only: it touches no filesystem, opens no socket, and knows nothing about
which analyzer will consume the result. Deciding whether a scope is
*usable* belongs to §4; resolving a workspace name to an ID belongs to §3.
Always passes on any machine.
"""

from pathlib import Path

import pytest

from fab_test.scripts._artifact_types import artifact_types
from fab_test.scripts._target import (
    TargetError,
    parse_target,
)

# --------------------------------------------------------------------------- #
# Path scope
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_relative_path_with_type_suffix():
    """./src/Sales.SemanticModel names a location, a name, and a type."""
    target = parse_target("./src/Sales.SemanticModel")

    assert target.scope == "path"
    assert target.name == "Sales"
    assert target.type == "SemanticModel"
    assert target.path == Path("./src/Sales.SemanticModel")
    assert target.workspace is None


@pytest.mark.fab_test
def test_bare_stem_is_a_name_filter_not_a_path():
    """A bare stem carries no type, so the analyzer's own glob still selects it."""
    target = parse_target("Sales")

    assert target.scope == "path"
    assert target.name == "Sales"
    assert target.type is None
    assert target.path is None


@pytest.mark.fab_test
def test_bare_name_with_type_is_a_typed_filter_not_a_path():
    """Sales.SemanticModel with no separator filters by name and type, not location."""
    target = parse_target("Sales.SemanticModel")

    assert target.scope == "path"
    assert target.name == "Sales"
    assert target.type == "SemanticModel"
    assert target.path is None


@pytest.mark.fab_test
def test_absolute_windows_path_is_a_path_target():
    """A drive-letter path is unambiguously a location."""
    target = parse_target(r"C:\repo\src\Sales.Report")

    assert target.scope == "path"
    assert target.name == "Sales"
    assert target.type == "Report"
    assert target.path is not None


@pytest.mark.fab_test
def test_backslash_separator_is_recognized():
    """Windows separators parse the same as forward slashes."""
    target = parse_target(r"src\Sales.SemanticModel")

    assert target.scope == "path"
    assert target.name == "Sales"
    assert target.path is not None


# --------------------------------------------------------------------------- #
# Desktop scope
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_local_prefix_selects_a_desktop_instance():
    """local/Sales is the running-Desktop scheme, matching pql-test."""
    target = parse_target("local/Sales")

    assert target.scope == "desktop"
    assert target.name == "Sales"
    assert target.workspace is None
    assert target.path is None


@pytest.mark.fab_test
def test_local_prefix_is_case_insensitive():
    """Local/Sales and local/Sales mean the same thing."""
    assert parse_target("Local/Sales").scope == "desktop"


@pytest.mark.fab_test
def test_local_prefix_accepts_a_name_containing_spaces_and_parentheses():
    """Desktop model names are display names, not identifiers."""
    target = parse_target("local/OLS_Model (1)")

    assert target.scope == "desktop"
    assert target.name == "OLS_Model (1)"


@pytest.mark.fab_test
def test_explicit_relative_prefix_escapes_the_local_scheme():
    """./local/Sales addresses a directory named 'local', not a Desktop instance."""
    target = parse_target("./local/Sales")

    assert target.scope == "path"
    assert target.path is not None


# --------------------------------------------------------------------------- #
# Workspace scope
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_workspace_qualified_target():
    """The Fabric CLI form names a workspace, an item, and the item's type."""
    target = parse_target("SalesDev.Workspace/Sales.SemanticModel")

    assert target.scope == "workspace"
    assert target.workspace == "SalesDev"
    assert target.name == "Sales"
    assert target.type == "SemanticModel"
    assert target.path is None


@pytest.mark.fab_test
def test_workspace_and_item_names_may_contain_spaces():
    """Display names are not identifiers; spaces survive parsing intact."""
    target = parse_target("Sales Dev.Workspace/Quarterly Sales.Report")

    assert target.workspace == "Sales Dev"
    assert target.name == "Quarterly Sales"
    assert target.type == "Report"


@pytest.mark.fab_test
def test_workspace_suffix_is_case_insensitive():
    """.workspace and .Workspace are the same suffix."""
    assert parse_target("SalesDev.workspace/Sales.Report").scope == "workspace"


@pytest.mark.fab_test
def test_workspace_item_without_a_type_is_rejected():
    """A deployed item cannot be found by name alone, so the form is refused."""
    with pytest.raises(TargetError) as excinfo:
        parse_target("SalesDev.Workspace/Sales")

    assert "SemanticModel" in str(excinfo.value)


@pytest.mark.fab_test
def test_workspace_target_with_extra_segments_is_rejected():
    """Nested folder paths are not supported; fail rather than mis-parse."""
    with pytest.raises(TargetError):
        parse_target("SalesDev.Workspace/Folder/Sales.SemanticModel")


@pytest.mark.fab_test
def test_workspace_with_an_empty_name_is_rejected():
    """'.Workspace/Sales.Report' names no workspace."""
    with pytest.raises(TargetError):
        parse_target(".Workspace/Sales.Report")


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


@pytest.mark.fab_test
def test_unknown_type_suffix_lists_the_known_types():
    """A typo in the type suffix names every type fab-test knows."""
    with pytest.raises(TargetError) as excinfo:
        parse_target("Sales.SemmanticModel")

    message = str(excinfo.value)
    for known in artifact_types(Path.cwd()):
        assert known in message


@pytest.mark.fab_test
@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_target_is_rejected(blank):
    """An empty target is a caller error, not a silent match-everything."""
    with pytest.raises(TargetError):
        parse_target(blank)


@pytest.mark.fab_test
def test_raw_target_is_preserved_verbatim():
    """`raw` round-trips what the caller wrote, for error messages and run.json."""
    raw = "Sales Dev.Workspace/Sales.SemanticModel"

    assert parse_target(raw).raw == raw


@pytest.mark.fab_test
def test_surrounding_whitespace_is_ignored():
    """Shell quoting habits should not change the parse."""
    assert parse_target("  local/Sales  ").name == "Sales"


@pytest.mark.fab_test
def test_every_analyzer_glob_names_a_declared_type():
    """Replaces an equality assertion that enforced the wrong invariant.

    That test required the set of artifact types to equal the set of types
    an analyzer handles, which conflated two different questions and kept
    the type list pinned at two. A type exists because Fabric has it; an
    analyzer handles it because someone wrote a wrapper. The containment
    that does matter is this direction: an analyzer cannot claim a glob
    for a type the map has never heard of.
    """
    from fab_test.scripts.fab_test_registry import ANALYZER_REGISTRY

    from_globs = {
        glob.lstrip("*.") for glob, _description in ANALYZER_REGISTRY.values() if glob
    }

    assert from_globs <= set(artifact_types(Path.cwd()))


@pytest.mark.fab_test
def test_a_type_no_analyzer_handles_still_parses():
    """`Sales.Notebook` was rejected as unknown while the repository's own
    map declared Notebook. Parsing is not the place to refuse it."""
    target = parse_target("Sales.Notebook")

    assert target.name == "Sales"
    assert target.type == "Notebook"


@pytest.mark.fab_test
def test_the_type_list_comes_from_the_map_not_the_code():
    """A repository declaring a type this build predates can still name it."""
    root = Path(__file__).resolve().parent.parent

    assert len(artifact_types(root)) >= 9


@pytest.mark.fab_test
def test_rdl_type_suffix_parses_even_though_it_is_not_in_the_artifact_map():
    """Sales.rdl -- a paginated report is a flat file, not a
    NAME.PaginatedReport/ folder, so "rdl" is not a value in
    artifact-map.json the way "SemanticModel"/"Report" are. It still needs
    to parse as a typed target rather than raise "unknown artifact type"."""
    target = parse_target("Sales.rdl")

    assert target.name == "Sales"
    assert target.type == "rdl"
