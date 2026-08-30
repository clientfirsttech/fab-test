"""`fab-test skill`: print and install fab-test's own skill resource.

Ships the skill content inside the wheel (fab-test Skill Distribution
epic) so a consumer's harness config can never drift from the installed
CLI version by hand-copying a stale file. Follows `fab_test_admin._init`'s
"idempotent, never clobber a differing local copy without --force,
--dry-run reports the plan" pattern rather than inventing a new one.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from fabric_ci_cd_dataops import __version__ as _FAB_TEST_VERSION

from ._cli_utils import narrate
from ._fab_test_context import REPO_ROOT
from ._metadata import resolve_skill_md

# Where each harness reads its own instructions from. Claude Code keeps
# fab-test's own SKILL.md shape unchanged; Copilot has no "skill" concept,
# so the closest one-file-per-topic equivalent is a scoped instructions
# file (`.github/instructions/*.instructions.md`, `applyTo` glob instead
# of `name`/`description`).
_HARNESS_TARGETS: dict[str, Path] = {
    "claude": Path(".claude") / "skills" / "fab-test" / "SKILL.md",
    "copilot": Path(".github") / "instructions" / "fab-test.instructions.md",
}

# Present in the shared description text regardless of harness, so
# --uninstall can refuse to delete a file this command did not create
# without needing a second, harness-specific marker.
_OWNERSHIP_MARKER = "fab-test CLI reference for running Fabric artifact analyzers locally"


class SkillContentError(Exception):
    """Raised when a resolved SKILL.md cannot be adapted to a harness's shape.

    Only ever raised for a repo-override file (`.fab-test/skill/SKILL.md` or
    `.github/skills/fab-test/SKILL.md`) with no valid YAML frontmatter --
    the packaged copy is guarded against this by test_skill_resource.py.
    """


def _content_for_harness(harness: str, skill_content: str) -> str:
    """Adapt the authored SKILL.md frontmatter to the target harness's shape.

    Only Copilot needs a rewrite: its instructions files use `applyTo`
    instead of `name`, so the frontmatter is rebuilt around the same
    description and body rather than shipped as a Claude-shaped skill file.
    """
    if harness != "copilot":
        return skill_content
    parts = skill_content.split("---", 2)
    if len(parts) != 3:
        raise SkillContentError(
            "the resolved SKILL.md has no YAML frontmatter (expected two "
            "'---' delimiters) -- cannot build a Copilot instructions file from it"
        )
    _, frontmatter, body = parts
    descriptions = [
        line.split(":", 1)[1].strip()
        for line in frontmatter.splitlines()
        if line.startswith("description:")
    ]
    if not descriptions:
        raise SkillContentError("the resolved SKILL.md's frontmatter has no 'description:' line")
    # Interpolated into a double-quoted YAML scalar below -- an embedded "
    # would otherwise close the string early and corrupt the frontmatter.
    description = descriptions[0].replace('"', "'")
    return f'---\napplyTo: "**"\ndescription: "{description}"\n---\n{body}'


def _installed_version(content: str) -> str | None:
    match = re.search(r"\(fab-test ([^)\s]+)\)", content)
    return match.group(1) if match else None


def _skill_status(harness: str) -> dict[str, str]:
    target = REPO_ROOT / _HARNESS_TARGETS[harness]
    if not target.is_file():
        return {"status": "missing", "path": str(target)}
    content = target.read_text(encoding="utf-8")
    installed_version = _installed_version(content)
    if installed_version is not None and installed_version != _FAB_TEST_VERSION:
        return {"status": "version_mismatch", "path": str(target), "version": installed_version}
    return {"status": "found", "path": str(target)}


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2))


def _skill_print(output_format: str, resolved) -> int:
    content = resolved.path.read_text(encoding="utf-8")
    if output_format == "json":
        _print_json({"version": _FAB_TEST_VERSION, "source_path": str(resolved.path), "content": content})
    else:
        print(content)
    return 0


def _skill_show(output_format: str) -> int:
    rows = {harness: _skill_status(harness) for harness in _HARNESS_TARGETS}
    if output_format == "json":
        _print_json(rows)
    else:
        for harness, row in rows.items():
            narrate(f"  {harness}: {row['status']} ({row['path']})", output_format=output_format)
    return 0


def _skill_install(harness: str, resolved, *, output_format: str, dry_run: bool, force: bool) -> int:
    target = REPO_ROOT / _HARNESS_TARGETS[harness]
    try:
        content = _content_for_harness(harness, resolved.path.read_text(encoding="utf-8"))
    except SkillContentError as exc:
        narrate(f"fab-test skill --install {harness}: {exc}", output_format=output_format)
        return 1
    existed_before = target.is_file()

    if existed_before and target.read_text(encoding="utf-8") == content:
        status = "unchanged"
    elif existed_before and not force:
        status = "differs"
    elif dry_run:
        status = "would_update" if existed_before else "would_create"
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        status = "updated" if existed_before else "created"

    payload = {"harness": harness, "path": str(target), "status": status}
    if output_format == "json":
        _print_json(payload)
    else:
        narrate(f"  fab-test skill --install {harness}: {status} ({target})", output_format=output_format)
    return 1 if status == "differs" else 0


def _skill_uninstall(harness: str | None, output_format: str) -> int:
    if harness is None:
        narrate(
            "fab-test skill --uninstall needs --install <harness>",
            output_format=output_format,
        )
        return 2

    target = REPO_ROOT / _HARNESS_TARGETS[harness]
    if not target.is_file():
        status = "missing"
    elif _OWNERSHIP_MARKER not in target.read_text(encoding="utf-8"):
        status = "not_fab_test_managed"
    else:
        target.unlink()
        status = "removed"

    payload = {"harness": harness, "path": str(target), "status": status}
    if output_format == "json":
        _print_json(payload)
    else:
        narrate(f"  fab-test skill --uninstall {harness}: {status} ({target})", output_format=output_format)
    return 1 if status == "not_fab_test_managed" else 0


def _skill(args: argparse.Namespace) -> int:
    """`fab-test skill`: print the resolved skill content, or install it.

    Bare, prints the repo-override-first resolved content (`--format
    json` wraps it with version/source metadata). `--install <harness>`
    writes or updates that harness's own copy; `--show` reports install
    state per harness; `--uninstall` (paired with `--install <harness>`)
    removes only a file this command's own marker text identifies as its.
    """
    output_format = getattr(args, "output_format", "text")

    if getattr(args, "uninstall", False):
        return _skill_uninstall(getattr(args, "install", None), output_format)
    if getattr(args, "show", False):
        return _skill_show(output_format)

    resolved = resolve_skill_md(REPO_ROOT)
    if not resolved.path.is_file():
        narrate(
            f"fab-test skill: resource missing at {resolved.path} -- reinstall fab-test",
            output_format=output_format,
        )
        return 1

    install = getattr(args, "install", None)
    if install:
        return _skill_install(
            install,
            resolved,
            output_format=output_format,
            dry_run=getattr(args, "dry_run", False),
            force=getattr(args, "force", False),
        )
    return _skill_print(output_format, resolved)
