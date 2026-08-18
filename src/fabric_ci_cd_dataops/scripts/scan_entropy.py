#!/usr/bin/env python3
"""Scan repository files for high-entropy strings that may be secrets."""

import json
import math
import os
import re
import sys
from pathlib import Path

EXCLUDE_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv'}
EXCLUDE_EXTENSIONS = {'.pyc', '.so', '.dll', '.exe', '.lock', '.tmdl', '.pbix', '.pbit'}  # .tmdl/.pbix contain Base64-encoded data
THRESHOLD = 4.5


def calculate_entropy(data: str) -> float:
    """Calculate Shannon entropy of a string."""
    if not data:
        return 0.0

    entropy = 0.0
    length = len(data)
    for x in range(256):
        count = data.count(chr(x))
        if count == 0:
            continue
        p_x = count / length
        entropy -= p_x * math.log2(p_x)
    return entropy


def scan_file_for_high_entropy(file_path: Path, threshold: float = THRESHOLD) -> list:
    """Scan a single file for high-entropy strings."""
    findings = []
    patterns = [
        r'["\']([A-Za-z0-9+/=]{20,})["\']',
        r'=\s*([A-Za-z0-9+/=]{20,})',
        r':\s*["\']([A-Za-z0-9+/=]{20,})["\']',
    ]

    try:
        with open(file_path, encoding='utf-8', errors='ignore') as f:
            for line_num, line in enumerate(f, 1):
                for pattern in patterns:
                    for match in re.finditer(pattern, line):
                        value = match.group(1)
                        entropy = calculate_entropy(value)
                        if entropy > threshold:
                            findings.append({
                                'file': str(file_path),
                                'line': line_num,
                                'entropy': round(entropy, 2),
                                'value_preview': value[:40] + '...' if len(value) > 40 else value,
                            })
    except Exception:
        pass  # Skip files that can't be read

    return findings


def main() -> int:
    all_findings = []
    for root, dirs, files in os_walk_filtered():
        for file in files:
            file_path = Path(root) / file
            if file_path.suffix in EXCLUDE_EXTENSIONS:
                continue
            all_findings.extend(scan_file_for_high_entropy(file_path))

    result = {'findings': all_findings, 'count': len(all_findings)}
    print(json.dumps(result, indent=2))
    return 0


def os_walk_filtered():
    """Walk the current directory while excluding common directories."""
    for root, dirs, files in os.walk('.'):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

        # Skip .github/skills directory
        root_path = root.replace('\\', '/')
        if '.github/skills' in root_path:
            continue

        # Skip .pbi directories (Power BI local dev files with legitimate high-entropy values)
        if '/.pbi' in root_path:
            continue

        yield root, dirs, files


if __name__ == '__main__':
    sys.exit(main())
