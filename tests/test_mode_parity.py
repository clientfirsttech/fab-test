"""Every service-capable analyzer takes the same mode flags and obeys quiet mode alike."""

from __future__ import annotations

import pytest

from fab_test.scripts import fab_test
from fab_test.scripts.fab_test_parser import build_parser

pytestmark = pytest.mark.fab_test

SERVICE_ANALYZERS = ["bpa", "pbir", "a11y", "rdl", "pql-test", "all"]


@pytest.mark.parametrize("analyzer", SERVICE_ANALYZERS)
def test_given_a_service_capable_analyzer_should_accept_the_same_mode_flags(analyzer):
    args = build_parser().parse_args(
        [analyzer, "--workspace", "Dev", "--keep-export", "--all", "--interactive", "--dry-run"]
    )

    assert (args.keep_export, args.all_items, args.interactive) == (True, True, True)
    assert (getattr(args, "service_workspace", "") or args.workspace_id) == "Dev"


@pytest.mark.parametrize("analyzer", SERVICE_ANALYZERS)
@pytest.mark.parametrize("silencer", [["-q"], ["--format", "json"]])
def test_given_quiet_or_json_should_print_no_mode_banner_for_any_analyzer(analyzer, silencer, capsys, monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("TF_BUILD", raising=False)
    parser = build_parser()
    args = parser.parse_args([analyzer, "--workspace", "00000000-0000-0000-0000-000000000001", *silencer])
    args.analyzer = fab_test._SUBCOMMAND_ALIASES.get(args.analyzer, args.analyzer)
    fab_test._prepare_target(args)

    assert "mode=" not in capsys.readouterr().err


@pytest.mark.parametrize("analyzer", SERVICE_ANALYZERS)
def test_given_a_workspace_should_print_the_mode_banner_for_any_analyzer(analyzer, capsys):
    args = build_parser().parse_args([analyzer, "--workspace", "00000000-0000-0000-0000-000000000001"])
    args.analyzer = fab_test._SUBCOMMAND_ALIASES.get(args.analyzer, args.analyzer)
    fab_test._prepare_target(args)

    assert "mode=service workspace=00000000-0000-0000-0000-000000000001" in capsys.readouterr().err
