"""Tests for `fab-test skill` (fab-test Skill Distribution epic).

`fab-test skill` prints the resolved skill content and, with `--install`,
writes a harness-specific copy of it into a consumer repository -- the
anti-drift install path this epic exists to add, following `fab-test
init`'s idempotent/never-clobber/`--dry-run` precedent.
"""

from __future__ import annotations

import argparse
import json

import pytest

from fabric_ci_cd_dataops.scripts import fab_test_skill as skill_module


def _args(**overrides) -> argparse.Namespace:
    defaults = {
        "output_format": "text",
        "install": None,
        "show": False,
        "uninstall": False,
        "dry_run": False,
        "force": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.fixture(autouse=True)
def _repo_root(tmp_path, monkeypatch):
    """Point the module at an empty repo so no override is ever picked up."""
    monkeypatch.setattr(skill_module, "REPO_ROOT", tmp_path)
    return tmp_path


def test_bare_skill_prints_the_resolved_content(capsys):
    exit_code = skill_module._skill(_args())

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "name: fab-test" in out


def test_skill_format_json_wraps_version_and_source(capsys):
    exit_code = skill_module._skill(_args(output_format="json"))

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"]
    assert payload["source_path"]
    assert "name: fab-test" in payload["content"]


def test_install_claude_writes_the_claude_skill_path(_repo_root, capsys):
    exit_code = skill_module._skill(_args(install="claude", output_format="json"))

    assert exit_code == 0
    target = _repo_root / ".claude" / "skills" / "fab-test" / "SKILL.md"
    assert target.is_file()
    assert "name: fab-test" in target.read_text(encoding="utf-8")
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "created"


def test_install_copilot_writes_an_instructions_file(_repo_root):
    exit_code = skill_module._skill(_args(install="copilot"))

    assert exit_code == 0
    target = _repo_root / ".github" / "instructions" / "fab-test.instructions.md"
    assert target.is_file()
    content = target.read_text(encoding="utf-8")
    assert 'applyTo: "**"' in content


def test_install_is_idempotent_on_a_second_run(_repo_root, capsys):
    skill_module._skill(_args(install="claude"))
    capsys.readouterr()

    exit_code = skill_module._skill(_args(install="claude", output_format="json"))

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "unchanged"


def test_install_dry_run_reports_without_writing(_repo_root, capsys):
    exit_code = skill_module._skill(_args(install="claude", dry_run=True, output_format="json"))

    assert exit_code == 0
    target = _repo_root / ".claude" / "skills" / "fab-test" / "SKILL.md"
    assert not target.exists()
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


def test_install_force_overwrites_a_differing_file(_repo_root, capsys):
    target = _repo_root / ".claude" / "skills" / "fab-test" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("stale content", encoding="utf-8")

    exit_code = skill_module._skill(_args(install="claude", force=True, output_format="json"))

    assert exit_code == 0
    assert "name: fab-test" in target.read_text(encoding="utf-8")
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "updated"


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


def test_uninstall_removes_only_fab_tests_own_file(_repo_root):
    skill_module._skill(_args(install="claude"))
    target = _repo_root / ".claude" / "skills" / "fab-test" / "SKILL.md"
    assert target.is_file()

    exit_code = skill_module._skill(_args(install="claude", uninstall=True))

    assert exit_code == 0
    assert not target.exists()


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
    override = _repo_root / ".github" / "skills" / "fab-test" / "SKILL.md"
    override.parent.mkdir(parents=True)
    override.write_text("no frontmatter here at all", encoding="utf-8")

    exit_code = skill_module._skill(_args(install="copilot"))

    assert exit_code == 1
    assert not (_repo_root / ".github" / "instructions" / "fab-test.instructions.md").exists()


def test_copilot_install_escapes_a_quote_in_the_description(_repo_root):
    override = _repo_root / ".github" / "skills" / "fab-test" / "SKILL.md"
    override.parent.mkdir(parents=True)
    override.write_text(
        '---\nname: fab-test\ndescription: uses "fab-test" quoted\n---\nbody\n',
        encoding="utf-8",
    )

    exit_code = skill_module._skill(_args(install="copilot"))

    assert exit_code == 0
    target = _repo_root / ".github" / "instructions" / "fab-test.instructions.md"
    content = target.read_text(encoding="utf-8")
    assert content.splitlines()[2] == 'description: "uses \'fab-test\' quoted"'
