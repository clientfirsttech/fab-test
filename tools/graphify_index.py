"""Optional local AST index: fresh allowlisted inputs, isolated upstream execution."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

VERSION = "0.9.81"
UPSTREAM_REVISION = "622474b8ecc061d9921c3d68a749cf78378d63f3"
CACHE = ".graphify-local"
ROOTS = ("src/", "tests/", "tools/", ".github/scripts/")
DENIED = re.compile(
    r"(^|[/_.-])(agents?|skills?|vendor|vendored|node_modules|build|dist|cache|artifacts?|"
    r"fixtures?|personal|private|credentials?|secrets?|tokens?|passwords?|env|venv)([/_.-]|$)",
    re.IGNORECASE,
)


def local_cache(root: Path) -> Path:
    """Reject redirected local state rather than writing outside the repository."""
    cache = root / CACHE
    if cache.is_symlink():
        raise ValueError(".graphify-local must not be a symlink")
    if cache.exists() and any(file.is_symlink() for file in cache.iterdir()):
        raise ValueError(".graphify-local entries must not be symlinks")
    return cache


def snapshot(root: Path) -> tuple[dict[str, bytes], str]:
    """Fingerprint tracked eligible names and current bytes, including dirty/deleted files."""
    root = root.resolve()
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"], check=True, capture_output=True,
    ).stdout.decode("utf-8").split("\0")
    files = {}
    digest = hashlib.sha256(f"graphifyy:{VERSION}:policy:1".encode())
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"], capture_output=True, check=False,
    )
    digest.update(head.stdout.strip())
    for name in sorted(set(tracked)):
        if not name.startswith(ROOTS) or not name.endswith(".py") or DENIED.search(name):
            continue
        path = root / name
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError("eligible input must not be a symlink")
        if not path.resolve().is_relative_to(root):
            raise ValueError("eligible input is outside repository")
        digest.update(name.encode() + b"\0")
        if not path.exists():
            digest.update(b"deleted\0")
            continue
        if not path.is_file():
            raise ValueError("eligible input must be a regular file")
        content = path.read_bytes()
        files[name] = content
        digest.update(hashlib.sha256(content).digest())
    return files, digest.hexdigest()


def _ambiguous(item: dict) -> bool:
    return any(
        bool(value) if "ambig" in key.lower() else _ambiguous(value) if isinstance(value, dict) else False
        for key, value in item.items()
    )


def filter_graph(raw: dict, stage: Path, files: set[str]) -> dict:
    """Validate upstream raw AST schema and strip non-EXTRACTED relationships."""
    if not isinstance(raw, dict) or not all(isinstance(raw.get(key), list) for key in ("nodes", "edges")):
        raise ValueError("invalid upstream graph shape")
    ids = set()
    nodes = []
    for node in raw["nodes"]:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or node["id"] in ids:
            raise ValueError("invalid or duplicate node id")
        ids.add(node["id"])
        if node.get("confidence") not in (None, "EXTRACTED") or _ambiguous(node):
            continue
        source = node.get("source_file")
        if not isinstance(source, str):
            continue
        path = Path(source)
        if path.is_absolute():
            if not path.is_relative_to(stage):
                continue
            source = path.relative_to(stage).as_posix()
        if source not in files:
            continue
        kept = {key: node[key] for key in ("id", "label", "type", "source_location") if key in node}
        if kept.get("source_location") is None:
            kept.pop("source_location", None)
        if any(not isinstance(value, (str, int)) for value in kept.values()):
            raise ValueError("invalid node attributes")
        kept["id"] = kept["id"].replace(str(stage) + "/", "")
        kept["source_file"] = source
        nodes.append(kept)
    retained = {node["id"] for node in nodes}
    if len(retained) != len(nodes):
        raise ValueError("normalized node id collision")
    edges = []
    for edge in raw["edges"]:
        if not isinstance(edge, dict) or not {"source", "target"} <= edge.keys():
            raise ValueError("invalid edge")
        source, target = edge.get("source"), edge.get("target")
        if not isinstance(source, str) or not isinstance(target, str) or source not in ids or target not in ids:
            raise ValueError("invalid edge endpoints")
        source, target = (value.replace(str(stage) + "/", "") for value in (source, target))
        if edge.get("confidence") != "EXTRACTED" or _ambiguous(edge):
            continue
        if source not in retained or target not in retained:
            continue
        relation = edge.get("relation", "")
        if not isinstance(relation, str) or "ambig" in relation.lower():
            continue
        edges.append({"source": source, "target": target, "relation": relation, "confidence": "EXTRACTED"})
    return {"nodes": nodes, "edges": edges, "directed": True, "multigraph": False}


def run_graphify(stage: Path, output: Path, arguments: list[str]) -> str:
    """Run the pinned CLI in a Linux network namespace, never falling back to egress."""
    unshare = shutil.which("unshare")
    if sys.platform != "linux" or unshare is None:
        raise RuntimeError("network-isolation-unavailable: use Linux/WSL with unshare enabled")
    home = output.parent / "home"
    home.mkdir(exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", ""),
        "LANG": "C.UTF-8",
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home),
        "XDG_CACHE_HOME": str(home),
        "TMPDIR": str(home),
        "GRAPHIFY_OUT": str(output.resolve()),
        "GRAPHIFY_GOOGLE_WORKSPACE": "0",
        "GRAPHIFY_VIZ_NODE_LIMIT": "0",
        "GRAPHIFY_QUERY_LOG_DISABLE": "1",
        "GRAPHIFY_NO_TIPS": "1",
        "GRAPHIFY_NO_AUTO_REFRESH": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
    }
    worker = Path(__file__).with_name("graphify_worker.py").resolve()
    result = subprocess.run(
        [unshare, "--user", "--map-root-user", "--net", sys.executable, "-I", str(worker), *arguments],
        cwd=stage, env=env, capture_output=True, text=True, timeout=300, check=False,
    )
    if result.returncode:
        raise RuntimeError(
            "network-isolation-or-extraction-failed: enable unprivileged user/network namespaces "
            f"and install tools/requirements-graphify.txt in this Python environment (graphifyy=={VERSION})"
        )
    return result.stdout


def _read_index(cache: Path) -> dict | None:
    path = cache / "index.json"
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or "graph" not in value:
        raise ValueError("invalid local index; remove it and rebuild")
    graph = value["graph"]
    if not isinstance(graph, dict) or "nodes" not in graph or not isinstance(graph["nodes"], list):
        raise ValueError("invalid local graph shape; remove it and rebuild")
    if any(not isinstance(node, dict) or not isinstance(node.get("source_file"), str) for node in graph["nodes"]):
        raise ValueError("invalid local graph provenance; remove it and rebuild")
    # Revalidation prevents a tampered local cache from supplying inferred context.
    validated = filter_graph(graph, cache, {node["source_file"] for node in graph["nodes"]})
    if validated != graph:
        raise ValueError("local index is not EXTRACTED-only; rebuild")
    return value


def _verify_build(graph: dict, files: dict, root: Path, revision: str) -> None:
    if files and not graph["nodes"]:
        raise ValueError("empty extraction")
    if snapshot(root)[1] != revision:
        raise ValueError("inputs changed while extracting")


def status(root: Path) -> dict:
    """Report freshness without modifying state or installing Graphify."""
    cache = local_cache(root)
    index = _read_index(cache)
    _, revision = snapshot(root)
    failure_path = cache / "failure.json"
    failure = json.loads(failure_path.read_text(encoding="utf-8")) if failure_path.exists() else None
    state = "missing" if index is None else "fresh" if index.get("revision") == revision and not failure else "stale"
    return {
        "state": state, "revision": revision,
        "indexed_revision": index.get("revision") if index else None,
        "failure": failure, "graphifyy": VERSION,
        "nodes": len(index["graph"]["nodes"]) if index else 0,
        "edges": len(index["graph"]["edges"]) if index else 0,
        "hint": (
            "Refresh with pinned graphifyy==0.9.81 in this Python and Linux/WSL unshare "
            "user/network namespaces; otherwise inspect source directly."
        ) if state != "fresh" else None,
    }


def refresh(root: Path) -> dict:
    """Atomically replace a valid index; keep the last valid graph on failure."""
    cache = local_cache(root)
    before = status(root)
    if before["state"] == "fresh":
        return {**before, "changed": False, "maintenance_seconds": 0}
    files, revision = snapshot(root)
    cache.mkdir(exist_ok=True)
    stage = cache / f"stage-{uuid.uuid4().hex}"
    inputs, output = stage / "input", stage / "output"
    inputs.mkdir(parents=True)
    started = time.monotonic()
    try:
        for name, content in files.items():
            file = inputs / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(content)
        run_graphify(inputs, output, ["extract", str(inputs), "--code-only", "--no-cluster"])
        graph = filter_graph(json.loads((output / "graph.json").read_text(encoding="utf-8")), inputs, set(files))
        _verify_build(graph, files, root, revision)
        index = {"revision": revision, "upstream_revision": UPSTREAM_REVISION, "graphifyy": VERSION, "graph": graph}
        pending = stage / "index.json"
        pending.write_text(json.dumps(index), encoding="utf-8")
        pending.replace(cache / "index.json")
        (cache / "failure.json").unlink(missing_ok=True)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        (cache / "failure.json").write_text(json.dumps("extraction-failed"), encoding="utf-8")
    finally:
        shutil.rmtree(stage)
    return {**status(root), "changed": True, "maintenance_seconds": time.monotonic() - started}


def query(root: Path, question: str, budget: int = 1500) -> dict:
    """Read-only query of the last valid graph with explicit stale/missing state."""
    if not question.strip() or not 1 <= budget <= 10000:
        raise ValueError("query requires a nonempty question and budget 1..10000")
    current = status(root)
    if current["state"] == "missing":
        return {**current, "context": "", "hint": "run build, or use direct source inspection"}
    cache = local_cache(root)
    index = _read_index(cache)
    stage = cache / f"stage-{uuid.uuid4().hex}"
    stage.mkdir()
    try:
        graph = stage / "graph.json"
        graph.write_text(json.dumps(index["graph"]), encoding="utf-8")
        text = run_graphify(
            stage, stage / "output", ["query", question, "--budget", str(budget), "--graph", str(graph)],
        )
        return {**current, "context": text}
    finally:
        shutil.rmtree(stage)
