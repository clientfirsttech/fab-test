"""Shared constants for fab_test.py and its split-out modules.

`fab_test.py`'s parser, telemetry, execution, admin, and local-bundle
extractions (Fab-Test Module Split epic) all read the same handful of
resolved paths and config defaults. Centralizing them here avoids a
circular import back into `fab_test.py` itself.
"""

from ._config import merged_file_config
from ._metadata import default_repo_root

# _metadata.default_repo_root is the one decider (see its docstring). When the
# package is installed as a wheel, __file__ points into site-packages, so
# resolving paths from the script location would be wrong -- the working
# directory is what `fab-test` operates on.
REPO_ROOT = default_repo_root()
SCRIPTS_DIR = REPO_ROOT / "scripts"
# Where discovery starts when nobody says otherwise. This was
# `.fabric/artifacts` -- this repository's CI layout, not anything Power BI
# Desktop or Fabric produces -- so the first command a new user typed
# failed against a directory they had never heard of, while `fab-test
# local` started here and found things. One answer to "where are my
# artifacts?", and it is the directory you are standing in.
ARTIFACT_ROOT = REPO_ROOT
# "analyzer-results" (pre-1.0.0.0) named nothing -- any repo already using
# another tool's directory of that name silently shared it, and a reader
# had no way to tell which tool wrote it. Renamed before the first release,
# so there is no installed base to keep working against the old name.
RESULTS_ROOT = REPO_ROOT / "fab-test-results"

_PYPROJECT_CONFIG, _FILE_CONFIG_WARNINGS = merged_file_config(REPO_ROOT, REPO_ROOT / "pyproject.toml")

# Default per-artifact subprocess timeout (seconds), used when neither
# --timeout nor ANALYZER_TIMEOUT is set. Matches the longest wrapper timeout:
# playwright's own render-wait budget (PLAYWRIGHT_TIMEOUT_SECONDS, default
# 180s) plus headroom for auth and browser startup.
_DEFAULT_SUBPROCESS_TIMEOUT = 200
