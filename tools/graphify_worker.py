"""Isolated entry point for the optional, pinned upstream CLI."""

import importlib.metadata
import os
import sys
from pathlib import Path

if __name__ == "__main__":
    if importlib.metadata.version("graphifyy") != "0.9.81":
        raise SystemExit("Install the pinned tools/requirements-graphify.txt")
    if not Path(os.environ["GRAPHIFY_OUT"]).is_absolute():
        raise SystemExit("GRAPHIFY_OUT must be absolute before importing graphify")
    if len(sys.argv) < 2 or sys.argv[1] not in ("extract", "query"):
        raise SystemExit("Only local extract/query dispatch is supported")
    # Bypass upstream startup's skill-refresh/install discovery, not its extractor/query.
    from graphify.cli import dispatch_command

    dispatch_command(sys.argv[1])
