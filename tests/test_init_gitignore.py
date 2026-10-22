"""`fab-test init` keeps fab-test's own folders out of Git.

Scope
-----
A run creates `.fab-test-tools/` (downloaded tool binaries, hundreds of MB)
and `fab-test-results/` (per-run output) at the repository root. `init`
adds both to the root `.gitignore`: it creates the file when there is none
and only ever appends to one that exists, so a user's own rules are never
rewritten. Always passes on any machine.

    pytest -m fab_test tests/test_init_gitignore.py
"""

import json
import subprocess

import pytest

_ENTRIES = (".fab-test-tools/", "fab-test-results/")


def _init(cwd, *flags):
    return subprocess.run(
        ["fab-test", "init", *flags],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=cwd,
        check=False,
    )


def _lines(path):
    return path.read_text(encoding="utf-8").splitlines()


@pytest.mark.fab_test
def test_creates_a_gitignore_ignoring_both_folders_when_there_is_none(tmp_path):
    result = _init(tmp_path)

    assert result.returncode == 0, result.stderr
    assert set(_ENTRIES) <= set(_lines(tmp_path / ".gitignore"))


@pytest.mark.fab_test
def test_appends_to_an_existing_gitignore_without_changing_what_is_there(tmp_path):
    """Given a .gitignore with no trailing newline, should keep its bytes as a
    prefix and start the added lines on a line of their own."""
    gitignore = tmp_path / ".gitignore"
    original = "node_modules/\n# keep me\n*.log"
    gitignore.write_bytes(original.encode("utf-8"))

    _init(tmp_path)

    text = gitignore.read_text(encoding="utf-8")
    assert text.startswith(original + "\n")
    assert set(_ENTRIES) <= set(text.splitlines())
    assert text.endswith("\n")


@pytest.mark.fab_test
@pytest.mark.parametrize(
    "existing", ["/fab-test-results\n.fab-test-tools/**\n", "fab-test-results/\n.fab-test-tools\n"]
)
def test_leaves_a_gitignore_alone_that_already_ignores_both(tmp_path, existing):
    """Given equivalent spellings already present, should add nothing."""
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(existing, encoding="utf-8")

    _init(tmp_path)

    assert gitignore.read_text(encoding="utf-8") == existing


@pytest.mark.fab_test
def test_adds_only_the_missing_entry(tmp_path):
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("fab-test-results/\n", encoding="utf-8")

    _init(tmp_path)

    assert _lines(gitignore).count("fab-test-results/") == 1
    assert ".fab-test-tools/" in _lines(gitignore)


@pytest.mark.fab_test
def test_running_init_twice_adds_nothing_the_second_time(tmp_path):
    _init(tmp_path)
    first = (tmp_path / ".gitignore").read_text(encoding="utf-8")

    _init(tmp_path)

    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == first


@pytest.mark.fab_test
def test_dry_run_reports_the_entries_without_writing(tmp_path):
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("node_modules/\n", encoding="utf-8")

    result = _init(tmp_path, "--dry-run", "--format", "json")

    assert gitignore.read_text(encoding="utf-8") == "node_modules/\n"
    payload = json.loads(result.stdout)
    assert payload["gitignore"] == {"path": str(gitignore), "added": [], "would_add": list(_ENTRIES)}


@pytest.mark.fab_test
def test_json_names_what_was_added(tmp_path):
    result = _init(tmp_path, "--format", "json")

    payload = json.loads(result.stdout)
    assert payload["gitignore"]["added"] == list(_ENTRIES)
    assert payload["gitignore"]["would_add"] == []


@pytest.mark.fab_test
def test_appends_with_the_files_own_crlf_line_endings(tmp_path):
    """Given a CRLF .gitignore, should append CRLF lines, not mix endings."""
    gitignore = tmp_path / ".gitignore"
    gitignore.write_bytes(b"node_modules/\r\n")

    _init(tmp_path)

    data = gitignore.read_bytes()
    assert data.startswith(b"node_modules/\r\n")
    assert data.count(b"\n") == data.count(b"\r\n")
    assert b".fab-test-tools/\r\n" in data


@pytest.mark.fab_test
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", list(_ENTRIES)),
        ("/fab-test-results\n.fab-test-tools/**\n", []),
        ("# fab-test-results/\n", list(_ENTRIES)),
        ("fab-test-results/\n", [".fab-test-tools/"]),
    ],
)
def test_missing_entries_ignore_comments_and_accept_other_spellings(text, expected):
    """Given a commented-out line, should still count the entry as missing."""
    from fab_test.scripts.fab_test_init import missing_gitignore_entries

    assert missing_gitignore_entries(text) == expected


@pytest.mark.fab_test
@pytest.mark.parametrize("dry_run", [True, False])
def test_update_reports_added_or_would_add_in_process(tmp_path, dry_run):
    from fab_test.scripts.fab_test_init import _narrate_gitignore, _update_root_gitignore

    path = tmp_path / ".gitignore"
    path.write_bytes(b"node_modules/")

    result = _update_root_gitignore(path, dry_run=dry_run)
    _narrate_gitignore(result, "text")

    assert result["would_add" if dry_run else "added"] == list(_ENTRIES)
    assert path.read_bytes().startswith(b"node_modules/" + (b"" if dry_run else b"\n"))
    assert _update_root_gitignore(path, dry_run=False)["added"] == ([] if not dry_run else list(_ENTRIES))


@pytest.mark.fab_test
@pytest.mark.parametrize("output_format", ["text", "json"])
def test_init_in_process_writes_its_files_and_the_gitignore(tmp_path, monkeypatch, capsys, output_format):
    import argparse

    from fab_test.scripts import fab_test_init

    monkeypatch.setattr(fab_test_init, "REPO_ROOT", tmp_path)
    args = argparse.Namespace(output_format=output_format, dry_run=False)

    assert fab_test_init._init(args) == 0
    assert fab_test_init._init(args) == 0  # second run: everything already exists

    assert (tmp_path / "fab-test.yml").exists()
    assert set(_ENTRIES) <= set(_lines(tmp_path / ".gitignore"))
    if output_format == "json":
        second = capsys.readouterr().out.strip().split("\n{")[-1]
        assert json.loads("{" + second)["gitignore"]["added"] == []
