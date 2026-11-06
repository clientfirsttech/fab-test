"""Same-named artifacts get their own results folder (Same-Named Artifacts task).

Results are written to ``<output-dir>/<analyzer>/<artifact stem>/``, so two
artifacts with one stem in different folders used to overwrite each other's
envelope and the summary reported the survivor twice. A colliding stem now
carries a deterministic suffix; a stem nobody else shares keeps the path it
always had.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from fab_test.scripts import _analyzer_annotations
from fab_test.scripts._results_stem import _SUFFIXED, results_stem
from fab_test.scripts._target import parse_target
from fab_test.scripts.fab_test_registry import discover_artifacts
from fab_test.scripts.fab_test_telemetry import _build_telemetry_payload

pytestmark = [pytest.mark.rdl, pytest.mark.analyzers]

_REPO = Path(__file__).resolve().parent.parent
_CLEAN = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<Report xmlns="http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition">'
    "<ReportSections><ReportSection><Body><ReportItems /><Height>1in</Height></Body>"
    "<Width>6in</Width><Page><PageWidth>8.5in</PageWidth></Page></ReportSection></ReportSections></Report>"
)


def _tree(root: Path, *relative: str) -> Path:
    for rel in relative:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_CLEAN, encoding="utf-8")
    return root


def test_artifacts_with_distinct_stems_keep_their_plain_stem(tmp_path):
    _tree(tmp_path, "One.rdl", "Two.rdl")

    found = discover_artifacts(tmp_path, "*.rdl", None)

    assert [results_stem(a) for a in found] == ["One", "Two"], "a stem nobody shares must not change"


def test_colliding_stems_get_distinct_deterministic_suffixed_stems(tmp_path):
    _tree(tmp_path, "ACC-03.rdl", "ACC-03.PaginatedReport/ACC-03.rdl")

    first = [results_stem(a) for a in discover_artifacts(tmp_path, "*.rdl", None)]
    again = [results_stem(a) for a in discover_artifacts(tmp_path, "*.rdl", None)]

    assert len(set(first)) == 2, "two artifacts must never share a results folder"
    assert all(s.startswith("ACC-03-") for s in first), "the suffix keeps the real name readable"
    assert first == again, "the suffix must be the same on every run"


def test_collision_suffix_does_not_depend_on_where_the_checkout_lives(tmp_path):
    """CI and a laptop must name a given artifact's results folder the same way."""
    a, b = tmp_path / "a", tmp_path / "b"
    _tree(a, "x/R.rdl", "y/R.rdl")
    _tree(b, "x/R.rdl", "y/R.rdl")

    assert [results_stem(p) for p in discover_artifacts(a, "*.rdl", None)] == [
        results_stem(p) for p in discover_artifacts(b, "*.rdl", None)
    ]


def test_a_stem_stops_being_suffixed_once_its_twin_is_out_of_the_run(tmp_path):
    _tree(tmp_path, "R.rdl", "sub/R.rdl")
    both = discover_artifacts(tmp_path, "*.rdl", None)
    assert all(results_stem(a) != "R" for a in both)

    only = discover_artifacts(tmp_path / "sub", "*.rdl", None)

    assert [results_stem(a) for a in only] == ["R"]


def test_a_narrowed_discovery_assigns_the_same_stems_as_the_full_one(tmp_path):
    """`all` discovers per analyzer with different narrowing; the last call must not move a folder."""
    _tree(tmp_path, "R.rdl", "sub/R.rdl", "Other.rdl")
    full = {a: results_stem(a) for a in discover_artifacts(tmp_path, "*.rdl", None)}

    narrowed = discover_artifacts(tmp_path, "*.rdl", parse_target("Other"))
    both = discover_artifacts(tmp_path, "*.rdl", parse_target("R"))

    assert [results_stem(a) for a in narrowed] == ["Other"]
    assert {a: results_stem(a) for a in both}.items() <= full.items(), "narrowing must not rename a collider"
    assert all(results_stem(a).startswith("R-") for a in both)


def test_telemetry_names_each_collided_artifact_by_its_own_folder(tmp_path):
    _tree(tmp_path, "ACC-03.rdl", "ACC-03.PaginatedReport/ACC-03.rdl", "Solo.rdl")
    found = discover_artifacts(tmp_path, "*.rdl", None)
    envelope = {"status": "passed", "findings": []}

    names = {a.name: _build_telemetry_payload("rdl", a, envelope, "DEV")["artifact_name"] for a in found}

    assert names["Solo.rdl"] == "Solo", "an unshared stem keeps the name telemetry already recorded"
    collided = [_build_telemetry_payload("rdl", a, envelope, "DEV")["artifact_name"] for a in found if "ACC" in a.name]
    assert len(set(collided)) == 2 and all(n.startswith("ACC-03-") for n in collided)


def test_pr_comments_name_a_collided_artifact_by_its_own_folder(tmp_path, monkeypatch):
    _tree(tmp_path, "ACC-03.rdl", "sub/ACC-03.rdl")
    first = discover_artifacts(tmp_path, "*.rdl", None)[0]
    posted = []
    monkeypatch.setattr(_analyzer_annotations, "_pr_context", lambda: {"pr": "1"})
    monkeypatch.setattr(_analyzer_annotations, "_post_pr_review_comment", lambda _ctx, body: posted.append(body))

    _analyzer_annotations.emit_pr_review_comments(
        {"analyzer": "rdl", "findings": [{"severity": "warning", "message": "m"}]}, str(first)
    )

    assert f"`{results_stem(first)}`" in posted[0]
    assert results_stem(first) != "ACC-03"


def test_results_stems_do_not_leak_between_tests():
    """conftest clears the registry before every test, so one test's collisions cannot rename another's."""
    assert _SUFFIXED == {}


def test_cli_run_over_same_named_artifacts_writes_one_envelope_each(tmp_path):
    artifacts = _tree(tmp_path / "artifacts", "ACC-03.rdl", "ACC-03.PaginatedReport/ACC-03.rdl")
    out = tmp_path / "out"
    env = {
        **{k: v for k, v in os.environ.items() if k not in ("GITHUB_ACTIONS", "CI", "ANALYZER_VERBOSITY")},
        "PYTHONPATH": str(_REPO / "src"),
        "PYTHONIOENCODING": "utf-8",
    }

    proc = subprocess.run(
        [sys.executable, "-m", "fab_test.scripts.fab_test", "rdl", "--artifact-dir", str(artifacts),
         "--output-dir", str(out), "--no-report"],
        capture_output=True, text=True, encoding="utf-8", env=env, cwd=tmp_path, timeout=120, check=False,
    )

    envelopes = sorted((out / "rdl").glob("*/envelope.json"))
    assert len(envelopes) == 2, f"expected one envelope per artifact:\n{proc.stdout}\n{proc.stderr}"
    assert all(json.loads(p.read_text(encoding="utf-8")) for p in envelopes), "envelopes are real"
    lines = [ln for ln in proc.stdout.splitlines() if "ACC-03" in ln]
    assert len({p.parent.name for p in envelopes}) == 2
    assert any(envelopes[0].parent.name in ln for ln in lines) and any(
        envelopes[1].parent.name in ln for ln in lines
    ), "the summary must name each artifact's own results folder, not one twice"


def test_a_path_targeted_discovery_does_not_rename_a_stem_a_full_scan_assigned(tmp_path):
    _tree(tmp_path, "R.rdl", "sub/R.rdl")
    full = {a: results_stem(a) for a in discover_artifacts(tmp_path, "*.rdl", None)}

    by_path = discover_artifacts(tmp_path, "*.rdl", parse_target(str(tmp_path / "sub" / "R.rdl")))

    assert [results_stem(a) for a in by_path] == [full[by_path[0]]]
    assert full[by_path[0]] != "R"
