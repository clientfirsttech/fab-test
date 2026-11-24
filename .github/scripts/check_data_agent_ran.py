"""Check the live Data Agent run asked every question and judged every answer.

A Data Agent answers agentically: the same question can pass one run and fail
the next, so this never judges which answers were right. The report shows that.
CI fails only when the tester itself did not work. `fab-test data-agent` exits 1
for findings, but also for a timeout, a promptfoo crash, or questions it could
not ask, so the exit code alone cannot tell "answers were wrong" from "the
tests never ran". This reads each envelope instead and fails when:

- the run did not complete (status error or skipped);
- fewer questions came back with a verdict than the suite asked.

The suite's question count comes from effective.promptfoo.yaml, which the run
writes beside its envelope.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

RESULTS = Path("fab-test-results/data_agent")


def problems(envelope: dict[str, Any], asked: int) -> list[str]:
    """Return why this run does not show the tester working, or [] when it does."""
    status = envelope.get("status")
    if status not in ("passed", "failed"):
        return [f"The run did not complete ({status}): {envelope.get('message', '')}"]
    judged = len(envelope.get("test_results") or [])
    if judged == 0 or judged < asked:
        return [f"{judged} of {asked} questions came back with a verdict."]
    return []


def _asked(folder: Path) -> int:
    suite = folder / "effective.promptfoo.yaml"
    if not suite.is_file():
        return 0
    return len((yaml.safe_load(suite.read_text(encoding="utf-8")) or {}).get("tests") or [])


def main(results: Path = RESULTS) -> int:
    """Print a verdict per run; return 1 when any run did not complete."""
    envelopes = sorted(results.glob("*/envelope.json"))
    if not envelopes:
        print(f"No Data Agent envelope under {results}: the run never got as far as writing one.")
        return 1
    failed = False
    for path in envelopes:
        envelope = json.loads(path.read_text(encoding="utf-8-sig"))
        asked = _asked(path.parent)
        found = problems(envelope, asked)
        if found:
            failed = True
            print(f"{path.parent.name}:")
            for problem in found:
                print(f"  {problem}")
        else:
            results_ = envelope["test_results"]
            passed = sum(1 for result in results_ if result.get("passed"))
            print(f"{path.parent.name}: all {len(results_)} questions answered "
                  f"({passed} passed, {len(results_) - passed} failed).")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
