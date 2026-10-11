"""RDL Rule Settings epic: rule parameters are declared, typed and bounded
in the catalog, and an overlay can only set them to validated numbers."""

import json
import math
import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.rdl, pytest.mark.analyzers]

_REPO = Path(__file__).resolve().parent.parent
_CATALOG_PATH = _REPO / "src" / "fab_test" / "metadata" / "rules" / "rdl-rules.json"
_RULES = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))["rules"]


def _numeric_fields(rule: dict) -> set[str]:
    return {k for k, v in rule.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


class TestDeclaredSettings:
    @pytest.mark.parametrize("rule", _RULES, ids=lambda r: r["id"])
    def test_every_numeric_threshold_is_declared_and_nothing_else(self, rule):
        assert set(rule.get("settings", {})) == _numeric_fields(rule)

    @pytest.mark.parametrize(
        ("rule_id", "setting", "value_type", "low", "high"),
        [
            ("QRY-07", "max_lines", int, 1, 10000),
            ("PRM-03", "max_parameters", int, 1, 100),
            ("SUB-02", "max_subreports", int, 0, 49),
            ("DS-04", "min_similarity", float, 0.5, 1.0),
            ("ACC-06", "min_contrast", float, 1.0, 21.0),
            ("ACC-06", "min_contrast_large", float, 1.0, 21.0),
        ],
    )
    def test_each_tunable_rule_declares_its_setting(self, rule_id, setting, value_type, low, high):
        rule = next(r for r in _RULES if r["id"] == rule_id)
        spec = rule["settings"][setting]

        assert spec == {"type": "integer" if value_type is int else "number", "min": low, "max": high}

    @pytest.mark.parametrize(
        ("rule", "setting"),
        [(r, s) for r in _RULES for s in r.get("settings", {})],
        ids=lambda x: x["id"] if isinstance(x, dict) else x,
    )
    def test_the_packaged_default_is_inside_its_own_range(self, rule, setting):
        spec, value = rule["settings"][setting], rule[setting]

        assert spec["min"] <= value <= spec["max"]
        assert math.isfinite(value)
        assert spec["type"] == "number" or isinstance(value, int)


def _overlay(settings):
    from fab_test.scripts._rule_overlay import apply_rdl_overlay

    return apply_rdl_overlay(_CATALOG_PATH, {"settings": settings})


def _rule_in(resolved: dict, rule_id: str) -> dict:
    return next(r for r in resolved["rules"] if r["id"] == rule_id)


class TestSettingsOverlay:
    def test_overrides_a_declared_setting_for_the_run(self):
        resolved = _overlay({"QRY-07": {"max_lines": 80}})

        assert _rule_in(resolved, "QRY-07")["max_lines"] == 80

    def test_a_number_setting_accepts_a_whole_number(self):
        resolved = _overlay({"DS-04": {"min_similarity": 1}})

        assert _rule_in(resolved, "DS-04")["min_similarity"] == 1

    def test_never_rewrites_the_packaged_catalog(self):
        before = _CATALOG_PATH.read_bytes()

        _overlay({"QRY-07": {"max_lines": 80}})

        assert _CATALOG_PATH.read_bytes() == before

    @pytest.mark.parametrize(
        "value",
        [True, False, "80", None, [80], {"value": 80}, 80.5, math.nan, math.inf, -math.inf, 0, 10001,
         "__import__('os').system('calc')", "${{ secrets.TOKEN }}", "80; rm -rf /"],
        ids=repr,
    )
    def test_refuses_anything_but_an_in_range_number_of_the_declared_type(self, value):
        from fab_test.scripts._rule_overlay import RuleOverlayError

        with pytest.raises(RuleOverlayError, match=r"QRY-07\.max_lines"):
            _overlay({"QRY-07": {"max_lines": value}})

    def test_names_the_tunable_rules_for_an_unknown_rule(self):
        from fab_test.scripts._rule_overlay import RuleOverlayError

        with pytest.raises(RuleOverlayError, match="QRY-07"):
            _overlay({"NOPE-99": {"max_lines": 80}})

    def test_refuses_a_rule_with_nothing_to_tune(self):
        from fab_test.scripts._rule_overlay import RuleOverlayError

        with pytest.raises(RuleOverlayError, match="LAY-04"):
            _overlay({"LAY-04": {"max_lines": 80}})

    def test_names_the_valid_settings_for_an_unknown_setting(self):
        from fab_test.scripts._rule_overlay import RuleOverlayError

        with pytest.raises(RuleOverlayError, match="min_contrast, min_contrast_large"):
            _overlay({"ACC-06": {"contrast": 7}})

    @pytest.mark.parametrize("settings", [["QRY-07"], "QRY-07: 80", {"QRY-07": 80}], ids=repr)
    def test_refuses_settings_that_are_not_a_mapping_of_mappings(self, settings):
        from fab_test.scripts._rule_overlay import RuleOverlayError

        with pytest.raises(RuleOverlayError, match="settings"):
            _overlay(settings)

    def test_an_echoed_value_cannot_carry_terminal_control_characters(self):
        from fab_test.scripts._rule_overlay import RuleOverlayError

        with pytest.raises(RuleOverlayError) as caught:
            _overlay({"QRY-07": {"max_lines": "\x1b]0;pwned\x07" + "x" * 500}})

        message = str(caught.value)
        assert "\x1b" not in message and "\x07" not in message
        assert len(message) < 300


class TestOverlaySections:
    @pytest.mark.parametrize(
        ("rules", "named"),
        [
            ({"rdll": {"disable": ["LAY-04"]}}, "did you mean 'rdl'"),
            ({"rdl": {"setting": {"QRY-07": {"max_lines": 80}}}}, "did you mean 'settings'"),
            ({"rdl": ["LAY-04"]}, "rules.rdl"),
            ({"bpa": {"settings": {}}}, "rules.bpa.settings"),
            ({"rdl": {"settings": ["QRY-07"]}}, "rules.rdl.settings"),
        ],
        ids=repr,
    )
    def test_refuses_unknown_sections_and_keys(self, rules, named):
        from fab_test.scripts._config import ConfigError, validate_config

        with pytest.raises(ConfigError, match=re.escape(named)):
            validate_config({"rules": rules})

    def test_a_missing_extend_file_is_an_overlay_error(self, tmp_path):
        from fab_test.scripts._rule_overlay import RuleOverlayError, validate_rule_overlays
        from fab_test.scripts.fab_test_registry import PACKAGED_RULE_FILES

        with pytest.raises(RuleOverlayError, match="extend"):
            validate_rule_overlays({"rdl": {"extend": str(tmp_path / "missing.json")}}, PACKAGED_RULE_FILES)


class TestInvalidOverlayAtTheCli:
    def test_exits_2_on_one_line_and_runs_nothing(self, tmp_path):
        import os
        import subprocess
        import sys

        config = tmp_path / "fab-test.yml"
        overlay = "rules:\n  rdl:\n    settings:\n      QRY-07: {max_lines: '80; rm -rf /'}\n"
        config.write_text(overlay, encoding="utf-8")
        out = tmp_path / "out"
        env = {**os.environ, "PYTHONPATH": str(_REPO / "src"), "PYTHONIOENCODING": "utf-8"}
        env.pop("GITHUB_ACTIONS", None)

        result = subprocess.run(
            [sys.executable, "-m", "fab_test.scripts.fab_test", "--config", str(config), "rdl",
             "--artifact-dir", str(_REPO / "fabric-artifacts" / "QRY-07.PaginatedReport"), "--output-dir", str(out)],
            capture_output=True, text=True, encoding="utf-8", env=env, timeout=120, check=False,
        )

        assert result.returncode == 2
        assert [line.strip() for line in result.stderr.splitlines() if line.strip()] == [
            "✗ fab-test: rules.rdl.settings.QRY-07.max_lines must be a finite number, got '80; rm -rf /'"
        ]
        assert not (out / "rdl").exists()


def _disable(disable):
    from fab_test.scripts._rule_overlay import apply_rdl_overlay

    return apply_rdl_overlay(_CATALOG_PATH, {"disable": disable})


class TestDisableWithAReason:
    def test_a_reason_disables_the_rule_and_travels_with_it(self):
        rule = _rule_in(_disable({"LAY-04": "interactive sort is a product requirement"}), "LAY-04")

        assert rule["disabled"] is True
        assert rule["disabled_reason"] == "interactive sort is a product requirement"

    def test_the_list_form_still_disables(self):
        rule = _rule_in(_disable(["LAY-04"]), "LAY-04")

        assert rule["disabled"] is True
        assert "disabled_reason" not in rule

    @pytest.mark.parametrize(
        "reason",
        [123, None, ["why"], "", "   ", "x" * 201, "line one\nline two", "bell\x07", "\x1b[31mred"],
        ids=repr,
    )
    def test_refuses_a_reason_that_is_not_a_short_single_line_string(self, reason):
        from fab_test.scripts._rule_overlay import RuleOverlayError

        with pytest.raises(RuleOverlayError, match=r"LAY-04"):
            _disable({"LAY-04": reason})

    def test_an_unknown_rule_is_still_refused(self):
        from fab_test.scripts._rule_overlay import RuleOverlayError

        with pytest.raises(RuleOverlayError, match="NOPE-99"):
            _disable({"NOPE-99": "why"})

    def test_the_skip_row_says_why(self):
        from fab_test.scripts._rdl_lint import build_test_results, implemented_rule_ids

        rules = _disable({"LAY-04": "interactive sort is a product requirement"})["rules"]

        rows = build_test_results(rules, [], implemented_rule_ids(rules))
        row = next(r for r in rows if r["rule"] == "LAY-04")

        assert (row["status"], row["message"]) == ("skip", "disabled: interactive sort is a product requirement")

    def test_the_config_accepts_a_reason_map_for_rdl_only(self):
        from fab_test.scripts._config import ConfigError, validate_config

        validate_config({"rules": {"rdl": {"disable": {"LAY-04": "why"}}}})
        with pytest.raises(ConfigError, match=r"rules\.bpa\.disable"):
            validate_config({"rules": {"bpa": {"disable": {"RULE": "why"}}}})

    def test_markup_in_a_reason_reaches_the_report_as_text(self, tmp_path):
        import os
        import subprocess
        import sys

        config = tmp_path / "fab-test.yml"
        config.write_text(
            "rules:\n  rdl:\n    disable: {LAY-04: \"<script>alert(1)</script> & <b>bold</b>\"}\n", encoding="utf-8"
        )
        out = tmp_path / "out"
        env = {**os.environ, "PYTHONPATH": str(_REPO / "src"), "PYTHONIOENCODING": "utf-8"}
        env.pop("GITHUB_ACTIONS", None)

        result = subprocess.run(
            [sys.executable, "-m", "fab_test.scripts.fab_test", "--config", str(config), "rdl", "--report",
             "--artifact-dir", str(_REPO / "fabric-artifacts" / "LAY-04.PaginatedReport"), "--output-dir", str(out)],
            capture_output=True, text=True, encoding="utf-8", env=env, timeout=120, check=False,
        )

        envelope = json.loads((out / "rdl" / "LAY-04" / "envelope.json").read_text(encoding="utf-8"))
        row = next(r for r in envelope["test_results"] if r["rule"] == "LAY-04")
        html = next((out / "rdl" / "LAY-04").glob("*.html")).read_text(encoding="utf-8")
        assert result.returncode == 0, result.stderr
        assert row["message"] == "disabled: <script>alert(1)</script> & <b>bold</b>"
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; &lt;b&gt;bold&lt;/b&gt;" in html


def _uncommented_rdl_block(template: str) -> dict:
    """The template's `rules.rdl` block with its `# ` prefixes removed, parsed."""
    import yaml

    lines = template.splitlines()
    start = lines.index("#   rdl:")
    block = []
    for line in lines[start:]:
        if not line.startswith("#   "):
            break
        block.append(line[2:])
    return yaml.safe_load("rules:\n" + "\n".join(block))


class TestInitTemplate:
    def test_lists_every_declared_setting_at_its_packaged_default(self):
        from fab_test.scripts.fab_test_init import _FAB_TEST_YML_TEMPLATE

        settings = _uncommented_rdl_block(_FAB_TEST_YML_TEMPLATE)["rules"]["rdl"]["settings"]

        assert settings == {
            r["id"]: {name: r[name] for name in r["settings"]} for r in _RULES if r.get("settings")
        }

    def test_names_each_setting_range_beside_it(self):
        from fab_test.scripts.fab_test_init import _FAB_TEST_YML_TEMPLATE

        line = next(row for row in _FAB_TEST_YML_TEMPLATE.splitlines() if "QRY-07: {max_lines:" in row)

        assert "whole number 1-10000" in line and "Move complex SQL into views or procs" in line

    def test_the_uncommented_block_is_a_valid_config_that_changes_no_threshold(self):
        from fab_test.scripts._config import validate_config
        from fab_test.scripts._rule_overlay import apply_rdl_overlay, validate_rule_overlays
        from fab_test.scripts.fab_test_init import _FAB_TEST_YML_TEMPLATE
        from fab_test.scripts.fab_test_registry import PACKAGED_RULE_FILES

        config = _uncommented_rdl_block(_FAB_TEST_YML_TEMPLATE)
        validate_config(config)
        validate_rule_overlays(config["rules"], PACKAGED_RULE_FILES)
        resolved = apply_rdl_overlay(_CATALOG_PATH, {"settings": config["rules"]["rdl"]["settings"]})

        assert resolved["rules"] == [
            {**r} for r in json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))["rules"]
        ]

    def test_shows_a_disable_reason_and_no_extend(self):
        from fab_test.scripts.fab_test_init import _FAB_TEST_YML_TEMPLATE

        rdl = _uncommented_rdl_block(_FAB_TEST_YML_TEMPLATE)["rules"]["rdl"]

        assert isinstance(rdl["disable"], dict) and "extend" not in rdl


class TestEffectiveSettingsShown:
    def test_lists_each_overlay_delta_with_its_origin(self):
        from fab_test.scripts._rule_overlay import overlay_rows

        rows = overlay_rows({
            "rdl": {"disable": {"LAY-04": "product wants sort"}, "severity": {"QRY-07": "info"},
                    "settings": {"QRY-07": {"max_lines": 80}}},
            "bpa": {"disable": ["AVOID_FLOATING_POINT_DATA_TYPES"]},
        })

        assert rows == [
            {"key": "rules.bpa.disable.AVOID_FLOATING_POINT_DATA_TYPES", "value": "disabled",
             "origin": "fab-test.yml:rules.bpa.disable"},
            {"key": "rules.rdl.disable.LAY-04", "value": "disabled: product wants sort",
             "origin": "fab-test.yml:rules.rdl.disable"},
            {"key": "rules.rdl.severity.QRY-07", "value": "info", "origin": "fab-test.yml:rules.rdl.severity"},
            {"key": "rules.rdl.settings.QRY-07.max_lines", "value": 80, "origin": "fab-test.yml:rules.rdl.settings"},
        ]

    def test_config_show_prints_them(self, tmp_path):
        import os
        import subprocess
        import sys

        config = tmp_path / "fab-test.yml"
        config.write_text("rules:\n  rdl:\n    settings:\n      QRY-07: {max_lines: 80}\n", encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": str(_REPO / "src"), "PYTHONIOENCODING": "utf-8"}

        result = subprocess.run(
            [sys.executable, "-m", "fab_test.scripts.fab_test", "--config", str(config), "config", "--show",
             "--format", "json"],
            capture_output=True, text=True, encoding="utf-8", env=env, timeout=120, check=False,
        )

        rows = json.loads(result.stdout)
        rows = rows if isinstance(rows, list) else rows.get("settings", rows.get("rows", []))
        assert {"key": "rules.rdl.settings.QRY-07.max_lines", "value": 80,
                "origin": "fab-test.yml:rules.rdl.settings"} in rows


class TestEditorSchema:
    def test_the_rdl_overlay_schema_knows_settings_reasons_and_refuses_extend(self):
        schema_path = _REPO / "src" / "fab_test" / "schemas" / "fab-test.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        rdl = schema["$defs"][schema["properties"]["rules"]["properties"]["rdl"]["$ref"].rsplit("/", 1)[1]]

        assert set(rdl["properties"]) == {"disable", "severity", "settings"}
        assert rdl["additionalProperties"] is False
        reasons = next(option for option in rdl["properties"]["disable"]["oneOf"] if option["type"] == "object")
        assert reasons["additionalProperties"] == {"type": "string", "minLength": 1, "maxLength": 200}
        assert rdl["properties"]["settings"]["additionalProperties"]["additionalProperties"] == {"type": "number"}
