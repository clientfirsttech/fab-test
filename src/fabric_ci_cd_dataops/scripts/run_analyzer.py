#!/usr/bin/env python3
"""
Generic Analyzer Runner

Metadata-driven analyzer execution script that:
1. Reads analyzer configuration from analyzers.json
2. Constructs CLI command with parameter substitution
3. Executes analyzer with proper error handling
4. Reports results in structured format

Usage:
    python run_analyzer.py \
        --analyzer pqlint \
        --artifact-name SalesModel \
        --artifact-path .fabric/artifacts/SalesModel.SemanticModel \
        --artifact-type SemanticModel \
        --metadata-path .github/metadata/analyzers.json \
        [--workspace-id <workspace_id>] \
        [--environment <environment>] \
        [--terse]
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from ._cli_utils import terse_print


class AnalyzerRunner:
    """Execute analyzers based on metadata configuration."""

    def __init__(self, metadata_path: str):
        """Initialize with metadata file path."""
        self.metadata_path = Path(metadata_path)
        self.metadata = self._load_metadata()

    def _load_metadata(self) -> dict[str, Any]:
        """Load analyzer metadata from JSON file."""
        if not self.metadata_path.exists():
            raise FileNotFoundError(f"Metadata file not found: {self.metadata_path}")

        with open(self.metadata_path) as f:
            return json.load(f)

    def get_analyzer_config(self, analyzer_name: str) -> dict[str, Any]:
        """Get configuration for a specific analyzer."""
        analyzer_registry = self.metadata.get('analyzer_registry', {})

        if analyzer_name not in analyzer_registry:
            raise ValueError(
                f"Analyzer '{analyzer_name}' not found in registry. "
                f"Available: {list(analyzer_registry.keys())}"
            )

        return analyzer_registry[analyzer_name]

    def build_command(
        self,
        analyzer_config: dict[str, Any],
        artifact_name: str,
        artifact_path: str,
        workspace_id: str = "",
        environment: str = "",
        output_path: str = "",
    ) -> list[str]:
        """Build analyzer command with parameter substitution."""
        command = [analyzer_config['command']]

        # Substitute placeholders in arguments
        substitutions = {
            '{artifact_name}': artifact_name,
            '{artifact_path}': artifact_path,
            '{workspace_id}': workspace_id,
            '{environment}': environment,
            '{output_path}': output_path,
        }
        for arg in analyzer_config.get('args', []):
            substituted = arg
            for placeholder, value in substitutions.items():
                substituted = substituted.replace(placeholder, value)
            command.append(substituted)

        return command

    def run_analyzer(
        self,
        analyzer_name: str,
        artifact_name: str,
        artifact_path: str,
        artifact_type: str,
        workspace_id: str = "",
        environment: str = "",
        dry_run: bool = False,
        terse: bool = False,
    ) -> dict[str, Any]:
        """
        Execute an analyzer and return results.

        Returns:
            Dict with keys: success, exit_code, stdout, stderr, analyzer, artifact
        """
        analyzer_config = self.get_analyzer_config(analyzer_name)
        command = self.build_command(
            analyzer_config,
            artifact_name,
            artifact_path,
            workspace_id,
            environment
        )

        result = {
            'analyzer': analyzer_name,
            'artifact_name': artifact_name,
            'artifact_type': artifact_type,
            'artifact_path': artifact_path,
            'command': ' '.join(command),
            'description': analyzer_config.get('description', ''),
            'type': analyzer_config.get('type', 'unknown')
        }

        if dry_run:
            if not terse:
                print(f"[DRY RUN] Would execute: {' '.join(command)}")
            terse_print(terse, "SKIP", f"analyzer.{analyzer_name}", f"dry-run: {' '.join(command)}")
            result.update({
                'success': True,
                'exit_code': 0,
                'stdout': '[DRY RUN] No output',
                'stderr': '',
                'dry_run': True
            })
            return result

        if not terse:
            print(f"### 🔍 Running {analyzer_name} on {artifact_name}")
            print(f"**Type**: {artifact_type}")
            print(f"**Description**: {analyzer_config.get('description', 'N/A')}")
            print(f"**Command**: `{' '.join(command)}`")
            print()

        # Execute the analyzer command
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
                check=False,
            )

            expected_exit_code = analyzer_config.get('exit_code_success', 0)
            success = proc.returncode == expected_exit_code

            result.update({
                'success': success,
                'exit_code': proc.returncode,
                'stdout': proc.stdout,
                'stderr': proc.stderr
            })

            if success:
                terse_print(terse, "OK", f"analyzer.{analyzer_name}", f"{artifact_name} passed")
                if not terse:
                    print(f"✅ {analyzer_name}: PASSED")
                    if proc.stdout:
                        print(f"Output:\n{proc.stdout}")
            else:
                terse_print(
                    terse, "FAIL", f"analyzer.{analyzer_name}",
                    f"{artifact_name} failed (exit {proc.returncode})",
                )
                if not terse:
                    print(f"❌ {analyzer_name}: FAILED (exit code {proc.returncode})")
                    if proc.stderr:
                        print(f"Error output:\n{proc.stderr}")

        except subprocess.TimeoutExpired:
            result.update({
                'success': False,
                'exit_code': -1,
                'stdout': '',
                'stderr': 'Analyzer execution timed out after 5 minutes'
            })
            terse_print(terse, "FAIL", f"analyzer.{analyzer_name}", f"{artifact_name} timed out after 5 minutes")
            if not terse:
                print(f"❌ {analyzer_name}: TIMEOUT")

        except FileNotFoundError:
            # Analyzer tool not found - provide helpful error message
            result.update({
                'success': False,
                'exit_code': -1,
                'stdout': '',
                'stderr': (
                    f'Analyzer command not found: {analyzer_config["command"]}. '
                    'Please ensure the tool is installed and available in PATH.'
                ),
            })
            terse_print(terse, "ERROR", f"analyzer.{analyzer_name}", f"command not found: {analyzer_config['command']}")
            if not terse:
                print(f"❌ {analyzer_name}: COMMAND NOT FOUND")
                print(f"Please install {analyzer_config['command']} before running this analyzer")

        except Exception as e:  # noqa: BLE001 - one analyzer must not abort the run
            result.update({
                'success': False,
                'exit_code': -1,
                'stdout': '',
                'stderr': str(e)
            })
            terse_print(terse, "ERROR", f"analyzer.{analyzer_name}", str(e))
            if not terse:
                print(f"❌ {analyzer_name}: ERROR - {e}")

        return result


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Generic analyzer runner using metadata-driven configuration'
    )
    parser.add_argument(
        '--analyzer',
        required=True,
        help='Analyzer name (e.g., pqlint, pbir_inspector)'
    )
    parser.add_argument(
        '--artifact-name',
        required=True,
        help='Name of the artifact'
    )
    parser.add_argument(
        '--artifact-path',
        required=True,
        help='Path to artifact directory'
    )
    parser.add_argument(
        '--artifact-type',
        required=True,
        help='Type of artifact (SemanticModel, Report, etc.)'
    )
    parser.add_argument(
        '--metadata-path',
        default='.github/metadata/analyzers.json',
        help='Path to analyzers.json metadata file'
    )
    parser.add_argument(
        '--workspace-id',
        default='',
        help='Workspace ID (for dynamic analyzers)'
    )
    parser.add_argument(
        '--environment',
        default='',
        help='Target environment'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print command without executing'
    )
    parser.add_argument(
        '--output-json',
        help='Write results to JSON file'
    )
    parser.add_argument(
        '--terse',
        action='store_true',
        help=(
            'Emit machine-readable one-line summaries (OK/FAIL prefix). '
            'Suppresses decorative output; retains actionable context for agents.'
        ),
    )

    args = parser.parse_args()

    try:
        runner = AnalyzerRunner(args.metadata_path)
        result = runner.run_analyzer(
            analyzer_name=args.analyzer,
            artifact_name=args.artifact_name,
            artifact_path=args.artifact_path,
            artifact_type=args.artifact_type,
            workspace_id=args.workspace_id,
            environment=args.environment,
            dry_run=args.dry_run,
            terse=args.terse,
        )

        # Output JSON if requested
        if args.output_json:
            with open(args.output_json, 'w') as f:
                json.dump(result, f, indent=2)

        # Exit with appropriate code
        sys.exit(0 if result['success'] else 1)

    except Exception as e:  # noqa: BLE001 - CLI boundary: every failure becomes exit 1
        terse_print(args.terse, "ERROR", "analyzer_runner", str(e))
        if not args.terse:
            print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
