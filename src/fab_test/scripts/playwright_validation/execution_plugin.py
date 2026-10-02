"""pytest-playwright fixtures loaded only for an explicitly selected YAML."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Browser, Error

from .execution_config import resolve_execution_config
from .execution_runtime import EXECUTION_PATH, EXECUTION_RUN_ID, browser_connection_options


class ExecutionFixtures:
    """Registered after pytest-playwright so these fixtures override its defaults."""

    @pytest.fixture(scope="session")
    def execution_config(self):
        """Load the already validated execution selection in each worker."""
        return resolve_execution_config(os.environ[EXECUTION_PATH])

    @pytest.fixture(scope="session")
    def connect_options(self, execution_config) -> dict[str, Any] | None:
        """Use Azure only when explicitly configured; never silently fall back."""
        return browser_connection_options(execution_config, os.environ, os.environ[EXECUTION_RUN_ID])

    @pytest.fixture(scope="session")
    def browser_type_launch_args(self, browser_type_launch_args, execution_config) -> dict[str, Any]:
        """Apply the supported launch settings through the upstream fixture."""
        return {**browser_type_launch_args, **execution_config.launch}

    @pytest.fixture(scope="session")
    def browser_context_args(self, browser_context_args, execution_config) -> dict[str, Any]:
        """Apply supported browser context settings without changing test selection."""
        return {**browser_context_args, **execution_config.context}

    @pytest.fixture(scope="session")
    def launch_browser(self, launch_browser: Callable[..., Browser]) -> Callable[..., Browser]:
        """Sanitize connection errors before pytest can include credential-bearing logs."""
        def launch(**kwargs: Any) -> Browser:
            try:
                return launch_browser(**kwargs)
            except Error as error:
                status = re.search(r"(?:response|status)(?: code)?:?\s*(\d{3})", str(error), re.IGNORECASE)
                detail = f"HTTP {status.group(1)}" if status else type(error).__name__
                pytest.fail(
                    f"Playwright browser setup failed ({detail}); check execution config and service credentials; "
                    "raw diagnostics withheld", pytrace=False,
                )

        return launch


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    config.pluginmanager.register(ExecutionFixtures(), "fab-test-execution-fixtures")
