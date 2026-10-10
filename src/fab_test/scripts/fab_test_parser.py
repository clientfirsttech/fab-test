"""fab-test's argument parser.

Extracted from fab_test.py (Fab-Test Module Split epic): `build_parser` and
its subparser builders were, by themselves, larger than most of the modules
this split produces. Pure move -- no behavior change; `fab-test --help`
stays byte-identical.
"""

import argparse
import difflib
import re

from fab_test import __version__ as _FAB_TEST_VERSION

from ._config import CONFIG_FILENAME
from ._fab_test_context import (
    _DEFAULT_SUBPROCESS_TIMEOUT,
    _PYPROJECT_CONFIG,
    ARTIFACT_ROOT,
    REPO_ROOT,
    RESULTS_ROOT,
)
from ._feature_flags import add_disabled_stubs
from ._service_flags import add_service_flags, add_workspace_flag
from .fab_test_registry import (
    _DEFAULT_A11Y_PATH,
    _DEFAULT_BPA_RULES,
    _DEFAULT_INSPECTOR_PATH,
    _DEFAULT_PBIR_RULES,
    _DEFAULT_RDL_RULES,
    _DEFAULT_TE_PATH,
)
from .fab_test_registry import (
    ANALYZER_REGISTRY as _ANALYZER_REGISTRY,
)
from .fab_test_registry import (
    HIDDEN_ANALYZERS as _HIDDEN_ANALYZERS,
)
from .playwright_validation.execution_config import add_execution_flags

_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _guid_type(value: str) -> str:
    """argparse type= validator for --workspace-id; empty (unset) is allowed."""
    if value and not _GUID_RE.match(value):
        raise argparse.ArgumentTypeError(
            f"'{value}' is not a valid GUID "
            "(expected format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)"
        )
    return value


class _ArtifactDirAction(argparse.Action):
    """Records that --artifact-dir was passed on the CLI, not defaulted.

    Playwright's workspace-wide discovery needs to tell "the caller typed
    the default path" from "nothing was passed" -- comparing the resolved
    value against the default string cannot do that (the default path is a
    perfectly valid explicit choice too).
    """

    def __call__(self, parser, namespace, values, option_string=None):  # noqa: ARG002 - argparse Action signature
        setattr(namespace, self.dest, values)
        namespace.artifact_dir_explicit = True


def _add_common_flags(
    parser: argparse.ArgumentParser,
    *,
    artifact_dir_default=ARTIFACT_ROOT,
    track_artifact_dir_explicit: bool = False,
) -> None:
    parser.add_argument(
        "--artifact-dir",
        default=str(_PYPROJECT_CONFIG.get("artifact_dir", artifact_dir_default)),
        metavar="DIR",
        action=_ArtifactDirAction if track_artifact_dir_explicit else "store",
        help="Root to discover artifacts under, recursively (default: the working directory)",
    )
    if track_artifact_dir_explicit:
        parser.set_defaults(artifact_dir_explicit=False)
    parser.add_argument(
        "--output-dir",
        default=str(_PYPROJECT_CONFIG.get("output_dir", RESULTS_ROOT)),
        metavar="DIR",
        help=f"Root for result envelopes (default: {RESULTS_ROOT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover and list matching artifacts without running any analyzer",
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        metavar="TARGET",
        help=(
            "Artifact to analyze: a path (./src/Sales.SemanticModel), a name "
            "(Sales or Sales.SemanticModel), local/NAME for a running Power BI "
            "Desktop instance, or WORKSPACE.Workspace/NAME.Type for a deployed item"
        ),
    )
    parser.add_argument(
        "--artifact",
        default=None,
        metavar="STEM",
        help="Deprecated alias for the TARGET argument; only analyze this stem",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        metavar="SECONDS",
        help=(
            "Per-artifact subprocess timeout in seconds "
            f"[env: ANALYZER_TIMEOUT, default: {_DEFAULT_SUBPROCESS_TIMEOUT}]. "
            "For playwright, setting this explicitly overrides fab-test's own "
            "case-count-scaled timeout (which otherwise raises the ceiling "
            "for a report with a large page/bookmark/role matrix)."
        ),
    )
    parser.add_argument(
        "--jobs",
        type=int,
        # None, not the config default, so a playwright execution YAML's `jobs` can tell an explicit flag apart.
        default=None,
        metavar="N",
        help="Run up to N artifacts in parallel for the same analyzer "
        "[playwright: execution YAML `jobs`; config: jobs; default: 1]",
    )
    verbosity_group = parser.add_mutually_exclusive_group()
    verbosity_group.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help=(
            "Increase output verbosity (one -v for per-finding detail, "
            "two -v for command + stdout/stderr; same as ANALYZER_VERBOSITY)"
        ),
    )
    verbosity_group.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Print the least output that still reports the result (same as ANALYZER_VERBOSITY=summary)",
    )
    report_group = parser.add_mutually_exclusive_group()
    report_group.add_argument(
        "--report",
        action="store_true",
        dest="report",
        default=None,
        help="Write a readable HTML report beside each result envelope",
    )
    report_group.add_argument(
        "--no-report",
        action="store_false",
        dest="report",
        help="Suppress HTML report generation (the default)",
    )
    parser.add_argument(
        "--open-report",
        action="store_true",
        dest="open_report",
        default=None,
        help=(
            "Open the produced HTML report/index in the default browser "
            "after the run; implies --report and is suppressed under CI "
            "[env: ANALYZER_OPEN_REPORT]"
        ),
    )
    telemetry_group = parser.add_mutually_exclusive_group()
    telemetry_group.add_argument(
        "--telemetry",
        action="store_true",
        dest="telemetry",
        default=None,
        help="Stream telemetry to Eventhouse when EVENTHOUSE_LOGGING is enabled",
    )
    telemetry_group.add_argument(
        "--no-telemetry",
        action="store_false",
        dest="telemetry",
        help="Suppress telemetry even when EVENTHOUSE_LOGGING is enabled",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default=_PYPROJECT_CONFIG.get("format", "text"),
        dest="output_format",
        help="Output format for aggregate summaries (default: text)",
    )


_SUBCOMMAND_ALIASES = {
    "pql-test": "pql_test",
    "pql_test": "pql_test",
    "pql-lint": "pql_lint",
    "pql_lint": "pql_lint",
}

# Canonical (hyphenated, displayed) subcommand name -> internal registry key,
# for the handful where they diverge. Result directories (fab-test-results/
# <key>/...) stay on the registry key so historical results remain readable.
_CANONICAL_TO_REGISTRY_KEY = {
    "pql-test": "pql_test",
    "pql-lint": "pql_lint",
}
_REGISTRY_KEY_TO_CANONICAL = {v: k for k, v in _CANONICAL_TO_REGISTRY_KEY.items()}


def _canonical_name(registry_key: str) -> str:
    """Return the canonical (hyphenated) display name for a registry key."""
    return _REGISTRY_KEY_TO_CANONICAL.get(registry_key, registry_key)


def _aliases_for(registry_key: str, canonical: str) -> list[str]:
    """Return every other accepted spelling for ``registry_key``."""
    return sorted(
        {
            alias
            for alias, key in _SUBCOMMAND_ALIASES.items()
            if key == registry_key and alias != canonical
        }
    )


_COMMON_COMPLETION_FLAGS = (
    "--artifact-dir --output-dir --dry-run --artifact --timeout --jobs "
    "-v --verbose --telemetry --no-telemetry --format --help"
)


def _completion_subcommands() -> str:
    return " ".join(
        (
            *(_canonical_name(name) for name in _ANALYZER_REGISTRY),
            "all",
            "clean-tools",
            "help",
        )
    )


def _generate_completion_script(shell: str) -> str:
    """Return a shell completion script that also completes artifact stems.

    Artifact stems are looked up from ``fabric-artifacts`` at *completion
    time* in the user's shell (not baked in here), so the list always
    reflects whatever directory they are tab-completing from.
    """
    subcommands = _completion_subcommands()
    if shell == "bash":
        return f"""\
_fab_test_completions() {{
    local cur prev
    COMPREPLY=()
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"

    if [[ ${{COMP_CWORD}} -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "{subcommands} --version --print-completion --help" -- "${{cur}}") )
        return 0
    fi

    if [[ "${{prev}}" == "--artifact" ]]; then
        local dir="fabric-artifacts"
        if [[ -d "${{dir}}" ]]; then
            local stems
            stems=$(for f in "${{dir}}"/*; do basename "$f" | sed 's/\\.[^.]*$//'; done | sort -u)
            COMPREPLY=( $(compgen -W "${{stems}}" -- "${{cur}}") )
        fi
        return 0
    fi

    if [[ "${{cur}}" == -* ]]; then
        COMPREPLY=( $(compgen -W "{_COMMON_COMPLETION_FLAGS}" -- "${{cur}}") )
    fi
}}
complete -F _fab_test_completions fab-test
"""
    return f"""\
#compdef fab-test

_fab_test() {{
    local -a subcommands
    subcommands=({subcommands})

    if (( CURRENT == 2 )); then
        compadd -a subcommands
        compadd -- --version --print-completion --help
        return
    fi

    if [[ "${{words[CURRENT-1]}}" == "--artifact" ]]; then
        local dir="fabric-artifacts"
        if [[ -d "${{dir}}" ]]; then
            local -a stems
            stems=($(for f in "${{dir}}"/*(N); do basename "$f" | sed 's/\\.[^.]*$//'; done | sort -u))
            compadd -a stems
        fi
        return
    fi

    compadd -- {_COMMON_COMPLETION_FLAGS}
}}

_fab_test
"""


class _PrintCompletionAction(argparse.Action):
    """argparse action that prints a completion script and exits, like --version."""

    def __call__(self, parser, namespace, values, option_string=None):  # noqa: ARG002 - argparse Action API
        print(_generate_completion_script(values))
        parser.exit()


class _FabTestParser(argparse.ArgumentParser):
    """Parser whose unknown-analyzer error names only the advertised commands.

    argparse renders `invalid choice` straight from the subparser table,
    which holds every alias spelling *and* the hidden analyzers — exactly
    the names the help listing works to keep off the surface (see
    HIDDEN_ANALYZERS). A wrong first word would otherwise be the one place
    that leaks them. The rewrite lists canonical spellings only, and points
    a near miss at what the caller probably meant.
    """

    #: Canonical, visible subcommand names, in the order they were declared.
    advertised_subcommands: tuple[str, ...] = ()
    #: Every accepted spelling, aliases and hidden names included, used only
    #: to match a typo — answering a direct question is not advertising.
    accepted_subcommands: tuple[str, ...] = ()

    def error(self, message: str):
        match = re.match(r"argument ANALYZER: invalid choice: '([^']*)'", message)
        if match and self.advertised_subcommands:
            message = self._unknown_analyzer_message(match.group(1))
        super().error(message)

    def _unknown_analyzer_message(self, name: str) -> str:
        close = difflib.get_close_matches(name, self.accepted_subcommands, n=1, cutoff=0.6)
        suggestion = ""
        if close:
            canonical = _canonical_name(_SUBCOMMAND_ALIASES.get(close[0], close[0]))
            suggestion = f"did you mean '{self.prog} {canonical}'? "
        return (
            f"unknown analyzer '{name}' -- {suggestion}"
            f"choose from {', '.join(self.advertised_subcommands)}"
        )


def _add_bpa_subparser(subs: argparse._SubParsersAction) -> None:
    bpa_p = subs.add_parser(
        "bpa",
        help="Tabular Editor Best Practice Analyzer (SemanticModel artifacts)",
    )
    _add_common_flags(bpa_p, track_artifact_dir_explicit=True)
    add_workspace_flag(bpa_p)
    add_service_flags(bpa_p)
    bpa_p.add_argument(
        "--tabular-editor-path",
        default=None,
        dest="tabular_editor_path",
        metavar="PATH",
        help=(
            "Path to TabularEditor.exe "
            f"[env: TABULAR_EDITOR_PATH, default: {_DEFAULT_TE_PATH}]"
        ),
    )
    bpa_p.add_argument(
        "--bpa-rules-path",
        default=_DEFAULT_BPA_RULES,
        dest="bpa_rules_path",
        metavar="PATH",
        help=f"BPA rules JSON file [default: {_DEFAULT_BPA_RULES}]",
    )

def _add_pbir_subparser(subs: argparse._SubParsersAction) -> None:
    pbir_p = subs.add_parser(
        "pbir",
        help="PBIR Inspector — static report analysis (Report artifacts)",
    )
    _add_common_flags(pbir_p, track_artifact_dir_explicit=True)
    add_workspace_flag(pbir_p)
    add_service_flags(pbir_p)
    pbir_p.add_argument(
        "--inspector-path",
        default=None,
        dest="inspector_path",
        metavar="PATH",
        help=(
            "Path to PBIR Inspector binary "
            f"[env: PBIR_INSPECTOR_PATH, default: {_DEFAULT_INSPECTOR_PATH}]"
        ),
    )
    pbir_p.add_argument(
        "--rules-path",
        default=_DEFAULT_PBIR_RULES,
        dest="rules_path",
        metavar="PATH",
        help=f"PBIR Inspector rules JSON [default: {_DEFAULT_PBIR_RULES}]",
    )

def _add_a11y_subparser(subs: argparse._SubParsersAction) -> None:
    a11y_p = subs.add_parser(
        "a11y",
        help="pbir-a11y — accessibility checks (Report artifacts)",
    )
    _add_common_flags(a11y_p, track_artifact_dir_explicit=True)
    add_workspace_flag(a11y_p)
    add_service_flags(a11y_p)
    a11y_p.add_argument(
        "--a11y-path",
        default=None,
        dest="a11y_path",
        metavar="PATH",
        help=(
            "Path to pbir-a11y's built CLI entry point (dist/cli.js) "
            f"[env: PBIR_A11Y_PATH, default: {_DEFAULT_A11Y_PATH}]"
        ),
    )
    a11y_p.add_argument(
        "--fail-on",
        default=None,
        dest="fail_on",
        metavar="SEVERITY",
        help="Forwarded to pbir-a11y's own --fail-on (warn|fail; tool default: fail)",
    )


def _add_pql_test_subparser(subs: argparse._SubParsersAction) -> None:
    pql_test_p = subs.add_parser(
        "pql-test",
        aliases=["pql_test"],
        help="pql-test DAX/PQL test runner (SemanticModel artifacts)",
    )
    _add_common_flags(pql_test_p)
    add_workspace_flag(pql_test_p, aliases=False, dest="service_workspace")
    add_service_flags(pql_test_p)
    pql_test_p.add_argument(
        "--workspace-id",
        default="",
        dest="workspace_id",
        metavar="ID",
        type=_guid_type,
        help="Fabric workspace ID [env: FABRIC_WORKSPACE_ID]",
    )
    pql_test_p.add_argument(
        "--env",
        default="",
        dest="environment",
        metavar="ENV",
        help="Environment label (e.g. DEV, PROD, ANY) [env: FABRIC_ENVIRONMENT]",
    )

def _add_pql_lint_subparser(subs: argparse._SubParsersAction) -> None:
    pql_lint_p = subs.add_parser(
        "pql-lint",
        aliases=["pql_lint"],
        # Omitting `help` (rather than passing argparse.SUPPRESS, which
        # renders a literal "==SUPPRESS==" line) keeps this out of the
        # subcommand listing while leaving it fully invocable. See
        # HIDDEN_ANALYZERS. Its own --help still works via `description`.
        description="pqlint Power Query linter (SemanticModel artifacts)",
    )
    _add_common_flags(pql_lint_p)


def _add_rdl_subparser(subs: argparse._SubParsersAction) -> None:
    rdl_p = subs.add_parser(
        "rdl",
        help="RDL static analysis — performance/correctness/a11y rules (.rdl files)",
    )
    _add_common_flags(rdl_p, track_artifact_dir_explicit=True)
    add_workspace_flag(rdl_p)
    add_service_flags(rdl_p)
    # dest is rdl_rules_path, not the more obvious rules_path: the `all`
    # subparser already defines a top-level --rules-path/rules_path
    # dedicated to pbir (mirrors --bpa-rules-path/bpa_rules_path for bpa).
    # Reusing that name here would make `fab-test all` silently hand rdl
    # pbir's own resolved rules path instead of its own -- found live via
    # `fab-test all --report`, whose rdl report showed PBIR Inspector's
    # rule catalog (RULE_TEMPLATE, ENSURE_ALTTEXT, ...) instead of rdl's.
    rdl_p.add_argument(
        "--rules-path",
        default=_DEFAULT_RDL_RULES,
        dest="rdl_rules_path",
        metavar="PATH",
        help=f"RDL rules JSON [default: {_DEFAULT_RDL_RULES}]",
    )


def _add_playwright_subparser(subs: argparse._SubParsersAction) -> None:
    playwright_p = subs.add_parser(
        "playwright",
        help="Playwright visual/error validation (Report artifacts)",
    )
    _add_common_flags(playwright_p, track_artifact_dir_explicit=True)
    playwright_p.add_argument(
        "--env-file",
        default=None,
        dest="playwright_env_file",
        metavar="PATH",
        help="Path to .env file with report and credential settings",
    )
    playwright_p.add_argument(
        "--impact-manifest",
        default=None,
        dest="impact_manifest",
        metavar="PATH",
        # Kept for pipelines built on the retired `playwright-impact` command;
        # --changed-since replaces it.
        help=argparse.SUPPRESS,
    )
    playwright_p.add_argument(
        "--changed-since",
        default="",
        dest="changed_since",
        metavar="REF",
        help=(
            "With --workspace, test only the deployed reports built on a semantic model "
            "changed since this Git branch, tag or commit, or themselves changed "
            "(committed, uncommitted or new)"
        ),
    )
    playwright_p.add_argument(
        "--workspace",
        "--workspace-id",
        "--from-workspace",
        default="",
        dest="workspace_id",
        metavar="NAME_OR_ID",
        help=(
            "Workspace name or GUID [env: FABRIC_WORKSPACE_ID]; --workspace-id and "
            "--from-workspace are accepted as aliases, prefer --workspace. Standalone, "
            "with no --artifact and no explicit --artifact-dir, tests every Report and "
            "PaginatedReport deployed in the workspace instead of scanning the repository"
        ),
    )
    playwright_p.add_argument(
        "--env",
        default="",
        dest="environment",
        metavar="ENV",
        help="Environment label (e.g. DEV, PROD, ANY) [env: FABRIC_ENVIRONMENT]",
    )
    playwright_p.add_argument(
        "--dataset-id",
        default="",
        dest="dataset_id",
        metavar="ID",
        help=(
            "Semantic model / dataset ID. With --artifact, overrides that "
            "report's binding; with no report named, tests every report "
            "built on this dataset"
        ),
    )
    playwright_p.add_argument(
        "--dataset-workspace-id",
        default="",
        dest="dataset_workspace_id",
        metavar="ID",
        help=(
            "Workspace ID the dataset lives in, when different from the "
            "report's own workspace [env: PLAYWRIGHT_DATASET_WORKSPACE_ID]"
        ),
    )
    playwright_p.add_argument(
        "--report-type",
        choices=["report", "paginated"],
        default="",
        dest="report_type",
        help=(
            "Force the report type instead of auto-detecting it (a local "
            "*.Report/*.PaginatedReport folder's own suffix decides it "
            "automatically; --artifact with no local match tries Report "
            "then PaginatedReport) [env: PLAYWRIGHT_REPORT_TYPE]"
        ),
    )
    playwright_p.add_argument(
        "--report-parameters",
        default="",
        dest="report_parameters",
        metavar="JSON",
        help=(
            "Force the paginated report's declared parameters instead of "
            "deriving them from a local .rdl file's own <ReportParameters> "
            "block, as a JSON list of {\"name\": ..., \"multi_value\": ...} "
            "[internal: set by fab-test's own discovery]"
        ),
    )
    playwright_p.add_argument(
        "--plan-only",
        action="store_true",
        dest="plan_only",
        help=(
            "Show what would be tested: discover the page/bookmark/role "
            "matrix, write test-cases.csv/json, and stop without minting an "
            "embed token or launching a browser. Unlike --dry-run, which "
            "only lists matching artifacts, this resolves each one"
        ),
    )
    playwright_p.add_argument(
        "--pages",
        choices=["auto", "none"],
        default="auto",
        dest="pages",
        help=(
            "Discover every report page and its own bookmarks by default. "
            "'none' tests only the default page (default: auto)"
        ),
    )
    playwright_p.add_argument(
        "--roles",
        choices=["auto", "none"],
        default="auto",
        dest="roles",
        help=(
            "Discover RLS/OLS roles and test the page matrix under each one "
            "when RLS is enabled. 'none' tests only PLAYWRIGHT_ROLE "
            "(default: auto)"
        ),
    )
    playwright_p.add_argument(
        "--user-name",
        default="",
        dest="user_name",
        metavar="UPN",
        help=(
            "Effective-identity user (UPN) for RLS embed tokens. Overrides "
            "PLAYWRIGHT_USER_NAME and playwright_user_name in fab-test.yml"
        ),
    )
    add_execution_flags(playwright_p)

def _add_dependencies_subparser(subs: argparse._SubParsersAction) -> None:
    deps_p = subs.add_parser(
        "dependencies",
        help="Discover reports that depend on a deployed semantic model",
    )
    _add_common_flags(deps_p)
    deps_p.add_argument(
        "--semantic-model",
        required=True,
        dest="semantic_model",
        metavar="NAME",
        help="Name of the deployed semantic model",
    )
    deps_p.add_argument(
        "--env-file",
        default=None,
        dest="playwright_env_file",
        metavar="PATH",
        help="Path to .env file with service principal credentials",
    )
    deps_p.add_argument(
        "--output",
        default=None,
        dest="output_path",
        metavar="PATH",
        help="Path to write JSON dependency manifest",
    )
    deps_p.add_argument(
        "--workspace-id",
        default="",
        dest="workspace_id",
        metavar="ID",
        type=_guid_type,
        help="Fabric workspace ID [env: FABRIC_WORKSPACE_ID]",
    )
    deps_p.add_argument(
        "--env",
        default="",
        dest="environment",
        metavar="ENV",
        help="Environment label (e.g. DEV, PROD, ANY) [env: FABRIC_ENVIRONMENT]",
    )

def _add_all_subparser(subs: argparse._SubParsersAction) -> None:
    all_p = subs.add_parser("all", help="Run all analyzers in sequence")
    _add_common_flags(all_p, track_artifact_dir_explicit=True)
    all_p.add_argument(
        "--tabular-editor-path",
        default=None,
        dest="tabular_editor_path",
        metavar="PATH",
    )
    all_p.add_argument(
        "--bpa-rules-path",
        default=_DEFAULT_BPA_RULES,
        dest="bpa_rules_path",
        metavar="PATH",
    )
    all_p.add_argument(
        "--inspector-path",
        default=None,
        dest="inspector_path",
        metavar="PATH",
    )
    all_p.add_argument(
        "--rules-path",
        default=_DEFAULT_PBIR_RULES,
        dest="rules_path",
        metavar="PATH",
    )
    all_p.add_argument(
        "--rdl-rules-path",
        default=_DEFAULT_RDL_RULES,
        dest="rdl_rules_path",
        metavar="PATH",
    )
    add_workspace_flag(all_p)
    add_service_flags(all_p)
    all_p.add_argument(
        "--env",
        default="",
        dest="environment",
        metavar="ENV",
    )
    all_p.add_argument(
        "--playwright-env-file",
        default=None,
        dest="playwright_env_file",
        metavar="PATH",
        help="Path to .env file for Playwright validation",
    )

def _add_auth_subparser(subs: argparse._SubParsersAction) -> None:
    auth_p = subs.add_parser(
        "auth",
        help="Report or acquire Fabric credentials (fab-test stores none of its own)",
    )
    auth_subs = auth_p.add_subparsers(dest="auth_command", metavar="COMMAND")
    auth_subs.required = True
    auth_status_p = auth_subs.add_parser(
        "status",
        help="Show which identity fab-test would use, verifying it for real",
    )
    auth_status_p.add_argument(
        "--workspace-id",
        default="",
        dest="workspace_id",
        metavar="ID",
        help="Check whether this workspace is reachable [env: FABRIC_WORKSPACE_ID]",
    )
    auth_status_p.add_argument(
        "--env-file",
        default=None,
        dest="playwright_env_file",
        metavar="PATH",
        help="Path to a .env file holding credentials",
    )
    auth_status_p.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        dest="output_format",
        help="Output format (default: text)",
    )
    auth_login_p = auth_subs.add_parser(
        "login",
        help="Delegate sign-in to the tool that owns the credential",
    )
    auth_login_p.add_argument(
        # Deliberately NOT --environment: in fab-test, --env is the test
        # environment label (DEV/PROD). pql-test spells the Azure cloud
        # --environment, and merging the two names would be a trap.
        "--cloud",
        default="public",
        choices=["public", "USGov", "USGovHigh", "USGovDoD", "Germany", "China"],
        help="Azure cloud to sign in to (default: public)",
    )
    auth_login_p.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        dest="output_format",
        help="Output format (default: text)",
    )

def _add_local_subparser(subs: argparse._SubParsersAction) -> None:
    local_p = subs.add_parser(
        "local",
        help=(
            # Deliberately not enumerated: the bundle includes the hidden
            # pql-lint, and naming only the visible members would be
            # incomplete rather than merely brief. `local --dry-run` lists
            # exactly what would run.
            "Run the local analyzer bundle "
            "against every discovered .pbip project -- no cloud required"
        ),
    )
    _add_common_flags(local_p, artifact_dir_default=REPO_ROOT)
    local_p.add_argument(
        "--tabular-editor-path", default=None, dest="tabular_editor_path", metavar="PATH",
    )
    local_p.add_argument(
        "--bpa-rules-path", default=_DEFAULT_BPA_RULES, dest="bpa_rules_path", metavar="PATH",
    )
    local_p.add_argument(
        "--inspector-path", default=None, dest="inspector_path", metavar="PATH",
    )
    local_p.add_argument(
        "--rules-path", default=_DEFAULT_PBIR_RULES, dest="rules_path", metavar="PATH",
    )

def _add_clean_tools_subparser(subs: argparse._SubParsersAction) -> None:
    clean_tools_p = subs.add_parser(
        "clean-tools",
        help="Remove or inspect the .fab-test-tools downloaded-binary cache",
    )
    clean_tools_p.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be removed without deleting anything",
    )


def _add_doctor_subparser(subs: argparse._SubParsersAction) -> None:
    doctor_p = subs.add_parser(
        "doctor",
        help="Check whether each analyzer's prerequisites are ready to run",
    )
    doctor_p.add_argument(
        "--format",
        choices=["text", "json"],
        default=_PYPROJECT_CONFIG.get("format", "text"),
        dest="output_format",
        help="Output format for the readiness report (default: text)",
    )
    doctor_p.add_argument(
        "--analyzer",
        dest="analyzer_filter",
        default=None,
        metavar="NAME",
        help="Only check this analyzer",
    )
    doctor_p.add_argument(
        "--local",
        action="store_true",
        help="Check prerequisites for the local Desktop workflow (fab-test local)",
    )

def _add_config_subparser(subs: argparse._SubParsersAction) -> None:
    config_p = subs.add_parser(
        "config",
        help="Show effective configuration and where each setting came from",
    )
    config_p.add_argument(
        "--show",
        action="store_true",
        help="Print every effective setting with its value and origin",
    )
    config_p.add_argument(
        "--validate",
        action="store_true",
        help="Confirm the config file's keys and types are valid, and exit",
    )
    config_p.add_argument(
        "--format",
        choices=["text", "json"],
        default=_PYPROJECT_CONFIG.get("format", "text"),
        dest="output_format",
        help="Output format for the settings report (default: text)",
    )

def _add_init_subparser(subs: argparse._SubParsersAction) -> None:
    init_p = subs.add_parser(
        "init",
        help="Scaffold a commented fab-test.yml and .env.example",
    )
    init_p.add_argument(
        "--format",
        choices=["text", "json"],
        default=_PYPROJECT_CONFIG.get("format", "text"),
        dest="output_format",
        help="Output format for the scaffold report (default: text)",
    )
    init_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be created without writing anything",
    )

def _add_skill_subparser(subs: argparse._SubParsersAction) -> None:
    skill_p = subs.add_parser(
        "skill",
        help="List fab-test's own skill resource, print one by name, or install it into an agent harness",
    )
    skill_p.add_argument(
        "name",
        nargs="?",
        default=None,
        help="'fab-test' or a reference topic (e.g. 'flags') to print; omit to list them",
    )
    skill_p.add_argument(
        "--install",
        choices=["claude", "copilot"],
        default=None,
        help="Write/update this harness's copy of the skill content",
    )
    skill_p.add_argument(
        "--show",
        action="store_true",
        help="Report install state (found/missing/version_mismatch) per harness",
    )
    skill_p.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove the file --install <harness> created, if fab-test owns it",
    )
    skill_p.add_argument(
        "--dry-run",
        action="store_true",
        help="With --install, report what would change without writing anything",
    )
    skill_p.add_argument(
        "--force",
        action="store_true",
        help="With --install, overwrite an existing file that differs",
    )
    skill_p.add_argument(
        "--format",
        choices=["text", "json"],
        default=_PYPROJECT_CONFIG.get("format", "text"),
        dest="output_format",
        help="Output format for the printed content or report (default: text)",
    )

def _add_list_subparser(subs: argparse._SubParsersAction) -> None:
    list_p = subs.add_parser(
        "list",
        help="List available analyzers with their artifact glob, matched count, and required tool",
    )
    list_p.add_argument(
        "--artifact-dir",
        default=str(_PYPROJECT_CONFIG.get("artifact_dir", ARTIFACT_ROOT)),
        metavar="DIR",
        help="Root to discover artifacts under, recursively (default: the working directory)",
    )
    list_p.add_argument(
        "--format",
        choices=["text", "json"],
        default=_PYPROJECT_CONFIG.get("format", "text"),
        dest="output_format",
        help="Output format for the capability report (default: text)",
    )

def _add_explain_subparser(subs: argparse._SubParsersAction) -> None:
    explain_p = subs.add_parser(
        "explain",
        help="Show the resolved command for one analyzer without running it",
    )
    explain_p.add_argument(
        "analyzer_name",
        metavar="ANALYZER",
        help="Analyzer to explain (e.g. bpa, pbir, pql_test)",
    )
    explain_p.add_argument(
        "target",
        nargs="?",
        default=None,
        metavar="TARGET",
        help="Optional target to resolve and explain (e.g. local/Sales)",
    )
    add_workspace_flag(explain_p)
    explain_p.add_argument(
        "--artifact-dir",
        default=str(_PYPROJECT_CONFIG.get("artifact_dir", ARTIFACT_ROOT)),
        metavar="DIR",
        help="Root to discover artifacts under, recursively (default: the working directory)",
    )
    explain_p.add_argument(
        "--output-dir",
        default=str(_PYPROJECT_CONFIG.get("output_dir", RESULTS_ROOT)),
        metavar="DIR",
        help=f"Root for result envelopes (default: {RESULTS_ROOT})",
    )
    explain_p.add_argument(
        "--artifact",
        default=None,
        metavar="STEM",
        help="Explain the command for the artifact whose stem matches STEM",
    )
    explain_p.add_argument(
        "--format",
        choices=["text", "json"],
        default=_PYPROJECT_CONFIG.get("format", "text"),
        dest="output_format",
        help="Output format for the explanation (default: text)",
    )

def _add_help_subparser(subs: argparse._SubParsersAction) -> None:
    help_p = subs.add_parser(
        "help",
        help="Show this help, or one analyzer's help (fab-test help bpa)",
    )
    help_p.add_argument(
        "help_topic",
        nargs="?",
        default=None,
        metavar="ANALYZER",
        help="Analyzer or command to show help for (e.g. bpa, doctor)",
    )


# One function per subcommand group, in the order each appears in --help.
_SUBPARSER_BUILDERS = (
    _add_bpa_subparser,
    _add_pbir_subparser,
    _add_a11y_subparser,
    _add_pql_test_subparser,
    _add_pql_lint_subparser,
    _add_rdl_subparser,
    _add_playwright_subparser,
    _add_dependencies_subparser,
    _add_all_subparser,
    _add_auth_subparser,
    _add_local_subparser,
    _add_clean_tools_subparser,
    _add_doctor_subparser,
    _add_config_subparser,
    _add_init_subparser,
    _add_skill_subparser,
    _add_list_subparser,
    _add_explain_subparser,
    _add_help_subparser,
)


def build_parser() -> argparse.ArgumentParser:
    parser = _FabTestParser(
        prog="fab-test",
        description=(
            "Run Fabric artifact analyzers locally.\n\n"
            "fab-test tests your Fabric artifacts — it is NOT pytest.\n"
            "  pytest -m bpa      tests the BPA wrapper (always green)\n"
            "  fab-test bpa       runs BPA against your actual Fabric artifacts"
        ),
        epilog=(
            "Exit codes:\n"
            "  0    All artifacts passed (warnings do not fail the build)\n"
            "  1    An analyzer found error-level findings, or the analyzer process crashed\n"
            "  2    Invalid CLI arguments (no analyzer was invoked)\n"
            "  126  Analyzer unsupported on this platform (see message for the supported OS)\n"
            "  127  Required external tool could not be resolved (see message for the fix)\n\n"
            f"Version: {_FAB_TEST_VERSION} | "
            "Docs: https://github.com/clientfirsttech/fab-test/blob/main/docs/QUICK-VALIDATION.md"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version=f"%(prog)s {_FAB_TEST_VERSION}",
        help="Show fab-test version and exit",
    )
    parser.add_argument(
        "--print-completion",
        choices=["bash", "zsh"],
        action=_PrintCompletionAction,
        help="Print a shell completion script for bash or zsh and exit",
    )
    parser.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help=f"Path to a config file (default: discover {CONFIG_FILENAME} at the repository root)",
    )

    subs = parser.add_subparsers(dest="analyzer", metavar="ANALYZER")
    subs.required = True

    for add_subparser in _SUBPARSER_BUILDERS:
        add_subparser(subs)
    stubs = add_disabled_stubs(subs)

    # Read back from the subparser table rather than maintained by hand, so
    # a new subcommand cannot be added without the error message learning
    # about it. Feature-flag stubs are never suggested.
    accepted = tuple(name for name in subs.choices if name not in stubs)
    parser.accepted_subcommands = accepted
    parser.advertised_subcommands = tuple(
        dict.fromkeys(
            _canonical_name(_SUBCOMMAND_ALIASES.get(name, name))
            for name in accepted
            if _SUBCOMMAND_ALIASES.get(name, name) not in _HIDDEN_ANALYZERS
        )
    )

    return parser
