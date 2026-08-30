"""Configuration loader for Playwright visual validation.

Values are read from environment variables and/or an ``.env`` file. The ``.env``
file path defaults to the repository root but can be overridden with
``PLAYWRIGHT_ENV_FILE``. Secrets (client id/secret, tenant id) are read only from
the environment or the env file; they are never persisted to generated test-case
artifacts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    """Return the repository root.

    In CI the runner checks out the repo into ``GITHUB_WORKSPACE``. Otherwise use
    the current working directory so fab-test operates on the repo it is invoked
    from.
    """
    workspace = os.getenv("GITHUB_WORKSPACE")
    if workspace:
        return Path(workspace).resolve()
    return Path.cwd().resolve()


def resolve_env_file(explicit: Path | str | None = None) -> Path:
    """Return the ``.env`` file both credential callers should read.

    Search order: ``explicit`` (``--env-file``) > ``PLAYWRIGHT_ENV_FILE`` >
    ``.fab-test/.env`` > ``./.env``. Defined once, here, so
    ``_credentials.py`` and this loader -- which used to default to a bare
    ``Path(".env")`` and ``repo_root / ".env"`` respectively, and therefore
    agreed only when invoked from the repository root -- cannot drift
    apart again. ``.fab-test/.env`` is preferred over the root when both
    exist: it is the location `fab-test init` scaffolds and guards with its
    own ``.gitignore``, rather than depending on a consumer's root
    ``.gitignore`` already covering ``.env``.
    """
    if explicit is not None:
        return Path(explicit).resolve()

    env_var = os.getenv("PLAYWRIGHT_ENV_FILE")
    if env_var:
        return Path(env_var).resolve()

    repo_root = _repo_root()
    fab_test_env = repo_root / ".fab-test" / ".env"
    if fab_test_env.exists():
        return fab_test_env
    return (repo_root / ".env").resolve()


def _api_root_for(cloud: str) -> str:
    """Return the Power BI REST API root URL for the named cloud.

    Mirrors the mapping in ``power_bi_api.py`` so dependent modules can reuse
    the same endpoint selection without importing the API helper.
    """
    mapping = {
        "public": "https://api.powerbi.com",
        "germany": "https://api.powerbi.de",
        "china": "https://api.powerbi.cn",
        "usgov": "https://api.powerbigov.us",
        "usgovhigh": "https://api.powerbigov.us",
        "usgovdod": "https://api.powerbigov.us",
    }
    return mapping.get(cloud.lower(), mapping["public"])


def _app_root_for(cloud: str) -> str:
    """Return the interactive Power BI app root URL for the named cloud.

    Distinct from ``_api_root_for``: this is the host a person's browser
    opens (``app.powerbi.com``), not the REST API host (``api.powerbi.com``).
    Used to build a deep link from a Playwright test case straight back to
    the report page/bookmark it validated.
    """
    mapping = {
        "public": "https://app.powerbi.com",
        "germany": "https://app.powerbi.de",
        "china": "https://app.powerbi.cn",
        "usgov": "https://app.powerbigov.us",
        "usgovhigh": "https://app.powerbigov.us",
        "usgovdod": "https://app.powerbigov.us",
    }
    return mapping.get(cloud.lower(), mapping["public"])


def _fabric_api_root_for(cloud: str) -> str:
    """Return the Fabric REST API root URL for the named cloud.

    Fabric workspaces and items are exposed through the Fabric REST API,
    separate from the Power BI REST API used for report embedding and
    semantic-model dependents.
    """
    mapping = {
        "public": "https://api.fabric.microsoft.com",
        "germany": "https://api.fabric.microsoft.de",
        "china": "https://api.fabric.microsoft.cn",
        "usgov": "https://api.fabric.microsoft.us",
        "usgovhigh": "https://api.fabric.microsoft.us",
        "usgovdod": "https://api.fabric.microsoft.us",
    }
    return mapping.get(cloud.lower(), mapping["public"])


@dataclass(frozen=True)
class PlaywrightValidationConfig:
    """Static configuration for one report validation target.

    The ``workspace_id``, ``report_id``, ``dataset_id``, and optional page/bookmark
    lists define the matrix of browser tests to execute.
    """

    workspace_id: str
    report_id: str
    report_name: str
    dataset_id: str
    page_ids: list[str]
    bookmark_ids: list[str]
    user_name: str
    role: str
    use_rls: bool
    cloud: str
    client_id: str
    client_secret: str
    tenant_id: str
    timeout_seconds: int
    headless: bool

    def to_test_case_dict(self) -> dict[str, Any]:
        """Return non-secret fields as a dictionary for test-case generation."""
        return {
            "workspace_id": self.workspace_id,
            "report_id": self.report_id,
            "report_name": self.report_name,
            "dataset_id": self.dataset_id,
            "page_ids": self.page_ids,
            "bookmark_ids": self.bookmark_ids,
            "user_name": self.user_name,
            "role": self.role,
            "use_rls": self.use_rls,
            "cloud": self.cloud,
            "timeout_seconds": self.timeout_seconds,
        }


def _split_comma(value: str | None) -> list[str]:
    """Split a comma-separated string, returning an empty list for empty/None input."""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_env_file(env_file: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file without mutating ``os.environ``."""
    values: dict[str, str] = {}
    if not env_file.exists():
        return values
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _env_or_env_file(name: str, env_file: Path | None = None) -> str:
    """Return the value of an environment variable, falling back to an env file.

    Environment variables take precedence over the env file. The env file is
    parsed without mutating ``os.environ`` so tests stay isolated.
    """
    env_value = os.getenv(name, "")
    if env_value:
        return env_value

    if env_file and env_file.exists():
        return _parse_env_file(env_file).get(name, "")

    return ""


def load_config(
    env_file: Path | str | None = None,
    *,
    required: bool = True,
) -> PlaywrightValidationConfig:
    """Load Playwright validation configuration from environment and/or .env file.

    Args:
        env_file: Path to the env file. If None, defaults to ``.env`` in the repo
            root, or the path from ``PLAYWRIGHT_ENV_FILE`` if set.
        required: If True, raise ``ValueError`` when required values are missing.
            Set to False for dry-run/discovery scenarios.

    Returns:
        A populated ``PlaywrightValidationConfig``.

    Raises:
        ValueError: If required configuration is missing.
    """
    env_file = resolve_env_file(env_file)

    def get(name: str) -> str:
        return _env_or_env_file(name, env_file)

    page_ids = _split_comma(get("PLAYWRIGHT_PAGE_IDS"))
    bookmark_ids = _split_comma(get("PLAYWRIGHT_BOOKMARK_IDS"))

    def _bool(name: str, default: bool) -> bool:
        raw = get(name)
        if not raw:
            return default
        return raw.lower() not in {"false", "0", "no", ""}

    headless = _bool("PLAYWRIGHT_HEADLESS", True)
    use_rls = _bool("PLAYWRIGHT_USE_RLS", False)

    # Prefer the explicit Playwright credential names, but fall back to the
    # workflow-wide service principal secrets that artifact-runner.yml sets.
    client_id = get("FABRIC_CLIENT_ID") or get(
        "FABRIC_SERVICE_PRINCIPAL_ID"
    )
    client_secret = get("FABRIC_CLIENT_SECRET") or get(
        "FABRIC_SERVICE_PRINCIPAL_SECRET"
    )

    config = PlaywrightValidationConfig(
        workspace_id=get("PLAYWRIGHT_WORKSPACE_ID"),
        report_id=get("PLAYWRIGHT_REPORT_ID"),
        report_name=get("PLAYWRIGHT_REPORT_NAME"),
        dataset_id=get("PLAYWRIGHT_DATASET_ID"),
        page_ids=page_ids,
        bookmark_ids=bookmark_ids,
        user_name=get("PLAYWRIGHT_USER_NAME"),
        role=get("PLAYWRIGHT_ROLE"),
        use_rls=use_rls,
        cloud=get("PLAYWRIGHT_CLOUD") or "public",
        client_id=client_id,
        client_secret=client_secret,
        tenant_id=get("FABRIC_TENANT_ID"),
        timeout_seconds=int(get("PLAYWRIGHT_TIMEOUT_SECONDS") or "180"),
        headless=headless,
    )

    if required:
        missing = [
            name
            for name, value in {
                "PLAYWRIGHT_WORKSPACE_ID": config.workspace_id,
                "PLAYWRIGHT_REPORT_ID": config.report_id,
                "PLAYWRIGHT_DATASET_ID": config.dataset_id,
                "FABRIC_CLIENT_ID / FABRIC_SERVICE_PRINCIPAL_ID": (
                    config.client_id
                ),
                "FABRIC_CLIENT_SECRET / FABRIC_SERVICE_PRINCIPAL_SECRET": (
                    config.client_secret
                ),
                "FABRIC_TENANT_ID": config.tenant_id,
            }.items()
            if not value
        ]
        if missing:
            raise ValueError(
                f"Missing required Playwright validation config: {', '.join(missing)}"
            )

    return config
