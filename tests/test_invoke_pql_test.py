"""Unit tests for scripts/invoke_pql_test.py."""

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

pytestmark = [pytest.mark.pql_test, pytest.mark.analyzers]


from fab_test.scripts._analyzer_envelope import ENVELOPE_REQUIRED_KEYS, WrapperResult
from fab_test.scripts.invoke_pql_test import (
    _parse_native_output,
    build_command,
    deployed_model,
    log,
    main,
    parse_findings,
    run_pql_test,
    validate_path,
    write_results,
)


class TestLog:
    """Tests for log(), the wrapper's human-banner choke point."""

    def test_log_routes_to_stdout_when_output_mode_absent(self, monkeypatch, capsys):
        """Direct invocation (no ANALYZER_OUTPUT_MODE) is unchanged: stdout."""
        monkeypatch.delenv("ANALYZER_OUTPUT_MODE", raising=False)
        log("hello")
        captured = capsys.readouterr()
        assert captured.out == "hello\n"
        assert captured.err == ""

    def test_log_routes_to_stderr_when_output_mode_json(self, monkeypatch, capsys):
        """fab-test sets ANALYZER_OUTPUT_MODE=json under --format json."""
        monkeypatch.setenv("ANALYZER_OUTPUT_MODE", "json")
        log("hello")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == "hello\n"


class TestValidatePath:
    """Tests for path validation."""

    def test_missing_path_exits(self, tmp_path: Path):
        """Missing artifact path exits with error."""
        missing = tmp_path / "missing"
        with pytest.raises(SystemExit) as exc_info:
            validate_path(str(missing), "Artifact path")
        assert exc_info.value.code == 1


class TestBuildCommand:
    """Tests for command builder."""

    def test_command_structure(self, tmp_path: Path):
        """Command includes run-tests subcommand and artifact path."""
        artifact = tmp_path / "SalesModel.SemanticModel"
        artifact.mkdir()
        output = tmp_path / "out.json"
        command = build_command(artifact, output_path=output)
        assert command[0] in {"pql-test", "pql_test", "python"}
        assert "run-tests" in command
        assert str(artifact) in command
        assert str(output) in command

    def test_deployed_model_is_passed_through_with_a_forward_slash(self, tmp_path: Path):
        """Service mode names a deployed model; pql-test reads its tests live.

        The name arrives through a Windows Path, so its separator may be a
        backslash. The workspace is in the name, so no --workspace-id.
        """
        model = Path("Sales Dev.Workspace") / "Sales.SemanticModel"
        command = build_command(model, output_path=tmp_path / "out.json", workspace_id="ws-guid")
        assert command[2] == "Sales Dev.Workspace/Sales.SemanticModel"
        assert "--workspace-id" not in command

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Dev.Workspace/Sales.SemanticModel", "Dev.Workspace/Sales.SemanticModel"),
            ("Dev.Workspace\\Sales.SemanticModel", "Dev.Workspace/Sales.SemanticModel"),
            ("fabric-artifacts/Sales.SemanticModel", None),
            ("C:\\repo\\Dev.Workspace\\Sales.SemanticModel", None),
        ],
    )
    def test_deployed_model_recognizes_only_the_workspace_form(self, raw, expected):
        assert deployed_model(raw) == expected

    def test_command_omits_credentials(self, tmp_path: Path):
        """Credentials are passed via environment, not command line."""
        artifact = tmp_path / "SalesModel.SemanticModel"
        artifact.mkdir()
        output = tmp_path / "out.json"
        command = build_command(artifact, output_path=output)
        assert "--tenant-id" not in command
        assert "--client-id" not in command
        assert "--client-secret" not in command

    def test_command_never_forwards_desktop_flags_to_pql_test_cli(self, tmp_path: Path):
        """--desktop-port/--desktop-model-name are fab-test bookkeeping only --
        pql-test's own CLI has no such flags, so build_command must never emit them.
        """
        artifact = tmp_path / "SalesModel.SemanticModel"
        artifact.mkdir()
        output = tmp_path / "out.json"
        command = build_command(artifact, output_path=output)
        assert "--desktop-port" not in command
        assert "--desktop-model-name" not in command


_FABRIC_SP_VARS = (
    "FABRIC_TENANT_ID",
    "FABRIC_SERVICE_PRINCIPAL_ID",
    "FABRIC_SERVICE_PRINCIPAL_SECRET",
    "FABRIC_CLIENT_ID",
    "FABRIC_CLIENT_SECRET",
)


class TestPqlEnv:
    """Tests for mapping Fabric credentials to pql-test env vars.

    pql-test must connect as the identity fab-test resolved, wherever that
    identity was configured -- otherwise it falls back to its own saved
    login and may not see the workspace fab-test listed.
    """

    @pytest.fixture(autouse=True)
    def _isolated(self, monkeypatch, tmp_path):
        for var in _FABRIC_SP_VARS:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("PLAYWRIGHT_ENV_FILE", str(tmp_path / "absent.env"))

    def test_pql_env_maps_fabric_client_alias_names(self, monkeypatch):
        """The FABRIC_CLIENT_* spelling fab-test accepts reaches pql-test too."""
        from fab_test.scripts.invoke_pql_test import _pql_env

        monkeypatch.setenv("FABRIC_TENANT_ID", "tenant-1")
        monkeypatch.setenv("FABRIC_CLIENT_ID", "client-1")
        monkeypatch.setenv("FABRIC_CLIENT_SECRET", "secret-1")
        env = _pql_env()
        assert (env["PQL_TENANT_ID"], env["PQL_CLIENT_ID"], env["PQL_CLIENT_SECRET"]) == (
            "tenant-1",
            "client-1",
            "secret-1",
        )

    def test_pql_env_maps_a_service_principal_from_the_env_file(self, monkeypatch, tmp_path):
        """A principal kept only in .fab-test/.env still reaches pql-test."""
        from fab_test.scripts.invoke_pql_test import _pql_env

        env_file = tmp_path / ".env"
        env_file.write_text(
            "FABRIC_TENANT_ID=tenant-2\nFABRIC_SERVICE_PRINCIPAL_ID=client-2\n"
            "FABRIC_SERVICE_PRINCIPAL_SECRET=secret-2\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("PLAYWRIGHT_ENV_FILE", str(env_file))
        env = _pql_env()
        assert (env["PQL_TENANT_ID"], env["PQL_CLIENT_ID"], env["PQL_CLIENT_SECRET"]) == (
            "tenant-2",
            "client-2",
            "secret-2",
        )

    def test_pql_env_maps_fabric_credentials(self, monkeypatch):
        """FABRIC_* env vars are mapped to PQL_* env vars."""
        from fab_test.scripts.invoke_pql_test import _pql_env

        monkeypatch.setenv("FABRIC_TENANT_ID", "tenant-1")
        monkeypatch.setenv("FABRIC_SERVICE_PRINCIPAL_ID", "client-1")
        monkeypatch.setenv("FABRIC_SERVICE_PRINCIPAL_SECRET", "secret-1")
        env = _pql_env()
        assert env["PQL_TENANT_ID"] == "tenant-1"
        assert env["PQL_CLIENT_ID"] == "client-1"
        assert env["PQL_CLIENT_SECRET"] == "secret-1"

    def test_pql_env_skips_missing_credentials(self, monkeypatch):
        """Missing Fabric credential env vars are not mapped."""
        from fab_test.scripts.invoke_pql_test import _pql_env

        monkeypatch.delenv("FABRIC_TENANT_ID", raising=False)
        monkeypatch.delenv("FABRIC_SERVICE_PRINCIPAL_ID", raising=False)
        monkeypatch.delenv("FABRIC_SERVICE_PRINCIPAL_SECRET", raising=False)
        env = _pql_env()
        assert "PQL_TENANT_ID" not in env
        assert "PQL_CLIENT_ID" not in env
        assert "PQL_CLIENT_SECRET" not in env

    def test_pql_env_maps_nothing_from_a_partial_service_principal(self, monkeypatch):
        """A half-set principal is a mistake fab-test reports, not one to hand on."""
        from fab_test.scripts.invoke_pql_test import _pql_env

        monkeypatch.setenv("FABRIC_TENANT_ID", "tenant-1")
        env = _pql_env()
        assert not {"PQL_TENANT_ID", "PQL_CLIENT_ID", "PQL_CLIENT_SECRET"} & env.keys()


class TestParseFindings:
    """Tests for output parsing."""

    def test_empty_string_returns_no_findings(self):
        """Empty output creates no findings."""
        assert parse_findings("") == []

    def test_dict_with_test_results_key(self):
        """A dict with test_results is parsed into findings."""
        raw = '{"test_results":[{"name":"TestOne","passed":false}]}'
        assert parse_findings(raw) == [{"name": "TestOne", "passed": False}]

    def test_dict_with_results_key(self):
        """A dict with results is parsed into findings."""
        raw = '{"results":[{"name":"TestOne","passed":false}]}'
        assert parse_findings(raw) == [{"name": "TestOne", "passed": False}]


class TestParseNativeOutput:
    """Tests for parsing the pql-test native JSON file."""

    def test_parses_counters_and_results(self, tmp_path: Path):
        """Native JSON with counters returns findings, results, and test_summary."""
        native_path = tmp_path / "native.json"
        native_path.write_text(
            json.dumps(
                {
                    "model_path": "model",
                    "passed": 76,
                    "failed": 10,
                    "skipped": 2,
                    "total": 88,
                    "results": [
                        {"test_name": "T1", "passed": True},
                        {
                            "test_name": "T2",
                            "passed": False,
                            "expected": "x",
                            "actual": "y",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        findings, results, test_summary = _parse_native_output(native_path)
        assert len(findings) == 1
        assert findings[0]["test_name"] == "T2"
        assert len(results) == 2
        assert test_summary == {"passed": 76, "failed": 10, "skipped": 2, "total": 88}

    def test_missing_file_returns_none(self, tmp_path: Path):
        """Given a missing native file, return None triple."""
        missing = tmp_path / "native.json"
        assert _parse_native_output(missing) == (None, None, None)

    def test_malformed_json_returns_none(self, tmp_path: Path):
        """Given malformed native JSON, return None triple without crashing."""
        native_path = tmp_path / "native.json"
        native_path.write_text("not json", encoding="utf-8")
        assert _parse_native_output(native_path) == (None, None, None)

    def test_skipped_results_are_not_findings(self, tmp_path: Path):
        """Skipped pql-test results must not be treated as findings."""
        native_path = tmp_path / "native.json"
        native_path.write_text(
            json.dumps(
                {
                    "model_path": "model",
                    "passed": 0,
                    "failed": 0,
                    "skipped": 3,
                    "total": 3,
                    "results": [
                        {"test_name": "T1", "passed": False, "skipped": True},
                        {"test_name": "T2", "passed": False, "skipped": True},
                        {"test_name": "T3", "passed": False, "skipped": True},
                    ],
                }
            ),
            encoding="utf-8",
        )
        findings, results, test_summary = _parse_native_output(native_path)
        assert findings == []
        assert len(results) == 3
        assert test_summary == {"passed": 0, "failed": 0, "skipped": 3, "total": 3}


class TestWriteResults:
    """Tests for result writer."""

    def test_results_written(self, tmp_path: Path):
        """Results JSON includes expected keys."""
        output_path = tmp_path / "results.json"
        artifact_path = tmp_path / "SalesModel.SemanticModel"
        artifact_path.mkdir()
        write_results(
            WrapperResult(
                output_path,
                "passed",
                [],
                artifact_path,
                message="OK",
                test_results=[{"name": "TestOne", "passed": True}],
            ),
        )

        data = json.loads(output_path.read_text(encoding="utf-8"))
        assert data["status"] == "passed"
        assert data["message"] == "OK"
        assert data["analyzer"] == "pql_test"
        assert data["findings"] == []
        assert data["test_results"][0]["name"] == "TestOne"

    def test_envelope_shape(self, tmp_path: Path):
        """Envelope contains every required key from the shared schema."""
        output_path = tmp_path / "envelope.json"
        write_results(WrapperResult(output_path, "passed", [], tmp_path / "model", message="OK"))
        data = json.loads(output_path.read_text(encoding="utf-8"))
        missing = ENVELOPE_REQUIRED_KEYS - data.keys()
        assert not missing, f"Envelope missing keys: {missing}"

    def test_envelope_includes_test_summary(self, tmp_path: Path):
        """Given a test_summary, envelope should include it."""
        output_path = tmp_path / "envelope.json"
        write_results(
            WrapperResult(
                output_path,
                "failed",
                [],
                tmp_path / "model",
                message="fail",
                test_summary={"total": 10, "passed": 8, "failed": 1, "skipped": 1},
            ),
        )
        data = json.loads(output_path.read_text(encoding="utf-8"))
        assert data["test_summary"] == {
            "total": 10,
            "passed": 8,
            "failed": 1,
            "skipped": 1,
        }

    def test_envelope_includes_desktop_info_when_provided(self, tmp_path: Path):
        """A bound Desktop instance's port and model name land in the envelope."""
        output_path = tmp_path / "envelope.json"
        write_results(
            WrapperResult(output_path, "passed", [], tmp_path / "model", message="OK"),
            desktop_port=51234,
            desktop_model_name="SampleModel",
        )
        data = json.loads(output_path.read_text(encoding="utf-8"))
        assert data["desktop"] == {"port": 51234, "model_name": "SampleModel"}

    def test_envelope_omits_desktop_key_when_not_bound(self, tmp_path: Path):
        """No Desktop binding means no 'desktop' key at all -- not a null placeholder."""
        output_path = tmp_path / "envelope.json"
        write_results(WrapperResult(output_path, "passed", [], tmp_path / "model", message="OK"))
        data = json.loads(output_path.read_text(encoding="utf-8"))
        assert "desktop" not in data


class TestVerbosity:
    """Tests for ANALYZER_VERBOSITY handling in run_pql_test."""

    @mock.patch("fab_test.scripts._analyzer_process.subprocess.run")
    def test_summary_suppresses_header(
        self, mock_run, tmp_path: Path, monkeypatch, capsys
    ):
        """Given ANALYZER_VERBOSITY=summary, wrapper prints no pql-test header."""
        monkeypatch.setenv("ANALYZER_VERBOSITY", "summary")
        artifact = tmp_path / "SalesModel.SemanticModel"
        artifact.mkdir()
        output = tmp_path / "out.json"
        mock_run.return_value = mock.Mock(
            returncode=0, stdout='{"test_results": []}', stderr=""
        )

        class Args:
            artifact_path = str(artifact)
            artifact_name = artifact.stem
            output_path = str(output)
            workspace_id = ""
            env = ""

        exit_code = run_pql_test(Args())
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "pql-test" not in captured.out.lower()

    @mock.patch("fab_test.scripts._analyzer_process.subprocess.run")
    def test_debug_includes_command(
        self, mock_run, tmp_path: Path, monkeypatch, capsys
    ):
        """Given ANALYZER_VERBOSITY=debug, wrapper prints the executed command."""
        monkeypatch.setenv("ANALYZER_VERBOSITY", "debug")
        artifact = tmp_path / "SalesModel.SemanticModel"
        artifact.mkdir()
        output = tmp_path / "out.json"
        mock_run.return_value = mock.Mock(
            returncode=0,
            stdout='{"test_results": []}',
            stderr="debug stderr",
        )

        class Args:
            artifact_path = str(artifact)
            artifact_name = artifact.stem
            output_path = str(output)
            workspace_id = ""
            env = ""

        exit_code = run_pql_test(Args())
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "Executing:" in captured.out
        assert "debug stderr" in captured.out


class TestRunPqlTest:
    """Tests for run_pql_test entry function."""

    @mock.patch("fab_test.scripts._analyzer_process.subprocess.run")
    def test_run_warns_when_a_clean_exit_ran_no_tests(self, mock_run, tmp_path: Path):
        """A clean exit having run nothing is a warning, not a pass.

        Zero tests passing is not a pass. A model that declares no tests --
        or one whose tests were never reached -- must not show the same
        green check as a model whose tests actually ran and passed.
        """
        artifact = tmp_path / "SalesModel.SemanticModel"
        artifact.mkdir()
        output = tmp_path / "out.json"
        mock_run.return_value = mock.Mock(
            returncode=0, stdout='{"test_results": []}', stderr=""
        )

        class Args:
            artifact_path = str(artifact)
            artifact_name = "SalesModel"
            output_path = str(output)
            workspace_id = ""
            env = ""

        exit_code = run_pql_test(Args())
        assert exit_code == 0
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "warning"
        assert data["test_results"] == []

    @mock.patch("fab_test.scripts.invoke_pql_test.native_output_path")
    @mock.patch("fab_test.scripts._analyzer_process.subprocess.run")
    def test_run_passes_when_tests_actually_ran_and_passed(
        self, mock_run, mock_native_path, tmp_path: Path
    ):
        """Tests that ran and passed still report passed."""
        artifact = tmp_path / "SalesModel.SemanticModel"
        artifact.mkdir()
        output = tmp_path / "out.json"
        nat_out = tmp_path / "native.json"
        mock_native_path.return_value = nat_out

        def _fake_run(*_a, **_k):
            nat_out.write_text(
                json.dumps(
                    {
                        "passed": 2,
                        "failed": 0,
                        "skipped": 0,
                        "total": 2,
                        "results": [
                            {"test_name": "T1", "suite_name": "S", "passed": True},
                            {"test_name": "T2", "suite_name": "S", "passed": True},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            return mock.Mock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = _fake_run

        class Args:
            artifact_path = str(artifact)
            artifact_name = "SalesModel"
            output_path = str(output)
            workspace_id = ""
            env = ""

        exit_code = run_pql_test(Args())
        assert exit_code == 0
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "passed"
        assert data["test_summary"]["passed"] == 2

    @mock.patch("fab_test.scripts._analyzer_process.subprocess.run")
    def test_run_writes_desktop_binding_to_envelope(self, mock_run, tmp_path: Path):
        """desktop_port/desktop_model_name args land in the written envelope."""
        artifact = tmp_path / "SalesModel.SemanticModel"
        artifact.mkdir()
        output = tmp_path / "out.json"
        mock_run.return_value = mock.Mock(
            returncode=0, stdout='{"test_results": []}', stderr=""
        )

        class Args:
            artifact_path = str(artifact)
            artifact_name = "SalesModel"
            output_path = str(output)
            workspace_id = ""
            env = ""
            desktop_port = "51234"
            desktop_model_name = "SalesModel"

        exit_code = run_pql_test(Args())
        assert exit_code == 0
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["desktop"] == {"port": 51234, "model_name": "SalesModel"}

    @mock.patch("fab_test.scripts._analyzer_process.subprocess.run")
    def test_run_fails_with_findings(self, mock_run, tmp_path: Path):
        """Failed execution writes a failed result with findings."""
        artifact = tmp_path / "SalesModel.SemanticModel"
        artifact.mkdir()
        output = tmp_path / "out.json"
        mock_run.return_value = mock.Mock(
            returncode=1,
            stdout='{"test_results":[{"name":"TestOne","passed":false}]}',
            stderr="",
        )

        class Args:
            artifact_path = str(artifact)
            artifact_name = "SalesModel"
            output_path = str(output)
            workspace_id = ""
            env = ""

        exit_code = run_pql_test(Args())
        assert exit_code == 1
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "failed"
        assert len(data["findings"]) == 1

    @mock.patch("fab_test.scripts._analyzer_process.subprocess.run")
    def test_run_warns_when_no_results_and_nonzero_exit(
        self, mock_run, tmp_path: Path
    ):
        """A run that produced no test results at all warns rather than failing.

        pql-test exits non-zero with no parsed test results when it never
        connected to a model -- most commonly a local Desktop session that
        closed or was never open. Nothing asserted wrong, so this is not a
        failure; nothing ran either, so it is not a pass.
        """
        artifact = tmp_path / "SalesModel.SemanticModel"
        artifact.mkdir()
        output = tmp_path / "out.json"
        mock_run.return_value = mock.Mock(
            returncode=1, stdout="", stderr="could not connect to model"
        )

        class Args:
            artifact_path = str(artifact)
            artifact_name = "SalesModel"
            output_path = str(output)
            workspace_id = ""
            env = ""

        exit_code = run_pql_test(Args())
        assert exit_code == 0
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "warning"
        assert data["findings"] == []

    @mock.patch("fab_test.scripts.invoke_pql_test.native_output_path")
    @mock.patch("fab_test.scripts._analyzer_process.subprocess.run")
    def test_run_warns_and_reports_no_tests_when_none_could_execute(
        self, mock_run, mock_native_path, tmp_path: Path
    ):
        """A closed Desktop file: pql-test finds tests statically but every
        execution fails with an ADOMD connection-refused error.

        The discovered count comes from scanning the model's TMDL, not from
        running anything, so the honest report is that no tests ran -- and
        that is a warning rather than a green pass, because a developer who
        believes their tests ran when they did not is worse off than one who
        is told nothing ran.
        """
        artifact = tmp_path / "SalesModel.SemanticModel"
        artifact.mkdir()
        output = tmp_path / "out.json"
        nat_out = tmp_path / "native.json"
        mock_native_path.return_value = nat_out

        connection_error = (
            "A connection cannot be made. Ensure that the server is running. "
            "---> System.Net.Sockets.SocketException: No connection could be "
            "made because the target machine actively refused it 127.0.0.1:61774"
        )
        native_payload = {
            "passed": 0,
            "failed": 2,
            "skipped": 0,
            "total": 2,
            "results": [
                {
                    "test_name": "Example.DEV.Tests",
                    "suite_name": "Example.DEV.Tests",
                    "passed": False,
                    "skipped": False,
                    "error": connection_error,
                },
                {
                    "test_name": "Schema.DEV.Tests",
                    "suite_name": "Schema.DEV.Tests",
                    "passed": False,
                    "skipped": False,
                    "error": connection_error,
                },
            ],
        }

        def _fake_run(*_a, **_k):
            nat_out.parent.mkdir(parents=True, exist_ok=True)
            nat_out.write_text(json.dumps(native_payload), encoding="utf-8")
            return mock.Mock(returncode=1, stdout="", stderr="")

        mock_run.side_effect = _fake_run

        class Args:
            artifact_path = str(artifact)
            artifact_name = "SalesModel"
            output_path = str(output)
            workspace_id = ""
            env = ""

        exit_code = run_pql_test(Args())
        # A platform gap must not turn CI red.
        assert exit_code == 0
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "warning"
        assert data["findings"] == []
        # Nothing executed, so no number of tests is the honest count.
        assert data["test_summary"] == {
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "total": 0,
        }
        assert data["test_results"] == []
        # The reason still has to reach the reader.
        assert "connect" in data["message"].lower()

    @mock.patch("fab_test.scripts.invoke_pql_test.native_output_path")
    @mock.patch("fab_test.scripts._analyzer_process.subprocess.run")
    def test_run_reports_failed_when_a_real_failure_accompanies_connection_errors(
        self, mock_run, mock_native_path, tmp_path: Path
    ):
        """A genuine assertion failure must never hide behind a connection skip.

        Even when other tests in the same run failed to connect, one real
        failure (no connection-error signature) means the run stays failed.
        """
        artifact = tmp_path / "SalesModel.SemanticModel"
        artifact.mkdir()
        output = tmp_path / "out.json"
        nat_out = tmp_path / "native.json"
        mock_native_path.return_value = nat_out

        connection_error = (
            "A connection cannot be made. Ensure that the server is running. "
            "---> System.Net.Sockets.SocketException: No connection could be "
            "made because the target machine actively refused it 127.0.0.1:61774"
        )
        native_payload = {
            "passed": 0,
            "failed": 2,
            "skipped": 0,
            "total": 2,
            "results": [
                {
                    "test_name": "Example.DEV.Tests",
                    "suite_name": "Example.DEV.Tests",
                    "passed": False,
                    "skipped": False,
                    "error": connection_error,
                },
                {
                    "test_name": "Schema.DEV.Tests",
                    "suite_name": "Schema.DEV.Tests",
                    "passed": False,
                    "skipped": False,
                    "expected": "5",
                    "actual": "3",
                    "error": "",
                },
            ],
        }

        def _fake_run(*_a, **_k):
            nat_out.parent.mkdir(parents=True, exist_ok=True)
            nat_out.write_text(json.dumps(native_payload), encoding="utf-8")
            return mock.Mock(returncode=1, stdout="", stderr="")

        mock_run.side_effect = _fake_run

        class Args:
            artifact_path = str(artifact)
            artifact_name = "SalesModel"
            output_path = str(output)
            workspace_id = ""
            env = ""

        exit_code = run_pql_test(Args())
        assert exit_code == 1
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "failed"
        assert len(data["findings"]) == 2

    @mock.patch("fab_test.scripts.invoke_pql_test.native_output_path")
    @mock.patch("fab_test.scripts._analyzer_process.subprocess.run")
    def test_run_creates_native_output_parent_dir(
        self, mock_run, mock_native_path, tmp_path: Path
    ):
        """The native output parent directory is created before invoking pql-test."""
        artifact = tmp_path / "SalesModel.SemanticModel"
        artifact.mkdir()
        output = tmp_path / "out.json"
        nat_out = tmp_path / "nested" / "native.json"
        mock_native_path.return_value = nat_out
        mock_run.return_value = mock.Mock(
            returncode=0, stdout='{"test_results": []}', stderr=""
        )

        class Args:
            artifact_path = str(artifact)
            artifact_name = "SalesModel"
            output_path = str(output)
            workspace_id = ""
            env = ""

        exit_code = run_pql_test(Args())
        assert exit_code == 0
        assert nat_out.parent.exists()


    @mock.patch("fab_test.scripts._analyzer_process.subprocess.run")
    def test_run_all_skipped_is_success(self, mock_run, tmp_path: Path):
        """An all-skipped test run exits 0 and writes status 'skipped'."""
        artifact = tmp_path / "SalesModel.SemanticModel"
        artifact.mkdir()
        output = tmp_path / "out.json"
        mock_run.return_value = mock.Mock(
            returncode=0,
            stdout=json.dumps(
                {
                    "passed": 0,
                    "failed": 0,
                    "skipped": 3,
                    "total": 3,
                    "results": [
                        {"test_name": "T1", "passed": False, "skipped": True},
                        {"test_name": "T2", "passed": False, "skipped": True},
                        {"test_name": "T3", "passed": False, "skipped": True},
                    ],
                }
            ),
            stderr="",
        )

        class Args:
            artifact_path = str(artifact)
            artifact_name = "SalesModel"
            output_path = str(output)
            workspace_id = ""
            env = ""

        exit_code = run_pql_test(Args())
        assert exit_code == 0
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "skipped"
        assert data["findings"] == []


class TestMain:
    """Tests for main entry point."""

    def test_main_invokes_runner(self, tmp_path: Path, monkeypatch):
        """Main forwards CLI arguments to the wrapper."""
        artifact = tmp_path / "SalesModel.SemanticModel"
        artifact.mkdir()
        output = tmp_path / "out.json"
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "invoke_pql_test.py",
                "--artifact-path",
                str(artifact),
                "--artifact-name",
                "SalesModel",
                "--output-path",
                str(output),
                "--env",
                "DEV",
            ],
        )
        with mock.patch("fab_test.scripts._analyzer_process.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=0, stdout='{"test_results": []}', stderr=""
            )
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0
