"""`fab-test skill`: print and install fab-test's own skill resource.

Ships the skill content inside the wheel (fab-test Skill Distribution
epic) so a consumer's harness config can never drift from the installed
CLI version by hand-copying a stale file. The resource is a directory --
a main `SKILL.md` plus `references/*.md` (fab-test Skill Componentization
epic split the original single 1065-line file, too many tokens to load
for one subcommand's flags). Follows `fab_test_admin._init`'s "idempotent,
never clobber a differing local copy without --force, --dry-run reports
the plan" pattern rather than inventing a new one.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from fab_test import __version__ as _FAB_TEST_VERSION

from ._cli_utils import narrate
from ._fab_test_context import REPO_ROOT
from ._metadata import resolve_skill_dir

# Where each harness reads its own instructions from, and what its main
# entry file is named. Claude Code keeps fab-test's own directory shape
# (SKILL.md + references/) unchanged; Copilot has no "skill" concept, so
# the closest one-entry-point equivalent is a scoped instructions file
# (`.github/instructions/*.instructions.md`, `applyTo` glob instead of
# `name`/`description`) with the same references/ alongside it.
_HARNESS_BASE_DIRS: dict[str, Path] = {
    "claude": Path(".claude") / "skills" / "fab-test",
    "copilot": Path(".github") / "instructions" / "fab-test",
}
_MAIN_FILENAMES: dict[str, str] = {
    "claude": "SKILL.md",
    "copilot": "fab-test.instructions.md",
}

# Present in the shared description text regardless of harness, so
# --uninstall can refuse to delete a directory this command did not
# create without needing a second, harness-specific marker. Checked only
# against the main file -- reference files carry no frontmatter of their
# own to mark.
_OWNERSHIP_MARKER = "fab-test CLI reference for running Fabric artifact analyzers locally"


class SkillContentError(Exception):
    """Raised when the resolved main SKILL.md cannot be adapted to a harness's shape.

    Only ever raised for a repo-override file (`.fab-test/skill/SKILL.md` or
    `.github/skills/fab-test/SKILL.md`) with no valid YAML frontmatter --
    the packaged copy is guarded against this by test_skill_resource.py.
    """


def _component_relative_paths(resolved_dir: Path) -> list[Path]:
    """Return SKILL.md plus every references/*.md, relative to resolved_dir."""
    paths = [Path("SKILL.md")]
    references_dir = resolved_dir / "references"
    if references_dir.is_dir():
        paths.extend(sorted(p.relative_to(resolved_dir) for p in references_dir.glob("*.md")))
    return paths


def _content_for_harness(harness: str, skill_content: str) -> str:
    """Adapt the main SKILL.md's frontmatter to the target harness's shape.

    Only Copilot needs a rewrite: its instructions files use `applyTo`
    instead of `name`, so the frontmatter is rebuilt around the same
    description and body rather than shipped as a Claude-shaped skill file.
    Reference files carry no frontmatter and are never passed here.
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


def _target_path(harness: str, relative: Path) -> Path:
    """Return the installed path for one component, relative to REPO_ROOT."""
    base = _HARNESS_BASE_DIRS[harness]
    if relative == Path("SKILL.md"):
        return base / _MAIN_FILENAMES[harness]
    return base / relative


def _main_target_path(harness: str) -> Path:
    return REPO_ROOT / _target_path(harness, Path("SKILL.md"))


def _installed_version(content: str) -> str | None:
    match = re.search(r"\(fab-test ([^)\s]+)\)", content)
    return match.group(1) if match else None


def _skill_status(harness: str) -> dict[str, str]:
    target = _main_target_path(harness)
    if not target.is_file():
        return {"status": "missing", "path": str(target)}
    content = target.read_text(encoding="utf-8")
    installed_version = _installed_version(content)
    if installed_version is not None and installed_version != _FAB_TEST_VERSION:
        return {"status": "version_mismatch", "path": str(target), "version": installed_version}
    return {"status": "found", "path": str(target)}


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2))


_REFERENCE_TABLE_ROW = re.compile(
    r"^\|\s*\[references/([\w-]+)\.md\]\(references/[\w-]+\.md\)\s*\|\s*(.+?)\s*\|\s*$",
    re.MULTILINE,
)


def _skill_frontmatter_description(main_content: str) -> str:
    for line in main_content.splitlines():
        if line.startswith("description:"):
            return line.split(":", 1)[1].strip()
    return ""


def _reference_topics(main_content: str) -> list[tuple[str, str]]:
    """Parse SKILL.md's own "## Reference files" table (name, description)
    per row -- the sub-topics a person means by "list the skill files" --
    rather than hardcoding a second list that would drift from it."""
    return _REFERENCE_TABLE_ROW.findall(main_content)


def _skill_list(output_format: str, resolved) -> int:
    main_content = (resolved.path / "SKILL.md").read_text(encoding="utf-8")
    rows = [
        {
            "name": "fab-test",
            "description": _skill_frontmatter_description(main_content),
            "source_path": str(resolved.path / "SKILL.md"),
        }
    ]
    for name, description in _reference_topics(main_content):
        rows.append({
            "name": name,
            "description": description,
            "source_path": str(resolved.path / "references" / f"{name}.md"),
        })
    if output_format == "json":
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            narrate(f"  {row['name']}: {row['description']}", output_format=output_format)
    return 0


def _skill_print_reference(name: str, output_format: str, resolved) -> int:
    target = resolved.path / "references" / f"{name}.md"
    content = target.read_text(encoding="utf-8")
    if output_format == "json":
        _print_json({
            "version": _FAB_TEST_VERSION,
            "source_path": str(target),
            "content": content,
        })
    else:
        print(content)
    return 0


def _skill_print_named(name: str, output_format: str, resolved) -> int:
    """Resolve an explicit `name` positional to the main skill, a reference
    topic, or an error -- split out of `_skill` to keep its own branch
    count under the complexity ratchet."""
    if name == "fab-test":
        return _skill_print(output_format, resolved)

    main_content = (resolved.path / "SKILL.md").read_text(encoding="utf-8")
    topics = dict(_reference_topics(main_content))
    if name in topics:
        return _skill_print_reference(name, output_format, resolved)

    available = ", ".join(["fab-test", *topics])
    narrate(
        f"fab-test skill: unknown skill '{name}' -- available: {available}",
        output_format=output_format,
    )
    return 2


def _skill_print(output_format: str, resolved) -> int:
    main_content = (resolved.path / "SKILL.md").read_text(encoding="utf-8")
    if output_format == "json":
        reference_paths = [
            str(resolved.path / relative)
            for relative in _component_relative_paths(resolved.path)
            if relative != Path("SKILL.md")
        ]
        _print_json({
            "version": _FAB_TEST_VERSION,
            "source_path": str(resolved.path / "SKILL.md"),
            "content": main_content,
            "reference_paths": reference_paths,
        })
    else:
        print(main_content)
    return 0


def _skill_show(output_format: str) -> int:
    rows = {harness: _skill_status(harness) for harness in _HARNESS_BASE_DIRS}
    if output_format == "json":
        _print_json(rows)
    else:
        for harness, row in rows.items():
            narrate(f"  {harness}: {row['status']} ({row['path']})", output_format=output_format)
    return 0


def _install_one(harness: str, relative: Path, content: str, *, dry_run: bool, force: bool) -> dict:
    target = REPO_ROOT / _target_path(harness, relative)
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

    return {"relative": str(relative), "path": str(target), "status": status}


def _skill_install(harness: str, resolved, *, output_format: str, dry_run: bool, force: bool) -> int:
    try:
        files = []
        for relative in _component_relative_paths(resolved.path):
            content = (resolved.path / relative).read_text(encoding="utf-8")
            if relative == Path("SKILL.md"):
                content = _content_for_harness(harness, content)
            files.append(_install_one(harness, relative, content, dry_run=dry_run, force=force))
    except SkillContentError as exc:
        narrate(f"fab-test skill --install {harness}: {exc}", output_format=output_format)
        return 1

    statuses = {entry["status"] for entry in files}
    if "differs" in statuses:
        overall = "differs"
    elif len(statuses) == 1:
        overall = next(iter(statuses))
    else:
        overall = "mixed"
    payload = {
        "harness": harness,
        "base_path": str(REPO_ROOT / _HARNESS_BASE_DIRS[harness]),
        "status": overall,
        "files": files,
    }
    if output_format == "json":
        _print_json(payload)
    else:
        for entry in files:
            narrate(
                f"  fab-test skill --install {harness}: {entry['status']} ({entry['path']})",
                output_format=output_format,
            )
    return 1 if "differs" in statuses else 0


def _skill_uninstall(harness: str | None, output_format: str) -> int:
    if harness is None:
        narrate(
            "fab-test skill --uninstall needs --install <harness>",
            output_format=output_format,
        )
        return 2

    main_target = _main_target_path(harness)
    if not main_target.is_file():
        payload = {"harness": harness, "path": str(main_target), "status": "missing"}
    elif _OWNERSHIP_MARKER not in main_target.read_text(encoding="utf-8"):
        payload = {"harness": harness, "path": str(main_target), "status": "not_fab_test_managed"}
    else:
        base = REPO_ROOT / _HARNESS_BASE_DIRS[harness]
        removed = []
        for path in sorted(base.rglob("*.md"), reverse=True):
            path.unlink()
            removed.append(str(path))
        for directory in sorted(base.rglob("*"), reverse=True):
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
        if base.is_dir() and not any(base.iterdir()):
            base.rmdir()
        payload = {"harness": harness, "path": str(base), "status": "removed", "removed": removed}

    if output_format == "json":
        _print_json(payload)
    else:
        narrate(
            f"  fab-test skill --uninstall {harness}: {payload['status']} ({payload['path']})",
            output_format=output_format,
        )
    return 1 if payload["status"] == "not_fab_test_managed" else 0


def _skill(args: argparse.Namespace) -> int:
    """`fab-test skill`: list skills and topics, print one by name, or install it.

    Bare, lists the main "fab-test" skill plus one row per reference
    topic (parsed from SKILL.md's own "## Reference files" table, so the
    two can't drift apart) -- each with its description and the file
    it'll print. `fab-test skill fab-test` prints the repo-override-first
    resolved main SKILL.md (`--format json` wraps it with version/source
    metadata and the reference file paths); `fab-test skill <topic>`
    (e.g. `flags`, `credentials`) prints that references/*.md file the
    same way, without the reference-paths list since it has none of its
    own. `--install <harness>` writes or updates every component
    (SKILL.md/instructions file plus references/*.md) for that harness;
    `--show` reports install state per harness; `--uninstall` (paired
    with `--install <harness>`) removes only a directory this command's
    own marker text identifies as its.
    """
    output_format = getattr(args, "output_format", "text")

    if getattr(args, "uninstall", False):
        return _skill_uninstall(getattr(args, "install", None), output_format)
    if getattr(args, "show", False):
        return _skill_show(output_format)

    resolved = resolve_skill_dir(REPO_ROOT)
    if not (resolved.path / "SKILL.md").is_file():
        narrate(
            f"fab-test skill: resource missing at {resolved.path} -- reinstall cft-fab-test",
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

    name = getattr(args, "name", None)
    if name is None:
        return _skill_list(output_format, resolved)

    return _skill_print_named(name, output_format, resolved)
