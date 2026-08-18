#!/usr/bin/env python3
"""Aggregate findings from secret, entropy, and credential scans."""

import json
import sys


def load_findings(path: str, finding_type: str) -> list:
    """Load findings from a JSON file and tag them with a type."""
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        return []

    if finding_type == 'secret':
        return data.get('results', [])

    return [{'type': finding_type, **finding} for finding in data.get('findings', [])]


def main() -> int:
    all_findings = []
    all_findings.extend(load_findings('secret-findings.json', 'secret'))
    all_findings.extend(load_findings('entropy-findings.json', 'high-entropy'))
    all_findings.extend(load_findings('credential-findings.json', 'credential-pattern'))

    result = {'findings': all_findings, 'count': len(all_findings)}
    with open('security-findings.json', 'w') as f:
        json.dump(result, f, indent=2)

    print(f"Total findings: {len(all_findings)}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
