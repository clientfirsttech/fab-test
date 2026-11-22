"""Where authored test files live: `fab-tests/` at the repository root (Data Agent decision 22).

Data Agent suites and slicer contracts are test files, not Fabric items. Fabric's Commit to Git
deletes files inside an item folder, and a Git subfolder becomes a workspace folder, so they live
outside the Git-connected folder in one place a person can find:
`fab-tests/data-agent/<Item>.DataAgent.promptfoo.yaml`, `fab-tests/pbir/<Report>.Report.odcs.yaml`.

Files still pair by logicalId, so a file's folder never decides what it tests. Discovery reads
`fab-tests/` as well as `--artifact-dir`, so a file beside its item keeps working.

`fab-tests/` is anchored to the repository holding the item (or, with no item named, the artifacts):
the nearest folder above it with a `.git`, never the caller's directory. A scratch copy outside any
repository then never reads the repository's own test files, which would claim the same items. A
named item outside `--artifact-dir` is searched for beside itself, not under `--artifact-dir`.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from ._config import resolve_setting

TESTS_DIR = "fab-tests"
TESTS_DIR_ENV = "FAB_TEST_TESTS_DIR"
TESTS_DIR_HELP = (f"Folder for authored test files, outside the Git-connected folder "
                  f"[default: {TESTS_DIR}/ at the repository root; {TESTS_DIR_ENV}; tests_dir in fab-test.yml]")


def add_tests_dir_flag(parser: argparse.ArgumentParser) -> None:
    """The one spelling every run and authoring verb shares."""
    parser.add_argument("--tests-dir", default=None, dest="tests_dir", metavar="DIR", help=TESTS_DIR_HELP)


def _repository(start: Path) -> Path | None:
    start = start.resolve()
    return next((folder for folder in (start, *start.parents) if (folder / ".git").exists()), None)


def tests_dir(args: argparse.Namespace, item: Path | None = None) -> Path | None:
    """`--tests-dir` → `FAB_TEST_TESTS_DIR` → `tests_dir:` → `fab-tests/` in the artifacts' repository.

    A relative setting is read from that repository's root, or the working directory outside one.
    None when nothing is set and the artifacts are in no repository.
    """
    repository = _repository(item if item is not None else Path(getattr(args, "artifact_dir", None) or "."))
    value, _origin = resolve_setting("tests_dir", cli_value=getattr(args, "tests_dir", None),
                                     env_var=TESTS_DIR_ENV, file_config=getattr(args, "file_config", None) or {},
                                     packaged_default=None)
    if value:
        path = Path(os.path.expanduser(str(value)))
        return path if path.is_absolute() else (repository or Path.cwd()) / path
    return repository / TESTS_DIR if repository else None


def flow_dir(args: argparse.Namespace, flow: str, item: Path | None = None) -> Path | None:
    """Where a flow writes a new file: `fab-tests/<flow>/`, or None to write beside the item."""
    home = tests_dir(args, item)
    return home / flow if home else None


def search_roots(args: argparse.Namespace, item: Path | None = None) -> list[Path]:
    """`--artifact-dir` (or a named item's own folder, outside it), then `fab-tests/` if it exists."""
    artifacts = Path(getattr(args, "artifact_dir", None) or ".").resolve()
    roots = [artifacts if item is None or item.resolve().is_relative_to(artifacts) else item.resolve().parent]
    home = tests_dir(args, item)
    if home is not None and home.is_dir():
        home = home.resolve()
        if not home.is_relative_to(roots[0]):
            roots.append(home)
    return roots
