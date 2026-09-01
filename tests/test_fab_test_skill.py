"""Tests for `fab-test skill` (fab-test Skill Distribution/Componentization epics).

`fab-test skill` prints the resolved skill content and, with `--install`,
writes a harness-specific copy of the whole component set (main
SKILL.md/instructions file plus references/*.md) into a consumer
repository -- the anti-drift install path this epic exists to add,
following `fab-test init`'s idempotent/never-clobber/`--dry-run`
precedent.
"""

from __future__ import annotations

import argparse
import json

import pytest

from fab_test import __version__
from fab_test.scripts import fab_test_skill as skill_module


def _args(**overrides) -> argparse.Namespace:
    defaults = {
        "output_format": "text",
        "install": None,
        "show": False,
        "uninstall": False,
        "dry_run": False,
        "force": False,
        "list": False,
        "name": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _write_skill_dir(root, *, description=None):
    description = description or (
        "fab-test CLI reference for running Fabric artifact analyzers "
        f"locally (fab-test {__version__})."
    )
    skill_dir = root / ".fab-test" / "skill"
    (skill_dir / "references").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: fab-test\ndescription: {description}\n---\nbody\n",
        encoding="utf-8",
    )
    (skill_dir / "references" / "flags.md").write_text("# Flags\ncontent\n", encoding="utf-8")
    return skill_dir


@pytest.fixture(autouse=True)
def _repo_root(tmp_path, monkeypatch):
    """Point the module at a repo with a two-file skill resource (main + one
    reference) so every test exercises the multi-file install path without
    depending on this repo's own real (much larger) skill content."""
    monkeypatch.setattr(skill_module, "REPO_ROOT", tmp_path)
    _write_skill_dir(tmp_path)
    return tmp_path


def test_bare_skill_prints_the_main_files_content(capsys):
    exit_code = skill_module._skill(_args())

    assert exit_code == 0
    assert "name: fab-test" in capsys.readouterr().out


def test_named_skill_prints_the_same_content_as_bare(capsys):
    exit_code = skill_module._skill(_args(name="fab-test"))

    assert exit_code == 0
    assert "name: fab-test" in capsys.readouterr().out


def test_unknown_name_errors_with_available_skills_listed(capsys):
    exit_code = skill_module._skill(_args(name="does-not-exist"))

    assert exit_code == 2
    err = capsys.readouterr().out
    assert "does-not-exist" in err
    assert "fab-test" in err


def test_list_flag_reports_the_known_skill_text(capsys):
    exit_code = skill_module._skill(_args(list=True))

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "fab-test" in out


def test_list_flag_format_json_reports_name_and_description(capsys):
    exit_code = skill_module._skill(_args(list=True, output_format="json"))

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    assert payload[0]["name"] == "fab-test"
    assert payload[0]["source_path"].endswith("SKILL.md")
    assert payload[0]["description"]


def test_skill_format_json_wraps_version_source_and_reference_paths(capsys):
    exit_code = skill_module._skill(_args(output_format="json"))

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"]
    assert payload["source_path"].endswith("SKILL.md")
    assert "name: fab-test" in payload["content"]
    assert any(p.endswith("flags.md") for p in payload["reference_paths"])


def test_install_claude_writes_the_whole_component_set(_repo_root, capsys):
    exit_code = skill_module._skill(_args(install="claude", output_format="json"))

    assert exit_code == 0
    base = _repo_root / ".claude" / "skills" / "fab-test"
    assert (base / "SKILL.md").is_file()
    assert (base / "references" / "flags.md").is_file()
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "created"
    relatives = {f["relative"].replace("\\", "/") for f in payload["files"]}
    assert relatives == {"SKILL.md", "references/flags.md"}


def test_install_copilot_writes_an_instructions_file_and_references(_repo_root):
    exit_code = skill_module._skill(_args(install="copilot"))

    assert exit_code == 0
    base = _repo_root / ".github" / "instructions" / "fab-test"
    main = base / "fab-test.instructions.md"
    assert main.is_file()
    assert 'applyTo: "**"' in main.read_text(encoding="utf-8")
    assert (base / "references" / "flags.md").is_file()
    assert (base / "references" / "flags.md").read_text(encoding="utf-8") == "# Flags\ncontent\n"


def test_install_is_idempotent_on_a_second_run(_repo_root, capsys):
    skill_module._skill(_args(install="claude"))
    capsys.readouterr()

    exit_code = skill_module._skill(_args(install="claude", output_format="json"))

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "unchanged"
    assert all(f["status"] == "unchanged" for f in payload["files"])


def test_install_dry_run_reports_without_writing(_repo_root, capsys):
    exit_code = skill_module._skill(_args(install="claude", dry_run=True, output_format="json"))

    assert exit_code == 0
    base = _repo_root / ".claude" / "skills" / "fab-test"
    assert not base.exists()
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "would_create"


def test_install_refuses_to_clobber_a_differing_file_without_force(_repo_root, capsys):
    target = _repo_root / ".claude" / "skills" / "fab-test" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("someone else's content", encoding="utf-8")

    exit_code = skill_module._skill(_args(install="claude", output_format="json"))

    assert exit_code == 1
    assert target.read_text(encoding="utf-8") == "someone else's content"
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "differs"


def test_install_force_overwrites_a_differing_file(_repo_root):
    target = _repo_root / ".claude" / "skills" / "fab-test" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("stale content", encoding="utf-8")

    exit_code = skill_module._skill(_args(install="claude", force=True))

    assert exit_code == 0
    assert "name: fab-test" in target.read_text(encoding="utf-8")


def test_show_reports_missing_for_every_harness_with_nothing_installed(capsys):
    exit_code = skill_module._skill(_args(show=True, output_format="json"))

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["claude"]["status"] == "missing"
    assert payload["copilot"]["status"] == "missing"


def test_show_reports_found_after_install(_repo_root, capsys):
    skill_module._skill(_args(install="claude"))
    capsys.readouterr()

    skill_module._skill(_args(show=True, output_format="json"))

    payload = json.loads(capsys.readouterr().out)
    assert payload["claude"]["status"] == "found"


def test_show_reports_version_mismatch_for_a_stale_installed_copy(_repo_root, capsys):
    target = _repo_root / ".claude" / "skills" / "fab-test" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text(
        "---\nname: fab-test\ndescription: stale (fab-test 0.0.0)\n---\n",
        encoding="utf-8",
    )

    skill_module._skill(_args(show=True, output_format="json"))

    payload = json.loads(capsys.readouterr().out)
    assert payload["claude"]["status"] == "version_mismatch"


def test_uninstall_removes_the_whole_component_set(_repo_root):
    skill_module._skill(_args(install="claude"))
    base = _repo_root / ".claude" / "skills" / "fab-test"
    assert (base / "references" / "flags.md").is_file()

    exit_code = skill_module._skill(_args(install="claude", uninstall=True))

    assert exit_code == 0
    assert not base.exists()


def test_uninstall_refuses_a_file_it_did_not_create(_repo_root, capsys):
    target = _repo_root / ".claude" / "skills" / "fab-test" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("not a fab-test skill file", encoding="utf-8")

    exit_code = skill_module._skill(_args(install="claude", uninstall=True))

    assert exit_code == 1
    assert target.is_file()


def test_uninstall_without_install_target_is_a_clear_error(capsys):
    exit_code = skill_module._skill(_args(uninstall=True))

    assert exit_code == 2


def test_copilot_install_fails_cleanly_on_a_frontmatter_free_override(_repo_root):
    skill_dir = _repo_root / ".fab-test" / "skill"
    (skill_dir / "SKILL.md").write_text("no frontmatter here at all", encoding="utf-8")

    exit_code = skill_module._skill(_args(install="copilot"))

    assert exit_code == 1
    assert not (_repo_root / ".github" / "instructions" / "fab-test").exists()


def test_copilot_install_escapes_a_quote_in_the_description(_repo_root):
    skill_dir = _repo_root / ".fab-test" / "skill"
    (skill_dir / "SKILL.md").write_text(
        '---\nname: fab-test\ndescription: uses "fab-test" quoted\n---\nbody\n',
        encoding="utf-8",
    )

    exit_code = skill_module._skill(_args(install="copilot"))

    assert exit_code == 0
    target = _repo_root / ".github" / "instructions" / "fab-test" / "fab-test.instructions.md"
    content = target.read_text(encoding="utf-8")
    assert content.splitlines()[2] == 'description: "uses \'fab-test\' quoted"'
