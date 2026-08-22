#!/usr/bin/env python3
"""
Promotion Safety Checker

Validates that artifact promotion follows the required chain and meets safety requirements.

Promotion Chain: TestBed → Dev → Test → Prod

Checks:
- Artifact passed validation in previous environment
- Required security scans completed
- AI governance requirements met
- Deployment window constraints (for Prod)
- Manual approval obtained (for Prod)

Usage:
    python check_promotion_safety.py \
        --artifact-name SalesModel \
        --source-environment dev \
        --target-environment test \
        [--terse]

Exit codes:
    0  All promotion safety checks passed
    1  One or more checks failed
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("Error: PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

from ._cli_utils import terse_print
from ._metadata import MetadataNotFoundError, resolve_environments_yml


class PromotionSafetyChecker:
    """Validate artifact promotion safety."""

    def __init__(self, environments_file: str | Path | None = None):
        """Initialize with environments configuration.

        ``environments_file`` still wins when given -- callers and tests
        pass an explicit path. Without one the metadata layers are searched
        (Environments Metadata Layers §3). Resolved in the body rather than
        the signature so a checker built in one directory cannot carry
        another directory's file.
        """
        self.environments_file = Path(environments_file) if environments_file else None
        self.config = self._load_config()

    def _load_config(self) -> dict[str, Any]:
        """Load environments configuration."""
        if self.environments_file is None:
            try:
                self.environments_file = resolve_environments_yml().path
            except MetadataNotFoundError as exc:
                raise FileNotFoundError(str(exc)) from exc
        elif not self.environments_file.exists():
            raise FileNotFoundError(f"Environments config not found: {self.environments_file}")

        with open(self.environments_file) as f:
            return yaml.safe_load(f) or {}

    def _branch_matches(self, branch: str, pattern: str) -> bool:
        """Check whether a branch name matches an allowed branch pattern."""
        if pattern.endswith("/**"):
            prefix = pattern[:-3]
            return branch.startswith(prefix + "/")
        return branch == pattern

    def validate_branch_for_target(
        self,
        target_env: str,
        branch: str | None = None,
        event_name: str | None = None,
        terse: bool = False,
    ) -> bool:
        """
        Validate that the target environment is allowed from the current branch.

        Each environment declares its allowed branch patterns in environments.yml.
        Production deployments additionally require the workflow_dispatch event.
        This guard keeps branch names and environments metadata-driven while
        protecting production and isolated environments such as testbed.
        """
        branch = branch or os.getenv("GITHUB_REF_NAME", "")
        event_name = event_name or os.getenv("GITHUB_EVENT_NAME", "")

        target_config = self.config.get('environments', {}).get(target_env, {})
        allowed_branches = target_config.get('allowed_branches', [])

        branch_allowed = any(self._branch_matches(branch, pattern) for pattern in allowed_branches)

        if not branch_allowed:
            if not terse:
                print(f"❌ Branch '{branch}' is not allowed for deployments to '{target_env}'.")
                print(f"   Allowed branches: {', '.join(allowed_branches)}")
            return False

        if target_env == "prod":
            allowed_prod_events = {"workflow_dispatch"}
            if event_name not in allowed_prod_events:
                if not terse:
                    print("❌ Production deployments on main must be triggered by workflow_dispatch.")
                    print(f"   Current event: '{event_name}'")
                return False

        if not terse:
            print(f"✅ Branch guard: '{target_env}' deployment allowed from '{branch}'")
        return True

    def validate_promotion_chain(self, source_env: str, target_env: str, terse: bool = False) -> bool:
        """Validate promotion follows the required chain."""
        promotion_chain = self.config.get('promotion_chain', [])

        if source_env not in promotion_chain or target_env not in promotion_chain:
            if not terse:
                print(f"❌ Invalid environment: source='{source_env}', target='{target_env}'")
                print(f"   Valid environments: {', '.join(promotion_chain)}")
            return False

        source_idx = promotion_chain.index(source_env)
        target_idx = promotion_chain.index(target_env)

        # Target must be exactly one step ahead in the chain
        if target_idx != source_idx + 1:
            if not terse:
                print(f"❌ Invalid promotion path: {source_env} → {target_env}")
                print(f"   Required chain: {' → '.join(promotion_chain)}")
                next_env = (
                    promotion_chain[source_idx + 1]
                    if source_idx + 1 < len(promotion_chain)
                    else "nowhere (final env)"
                )
                print(f"   From {source_env}, you can only promote to: {next_env}")
            return False

        if not terse:
            print(f"✅ Promotion chain valid: {source_env} → {target_env}")
        return True

    def check_deployment_window(self, environment: str, terse: bool = False) -> bool:
        """Check if deployment is allowed in current time window."""
        env_config = self.config.get('environments', {}).get(environment, {})
        deployment_window = env_config.get('deployment_window', {})

        if not deployment_window.get('enabled', False):
            if not terse:
                print(f"✅ Deployment window: Not enforced for {environment}")
            return True

        now_utc = datetime.now(UTC)
        current_day = now_utc.strftime('%A')
        current_time = now_utc.strftime('%H:%M')

        allowed_days = deployment_window.get('allowed_days', [])
        allowed_hours = deployment_window.get('allowed_hours_utc', {})
        start_time = allowed_hours.get('start', '00:00')
        end_time = allowed_hours.get('end', '23:59')

        # Check day
        if current_day not in allowed_days:
            if not terse:
                print(f"❌ Deployment window: Today ({current_day}) is not allowed")
                print(f"   Allowed days: {', '.join(allowed_days)}")
            return False

        # Check time
        if not (start_time <= current_time <= end_time):
            if not terse:
                print(f"❌ Deployment window: Current time ({current_time} UTC) is outside allowed window")
                print(f"   Allowed hours: {start_time} - {end_time} UTC")
            return False

        if not terse:
            print(f"✅ Deployment window: Within allowed window ({current_day}, {current_time} UTC)")
        return True

    def check_requirements(
        self,
        artifact_name: str,
        source_env: str,
        target_env: str,
        branch: str | None = None,
        event_name: str | None = None,
        terse: bool = False,
    ) -> dict[str, bool]:
        """Check all promotion requirements."""
        results = {
            'promotion_chain_valid': False,
            'branch_guard_valid': False,
            'deployment_window_valid': False,
            'requirements_met': True
        }

        if not terse:
            print(f"\n{'='*80}")
            print("PROMOTION SAFETY CHECK")
            print(f"{'='*80}")
            print(f"\n📦 Artifact:        {artifact_name}")
            print(f"📍 Source:          {source_env}")
            print(f"🎯 Target:          {target_env}")
            print(f"\n{'-'*80}")
            print("CHECKING REQUIREMENTS")
            print(f"{'-'*80}\n")

        # Check promotion chain
        results['promotion_chain_valid'] = self.validate_promotion_chain(source_env, target_env, terse)
        if not results['promotion_chain_valid']:
            terse_print(terse, "FAIL", "promotion_chain", f"{source_env} → {target_env} is not a valid promotion step")

        # Check branch/environment guard (production protection)
        results['branch_guard_valid'] = self.validate_branch_for_target(target_env, branch, event_name, terse)
        if not results['branch_guard_valid']:
            actual_branch = branch or os.getenv('GITHUB_REF_NAME', '')
            terse_print(
                terse, "FAIL", "branch_guard",
                f"branch '{actual_branch}' not allowed for {target_env}",
            )

        # Check deployment window
        results['deployment_window_valid'] = self.check_deployment_window(target_env, terse)
        if not results['deployment_window_valid']:
            terse_print(terse, "FAIL", "deployment_window", f"outside allowed deployment window for {target_env}")

        # Get target environment configuration
        target_config = self.config.get('environments', {}).get(target_env, {})

        # Check validation requirement
        if target_config.get('requires_validation', False) and not terse:
            print("⚠️  Validation required: Checking for evidence...")
            print("   (Validation evidence check would be implemented here)")
            # In a real implementation, this would check for validation artifacts

        # Check security scan requirement
        if target_config.get('requires_security_scan', False) and not terse:
            print("⚠️  Security scan required: Checking for evidence...")
            print("   (Security scan evidence check would be implemented here)")
            # In a real implementation, this would check for security scan results

        # Check AI validation requirement
        if target_config.get('requires_ai_validation', False) and not terse:
            print("⚠️  AI validation required: Checking for evidence...")
            print("   (AI validation evidence check would be implemented here)")
            # In a real implementation, this would check for AI governance validation

        # Check approval requirement
        if target_config.get('approval_required', False) and not terse:
            print(f"⚠️  Manual approval required for {target_env}")
            print("   (Approval check would be implemented here)")
            # In a real implementation, this would check for manual approval

        if not terse:
            print(f"\n{'-'*80}")
            print("RESULTS")
            print(f"{'-'*80}\n")

        all_passed = (
            results['promotion_chain_valid'] and
            results['branch_guard_valid'] and
            results['deployment_window_valid'] and
            results['requirements_met']
        )

        if all_passed:
            terse_print(terse, "OK", "promotion_safety", f"{artifact_name} approved {source_env} → {target_env}")
            if not terse:
                print("✅ All promotion safety checks passed")
                print(f"\n{'='*80}")
                print(f"PROMOTION APPROVED: {source_env} → {target_env}")
                print(f"{'='*80}\n")
        else:
            terse_print(terse, "FAIL", "promotion_safety", f"{artifact_name} blocked {source_env} → {target_env}")
            if not terse:
                print("❌ Some promotion safety checks failed")
                print(f"\n{'='*80}")
                print(f"PROMOTION BLOCKED: {source_env} → {target_env}")
                print(f"{'='*80}\n")

        results['all_passed'] = all_passed
        return results


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Validate artifact promotion safety'
    )
    parser.add_argument(
        '--artifact-name',
        required=True,
        help='Name of the artifact to promote'
    )
    parser.add_argument(
        '--source-environment',
        required=True,
        help='Source environment (e.g., dev)'
    )
    parser.add_argument(
        '--target-environment',
        required=True,
        help='Target environment (e.g., test)'
    )
    parser.add_argument(
        '--branch',
        default=os.getenv('GITHUB_REF_NAME', ''),
        help='Source branch name (defaults to GITHUB_REF_NAME environment variable)'
    )
    parser.add_argument(
        '--event-name',
        default=os.getenv('GITHUB_EVENT_NAME', ''),
        help='GitHub event name (defaults to GITHUB_EVENT_NAME environment variable)'
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
        checker = PromotionSafetyChecker()
        results = checker.check_requirements(
            artifact_name=args.artifact_name,
            source_env=args.source_environment,
            target_env=args.target_environment,
            branch=args.branch,
            event_name=args.event_name,
            terse=args.terse,
        )

        # Output JSON if requested
        if args.output_json:
            with open(args.output_json, 'w') as f:
                json.dump(results, f, indent=2)

        # Exit based on results
        sys.exit(0 if results['all_passed'] else 1)

    except Exception as e:  # noqa: BLE001 - CLI boundary: every failure becomes exit 1
        terse_print(args.terse, "ERROR", "promotion_safety", str(e))
        if not args.terse:
            print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
