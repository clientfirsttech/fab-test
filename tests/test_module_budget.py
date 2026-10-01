"""A ratchet on file-level size budgets (Test Module Split epic, task 4).

Scope
-----
[aidd-module-budgets](../.github/skills/aidd-module-budgets/SKILL.md) set
file-level budgets that nothing in this repo measured before this epic:
source modules soft 400 / hard 800, test modules soft 500 / hard 900.
`tests/test_fab_test.py` crossed the hard test budget at 4,383 lines before
anyone noticed, one epic section at a time -- the same shape
`test_complexity_budget.py` already solved for complexity findings: a
non-gating report in `build.yml` for the soft budget, and a hard failure
here for anything that would make the next file unreviewable the same way.

A file already over its hard budget when this ratchet was written is not
silently re-permitted by a raised number -- it is named here, with the date
and the reason it isn't being split in this commit, so grepping this file
tells you every file this repo has already agreed to carry debt on.
"""

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent

SOURCE_SOFT = 400
SOURCE_HARD = 800
TEST_SOFT = 500
TEST_HARD = 900

# path (relative to repo root) -> (line count when exempted, reason).
# The recorded count is the ceiling: growing past it needs a new entry (or a
# split), not a silent pass. Shrinking well below it is slack -- the
# exemption should be tightened or dropped, matching
# test_the_ceiling_is_not_left_slack_after_a_cleanup in
# test_complexity_budget.py.
EXEMPTIONS: dict[str, tuple[int, str]] = {
    "src/fab_test/scripts/_rdl_lint.py": (
        881,
        (
            "2026-09-30: +9 lines for rule status (_is_active; planned rules neither run nor show). "
            "2026-09-30: +31 lines of location breadcrumbs (_parents, _location) and the real-shape QRY-04 check (RDL Finding Clarity epic; Tier B work should split the module as noted below). "
            "2026-09-30: +7 lines of finding breadcrumbs (_snippet, _filter_text) so messages quote the offender (RDL Finding Clarity epic). "
            "2026-09-30: +2 lines carrying a rule's source_urls onto its findings and test_results rows. "
            "2026-09-27: born over the hard budget adding ACC-01/02/03/08, "
            "the eighth and final Tier A rule-implementation task in the RDL "
            "Static Analysis epic -- 28 check functions across six rule "
            "families (structure/data-source, query, parameters, layout/"
            "subreport, accessibility), one function per rule ID, the same "
            "shape fab_test_parser.py's own exemption already argues for "
            "('one function per subcommand keeps each piece small; "
            "splitting the module further would cut across that seam rather "
            "than with it'). Growth here is bounded within this epic: Tier B "
            "and Tier C rules (plan/rdl-rule-set.md) are explicitly out of "
            "scope, and the remaining epic task (documentation) adds no "
            "code. If a future epic implements Tier B/C rules and this file "
            "keeps growing, split then along the same family lines "
            "tests/_rdl_lint_fixtures.py and tests/test_rdl_lint_*.py "
            "already use -- one _rdl_checks_<family>.py per family, "
            "_rdl_lint.py keeping only the core engine (RDL Static Analysis "
            "epic)."
        ),
    ),
    "src/fab_test/scripts/fab_test_parser.py": (
        1079,
        (
            "2026-09-27: +16 lines adding _add_rdl_subparser -- one more "
            "subcommand builder, same shape as every other one already here "
            "(_add_pql_lint_subparser is its closest model: no external-tool "
            "path flag, just --rules-path like _add_pbir_subparser's). "
            "+13 lines adding --rdl-rules-path to _add_all_subparser, "
            "dest=rdl_rules_path -- found live that reusing pbir's own "
            "--rules-path/rules_path name here made `fab-test all` hand rdl "
            "pbir's resolved rules path instead of its own, since that name "
            "already defaults to _DEFAULT_PBIR_RULES on the `all` subparser; "
            "this mirrors --bpa-rules-path/bpa_rules_path, bpa's own "
            "dedicated flag for the same reason "
            "(RDL Static Analysis epic). "
            "2026-08-31: +11 lines adding a `name` positional and --list to "
            "the skill subparser, so `fab-test skill` can list known skills "
            "and print one by name (fab-test Skill Listing). "
            "2026-08-31: +12 lines adding --report-parameters to the "
            "playwright subparser, an internal override for the JSON list "
            "of report parameters otherwise derived from a local .rdl "
            "file's own <ReportParameters> block (Paginated Report "
            "Parameter Testing epic). "
            "2026-08-31: +12 lines adding --report-type to the playwright "
            "subparser, an explicit override for report-type auto-detection "
            "(Playwright Report Type Auto-Detection epic). "
            "2026-08-31: +10 lines adding --dataset-workspace-id to the "
            "playwright subparser, for a dataset that lives in a different "
            "workspace than its report -- common practice for a dataset "
            "shared across several reports (Paginated Report Testing epic, "
            "live-verification fix). "
            "2026-08-28: born over the hard budget by the move itself -- "
            "build_parser's 17 subparser builders were, together, larger than "
            "most modules this split produces even before the move (see "
            "tasks/fab-test-module-split-epic.md, 'Extract the argument "
            "parser'). One function per subcommand keeps each piece small; "
            "splitting the module further would cut across that seam rather "
            "than with it. Revisit if it keeps growing. "
            "2026-08-29: +27 lines adding _add_a11y_subparser (PBIR "
            "Accessibility Integration epic, Analyzer Registration and "
            "Targeting task) -- one more subcommand builder, same shape as "
            "every other one already here. "
            "2026-08-30: +3 lines noting in --timeout's help text that "
            "playwright scales it automatically, and that setting this "
            "flag overrides that (Playwright Case Scaling epic). "
            "2026-08-30: +13 lines adding --workers to the playwright "
            "subparser, so the pytest-xdist worker cap is configurable "
            "(e.g. higher on a VM that can run more concurrent browser "
            "instances) rather than a fixed constant. "
            "2026-08-30: +40 lines adding _add_skill_subparser (`fab-test "
            "skill --install/--show/--uninstall/--dry-run/--force`, fab-test "
            "Skill Distribution epic) -- one more subcommand builder, same "
            "shape as every other one already here. "
            "2026-08-31: +11 lines adding --open-report to the shared "
            "common-flags block, alongside --report/--no-report (Open "
            "Report Flag epic, Task 1)."
        ),
    ),
    "src/fab_test/scripts/fab_test_summary.py": (
        925,
        (
            "2026-09-01: +5 net lines teaching the summary that an analyzer can "
            "exit 0 and still be warning us -- _artifact_status now reads a "
            "`warning` envelope as a warning instead of falling through to "
            "passed, and _artifact_summary_prefix takes the status so such a "
            "run gets its own icon rather than a green check (pql-test "
            "Connection-Failure Reporting epic, Task 4). Net of deleting "
            "_pql_test_status, a byte-identical twin of _analyzer_envelope's "
            "finding_status that the one-definition guard missed because the "
            "copy had been renamed. "
            "2026-08-23: 12 lines over hard, from unrelated feature work landing "
            "since this file was last at 793; not yet worth a forced split for "
            "12 lines. Revisit if it keeps growing. "
            "2026-08-31: +71 lines wiring --open-report into _print_all_summary "
            "(open the run index once) and _print_summary (open a single "
            "analyzer's sole report, or note when there are several with "
            "nothing single to open) -- Open Report Flag epic, Task 3. Split "
            "into _write_and_open_index/_open_single_analyzer_report to keep "
            "both callers under the branch budget (net new lines, not "
            "shrinkage, since the decision logic itself is unchanged). "
            "2026-08-31: +36 lines making _open_single_analyzer_report build and "
            "open a per-run index for a single analyzer's several artifacts, "
            "the same way _write_and_open_index does for `fab-test all` -- was "
            "printing a warning and opening nothing, which was the inconsistency "
            "reported for `fab-test a11y` with multiple artifacts. New "
            "_index_row_fields factors out the envelope-reading rules shared "
            "with build_all_summary_rows so both index shapes classify status "
            "identically."
        ),
    ),
    "src/fab_test/scripts/fab_test_registry.py": (
        1017,
        (
            "2026-09-27: +40 lines registering the rdl analyzer -- "
            "ANALYZER_REGISTRY/ANALYZER_SCOPES entries, _resolve_rdl_rules_path "
            "(mirrors _resolve_pbir_rules_path), build_rdl_command, and its "
            "_COMMAND_BUILDERS entry. Smaller than a11y's own registration "
            "(PBIR Accessibility Integration epic) because rdl wraps no "
            "external tool: no _BOOTSTRAPPED_ANALYZERS/_BOOTSTRAP_REGISTRY_NAME/"
            "_TOOL_FLAG_HINTS entry, and no explicit-path branch in "
            "resolve_tool/_readiness_without_version -- those already fall "
            "through to \"no external tool required\" for any analyzer absent "
            "from _BOOTSTRAPPED_ANALYZERS and _CLOUD_ANALYZERS (RDL Static "
            "Analysis epic). "
            "2026-08-31: +28 lines adding _report_parameters_for_command, "
            "which derives --report-parameters from a discovered .rdl "
            "file's own <ReportParameters> block when not given explicitly "
            "-- mirrors _dataset_override_for_command's shape (Paginated "
            "Report Parameter Testing epic). "
            "2026-08-31: +28 lines adding _dataset_override_for_command, "
            "which derives --dataset-id/--dataset-workspace-id from a "
            "discovered .rdl file's own PBIDATASET data source when neither "
            "was given explicitly -- the caller should never have to already "
            "know and supply a GUID fab-test can read out of a file already "
            "checked into the repository (Paginated Report RDL Data Source "
            "Resolution epic). "
            "2026-08-31: +27 lines adding _report_type_for_command, which "
            "derives --report-type for the subprocess from a discovered "
            "local folder's own suffix (or an explicit override), so the "
            "subprocess never has to ask Fabric something the outer CLI "
            "already knows (Playwright Report Type Auto-Detection epic). "
            "2026-08-31: +3 lines forwarding --dataset-workspace-id to "
            "invoke_playwright.py's subprocess command (Paginated Report "
            "Testing epic, live-verification fix). "
            "2026-08-23: 11 lines over hard, same story as fab_test_summary.py -- "
            "small drift from other epics, not yet worth a forced split. "
            "2026-08-24: +6 lines forwarding --pages/--roles to "
            "invoke_playwright (Playwright Test Matrix Discovery epic). "
            "2026-08-29: +12 lines splitting check_readiness's dict-merge into "
            "_readiness_without_version so every readiness branch (including "
            "_cloud_readiness's five returns) gets a uniform `version` key from "
            "one place, not five (Tool Version Currency epic). "
            "2026-08-29: +13 lines registering the `a11y` analyzer (hidden until "
            "its command builder lands) into ANALYZER_REGISTRY/ANALYZER_SCOPES/"
            "_BOOTSTRAPPED_ANALYZERS/_BOOTSTRAP_REGISTRY_NAME plus its explicit-path "
            "branch in resolve_tool and _readiness_without_version (PBIR "
            "Accessibility Integration epic, Node and pbir-a11y Readiness in "
            "Doctor task). "
            "2026-08-29: +30 lines adding build_a11y_command and "
            "_DEFAULT_A11Y_PATH, and registering it in _COMMAND_BUILDERS, "
            "removing it from HIDDEN_ANALYZERS now that its command builder "
            "and subparser exist (PBIR Accessibility Integration epic, "
            "Analyzer Registration and Targeting task). "
            "2026-08-30: +16 lines adding playwright_test_cases_dir, the "
            "single source of truth build_playwright_command and "
            "fab_test_execution.py's case-count-scaled timeout both need to "
            "agree on the same path (Playwright Case Scaling epic). "
            "2026-08-30: +3 lines forwarding --workers to invoke_playwright.py "
            "when explicitly set on the outer CLI."
        ),
    ),
    "src/fab_test/scripts/invoke_playwright.py": (
        929,
        (
            "2026-09-26: +9 lines replacing the `_SPEC_PATH = Path(\"tests\") / "
            "\"test_playwright_visual.py\"` constant with `_spec_path()`, resolved "
            "from the installed `render_spec` module's own file -- a `pip install "
            "fab-test` consumer has no checkout of this repository's tests/ "
            "directory, so every real run failed outright until the spec itself "
            "moved into the package (Playwright CI Guide epic, Render Spec "
            "Packaging task). "
            "2026-08-31: +11 lines adding --report-parameters and threading "
            "it into the resolved PlaywrightValidationConfig, so a "
            "paginated report's declared parameters reach the pytest spec "
            "even for a service-resolved (non-static-.env) run (Paginated "
            "Report Parameter Testing epic). "
            "2026-08-31: +8 lines resolving --dataset-workspace-id through "
            "resolve_workspace_id, since a value here may be a display name "
            "-- e.g. a .rdl file's own rd:PowerBIWorkspaceName -- rather "
            "than a GUID (Paginated Report RDL Data Source Resolution "
            "epic). "
            "2026-08-31: +19 lines adding --report-type as an explicit "
            "auto-detection override and using the resolved report's own "
            "report_type (never the pre-resolution \"auto\") for the final "
            "PlaywrightValidationConfig (Playwright Report Type "
            "Auto-Detection epic). "
            "2026-08-31: +11 lines adding --dataset-workspace-id and "
            "threading it into the service-resolved PlaywrightValidationConfig "
            "(Paginated Report Testing epic, live-verification fix). "
            "2026-08-30: born over the hard budget adding configurable "
            "pytest-xdist worker resolution (--workers/PLAYWRIGHT_XDIST_WORKERS "
            "> packaged default) -- a small, cohesive addition to an already "
            "large file, not worth a forced split for ~20 lines. Revisit if "
            "it keeps growing. "
            "2026-08-30: +47 lines adding _report_deep_link and threading "
            "cloud through _test_results_rows/_write_embed_error_envelope, so "
            "the HTML report can link back to the report page/bookmark a "
            "Playwright case validated (Report Page Deep Link work). "
            "2026-08-30: +4 lines threading report_type through the "
            "resolve_report call and the resulting PlaywrightValidationConfig "
            "so a paginated target resolves against PaginatedReport instead of "
            "Report (Paginated Report Testing epic)."
        ),
    ),
}

# How much headroom an exemption may carry before it should be tightened.
_EXEMPTION_SLACK_MARGIN = 40


def _budgets_for(path: Path) -> tuple[int, int]:
    """Return (soft, hard) for a file, based on which tree it lives under."""
    relative = path.relative_to(_ROOT).as_posix()
    if relative.startswith("tests/"):
        return TEST_SOFT, TEST_HARD
    return SOURCE_SOFT, SOURCE_HARD


@pytest.fixture(scope="module")
def _line_counts() -> dict[str, int]:
    """Line count for every tracked .py file, keyed by repo-relative posix path."""
    counts = {}
    for tree in ("src", "tests"):
        for path in (_ROOT / tree).rglob("*.py"):
            relative = path.relative_to(_ROOT).as_posix()
            counts[relative] = len(path.read_text(encoding="utf-8").splitlines())
    return counts


@pytest.mark.fab_test
def test_no_unexempted_file_exceeds_its_hard_budget(_line_counts):
    """Any file over its hard budget must be named in EXEMPTIONS, on purpose."""
    offenders = []
    for relative, count in _line_counts.items():
        if relative in EXEMPTIONS:
            continue
        _soft, hard = _budgets_for(_ROOT / relative)
        if count > hard:
            offenders.append(f"{relative}: {count} lines (hard budget {hard})")

    assert not offenders, (
        "file(s) exceed their hard budget with no exemption on record:\n"
        + "\n".join(offenders)
        + "\nSplit the file, or add a named, dated EXEMPTIONS entry with a reason."
    )


@pytest.mark.fab_test
def test_exempted_files_have_not_grown_past_their_recorded_size(_line_counts):
    """An exemption is a ceiling, not a blank check -- growing past it needs a new one."""
    grown = []
    for relative, (ceiling, _reason) in EXEMPTIONS.items():
        count = _line_counts.get(relative)
        assert count is not None, f"exempted file no longer exists: {relative}"
        if count > ceiling:
            grown.append(f"{relative}: {count} lines (exemption recorded at {ceiling})")

    assert not grown, (
        "exempted file(s) grew past their recorded ceiling:\n"
        + "\n".join(grown)
        + "\nUpdate the EXEMPTIONS entry with the new count and a reason for the growth."
    )


@pytest.mark.fab_test
def test_an_exemption_is_not_left_with_slack_after_a_cleanup(_line_counts):
    """A ceiling far above the real size stops being a ratchet.

    Mirrors test_the_ceiling_is_not_left_slack_after_a_cleanup in
    test_complexity_budget.py: a cleanup that shrinks an exempted file should
    be followed by tightening (or dropping) its exemption, not left to quietly
    carry stale headroom forever.
    """
    slack = []
    for relative, (ceiling, _reason) in EXEMPTIONS.items():
        count = _line_counts.get(relative, ceiling)
        if ceiling - count > _EXEMPTION_SLACK_MARGIN:
            slack.append(
                f"{relative}: exemption recorded at {ceiling} but file is now "
                f"{count} lines -- tighten the exemption to {count}"
            )

    assert not slack, "\n".join(slack)


@pytest.mark.fab_test
def test_every_exemption_still_needs_one(_line_counts):
    """An exemption for a file that no longer exceeds its hard budget is dead weight."""
    unnecessary = []
    for relative in EXEMPTIONS:
        count = _line_counts.get(relative)
        if count is None:
            continue
        _soft, hard = _budgets_for(_ROOT / relative)
        if count <= hard:
            unnecessary.append(f"{relative}: {count} lines is within the {hard} hard budget")

    assert not unnecessary, (
        "exemption(s) are no longer needed -- remove them from EXEMPTIONS:\n"
        + "\n".join(unnecessary)
    )
