"""Promptfoo entry point outside scripts, where fab_test.py would shadow the package."""

from fab_test.scripts.fabric_data_agent_provider import call_api

__all__ = ["call_api"]
