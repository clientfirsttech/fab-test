#!/usr/bin/env python3
"""Scan repository files for common credential patterns."""

import json
import os
import re
import sys
from pathlib import Path

EXCLUDE_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.github/skills'}
EXCLUDE_EXTENSIONS = {'.pyc', '.so', '.dll', '.exe', '.bin', '.lock', '.png', '.jpg', '.gif'}
SAFE_FILES = {'README.md', 'CHANGELOG.md', 'LICENSE', '.gitignore'}
# Patterns that indicate documentation/examples, not real credentials
DOCUMENTATION_PATTERNS = {
    'code_example_marker': r'```|```(?:python|javascript|sql|powershell)',
    'example_comment': r'#\s*Example|//\s*Example|<!--\s*Example',
    'usage_comment': r'Usage:|EXAMPLE:|Example:',
}
# Special handling for .pbi files (Power BI local settings)
SKIP_FILE_PATTERNS = {r'\.pbi/localSettings\.json$'}

PATTERNS = {
    'aws_key': r'AKIA[0-9A-Z]{16}',
    'azure_storage_key': r'AccountKey=[A-Za-z0-9+/=]{88}',
    'github_token': r'ghp_[0-9a-zA-Z]{36}',
    'slack_token': r'xox[baprs]-[0-9a-zA-Z-]{10,}',
    'private_key': r'-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----',
    'api_key': r'[aA][pP][iI]_?[kK][eE][yY][\s]*[:=][\s]*["\']?[A-Za-z0-9_\-]{20,}["\']?',
    'password': r'[pP][aA][sS][sS][wW][oO][rR][dD][\s]*[:=][\s]*["\']?[^\s"\']{8,}["\']?',
    'secret': r'[sS][eE][cC][rR][eE][tT][\s]*[:=][\s]*["\']?[A-Za-z0-9_\-]{20,}["\']?',
    'token': r'[tT][oO][kK][eE][nN][\s]*[:=][\s]*["\']?[A-Za-z0-9_\-]{20,}["\']?',
    'connection_string': r'(Data Source|Server|Host)=.*(User ID|UID|Password|PWD)=[^;]+',
}


def scan_file_for_credentials(file_path: Path) -> list:
    """Scan a single file for credential patterns."""
    findings = []

    if file_path.name in SAFE_FILES:
        return findings

    # Skip specific file patterns (e.g., .pbi/localSettings.json - Power BI local dev files)
    file_path_str = str(file_path).replace('\\', '/')
    for skip_pattern in SKIP_FILE_PATTERNS:
        if re.search(skip_pattern, file_path_str):
            return findings

    # Skip documentation files in .github/skills
    if '.github/skills' in file_path_str and file_path.suffix in {'.md', '.yaml', '.yml'}:
        return findings

    try:
        with open(file_path, encoding='utf-8', errors='ignore') as f:
            content = f.read()

        for pattern_name, pattern in PATTERNS.items():
            for match in re.finditer(pattern, content, re.MULTILINE):
                line_num = content[:match.start()].count('\n') + 1

                # Get context around match to determine if it's documentation
                start = max(0, match.start() - 100)
                end = min(len(content), match.end() + 100)
                context = content[start:end]

                # Skip if this appears to be in documentation/examples
                is_documentation = False
                for doc_pattern in DOCUMENTATION_PATTERNS.values():
                    if re.search(doc_pattern, context, re.IGNORECASE):
                        is_documentation = True
                        break

                if not is_documentation:
                    findings.append({
                        'file': str(file_path),
                        'line': line_num,
                        'pattern': pattern_name,
                        'match_preview': match.group(0)[:60] + '...' if len(match.group(0)) > 60 else match.group(0),
                    })
    except Exception:
        pass  # Skip files that can't be read

    return findings


def main() -> int:
    all_findings = []
    for root, dirs, files in os.walk('.'):
        # Filter out excluded directories by name
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

        # Skip .github/skills directory and any subdirectories
        root_path = root.replace('\\', '/')
        if '.github/skills' in root_path:
            continue

        for file in files:
            file_path = Path(root) / file
            if file_path.suffix in EXCLUDE_EXTENSIONS:
                continue
            all_findings.extend(scan_file_for_credentials(file_path))

    result = {'findings': all_findings, 'count': len(all_findings)}
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
