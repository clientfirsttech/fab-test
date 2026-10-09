"""Native output lands beside its envelope, so `--output-dir` governs both (Service Targeting).

Found live (2026-10-09): with `--output-dir DIR` each envelope went to DIR but
every wrapper wrote `native.json`/`native.xml` to `./fab-test-results/`,
because the native path was built from the default root, not from the
envelope path the parent passes as `--output-path`.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from fab_test.scripts._analyzer_envelope import native_output_path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "fab_test" / "scripts"


def test_given_an_envelope_path_should_put_native_output_beside_it(tmp_path):
    envelope = tmp_path / "out" / "rdl" / "Sales" / "envelope.json"
    assert native_output_path("rdl", "Sales", "json", beside=envelope) == envelope.parent / "native.json"


def test_given_no_envelope_path_should_keep_the_default_location():
    assert native_output_path("bpa", "Sales", ".xml") == Path("fab-test-results") / "bpa" / "Sales" / "native.xml"


@pytest.mark.parametrize("wrapper", sorted(p.name for p in SCRIPTS.glob("invoke_*.py")))
def test_every_wrapper_places_native_output_beside_its_envelope(wrapper):
    calls = re.findall(r"native_output_path\(([^)]*)\)", (SCRIPTS / wrapper).read_text(encoding="utf-8"))
    assert all("beside=" in call for call in calls), f"{wrapper} builds a native path from the default root"


def test_given_output_dir_should_write_no_native_output_under_the_default_root(tmp_path):
    shutil.copy(ROOT / "fabric-artifacts" / "PaginatedExample-BrokenRDL.rdl", tmp_path / "Sample.rdl")
    result = subprocess.run(
        [sys.executable, "-m", "fab_test.scripts.fab_test", "rdl", "Sample.rdl", "--output-dir", "out"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        check=False,
    )
    assert (tmp_path / "out" / "rdl" / "Sample" / "native.json").exists(), result.stderr
    assert not (tmp_path / "fab-test-results").exists()
