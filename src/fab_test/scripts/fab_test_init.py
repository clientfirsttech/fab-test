"""`fab-test init`: scaffold a repository's fab-test files.

Moved out of fab_test_admin.py (2026-10-10) when init also took over the
root `.gitignore`: the admin module was at its 800-line budget, and init's
templates and file writes are a unit of their own.
"""

import argparse
import json
from pathlib import Path

from ._cli_utils import narrate
from ._config import CONFIG_FILENAME
from ._fab_test_context import REPO_ROOT
from ._rule_overlay import rdl_overlay_template
from .fab_test_registry import _DEFAULT_RDL_RULES

_FAB_TEST_YML_TEMPLATE = """\
# fab-test.yml -- optional config-file front door for the fab-test CLI.
#
# Every key below is entirely optional and commented out: an absent key
# falls back to its environment variable (where one exists) and then its
# packaged default. Uncomment and edit only the settings you want to pin.
#
# Precedence for every setting: CLI flag > environment variable >
# this file > packaged default. Run `fab-test config --show` to see the
# effective value and origin of each setting right now.

# artifact_dir: fabric-artifacts   # root to discover artifacts (repo root for `fab-test local`)
# output_dir: fab-test-results      # root for result envelopes and the run manifest
# jobs: 1                          # artifacts to run in parallel for the same analyzer
# format: text                     # text | json
# timeout: 200                     # per-artifact subprocess timeout in seconds [env: ANALYZER_TIMEOUT]
#                                   # (playwright scales this up on its own for a large matrix;
#                                   # setting this overrides that)
# verbosity: default               # summary | default | verbose | debug [env: ANALYZER_VERBOSITY]
#                                   # summary = -q (one line per artifact); -q/-v flags override this
# environment: DEV                 # default environment label [env: FABRIC_ENVIRONMENT]
# workspace: Sales Dev             # default workspace name or GUID [env: FABRIC_WORKSPACE_ID]
# playwright_user_name: analyst@contoso.com
#                                  # effective-identity UPN for RLS embed tokens
#                                  # [env: PLAYWRIGHT_USER_NAME]; only used for
#                                  # cases that carry a discovered role
# playwright_config: .fab-test/playwright.yml
#                                  # optional local/Azure YAML [env: PLAYWRIGHT_CONFIG_PATH]

# Rule overlays: deltas applied to a packaged ruleset instead of forking it.
# rules:
#   bpa:
#     disable: [RULE_ID]                  # remove a rule from the effective ruleset
#     severity: {RULE_ID: warning}        # info | warning | error
#     extend: path/to/extra-rules.json    # append rules from another file
#   pbir:
#     disable: [RULE_ID]
#     severity: {RULE_ID: warning}        # warning | error (PBIR Inspector has no "info" level)
{rdl_overlay}

# Ship analyzer telemetry to a Fabric Eventhouse and/or a Fabric Lakehouse.
# A configured destination is the enablement -- there is no separate on/off
# flag. Either, both, or neither section may be present.
# telemetry:
#   eventhouse:
#     uri: https://<cluster>.kusto.fabric.microsoft.com       # [env: EVENTHOUSE_URI]
#     database: <database-name>                               # [env: EVENTHOUSE_DATABASE]
#   lakehouse:
#     workspace: <workspace-name-or-guid>                     # [env: LAKEHOUSE_WORKSPACE]
#     lakehouse: <lakehouse-name>                              # [env: LAKEHOUSE_NAME]
"""
_FAB_TEST_YML_TEMPLATE = _FAB_TEST_YML_TEMPLATE.replace("{rdl_overlay}", rdl_overlay_template(Path(_DEFAULT_RDL_RULES)))

_ENV_EXAMPLE_TEMPLATE = """\
# .env.example -- copy to .fab-test/.env and fill in the values you need.
# Search order: --env-file > PLAYWRIGHT_ENV_FILE > .fab-test/.env > ./.env.
# Never commit the real .env -- .fab-test/.gitignore keeps this directory's
# copy untracked even though .fab-test/metadata/ is meant to be checked in.

# Service principal for Fabric/Power BI REST API access.
# All three are optional for local use: leave them unset to fall back to
# DefaultAzureCredential (az login, a managed identity, VS Code sign-in,
# ...) for every command except `fab-test playwright`, which always needs
# a full service principal to generate an embed token.
FABRIC_TENANT_ID=
FABRIC_CLIENT_ID=
FABRIC_CLIENT_SECRET=

# Playwright visual/error validation target. Only needed when not using
# --artifact to resolve a report from a deployed workspace.
PLAYWRIGHT_WORKSPACE_ID=
PLAYWRIGHT_REPORT_ID=
PLAYWRIGHT_REPORT_NAME=
PLAYWRIGHT_DATASET_ID=

# Effective-identity user (UPN) for models secured with row-level security.
# Required to test RLS: without it fab-test never discovers the model's roles
# or attaches an identity, and Power BI rejects the embed token with
# "requires effective identity". Harmless for models without RLS -- only cases
# that carry a discovered role use it. Can also be set as playwright_user_name
# in fab-test.yml.
# PLAYWRIGHT_USER_NAME=analyst@contoso.com

# Optional Azure browsers: enable access-token authentication in the workspace.
# Selected only by --playwright-config / PLAYWRIGHT_CONFIG_PATH / playwright_config.
# Keep the access token here or in protected CI secrets, never in execution YAML.
PLAYWRIGHT_SERVICE_URL=
PLAYWRIGHT_SERVICE_ACCESS_TOKEN=

# A paginated (RDL) report is validated with a different check than an
# interactive one -- skips page/bookmark/role discovery and checks for an
# error modal after a fixed wait rather than racing render events. With
# --artifact, fab-test detects which kind a target is itself (tries Report,
# then PaginatedReport) -- you should not normally need to set this. Set it
# to "report"/"paginated" only to force the type, or if using the static IDs
# above with no --artifact at all, where there is no name to detect from and
# this becomes required. A paginated report's dataset is often not
# auto-discoverable; set PLAYWRIGHT_DATASET_ID above if resolution reports
# "At least one dataset is required".
# PLAYWRIGHT_REPORT_TYPE=paginated
# PLAYWRIGHT_RENDER_WAIT_SECONDS=20

# Only needed when a report's dataset lives in a different workspace than the
# report itself -- common practice for a dataset shared across several
# reports. Leave unset when the dataset is in the report's own workspace.
# PLAYWRIGHT_DATASET_WORKSPACE_ID=
"""

_FAB_TEST_GITIGNORE_TEMPLATE = """\
# fab-test's own guard: .fab-test/metadata/ is meant to be checked in,
# but a .env in this directory holds credentials and never should be.
.env
"""


def _init(args: argparse.Namespace) -> int:
    """Scaffold a commented fab-test.yml, .fab-test/.gitignore, and
    .fab-test/.env.example, and add fab-test's folders to the root .gitignore.

    Never overwrites an existing file -- each is reported and left
    untouched instead. --dry-run reports what would be created without
    writing anything. `.fab-test/.env.example` replaces the root
    `.env.example` for new repositories: it lives beside the `.gitignore`
    that makes a real `.env` in the same directory safe to keep, rather
    than depending on a consumer's root `.gitignore` already covering it.
    """
    output_format = getattr(args, "output_format", "text")
    dry_run = getattr(args, "dry_run", False)
    fab_test_dir = REPO_ROOT / ".fab-test"
    templates = {
        REPO_ROOT / CONFIG_FILENAME: _FAB_TEST_YML_TEMPLATE,
        fab_test_dir / ".gitignore": _FAB_TEST_GITIGNORE_TEMPLATE,
        fab_test_dir / ".env.example": _ENV_EXAMPLE_TEMPLATE,
    }

    created = []
    would_create = []
    already_existed = []
    for path, template in templates.items():
        if path.exists():
            already_existed.append(str(path))
            narrate(
                f"  • fab-test init: already exists, left untouched: {path}",
                output_format=output_format,
            )
        elif dry_run:
            would_create.append(str(path))
            narrate(f"  fab-test init: would create {path}", output_format=output_format)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(template, encoding="utf-8")
            created.append(str(path))
            narrate(f"  ✓ fab-test init: created {path}", output_format=output_format)

    gitignore = _update_root_gitignore(REPO_ROOT / ".gitignore", dry_run=dry_run)
    _narrate_gitignore(gitignore, output_format)

    if output_format == "json":
        print(json.dumps(
            {
                "created": created,
                "would_create": would_create,
                "already_existed": already_existed,
                "gitignore": gitignore,
            },
            indent=2,
        ))
    return 0


# What a run creates at the repository root and nobody should commit:
# downloaded tool binaries, and per-run results and kept exports.
_ROOT_GITIGNORE_ENTRIES = (".fab-test-tools/", "fab-test-results/")
_ROOT_GITIGNORE_HEADER = "# fab-test: downloaded tools and run results (added by fab-test init)"


def _ignore_pattern(line: str) -> str:
    """A .gitignore line reduced to the folder it names, so `/fab-test-results`,
    `fab-test-results/` and `.fab-test-tools/**` all count as present."""
    return line.strip().removeprefix("/").removesuffix("/**").removesuffix("/")


def missing_gitignore_entries(text: str) -> list[str]:
    """Return the entries ``text`` doesn't already ignore, in a stable order."""
    present = {_ignore_pattern(line) for line in text.splitlines() if not line.lstrip().startswith("#")}
    return [entry for entry in _ROOT_GITIGNORE_ENTRIES if _ignore_pattern(entry) not in present]


def _update_root_gitignore(path: Path, *, dry_run: bool) -> dict[str, object]:
    """Append the missing entries to ``path``, creating it if absent.

    Only ever appends: a user's own rules, and the file's bytes up to its
    end, are never rewritten.
    """
    text = path.read_bytes().decode("utf-8") if path.exists() else ""
    missing = missing_gitignore_entries(text)
    if missing and not dry_run:
        eol = "\r\n" if "\r\n" in text else "\n"  # match the file's own line endings
        separator = eol if text and not text.endswith("\n") else ""
        spacer = eol if text else ""
        addition = separator + spacer + eol.join((_ROOT_GITIGNORE_HEADER, *missing)) + eol
        with path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(addition)
    return {"path": str(path), "added": [] if dry_run else missing, "would_add": missing if dry_run else []}


def _narrate_gitignore(result: dict[str, object], output_format: str) -> None:
    path, added, would_add = result["path"], result["added"], result["would_add"]
    if added:
        message = f"  ✓ fab-test init: added {', '.join(added)} to {path}"
    elif would_add:
        message = f"  fab-test init: would add {', '.join(would_add)} to {path}"
    else:
        message = f"  • fab-test init: {path} already ignores fab-test's folders"
    narrate(message, output_format=output_format)
