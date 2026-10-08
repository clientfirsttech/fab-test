"""Local graph privacy, freshness, and failure contracts."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from graphify_index import filter_graph, query, refresh, snapshot, status


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for name in ("src/main.py", "tests/test_main.py", ".github/agents/private.py", "src/credentials.py"):
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("def example():\n    pass\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    return root


def raw_graph(stage):
    return {
        "nodes": [
            {"id": "a", "label": "example", "source_file": str(stage / "src/main.py"), "type": "function"},
            {"id": "b", "label": "main.py", "source_file": str(stage / "src/main.py"), "type": "file"},
            {"id": "semantic", "label": "secret", "confidence": "INFERRED"},
        ],
        "edges": [
            {"source": "a", "target": "b", "confidence": "EXTRACTED", "relation": "contains"},
            {"source": "b", "target": "a", "confidence": "INFERRED"},
            {"source": "a", "target": "semantic", "confidence": "EXTRACTED"},
            {"source": "a", "target": "b", "confidence": "EXTRACTED", "ambiguous": True},
        ],
        "hyperedges": [{"nodes": ["a", "b", "semantic"]}],
        "input_tokens": 999,
    }


def test_snapshot_allowlist_and_worktree_freshness(repository):
    files, first = snapshot(repository)
    assert sorted(files) == ["src/main.py", "tests/test_main.py"]
    (repository / "src/main.py").write_text("def changed(): pass\n", encoding="utf-8")
    assert snapshot(repository)[1] != first
    (repository / "src/main.py").unlink()
    assert snapshot(repository)[1] != first
    assert "src/main.py" not in snapshot(repository)[0]


def test_snapshot_rejects_symlink(repository):
    file = repository / "src/main.py"
    file.unlink()
    file.symlink_to(repository / ".github/agents/private.py")
    with pytest.raises(ValueError, match="symlink"):
        snapshot(repository)


def test_filter_retains_only_extracted_edges_and_local_nodes(tmp_path):
    result = filter_graph(raw_graph(tmp_path), tmp_path, {"src/main.py"})
    assert len(result["nodes"]) == 2
    assert len(result["edges"]) == 1
    assert result["nodes"][0]["source_file"] == "src/main.py"
    assert "hyperedges" not in result
    assert "input_tokens" not in result


def test_filter_accepts_empty_module_null_source_location(tmp_path):
    source = str(tmp_path / "src/__init__.py")
    graph = {
        "nodes": [
            {
                "id": "empty-module", "label": "__init__.py", "file_type": "code",
                "source_file": source, "source_location": None,
            },
        ],
        "edges": [],
    }
    result = filter_graph(graph, tmp_path, {"src/__init__.py"})
    assert result["nodes"] == [
        {"id": "empty-module", "label": "__init__.py", "source_file": "src/__init__.py"},
    ]
    assert filter_graph(result, tmp_path, {"src/__init__.py"}) == result


@pytest.mark.parametrize("field,value", [("label", None), ("type", None), ("source_location", [])])
def test_filter_still_rejects_invalid_node_attributes(tmp_path, field, value):
    graph = raw_graph(tmp_path)
    graph["nodes"][0][field] = value
    with pytest.raises(ValueError, match="invalid node attributes"):
        filter_graph(graph, tmp_path, {"src/main.py"})


@pytest.mark.parametrize(
    "graph",
    [
        {"nodes": {}, "edges": []},
        {"nodes": [{"id": "x"}, {"id": "x"}], "edges": []},
        {"nodes": [], "edges": [{"source": "x", "target": "y", "confidence": "EXTRACTED"}]},
    ],
)
def test_filter_rejects_malformed_graph(graph, tmp_path):
    with pytest.raises(ValueError):
        filter_graph(graph, tmp_path, set())


def test_refresh_unchanged_and_failure_retains_last_graph(repository, monkeypatch):
    calls = []

    def extract(stage, output, arguments):
        calls.append(arguments)
        output.mkdir()
        (output / "graph.json").write_text(json.dumps(raw_graph(stage)), encoding="utf-8")
        return ""

    monkeypatch.setattr("graphify_index.run_graphify", extract)
    assert refresh(repository)["state"] == "fresh"
    original = (repository / ".graphify-local/index.json").read_bytes()
    assert refresh(repository)["state"] == "fresh"
    assert len(calls) == 1
    (repository / "src/main.py").write_text("def changed(): pass\n", encoding="utf-8")

    def fail(*args):
        raise RuntimeError("must not disclose raw upstream text")

    monkeypatch.setattr("graphify_index.run_graphify", fail)
    assert refresh(repository)["state"] == "stale"
    assert (repository / ".graphify-local/index.json").read_bytes() == original
    assert status(repository)["failure"] == "extraction-failed"
    assert not list((repository / ".graphify-local").glob("stage-*"))


def test_missing_graph_is_optional(repository):
    assert status(repository)["state"] == "missing"


def test_network_failure_has_no_unsafe_fallback(tmp_path, monkeypatch):
    from graphify_index import run_graphify

    monkeypatch.setattr("graphify_index.shutil.which", lambda name: f"/usr/bin/{name}")

    def denied(command, **kwargs):
        assert command[:4] == ["/usr/bin/unshare", "--user", "--map-root-user", "--net"]
        assert kwargs["env"]["GRAPHIFY_GOOGLE_WORKSPACE"] == "0"
        assert "GEMINI_API_KEY" not in kwargs["env"]
        return subprocess.CompletedProcess(command, 1, "", "private")

    monkeypatch.setattr("graphify_index.subprocess.run", denied)
    with pytest.raises(RuntimeError, match="network-isolation-or-extraction-failed"):
        run_graphify(tmp_path, tmp_path / "out", ["extract", str(tmp_path), "--code-only", "--no-cluster"])


def test_stale_query_is_read_only_and_no_queries_are_logged(repository, monkeypatch):
    def extract(stage, output, arguments):
        output.mkdir()
        (output / "graph.json").write_text(json.dumps(raw_graph(stage)), encoding="utf-8")
        return ""

    monkeypatch.setattr("graphify_index.run_graphify", extract)
    refresh(repository)
    (repository / "src/main.py").write_text("def changed(): pass\n", encoding="utf-8")
    cache = repository / ".graphify-local"
    original = (cache / "index.json").read_bytes()

    def search(stage, output, arguments):
        assert arguments[0] == "query"
        assert "--graph" in arguments
        assert json.loads((stage / "graph.json").read_text())["edges"][0]["confidence"] == "EXTRACTED"
        return "example"

    monkeypatch.setattr("graphify_index.run_graphify", search)
    result = query(repository, "private question")
    assert result["state"] == "stale"
    assert result["context"] == "example"
    assert (cache / "index.json").read_bytes() == original
    assert sorted(path.name for path in cache.iterdir()) == ["index.json"]


def test_cache_redirect_is_rejected(repository):
    (repository / ".graphify-local").symlink_to(repository / "tests", target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        status(repository)


def test_dirty_inputs_during_build_do_not_replace_graph(repository, monkeypatch):
    def raced(stage, output, arguments):
        output.mkdir()
        (output / "graph.json").write_text(json.dumps(raw_graph(stage)), encoding="utf-8")
        (repository / "src/main.py").write_text("def changed(): pass\n", encoding="utf-8")
        return ""

    monkeypatch.setattr("graphify_index.run_graphify", raced)
    assert refresh(repository)["state"] == "missing"
    assert not (repository / ".graphify-local/index.json").exists()


def test_cli_missing_query_and_invalid_observation(repository):
    cli = Path(__file__).resolve().parents[1] / "tools/graphify_local.py"
    result = subprocess.run(
        [sys.executable, str(cli), "--root", str(repository), "query", "where is example"],
        check=True, capture_output=True, text=True,
    )
    assert json.loads(result.stdout)["state"] == "missing"
    result = subprocess.run(
        [sys.executable, str(cli), "--root", str(repository), "record", "--observation", '{"prompt":"private"}'],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "private" not in result.stdout


def test_cli_status_record_report_with_provider_tokens(repository):
    cli = Path(__file__).resolve().parents[1] / "tools/graphify_local.py"
    command = [sys.executable, str(cli), "--root", str(repository)]
    status_result = subprocess.run([*command, "status"], check=True, capture_output=True, text=True)
    current = json.loads(status_result.stdout)
    assert current["state"] == "missing"
    for mode, elapsed in (("baseline", 100), ("graph", 50)):
        trial = {
            "assistant": "copilot", "mode": mode, "benchmark": "cli-trial",
            "revision": current["revision"], "model": "model1", "source": "manual",
            "token_source": "provider_reported", "input_tokens": elapsed,
            "elapsed_seconds": elapsed, "correct": mode == "baseline",
        }
        result = subprocess.run(
            [*command, "record"], input=json.dumps(trial), check=True, capture_output=True, text=True,
        )
        assert json.loads(result.stdout) == {"recorded": True}
    result = subprocess.run([*command, "report"], check=True, capture_output=True, text=True)
    summary = json.loads(result.stdout)["assistants"]["copilot"]
    assert summary["total_trials"] == 2
    assert summary["complete_pairs"] == 1
    assert summary["pairs"] == 0
    assert summary["correctness_regressions"] == 1
    assert summary["median_actual_input_tokens_saved"] is None


def test_cli_build_without_unshare_fails_without_extraction(repository, monkeypatch):
    bin_path = repository / "bin"
    bin_path.mkdir()
    (bin_path / "git").symlink_to(shutil.which("git"))
    monkeypatch.setenv("PATH", str(bin_path))
    cli = Path(__file__).resolve().parents[1] / "tools/graphify_local.py"
    result = subprocess.run(
        [sys.executable, str(cli), "--root", str(repository), "build"],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 1
    current = json.loads(result.stdout)
    assert current["state"] == "missing"
    assert current["failure"] == "extraction-failed"
    assert "unshare" in current["hint"]
    assert not (repository / ".graphify-local/index.json").exists()
    assert not list((repository / ".graphify-local").glob("stage-*"))
    assert not result.stderr


def test_filter_detects_normalized_collision(tmp_path):
    graph = {
        "nodes": [
            {"id": "a", "source_file": str(tmp_path / "src/main.py")},
            {"id": str(tmp_path) + "/a", "source_file": str(tmp_path / "src/main.py")},
        ],
        "edges": [],
    }
    with pytest.raises(ValueError, match="collision"):
        filter_graph(graph, tmp_path, {"src/main.py"})


def test_filter_drops_nested_ambiguity(tmp_path):
    graph = raw_graph(tmp_path)
    graph["edges"][0]["metadata"] = {"resolution": {"ambiguous": True}}
    assert filter_graph(graph, tmp_path, {"src/main.py"})["edges"] == []
