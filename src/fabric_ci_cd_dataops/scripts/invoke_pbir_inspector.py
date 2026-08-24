#!/usr/bin/env python3
"""
Invoke PBIR Inspector

Python wrapper for running PBIR Inspector against a Power BI report artifact.
Aligns with the project vision of Python-only analyzer invocation.

Usage:
    python invoke_pbir_inspector.py \
        --artifact-path ".fabric/artifacts/SalesReport.Report" \
        --rules-path ".github/metadata/rules/pbi-inspector-custom-rules.json" \
        --inspector-path "./PBIR-Inspector/PBIRInspectorCLI" \
        --output-path "./pbir-results.json"
"""

import argparse
import base64
import contextlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from tabulate import tabulate

from ._analyzer_envelope import (
    Timer,
    build_envelope,
    envelope_path,
    native_output_path,
    write_envelope,
)

_VERBOSITY_LEVELS = {"summary": 0, "default": 1, "verbose": 2, "debug": 3}


def _verbosity() -> int:
    raw = os.environ.get("ANALYZER_VERBOSITY", "default").lower().strip()
    return _VERBOSITY_LEVELS.get(raw, 1)


# Default timeout for PBIR Inspector execution (seconds).
INSPECTOR_TIMEOUT_SECONDS = 120

# Default output path when the caller does not specify one.
DEFAULT_OUTPUT_PATH = "./pbir-results.json"


def log(message: str) -> None:
    """Print a GitHub Actions-friendly message.

    Routes to stderr when ANALYZER_OUTPUT_MODE=json (set by fab-test under
    --format json) so only the envelope write touches stdout/disk. Direct
    invocation without the env var is unchanged (stdout).
    """
    if os.environ.get("ANALYZER_OUTPUT_MODE", "").lower() == "json":
        print(message, file=sys.stderr)
    else:
        print(message)


def validate_path(path_str: str, description: str, must_exist: bool = True) -> Path:
    """Validate that a required path exists and return a Path object."""
    path = Path(path_str).resolve()
    if must_exist and not path.exists():
        print(f"::error::{description} not found: {path}", file=sys.stderr)
        sys.exit(1)
    return path


def ensure_executable(inspector_path: Path) -> None:
    """Ensure the inspector binary has executable permissions."""
    if not inspector_path.is_file():
        print(
            f"::error::PBIR Inspector binary not found: {inspector_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    if os.name == "posix" and not inspector_path.stat().st_mode & 0o111:
        try:
            inspector_path.chmod(inspector_path.stat().st_mode | 0o111)
        except OSError as e:
            print(
                f"::error::Failed to make PBIR Inspector executable: {e}",
                file=sys.stderr,
            )
            sys.exit(1)


def build_inspector_command(
    inspector_path: Path,
    artifact_path: Path,
    rules_path: Path,
    output_path: Path,
    output_format: str = "JSON",
    verbose: bool = True,
) -> list[str]:
    """Build the PBIR Inspector CLI command."""
    command: list[str] = [
        str(inspector_path),
        "-fabricitem",
        str(artifact_path),
        "-rules",
        str(rules_path),
        "-output",
        str(output_path),
        "-formats",
        output_format,
    ]
    if verbose:
        command.extend(["-verbose", "true"])
    return command


_BROKEN_FAVICON_LINK = '<link rel="icon" href="../icon/pbiinspector.png">'


def fix_favicon_link(report_path: Path, inspector_path: Path) -> None:
    """Inline TestRun.html's favicon so it survives leaving its install dir.

    FabInspCLI's template points the favicon at ``../icon/pbiinspector.png``,
    relative to where the template lives inside the FabInspCLI install --
    not the output directory where the generated report actually lands
    (``analyzer-results/pbir/...``), so the link 404s once opened from
    there. The icon file still exists next to the inspector binary, so it
    is read once and inlined as a data URI, the same technique the
    template already uses for its logo and page-wireframe images.

    Never raises: a missing report, a missing icon, or a template that no
    longer contains the expected marker all leave the report untouched
    rather than fail the pbir-test run over a cosmetic asset.
    """
    icon_path = inspector_path.parent / "Files" / "icon" / "pbiinspector.png"
    if not report_path.is_file() or not icon_path.is_file():
        return
    try:
        html = report_path.read_text(encoding="utf-8-sig")
    except OSError:
        return
    if _BROKEN_FAVICON_LINK not in html:
        return
    data_uri = "data:image/png;base64," + base64.b64encode(icon_path.read_bytes()).decode("ascii")
    html = html.replace(_BROKEN_FAVICON_LINK, f'<link rel="icon" href="{data_uri}">')
    with contextlib.suppress(OSError):
        report_path.write_text(html, encoding="utf-8")


_BROKEN_IMAGE_SRC_MARKER = 'return "PBIInspectorPNG\\\\" + this.Id + ".png"'
_INLINE_IMAGE_LOOKUP = "window.__pbirScreenshots"


def _inline_png_map(folder: Path) -> dict[str, str]:
    """Return ``{file stem: data URI}`` for every PNG in ``folder``.

    A file that cannot be read is skipped rather than failing the whole
    map -- one corrupt screenshot should not cost every other one its fix.
    """
    images: dict[str, str] = {}
    for png in sorted(folder.glob("*.png")):
        try:
            images[png.stem] = "data:image/png;base64," + base64.b64encode(
                png.read_bytes()
            ).decode("ascii")
        except OSError:
            continue
    return images


def fix_screenshot_images(report_path: Path) -> None:
    """Inline TestRun.html's per-object screenshots as base64 data URIs.

    FabInspCLI's own template builds each screenshot's ``src`` as
    ``PBIInspectorPNG\\<Id>.png`` -- a Windows-style relative path that
    404s the moment the report is opened from somewhere that didn't keep
    that exact sibling folder alongside it. The screenshots already ship
    next to the report (``PBIInspectorPNG/``), so they are read once and
    inlined the same way the favicon and the wireframe placeholder
    already are, via a lookup table the template's own ``src`` function
    checks first.

    Never raises: a missing ``PBIInspectorPNG`` folder, a report that no
    longer contains the expected template marker, or a file that cannot
    be read all leave the report untouched -- the same contract
    ``fix_favicon_link`` has. Also a no-op if the fix already ran once:
    the lookup table it injects is itself the marker that it has.
    """
    folder = report_path.parent / "PBIInspectorPNG"
    if not report_path.is_file() or not folder.is_dir():
        return
    try:
        html = report_path.read_text(encoding="utf-8-sig")
    except OSError:
        return
    if _BROKEN_IMAGE_SRC_MARKER not in html or _INLINE_IMAGE_LOOKUP in html:
        return
    images = _inline_png_map(folder)
    if not images:
        return
    # </ is escaped so a filename cannot prematurely close the <script> tag.
    payload = json.dumps(images).replace("</", "<\\/")
    lookup_script = f"<script>{_INLINE_IMAGE_LOOKUP} = {payload};</script>"
    fixed_src = (
        f"return ({_INLINE_IMAGE_LOOKUP} && {_INLINE_IMAGE_LOOKUP}[this.Id]) "
        '|| ("PBIInspectorPNG\\\\" + this.Id + ".png")'
    )
    html = html.replace(_BROKEN_IMAGE_SRC_MARKER, fixed_src)
    html = html.replace("</head>", f"{lookup_script}</head>", 1) if "</head>" in html else lookup_script + html
    with contextlib.suppress(OSError):
        report_path.write_text(html, encoding="utf-8")


def write_results(
    output_path: Path,
    status: str,
    findings: list[dict[str, Any]],
    artifact_path: Path,
    rules_path: Path,
    message: str = "",
    native_out: "Path | None" = None,
    native_html_out: "Path | None" = None,
    duration_ms: int = 0,
    test_results: list[dict[str, Any]] | None = None,
) -> None:
    """Write standardized PBIR Inspector envelope JSON."""
    env = build_envelope(
        analyzer="pbir_inspector",
        artifact_path=str(artifact_path),
        status=status,
        message=message,
        findings=findings,
        native_output_path_str=str(native_out) if native_out else "",
        duration_ms=duration_ms,
    )
    env["rules_file"] = str(rules_path)
    if native_html_out is not None:
        env["native_html_output_path"] = str(native_html_out)
    # Additive: every rule PBIR Inspector evaluated, passed or failed --
    # `findings` stays violations-only for callers already reading that
    # meaning. Mirrors BPA's `test_results` (HTML Report Format epic).
    env["test_results"] = test_results or []
    write_envelope(output_path, env)


def parse_findings(raw_text: str) -> list[dict[str, Any]]:
    """Parse PBIR Inspector JSON output into a list of findings."""
    if not raw_text.strip():
        return []

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return []

    if isinstance(parsed, list):
        return parsed

    if isinstance(parsed, dict):
        # Some versions wrap results under an "items" or "findings" key;
        # PBIR Inspector native output uses "Results".
        for key in ("findings", "items", "results", "Results"):
            value = parsed.get(key)
            if isinstance(value, list):
                return value

    return []


def _coerce_log_type(value: Any) -> int | None:
    """Normalize PBIR LogType to int, tolerating string-encoded values."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except (ValueError, TypeError):
            return None
    return None


def _is_error_finding(finding: dict[str, Any]) -> bool:
    """Return True if a PBIR finding should fail the build.

    PBIR Inspector uses ``LogType`` (0 = Error, 1 = Warning) and ``Pass``.
    A finding is only an error-level violation when ``LogType == 0`` **and**
    ``Pass == false``. Passed results are never violations, regardless of
    ``LogType``.
    """
    log_type = _coerce_log_type(finding.get("LogType"))
    return log_type == 0 and finding.get("Pass") is False


def _is_warning_finding(finding: dict[str, Any]) -> bool:
    """Return True if a PBIR finding is a warning-level violation."""
    return (
        _coerce_log_type(finding.get("LogType")) == 1
        and finding.get("Pass") is False
    )


def _is_violation(finding: dict[str, Any]) -> bool:
    """Return True if the finding represents an actionable violation."""
    return _is_error_finding(finding) or _is_warning_finding(finding)


def _page_name(finding: dict[str, Any]) -> str:
    """Extract a page name from a PBIR finding."""
    parent = finding.get("ParentDisplayName") or ""
    item_path = finding.get("ItemPath") or ""
    if parent:
        return parent
    if item_path:
        parts = [p for p in item_path.replace("\\", "/").split("/") if p]
        if parts:
            return parts[0]
    return ""


def _object_name(finding: dict[str, Any]) -> str:
    """Extract an object name from a PBIR finding."""
    item_path = finding.get("ItemPath") or ""
    if item_path:
        parts = [p for p in item_path.replace("\\", "/").split("/") if p]
        if parts:
            return parts[-1]
    return finding.get("ParentDisplayName") or ""


def _truncate(text: str, width: int) -> str:
    text = str(text).replace("\n", " ").replace("\r", "")
    if len(text) <= width:
        return text
    return text[: width - 3] + "..." if width > 3 else text[:width]


def _pbir_severity_label(finding: dict[str, Any]) -> str:
    """Return a severity label string for a PBIR finding."""
    return "Error" if _is_error_finding(finding) else "Warning"


def _pbir_severity_rank(finding: dict[str, Any]) -> int:
    """Return numeric severity rank for sorting PBIR findings (errors first)."""
    return 3 if _is_error_finding(finding) else 2


def _pbir_rule_id(finding: dict[str, Any]) -> str:
    """Return the best available rule id for a PBIR finding."""
    return (
        finding.get("RuleId")
        or finding.get("RuleID")
        or finding.get("ruleId")
        or finding.get("rule")
        or ""
    )


def _normalize_finding(finding: dict[str, Any]) -> dict[str, Any]:
    """Translate a PBIR Inspector result into the shared finding schema.

    The shared schema expects ``rule``, ``severity``, ``object``, and
    ``message``. PBIR Inspector uses ``RuleId``, ``LogType`` (0 = error,
    1 = warning), ``ParentDisplayName``, and ``Message``. The object
    field is surfaced as the page/display name so the verbose table is
    immediately actionable.
    """
    severity = "error" if _is_error_finding(finding) else "warning"
    return {
        "rule": _pbir_rule_id(finding),
        "severity": severity,
        "object": finding.get("ParentDisplayName") or "",
        "message": finding.get("Message") or "",
    }


def _pbir_status(finding: dict[str, Any]) -> str:
    """Map a PBIR finding to the pass/error/warning vocabulary test_results shares."""
    if _is_error_finding(finding):
        return "error"
    if _is_warning_finding(finding):
        return "warning"
    return "pass"


def _pbir_test_results(raw_findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one row per rule result PBIR Inspector evaluated, passed or failed.

    ``findings`` stays violations-only for the callers already reading
    that meaning (exit code, printed table); this is the full list --
    additive, same as BPA's ``_bpa_test_results`` -- so telemetry can see
    what ran even on a run with nothing to report.
    """
    return [{**_normalize_finding(f), "status": _pbir_status(f)} for f in raw_findings]


def _print_findings_table(findings: list[dict[str, Any]]) -> None:
    """Print normalized PBIR findings as a tabulate table aligned with BPA format."""
    if not findings:
        return

    try:
        tw = max(shutil.get_terminal_size().columns, 80)
    except OSError:
        tw = 120

    severity_rank = {"error": 3, "warning": 2}
    sorted_findings = sorted(
        findings,
        key=lambda f: (
            -severity_rank.get(f.get("severity"), 0),
            str(f.get("rule") or "").lower(),
            str(f.get("object") or "").lower(),
        ),
    )

    rows = [
        (
            _truncate(f.get("rule") or "", 25),
            _truncate((f.get("severity") or "").capitalize(), 10),
            _truncate(f.get("object") or "", 20),
            _truncate(f.get("message") or "", max(20, tw - 55)),
        )
        for f in sorted_findings
    ]

    log(
        tabulate(
            rows,
            headers=("Rule", "Severity", "Object", "Message"),
            tablefmt="simple",
            stralign="left",
        )
    )


def run_inspector(args: argparse.Namespace) -> int:
    """Run the PBIR Inspector analyzer and return an exit code."""
    artifact_path = validate_path(args.artifact_path, "Report artifact path")
    rules_path = validate_path(args.rules_path, "Rules file")
    inspector_path = validate_path(args.inspector_path, "PBIR Inspector binary")
    ensure_executable(inspector_path)

    artifact_stem = artifact_path.stem
    _env_out = envelope_path("pbir", artifact_stem)
    _nat_out = native_output_path("pbir", artifact_stem, "json")

    output_path = Path(args.output_path) if args.output_path else _env_out
    native_out = _nat_out
    emit_html: bool = getattr(args, "emit_html", False)
    native_html_out: Path | None = None

    level = _verbosity()

    if level >= _VERBOSITY_LEVELS["default"]:
        log("================================")
        log(f"PBIR Inspector  →  {artifact_stem}")
        log("================================")
        log(f"📋 Artifact: {artifact_path}")
        log(f"📏 Rules:    {rules_path}")
        log(f"🔧 Tool:     {inspector_path}")
        log(f"📊 Envelope: {output_path}")
        log(f"📄 Native JSON: {native_out}")
        if native_html_out:
            log(f"📄 Native HTML: {native_html_out}")
        log("")

    # Ensure output directories exist before invoking the tool.
    native_out.parent.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    formats = "JSON,HTML" if emit_html else "JSON"
    command = build_inspector_command(
        inspector_path=inspector_path,
        artifact_path=artifact_path,
        rules_path=rules_path,
        output_path=native_out,
        output_format=formats,
    )

    if level >= _VERBOSITY_LEVELS["debug"]:
        log(f"Executing: {' '.join(command)}")
        log("")

    with Timer() as timer:
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=INSPECTOR_TIMEOUT_SECONDS,
                stdin=subprocess.DEVNULL,
                check=False,
            )
        except subprocess.TimeoutExpired:
            message = (
                f"PBIR Inspector timed out after {INSPECTOR_TIMEOUT_SECONDS} seconds"
            )
            write_results(
                output_path,
                "timeout",
                [],
                artifact_path,
                rules_path,
                message=message,
                native_out=native_out,
            )
            print(f"::error::{message}", file=sys.stderr)
            return 1
        except FileNotFoundError:
            message = f"PBIR Inspector binary not found: {inspector_path}"
            write_results(
                output_path,
                "error",
                [],
                artifact_path,
                rules_path,
                message=message,
                native_out=native_out,
            )
            print(f"::error::{message}", file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001 - catch-all for wrapper safety
            message = f"Unexpected error running PBIR Inspector: {exc}"
            write_results(
                output_path,
                "error",
                [],
                artifact_path,
                rules_path,
                message=message,
                native_out=native_out,
            )
            print(f"::error::{message}", file=sys.stderr)
            return 1

    if level >= _VERBOSITY_LEVELS["debug"] and (proc.stdout or proc.stderr):
        log("--- stdout ---")
        log(proc.stdout or "(empty)")
        log("--- stderr ---")
        log(proc.stderr or "(empty)")
        log("")

    findings: list[dict[str, Any]] = []
    raw_text = ""
    if native_out.is_dir():
        json_files = sorted(
            native_out.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if json_files:
            try:
                # PBIR Inspector can write a UTF-8 BOM at the start of the
                # JSON file; utf-8-sig strips it before json.loads sees it.
                raw_text = json_files[0].read_text(encoding="utf-8-sig")
            except OSError:
                raw_text = ""
    elif native_out.exists():
        try:
            raw_text = native_out.read_text(encoding="utf-8-sig")
        except OSError:
            raw_text = ""

    if not raw_text.strip() and proc.stdout:
        raw_text = proc.stdout

    raw_findings = parse_findings(raw_text)
    findings = [_normalize_finding(f) for f in raw_findings if _is_violation(f)]
    test_results = _pbir_test_results(raw_findings)

    has_errors = any(f["severity"] == "error" for f in findings)

    if emit_html and native_out.is_dir():
        html_files = list(native_out.glob("*.html"))
        if html_files:
            native_html_out = html_files[0]
            fix_favicon_link(native_html_out, inspector_path)
            fix_screenshot_images(native_html_out)

    error_count = sum(1 for f in findings if f.get("severity") == "error")
    warning_count = sum(1 for f in findings if f.get("severity") == "warning")

    if not findings:
        message = "PBIR Inspector passed with no findings"
        write_results(
            output_path=output_path,
            status="passed",
            findings=[],
            artifact_path=artifact_path,
            rules_path=rules_path,
            message=message,
            native_out=native_out,
            native_html_out=native_html_out,
            duration_ms=timer.elapsed_ms,
            test_results=test_results,
        )
        if level >= _VERBOSITY_LEVELS["default"]:
            log(f"✅ {message}")
            log(f"📁 Envelope:    {output_path}")
            log(f"📄 Native JSON: {native_out}")
            if native_html_out:
                log(f"📄 Native HTML: {native_html_out}")
        return 0

    message = (
        f"PBIR Inspector found {len(findings)} finding(s) "
        f"(errors: {error_count}, warnings: {warning_count}, "
        f"exit code {proc.returncode})"
    )
    status = "failed" if has_errors else "warning"
    write_results(
        output_path=output_path,
        status=status,
        findings=findings,
        artifact_path=artifact_path,
        rules_path=rules_path,
        message=message,
        native_out=native_out,
        native_html_out=native_html_out,
        duration_ms=timer.elapsed_ms,
        test_results=test_results,
    )

    if level >= _VERBOSITY_LEVELS["default"]:
        log(f"📁 Envelope:    {output_path}")
        log(f"📄 Native JSON: {native_out}")
        if native_html_out:
            log(f"📄 Native HTML: {native_html_out}")

    if level >= _VERBOSITY_LEVELS["default"] and findings:
        log(
            f"📊 {len(findings)} finding(s) "
            f"({error_count} error(s), {warning_count} warning(s))"
        )

    if level >= _VERBOSITY_LEVELS["verbose"]:
        _print_findings_table(findings)

    if proc.stderr:
        print(f"::error::{proc.stderr}", file=sys.stderr)

    annotation = "::error::" if has_errors else "::warning::"
    print(f"{annotation}{message}", file=sys.stderr)
    return 1 if has_errors else 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run PBIR Inspector from Python"
    )
    parser.add_argument(
        "--artifact-path",
        required=True,
        help="Path to the report artifact directory (PBIR)",
    )
    parser.add_argument(
        "--rules-path",
        required=True,
        help="Path to the PBIR Inspector rules JSON file",
    )
    parser.add_argument(
        "--inspector-path",
        required=True,
        help="Path to the PBIR Inspector CLI binary",
    )
    parser.add_argument(
        "--output-path",
        default=None,
        help=(
            "Path where the PBIR Inspector envelope JSON will be written "
            "(default: analyzer-results/pbir/<stem>/envelope.json)"
        ),
    )
    parser.add_argument(
        "--emit-html",
        action="store_true",
        default=False,
        help="Also emit HTML output to native.html/ alongside native.json/",
    )
    parser.add_argument(
        "--verbose",
        "--v",
        action="store_true",
        default=False,
        help="Enable verbose output (prints findings table and paths)",
    )

    args = parser.parse_args()
    if args.verbose:
        os.environ["ANALYZER_VERBOSITY"] = "verbose"
    return run_inspector(args)


if __name__ == "__main__":
    sys.exit(main())
