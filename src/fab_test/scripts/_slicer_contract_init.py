"""`fab-test pbir contract init`: build a report's slicer contract by asking (PBIR Slicer Default State epic).

The questions are data, so all three callers get the same ones:

- a human on a terminal is asked each in turn (on stderr); Enter takes the suggestion
- an agent runs `--questions --format json`, asks the human what it can't
  decide, and applies the answers with `--answers FILE`
- with no terminal and no answers the command exits 2 and never waits

Per slicer the answer is `keep` (check today's selection), `calendar` (follow
the calendar, with the suggested format) or `{"calendar": "<format>"}`, or
`skip`; a slicer with nothing ticked or "Select all" is offered `keep`/`skip`,
and one a rule can't check only `skip`. Each page's bookmark navigator (a
question with `kind: navigator`) is `keep` or `skip`. A missing answer takes
the suggestion. The contract is written beside the report
as `<Report>.Report.odcs.yaml`, and only after it reads back the way
`fab-test pbir` will read it. An existing contract gains rules for slicers and
navigators it doesn't cover; an existing rule's `implementation` changes only with --force,
and anything else in it (severity, description) is kept. PyYAML drops comments,
so a contract containing `#` is rewritten only with --force.
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

from ._bookmark_navigators import apply_navigator_answers, navigator_questions
from ._pbir_slicers import Slicer, read_slicers
from ._scan import find_artifact_dirs
from ._slicer_calendar import FIELDS, CalendarError, calendar_fields, resolve_contract, today, validate_calendar
from ._slicer_contract import ENGINE, SELECT_ALL, ContractError, parse_contract
from ._slicer_contract_run import CONTRACT_SUFFIX, report_logical_id

CHOICES = ("keep", "calendar", "skip")
_START = "calendar.fiscal_year_start_month"
_NAMED_BY = "calendar.fiscal_year_named_by"
_CALENDAR_PROPERTY = "fabTestCalendar"
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
        questions = build_questions(report, args.as_of or today())
        if args.questions:
            _print(args, questions, _questions_text)
            return 0
        answers = _answers(args, questions)
        return _write(args, report, questions, answers)
    except (InitError, CalendarError, ContractError) as exc:
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
        found = [p for p in find_artifact_dirs(Path(args.artifact_dir), [".Report"]) if p.name == name]
        if len(found) > 1:
            raise InitError(f"--artifact {args.artifact} matches {len(found)} reports; pass the path to one: "
                            + ", ".join(map(str, found)))
        report = found[0] if found else Path(args.artifact_dir) / name
    else:
        raise InitError("name the report: a path to its .Report folder, or --artifact NAME")
    if not (report / "definition" / "pages").is_dir():
        raise InitError(f"{report} is not a PBIR report folder (no definition/pages)")
    return report


def build_questions(report: Path, as_of: datetime.date) -> dict[str, Any]:
    used: set[str] = set()
    try:
        slicers = _one_per_column(read_slicers(report))
        questions = [_slicer_question(s, _rule_id(f"{s.page} {s.column}", used, f"slicer-{i + 1}"), as_of)
                     for i, s in enumerate(slicers)]
        questions += navigator_questions(report, lambda text: _rule_id(text, used))
    except (OSError, ValueError) as exc:
        raise InitError(f"{report}: a page or visual file can't be read ({exc})") from exc
    starts = [q.pop("_starts") for q in questions if q.get("_starts")]
    reproduces = sorted(set.intersection(*map(set, starts))) if starts else list(range(1, 13))
    suggested_start = next((m for m in _START_PREFERENCE if m in reproduces), 1)
    questions.append({"id": _START, "prompt": "Which month does the fiscal year start in (1-12)?",
                      "suggested": suggested_start, "reproduces": reproduces, "needs_human": bool(starts)})
    questions.append({"id": _NAMED_BY, "prompt": "Is a fiscal year named by the calendar year it starts or ends in?",
                      "choices": ["end", "start"], "suggested": "end", "needs_human": bool(starts)})
    return {"report": str(report), "contract": str(_contract_path(report)), "as_of": as_of.isoformat(),
            "questions": questions}


def _one_per_column(slicers: list[Slicer]) -> list[Slicer]:
    """One slicer per (page, field): a rule matches every slicer on its column, so two with different
    selections can't both be checked; the same selection twice needs one rule."""
    groups: dict[tuple, list[Slicer]] = {}
    for s in slicers:
        groups.setdefault((s.page, s.table, s.column), []).append(s)
    result = []
    for group in groups.values():
        first = group[0]
        if any(s.current != first.current for s in group):
            reason = f"{len(group)} slicers on this page share this column with different selections"
            first = Slicer(first.page, first.table, first.column, {"unsupported": reason})
        result.append(first)
    return result


def _rule_id(text: str, used: set[str], fallback: str = "rule") -> str:
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or fallback
    rule_id, n = base, 1
    while rule_id in used or rule_id.startswith("page."):
        n += 1
        rule_id = f"{base}-{n}"
    used.add(rule_id)
    return rule_id


def _slicer_question(slicer: Slicer, rule_id: str, as_of: datetime.date) -> dict[str, Any]:
    field = f"'{slicer.table}'[{slicer.column}]"
    question = {"id": rule_id, "page": slicer.page, "table": slicer.table, "column": slicer.column,
                "field": field, "current": slicer.current}
    if "unsupported" in slicer.current:
        return {**question, "prompt": f"{slicer.page}: {field} opens with {slicer.current['unsupported']}, "
                                      "which a contract can't check. Skip it?",
                "choices": ["skip"], "suggested": "skip", "needs_human": False}
    [value] = slicer.current.values()
    if value in ([], SELECT_ALL):  # nothing to follow the calendar
        return {**question, "prompt": f"{slicer.page}: {field} opens with {_show(slicer.current)}. "
                                      "Keep checking that or skip it?",
                "choices": ["keep", "skip"], "suggested": "keep", "needs_human": False}
    question.update(prompt=f"{slicer.page}: {field} opens with {_show(slicer.current)}. "
                           "Keep checking that, follow the calendar, or skip it?",
                    choices=list(CHOICES), suggested="keep", needs_human=False)
    suggestion = _calendar_suggestion(slicer.current, as_of)
    if suggestion:
        question.update(suggested="calendar", calendar_format=suggestion[0], needs_human=True, _starts=suggestion[1])
    return question


def _show(current: dict) -> str:
    [(check, value)] = current.items()
    if value == SELECT_ALL:
        return "Select all"
    if check in ("selected", "contains"):
        return ", ".join(map(str, value)) or ("no selection" if check == "selected" else "nothing typed")
    return json.dumps(value, default=str)


def _calendar_suggestion(current: dict, as_of: datetime.date) -> tuple[str, list[int]] | None:
    """The first format that reproduces a single current value today, and the fiscal starts that do."""
    values = current.get("selected")
    values = values if isinstance(values, list) else []  # `all` names no value
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
        if not isinstance(given, dict):
            raise InitError(f"--answers {args.answers}: must be a JSON object of question id -> answer")
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
    """Ask on stderr, so stdout stays one document under --format json; re-ask until an answer is valid."""
    answers: dict[str, Any] = {}
    for q in questions:
        if q["id"] in (_START, _NAMED_BY) and "calendar" not in answers.values():
            continue
        hint = f" (format {q['calendar_format']})" if q.get("calendar_format") else ""
        valid = [str(c) for c in q.get("choices", range(1, 13))]
        while True:
            print(f"{q['prompt']}{hint}\n  [{'/'.join(valid)}] default {q['suggested']}: ", end="", file=sys.stderr)
            try:
                typed = input().strip()
            except EOFError:
                typed = ""
            if not typed or typed in valid:
                break
            print(f"  '{typed}' isn't one of {', '.join(valid)}", file=sys.stderr)
        answers[q["id"]] = (int(typed) if typed.isdigit() else typed) if typed else q["suggested"]
    return answers


def _rule(q: dict, answer: Any) -> tuple[dict[str, Any] | None, bool]:
    """(the rule for this answer, or None to skip; whether it follows the calendar)."""
    if answer == "skip":
        return None, False
    if "unsupported" in q["current"]:
        raise InitError(f"{q['id']}: {q['current']['unsupported']}; the only answer is skip")
    if answer == "calendar" or isinstance(answer, dict):
        text = answer.get("calendar") if isinstance(answer, dict) else q.get("calendar_format")
        if not isinstance(text, str) or not text:
            raise InitError(f"{q['id']}: no calendar format reproduces {_show(q['current'])} today; "
                            'answer {"calendar": "<format>"} to name one')
        implementation = {"page": q["page"], "selected": [text]}
        calendar = True
    elif answer == "keep":
        [(check, value)] = q["current"].items()
        implementation = {"page": q["page"], check: _escaped(value) if check in ("selected", "contains") else value}
        calendar = False
    else:
        raise InitError(f"{q['id']}: answer must be keep, calendar, skip or {{\"calendar\": \"<format>\"}}, "
                        f"got {answer!r}")
    return {"id": q["id"], "type": "custom", "engine": ENGINE, "implementation": implementation}, calendar


def _escaped(values: list | str) -> list | str:
    """A kept value is literal text, so its braces mustn't read as calendar fields."""
    if values == SELECT_ALL:
        return values
    return [v.replace("{", "{{").replace("}", "}}") if isinstance(v, str) else v for v in values]


def _write(args: argparse.Namespace, report: Path, questions: dict, answers: dict) -> int:
    built = [(q, *_rule(q, answers[q["id"]])) for q in questions["questions"] if "column" in q]
    rules = [(q, rule) for q, rule, _ in built if rule]
    calendar = None
    if any(follows for _, rule, follows in built if rule):
        calendar = {"fiscal_year_start_month": answers[_START], "fiscal_year_named_by": answers[_NAMED_BY]}
        validate_calendar(calendar)
    path = _contract_path(report)
    document, summary = _merge(path, report, rules, calendar, args.force)
    try:
        apply_navigator_answers(document, questions["questions"], answers, args.force, summary)
    except ValueError as exc:
        raise InitError(str(exc)) from exc
    try:  # the file must read back exactly as `fab-test pbir` will read it
        resolve_contract(parse_contract(document, path), datetime.date.fromisoformat(questions["as_of"]))
    except (ContractError, CalendarError) as exc:
        raise InitError(f"the contract wouldn't be valid, so nothing was written:\n{exc}") from exc
    text = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    if not args.dry_run:
        path.write_text(text, encoding="utf-8")
    _print(args, {"contract": str(path), "written": not args.dry_run, **summary,
                  **({"content": text} if args.dry_run else {})},
           lambda s: text if args.dry_run else _summary_text(s))
    return 0


def _merge(path: Path, report: Path, rules: list, calendar: dict | None, force: bool):
    summary: dict[str, Any] = {"added": [], "kept": [], "replaced": [], "unchanged": [], "calendar": None}
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if "#" in text and not force:
            raise InitError(f"{path} contains '#' (a comment), which rewriting would drop; edit it by hand, "
                            "or pass --force to rewrite it (see the result first with --dry-run)")
        document = yaml.safe_load(text)
        if not isinstance(document, dict):
            raise InitError(f"{path} isn't a contract (not a YAML mapping); move it aside or fix it")
    else:
        document = _new_document(report)
    summary["calendar"] = _merge_calendar(document, calendar, force)
    for q, rule in rules:
        quality = _column(document, q["table"], q["column"])
        existing = next((r for r in quality if isinstance(r, dict) and r.get("id") == rule["id"]), None)
        if existing is None:
            quality.append(rule)
            summary["added"].append(rule["id"])
        elif existing.get("implementation") == rule["implementation"]:
            summary["unchanged"].append(rule["id"])
        elif force:
            existing["implementation"] = rule["implementation"]
            summary["replaced"].append(rule["id"])
        else:
            summary["kept"].append(rule["id"])
    return document, summary


def _merge_calendar(document: dict, calendar: dict | None, force: bool) -> str | None:
    if not calendar:
        return None
    properties = document.setdefault("customProperties", [])
    existing = next((p for p in properties if isinstance(p, dict) and p.get("property") == _CALENDAR_PROPERTY), None)
    if existing is None:
        properties.append({"property": _CALENDAR_PROPERTY, "value": calendar})
        return "added"
    if existing.get("value") == calendar:
        return "unchanged"
    if force:
        existing["value"] = calendar
        return "replaced"
    return "kept"


def _new_document(report: Path) -> dict[str, Any]:
    logical_id = report_logical_id(report)
    if not logical_id:
        raise InitError(f"{report} has no .platform logicalId, which a contract pairs by; "
                        "save the report from Power BI Desktop or Fabric to create it")
    name = report.name.removesuffix(".Report")
    return {"apiVersion": "v3.1.0", "kind": "DataContract",
            "id": re.sub(r"[^a-z0-9]+", "-", f"{name} slicer defaults".lower()).strip("-") or "slicer-defaults",
            "name": f"{name} slicer defaults", "version": "1.0.0", "status": "active",
            "customProperties": [{"property": "fabTestReport", "value": logical_id}], "schema": []}


def _column(document: dict, table: str, column: str) -> list:
    """The quality list of ``table``.``column``, created if the contract doesn't have it yet."""
    entry = _named(document.setdefault("schema", []), table)
    return _named(entry.setdefault("properties", []), column).setdefault("quality", [])


def _named(items: list, name: str) -> dict:
    for item in items:
        if isinstance(item, dict) and item.get("name") == name:
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
        lines.append("    kept: their checks differ from the report today; --force replaces them")
    if summary["calendar"] == "kept":
        lines.append("    the contract's fabTestCalendar differs from your answers and was kept; --force replaces it")
    return "\n".join(lines)
