"""Opt-in contributor CLI, separate from the shipped fab-test facade."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from graphify_index import local_cache, query, refresh, status
from graphify_metrics import record, report


def main() -> int:
    """Emit JSON; stale/missing indexing fails explicitly without blocking other tooling."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "refresh", "status", "report"):
        commands.add_parser(name)
    search = commands.add_parser("query")
    search.add_argument("question")
    search.add_argument("--budget", type=int, default=1500)
    measure = commands.add_parser("record", help="aggregate JSON on stdin; never prompts or transcripts")
    measure.add_argument("--observation", help="aggregate JSON, or omit to read stdin")
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        if args.command in ("build", "refresh"):
            result = refresh(root)
        elif args.command == "status":
            result = status(root)
        elif args.command == "query":
            result = query(root, args.question, args.budget)
        elif args.command == "record":
            result = record(local_cache(root), json.loads(args.observation or sys.stdin.read()))
        else:
            result = report(local_cache(root))
        print(json.dumps(result, allow_nan=False))
        return 1 if args.command in ("build", "refresh") and result["state"] != "fresh" else 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        # Process boundary: never echo raw upstream diagnostics or private input.
        print(json.dumps({"state": "error", "hint": (
            "Check aggregate fields/local index; build/query require graphifyy==0.9.81 "
            "in this Python and Linux/WSL unshare user/network namespaces. No unsafe fallback."
        )}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
