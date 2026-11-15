"""`fab-test pbir contract init`: build a report's slicer contract by asking (PBIR Slicer Default State epic).

The questions are data, so all three callers get the same ones:

- a human on a terminal is asked each in turn; Enter takes the suggestion
- an agent runs `--questions --format json`, asks the human what it can't
  decide, and applies the answers with `--answers FILE`
- with no terminal and no answers the command exits 2 and never waits

Per slicer the answer is `keep` (check today's selection), `calendar` (follow
the calendar, with the suggested format) or `{"calendar": "<format>"}`, or
`skip`. A missing answer takes the suggestion. The contract is written beside
the report as `<Report>.Report.odcs.yaml`; an existing one gains rules for
slicers it doesn't cover, keeps every rule it has, and changes one only with
--force. PyYAML drops comments, so a commented contract is rewritten only
with --force.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from ._pbir_slicers import Slicer, read_slicers
from ._slicer_calendar import FIELDS, CalendarError, calendar_fields, validate_calendar
from ._slicer_contract import ENGINE
from ._slicer_contract_run import CONTRACT_SUFFIX, report_logical_id

CHOICES = ("keep", "calendar", "skip")
_START = "calendar.fiscal_year_start_month"
_NAMED_BY = "calendar.fiscal_year_named_by"
_START_PREFERENCE = (1, 7, 10, 4, 2, 3, 5, 6, 8, 9, 11, 12)
_FORMATS = (
    "FY{fiscal_year_short}-S{fiscal_semester}", "FY{fiscal_year_short} S{fiscal_semester}",
    "FY{fiscal_year_short}-Q{fiscal_quarter}", "FY{fiscal_year_short} Q{fiscal_quarter}",
    "FY{fiscal_year}", "FY{fiscal_year_short}", "{year} H{half}", "{year}-H{half}", "H{half} {year}",
    "{year} Q{quarter}", "{year}-Q{quarter}", "Q{quarter} {year}", "{year}-{month:02}",
    "{year}", "{fiscal_year}",
)


class InitError(Exception):
    """A request the generator can't carry out; the message says how to fix it."""


def contract_main(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    try:
        report = _report(args)
        questions = build_questions(report, args.as_of or datetime.datetime.now(datetime.UTC).astimezone().date())
        if args.questions:
            _print(args, questions, _questions_text)
            return 0
        answers = _answers(args, questions)
        return _write(args, report, questions, answers)
    except (InitError, CalendarError) as exc:
        print(f"  ✗ fab-test pbir contract: {exc}", file=sys.stderr)
        return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fab-test pbir contract",
                                     description="Build a report's slicer contract (`fab-test pbir` checks it)")
    subs = parser.add_subparsers(dest="action", required=True)
    init = subs.add_parser("init", help="Create or extend <Report>.Report.odcs.yaml, asking how to check each slicer")
    init.add_argument("target", nargs="?", default=None, metavar="REPORT", help="Path to the .Report folder")
    init.add_argument("--artifact", default=None, metavar="NAME", help="Report name to find under --artifact-dir")
    init.add_argument("--artifact-dir", default=".", metavar="DIR", help="Where to look for --artifact [default: .]")
    init.add_argument("--as-of", default=None, dest="as_of", type=datetime.date.fromisoformat, metavar="YYYY-MM-DD",
                      help="Date used to suggest calendar formats [default: today]")
    init.add_argument("--questions", action="store_true", help="Print the questions and suggested answers, then stop")
    init.add_argument("--answers", default=None, metavar="FILE",
                      help="JSON answers by question id; unanswered questions take the suggestion")
    init.add_argument("--dry-run", action="store_true", help="Print the contract instead of writing it")
    init.add_argument("--force", action="store_true",
                      help="Replace rules that differ, and rewrite a commented contract")
    init.add_argument("--format", choices=("text", "json"), default="text", dest="output_format")
    return parser


def _report(args: argparse.Namespace) -> Path:
    if args.target:
        report = Path(args.target)
    elif args.artifact:
        name = args.artifact if args.artifact.endswith(".Report") else f"{args.artifact}.Report"
        found = sorted(Path(args.artifact_dir).rglob(name))
        report = found[0] if found else Path(args.artifact_dir) / name
    else:
        raise InitError("name the report: a path to its .Report folder, or --artifact NAME")
    if not (report / "definition" / "pages").is_dir():
        raise InitError(f"{report} is not a PBIR report folder (no definition/pages)")
    return report


def build_questions(report: Path, as_of: datetime.date) -> dict[str, Any]:
    slicers = read_slicers(report)
    questions = [_slicer_question(s, _rule_id(s, slicers[:i]), as_of) for i, s in enumerate(slicers)]
    starts = [q.pop("_starts") for q in questions if q.get("_starts")]
    reproduces = sorted(set.intersection(*map(set, starts))) if starts else list(range(1, 13))
    suggested_start = next((m for m in _START_PREFERENCE if m in reproduces), 1)
    questions.append({"id": _START, "prompt": "Which month does the fiscal year start in (1-12)?",
                      "suggested": suggested_start, "reproduces": reproduces, "needs_human": bool(starts)})
    questions.append({"id": _NAMED_BY, "prompt": "Is a fiscal year named by the calendar year it starts or ends in?",
                      "choices": ["end", "start"], "suggested": "end", "needs_human": bool(starts)})
    for q in questions:
        q.pop("_starts", None)
    return {"report": str(report), "contract": str(_contract_path(report)), "as_of": as_of.isoformat(),
            "questions": questions}


def _rule_id(slicer: Slicer, earlier: list[Slicer]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", f"{slicer.page} {slicer.column}".lower()).strip("-")
    taken = sum(1 for s in earlier if (s.page, s.column) == (slicer.page, slicer.column))
    return f"{base}-{taken + 1}" if taken else base


def _slicer_question(slicer: Slicer, rule_id: str, as_of: datetime.date) -> dict[str, Any]:
    question = {"id": rule_id, "page": slicer.page, "table": slicer.table, "column": slicer.column,
                "field": f"'{slicer.table}'[{slicer.column}]", "current": slicer.current,
                "prompt": f"{slicer.page}: '{slicer.table}'[{slicer.column}] opens with {_show(slicer.current)}. "
                          "Keep checking that, follow the calendar, or skip it?",
                "choices": list(CHOICES), "suggested": "keep", "needs_human": False}
    suggestion = _calendar_suggestion(slicer.current, as_of)
    if suggestion:
        question.update(suggested="calendar", calendar_format=suggestion[0], needs_human=True, _starts=suggestion[1])
    return question


def _show(current: dict) -> str:
    [(check, value)] = current.items()
    return json.dumps(value, default=str) if check != "selected" else (
        ", ".join(map(str, value)) or "no selection")


def _calendar_suggestion(current: dict, as_of: datetime.date) -> tuple[str, list[int]] | None:
    """The first format that reproduces a single current value today, and the fiscal starts that do."""
    values = current.get("selected") or []
    if len(values) != 1 or not isinstance(values[0], (str, int)) or isinstance(values[0], bool):
        return None
    for text in _FORMATS:
        starts = [start for start in range(1, 13) if _renders(text, as_of, start) == values[0]]
        if starts:
            return text, starts
    return None


def _renders(text: str, as_of: datetime.date, start: int) -> Any:
    fields = calendar_fields(as_of, {"fiscal_year_start_month": start, "fiscal_year_named_by": "end"})
    bare = text[1:-1] if text.startswith("{") and text.endswith("}") and text.count("{") == 1 else None
    return fields[bare] if bare in FIELDS else text.format_map(fields)


def _answers(args: argparse.Namespace, questions: dict) -> dict[str, Any]:
    if args.answers:
        try:
            given = json.loads(Path(args.answers).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise InitError(f"--answers {args.answers}: {exc}") from exc
    elif sys.stdin.isatty():
        given = _ask(questions["questions"])
    else:
        raise InitError("no terminal to ask on: run with --questions --format json to see the questions, "
                        "then pass --answers FILE (a JSON object of question id -> answer)")
    known = {q["id"]: q for q in questions["questions"]}
    unknown = sorted(set(given) - set(known))
    if unknown:
        raise InitError(f"--answers names unknown question(s): {', '.join(unknown)}")
    return {qid: given.get(qid, q["suggested"]) for qid, q in known.items()}


def _ask(questions: list[dict]) -> dict[str, Any]:
    answers: dict[str, Any] = {}
    for q in questions:
        if q["id"] in (_START, _NAMED_BY) and "calendar" not in answers.values():
            continue
        hint = f" (format {q['calendar_format']})" if q.get("calendar_format") else ""
        choices = "/".join(map(str, q.get("choices", []))) or "number"
        print(f"{q['prompt']}{hint}\n  [{choices}] default {q['suggested']}: ", end="")
        try:
            typed = input().strip()
        except EOFError:
            typed = ""
        answers[q["id"]] = (int(typed) if typed.isdigit() else typed) if typed else q["suggested"]
    return answers


def _rule(q: dict, answer: Any) -> dict[str, Any] | None:
    if answer == "skip":
        return None
    implementation: dict[str, Any] = {"page": q["page"], **q["current"]}
    if answer == "calendar" or isinstance(answer, dict):
        text = answer.get("calendar") if isinstance(answer, dict) else q.get("calendar_format")
        if not text:
            raise InitError(f"{q['id']}: no calendar format reproduces {_show(q['current'])} today; "
                            'answer {"calendar": "<format>"} to name one')
        implementation = {"page": q["page"], "selected": [text]}
    elif answer != "keep":
        raise InitError(f"{q['id']}: answer must be keep, calendar, skip or {{\"calendar\": \"<format>\"}}, "
                        f"got {answer!r}")
    return {"id": q["id"], "type": "custom", "engine": ENGINE, "implementation": implementation}


def _write(args: argparse.Namespace, report: Path, questions: dict, answers: dict) -> int:
    slicer_questions = [q for q in questions["questions"] if "page" in q]
    rules = [(q, r) for q in slicer_questions if (r := _rule(q, answers[q["id"]]))]
    calendar = None
    if any(r["implementation"].get("selected") and _is_calendar(r) for _, r in rules):
        calendar = {"fiscal_year_start_month": answers[_START], "fiscal_year_named_by": answers[_NAMED_BY]}
        validate_calendar(calendar)
    path = _contract_path(report)
    document, summary = _merge(path, report, rules, calendar, args.force)
    text = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    if not args.dry_run:
        path.write_text(text, encoding="utf-8")
    _print(args, {"contract": str(path), "written": not args.dry_run, **summary,
                  **({"content": text} if args.dry_run else {})},
           lambda s: text if args.dry_run else _summary_text(s))
    return 0


def _is_calendar(rule: dict) -> bool:
    return any(isinstance(v, str) and "{" in v for v in rule["implementation"].get("selected", []))


def _merge(path: Path, report: Path, rules: list, calendar: dict | None, force: bool):
    summary: dict[str, list[str]] = {"added": [], "kept": [], "replaced": [], "unchanged": []}
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if any(line.lstrip().startswith("#") for line in text.splitlines()) and not force:
            raise InitError(f"{path} has comments, which rewriting would drop; edit it by hand, "
                            "or pass --force to rewrite it (see the result first with --dry-run)")
        document = yaml.safe_load(text) or {}
    else:
        document = _new_document(report)
    properties = document.setdefault("customProperties", [])
    if calendar and not any(p.get("property") == "fabTestCalendar" for p in properties):
        properties.append({"property": "fabTestCalendar", "value": calendar})
    for q, rule in rules:
        quality = _column(document, q["table"], q["column"])
        existing = next((i for i, r in enumerate(quality) if r.get("id") == rule["id"]), None)
        if existing is None:
            quality.append(rule)
            summary["added"].append(rule["id"])
        elif quality[existing] == rule:
            summary["unchanged"].append(rule["id"])
        elif force:
            quality[existing] = rule
            summary["replaced"].append(rule["id"])
        else:
            summary["kept"].append(rule["id"])
    return document, summary


def _new_document(report: Path) -> dict[str, Any]:
    name = report.name.removesuffix(".Report")
    return {"apiVersion": "v3.1.0", "kind": "DataContract",
            "id": re.sub(r"[^a-z0-9]+", "-", f"{name} slicer defaults".lower()).strip("-"),
            "name": f"{name} slicer defaults", "version": "1.0.0", "status": "active",
            "customProperties": [{"property": "fabTestReport", "value": report_logical_id(report)}], "schema": []}


def _column(document: dict, table: str, column: str) -> list:
    """The quality list of ``table``.``column``, created if the contract doesn't have it yet."""
    entry = _named(document.setdefault("schema", []), table)
    return _named(entry.setdefault("properties", []), column).setdefault("quality", [])


def _named(items: list, name: str) -> dict:
    for item in items:
        if item.get("name") == name:
            return item
    items.append({"name": name})
    return items[-1]


def _contract_path(report: Path) -> Path:
    return report.parent / f"{report.name}{CONTRACT_SUFFIX}"


def _print(args: argparse.Namespace, payload: dict, as_text) -> None:
    print(json.dumps(payload, indent=2, default=str) if args.output_format == "json" else as_text(payload))


def _questions_text(questions: dict) -> str:
    lines = [f"Contract: {questions['contract']} (as of {questions['as_of']})"]
    for q in questions["questions"]:
        hint = f" -> {q['calendar_format']}" if q.get("calendar_format") else ""
        lines.append(f"  {q['id']}: {q['prompt']} [suggested: {q['suggested']}{hint}]")
    return "\n".join(lines)


def _summary_text(summary: dict) -> str:
    lines = [f"  ✓ {summary['contract']}"]
    lines += [f"    {key}: {', '.join(ids)}" for key, ids in summary.items() if isinstance(ids, list) and ids]
    if summary["kept"]:
        lines.append("    (kept rules differ from the report today; --force replaces them)")
    return "\n".join(lines)
