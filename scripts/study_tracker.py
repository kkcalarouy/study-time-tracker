#!/usr/bin/env python3
"""Local study timer, session log, and report generator."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DIRECTORY = ".study-time-tracker"
DEFAULT_SESSION_FILE = "sessions.jsonl"
ACTIVE_SUFFIX = ".active.json"


class TrackerError(Exception):
    """A user-facing study tracker error."""


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _resolve_data_file(value: Path | None) -> Path:
    if value is not None:
        path = value.expanduser()
    elif os.environ.get("STUDY_TRACKER_DATA"):
        path = Path(os.environ["STUDY_TRACKER_DATA"]).expanduser()
    else:
        path = Path.home() / DEFAULT_DIRECTORY / DEFAULT_SESSION_FILE
    return path.resolve()


def _active_file(data_file: Path) -> Path:
    return data_file.with_name(data_file.name + ACTIVE_SUFFIX)


def _parse_datetime(value: str, field: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise TrackerError(
            f"{field} must be an ISO 8601 timestamp, for example "
            "2026-11-18T09:00:00+08:00."
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def _parse_date(value: str | None) -> date:
    if value is None:
        return _local_now().date()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise TrackerError("--anchor must use YYYY-MM-DD.") from exc


def _format_datetime(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _validate_course(value: str) -> str:
    course = value.strip()
    if not course:
        raise TrackerError("--course cannot be empty.")
    return course


def _positive_number(value: float | None, field: str) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise TrackerError(f"{field} must be a number.") from exc
    if not math.isfinite(number) or number <= 0:
        raise TrackerError(f"{field} must be a positive finite number.")
    return number


def _minutes_to_seconds(minutes: float) -> int:
    return int(round(minutes * 60))


def _format_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _format_duration(seconds: int) -> str:
    total_minutes = int(round(max(0, seconds) / 60))
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def _format_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}%"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_active(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrackerError(f"Cannot read active timer state at {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise TrackerError(f"Active timer state at {path} is not a JSON object.")
    required = ("id", "course", "started_at")
    missing = [key for key in required if key not in payload]
    if missing:
        raise TrackerError(
            f"Active timer state at {path} is missing: {', '.join(missing)}."
        )
    return payload


def _save_active(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_json(path, payload)


def _remove_active(path: Path) -> None:
    path.unlink(missing_ok=True)


def _load_sessions(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    sessions: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise TrackerError(
                        f"Invalid JSON in {path} at line {line_number}: {exc}"
                    ) from exc
                if not isinstance(record, dict):
                    raise TrackerError(
                        f"Session record in {path} at line {line_number} "
                        "must be a JSON object."
                    )
                _validate_session_record(record, path, line_number)
                sessions.append(record)
    except OSError as exc:
        raise TrackerError(f"Cannot read session history at {path}: {exc}") from exc
    return sessions


def _validate_session_record(
    record: dict[str, Any], path: Path, line_number: int
) -> None:
    required = ("id", "course", "started_at", "ended_at", "duration_seconds")
    missing = [key for key in required if key not in record]
    if missing:
        raise TrackerError(
            f"Session record in {path} at line {line_number} is missing: "
            f"{', '.join(missing)}."
        )
    if not isinstance(record["course"], str) or not record["course"].strip():
        raise TrackerError(
            f"Session record in {path} at line {line_number} has an invalid course."
        )
    if not isinstance(record["id"], str) or not record["id"].strip():
        raise TrackerError(
            f"Session record in {path} at line {line_number} has an invalid id."
        )
    _parse_datetime(str(record["started_at"]), "started_at")
    _parse_datetime(str(record["ended_at"]), "ended_at")
    try:
        duration = int(record["duration_seconds"])
    except (TypeError, ValueError) as exc:
        raise TrackerError(
            f"Session record in {path} at line {line_number} has an invalid "
            "duration_seconds value."
        ) from exc
    if duration < 0:
        raise TrackerError(
            f"Session record in {path} at line {line_number} has a negative duration."
        )
    planned = record.get("planned_minutes")
    if planned is not None:
        _positive_number(planned, "planned_minutes")


def _append_session(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            json.dump(record, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise TrackerError(f"Cannot write session history at {path}: {exc}") from exc


def _session_start(record: dict[str, Any]) -> datetime:
    return _parse_datetime(str(record["started_at"]), "started_at")


def _session_end(record: dict[str, Any]) -> datetime:
    return _parse_datetime(str(record["ended_at"]), "ended_at")


def _session_seconds(record: dict[str, Any]) -> int:
    return max(0, int(record.get("duration_seconds", 0)))


def _find_overlap(
    sessions: Iterable[dict[str, Any]], start: datetime, end: datetime
) -> dict[str, Any] | None:
    for record in sessions:
        existing_start = _session_start(record)
        existing_end = _session_end(record)
        if start < existing_end and end > existing_start:
            return record
    return None


def _session_record(
    *,
    course: str,
    started_at: datetime,
    ended_at: datetime,
    duration_seconds: int,
    planned_minutes: float | None,
    note: str,
    source: str,
) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex,
        "course": course,
        "started_at": _format_datetime(started_at),
        "ended_at": _format_datetime(ended_at),
        "duration_seconds": duration_seconds,
        "planned_minutes": planned_minutes,
        "note": note.strip(),
        "source": source,
    }


def _command_start(args: argparse.Namespace, data_file: Path) -> tuple[dict[str, Any], str]:
    active_file = _active_file(data_file)
    active = _read_active(active_file)
    if active is not None:
        course = str(active.get("course", "unknown"))
        started_at = active.get("started_at", "unknown time")
        raise TrackerError(
            f'A study timer is already active for "{course}" since {started_at}. '
            "Run stop or cancel first."
        )

    course = _validate_course(args.course)
    planned_minutes = _positive_number(args.plan_minutes, "--plan-minutes")
    started_at = _parse_datetime(args.at, "--at") if args.at else _local_now()
    payload = {
        "id": uuid.uuid4().hex,
        "course": course,
        "started_at": _format_datetime(started_at),
        "planned_minutes": planned_minutes,
        "note": (args.note or "").strip(),
    }
    _save_active(active_file, payload)
    plan_text = (
        f" Plan: {_format_number(planned_minutes)} minutes."
        if planned_minutes is not None
        else ""
    )
    text = (
        f'Started "{course}" at {_format_datetime(started_at)}.{plan_text} '
        f"Session ID: {payload['id']}."
    )
    return {
        "status": "started",
        "session": payload,
        "data_file": str(data_file),
    }, text


def _command_stop(args: argparse.Namespace, data_file: Path) -> tuple[dict[str, Any], str]:
    active_file = _active_file(data_file)
    active = _read_active(active_file)
    if active is None:
        raise TrackerError("No active study session. Start one with the start command.")

    started_at = _parse_datetime(str(active["started_at"]), "active started_at")
    ended_at = _parse_datetime(args.at, "--at") if args.at else _local_now()
    if ended_at < started_at:
        raise TrackerError("--at cannot be earlier than the active session start.")

    duration_seconds = int(round((ended_at - started_at).total_seconds()))
    planned = _positive_number(active.get("planned_minutes"), "planned_minutes")
    note = args.note if args.note is not None else str(active.get("note", ""))
    record = _session_record(
        course=_validate_course(str(active["course"])),
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=duration_seconds,
        planned_minutes=planned,
        note=note,
        source="timer",
    )
    _append_session(data_file, record)
    _remove_active(active_file)

    text = (
        f'Stopped "{record["course"]}". Recorded '
        f"{_format_duration(duration_seconds)} of study time."
    )
    return {
        "status": "stopped",
        "session": record,
        "data_file": str(data_file),
    }, text


def _command_status(args: argparse.Namespace, data_file: Path) -> tuple[dict[str, Any], str]:
    active = _read_active(_active_file(data_file))
    if active is None:
        return {"status": "idle", "data_file": str(data_file)}, "No active study session."

    started_at = _parse_datetime(str(active["started_at"]), "active started_at")
    current = _parse_datetime(args.at, "--at") if args.at else _local_now()
    elapsed_seconds = max(0, int(round((current - started_at).total_seconds())))
    planned = _positive_number(active.get("planned_minutes"), "planned_minutes")
    remaining_seconds: int | None = None
    if planned is not None:
        remaining_seconds = max(0, _minutes_to_seconds(planned) - elapsed_seconds)

    plan_text = ""
    if planned is not None:
        plan_text = (
            f" Plan: {_format_number(planned)} minutes; "
            f"remaining: {_format_duration(remaining_seconds or 0)}."
        )
    text = (
        f'Active: "{active["course"]}" since {_format_datetime(started_at)}. '
        f"Elapsed: {_format_duration(elapsed_seconds)}.{plan_text}"
    )
    return {
        "status": "active",
        "session": active,
        "elapsed_seconds": elapsed_seconds,
        "remaining_seconds": remaining_seconds,
        "data_file": str(data_file),
    }, text


def _command_cancel(args: argparse.Namespace, data_file: Path) -> tuple[dict[str, Any], str]:
    del args
    active_file = _active_file(data_file)
    active = _read_active(active_file)
    if active is None:
        return {"status": "idle", "data_file": str(data_file)}, "No active study session."
    _remove_active(active_file)
    return {
        "status": "cancelled",
        "session": active,
        "data_file": str(data_file),
    }, f'Cancelled the active session for "{active.get("course", "unknown")}".'


def _command_add(args: argparse.Namespace, data_file: Path) -> tuple[dict[str, Any], str]:
    course = _validate_course(args.course)
    minutes = _positive_number(args.minutes, "--minutes")
    assert minutes is not None
    planned = _positive_number(args.planned_minutes, "--planned-minutes")
    duration_seconds = _minutes_to_seconds(minutes)
    now = _local_now()
    if args.started_at:
        started_at = _parse_datetime(args.started_at, "--started-at")
        ended_at = started_at + timedelta(seconds=duration_seconds)
    else:
        ended_at = now
        started_at = ended_at - timedelta(seconds=duration_seconds)

    sessions = _load_sessions(data_file)
    conflict = _find_overlap(sessions, started_at, ended_at)
    if conflict is not None and not args.allow_overlap:
        raise TrackerError(
            f"The new session overlaps an existing session for "
            f'"{conflict["course"]}" ({conflict["started_at"]} to '
            f'{conflict["ended_at"]}). Use --allow-overlap only if this is intentional.'
        )

    record = _session_record(
        course=course,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=duration_seconds,
        planned_minutes=planned,
        note=args.note or "",
        source="manual",
    )
    _append_session(data_file, record)
    text = (
        f'Added {_format_duration(duration_seconds)} for "{course}" as a manual entry. '
        f"Session ID: {record['id']}."
    )
    return {
        "status": "added",
        "session": record,
        "data_file": str(data_file),
    }, text


def _period_bounds(period: str, anchor: date) -> tuple[date | None, date | None, str]:
    if period == "all":
        return None, None, "All time"
    if period == "day":
        return anchor, anchor + timedelta(days=1), f"Day of {anchor.isoformat()}"
    if period == "week":
        start = anchor - timedelta(days=anchor.weekday())
        return start, start + timedelta(days=7), f"Week of {start.isoformat()}"
    if period == "month":
        start = anchor.replace(day=1)
        if start.month == 12:
            end = date(start.year + 1, 1, 1)
        else:
            end = date(start.year, start.month + 1, 1)
        return start, end, f"Month of {start.strftime('%Y-%m')}"
    raise TrackerError(f"Unsupported report period: {period}")


def _filter_sessions(
    sessions: Iterable[dict[str, Any]],
    *,
    start_date: date | None,
    end_date: date | None,
    course_filter: str | None,
) -> list[dict[str, Any]]:
    normalized_course = course_filter.strip().casefold() if course_filter else None
    selected: list[dict[str, Any]] = []
    for record in sessions:
        record_date = _session_start(record).astimezone().date()
        if start_date is not None and record_date < start_date:
            continue
        if end_date is not None and record_date >= end_date:
            continue
        if normalized_course and str(record["course"]).casefold() != normalized_course:
            continue
        selected.append(record)
    selected.sort(key=_session_start)
    return selected


def _build_stats(sessions: Iterable[dict[str, Any]]) -> dict[str, Any]:
    course_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"seconds": 0, "sessions": 0, "planned_minutes": 0.0, "planned_sessions": 0}
    )
    day_stats: dict[str, int] = defaultdict(int)
    source_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"seconds": 0, "sessions": 0}
    )
    total_seconds = 0
    total_sessions = 0
    total_planned_minutes = 0.0
    planned_sessions = 0

    for record in sessions:
        seconds = _session_seconds(record)
        course = str(record["course"])
        source = str(record.get("source", "unknown"))
        record_date = _session_start(record).astimezone().date().isoformat()
        planned = record.get("planned_minutes")

        total_seconds += seconds
        total_sessions += 1
        day_stats[record_date] += seconds
        source_stats[source]["seconds"] += seconds
        source_stats[source]["sessions"] += 1

        entry = course_stats[course]
        entry["seconds"] += seconds
        entry["sessions"] += 1
        if planned is not None:
            planned_number = float(planned)
            if math.isfinite(planned_number) and planned_number > 0:
                entry["planned_minutes"] += planned_number
                entry["planned_sessions"] += 1
                total_planned_minutes += planned_number
                planned_sessions += 1

    completion_ratio: float | None = None
    if total_planned_minutes > 0:
        completion_ratio = total_seconds / 60 / total_planned_minutes * 100

    courses = []
    for course, entry in sorted(
        course_stats.items(), key=lambda item: (-item[1]["seconds"], item[0].casefold())
    ):
        planned_minutes = float(entry["planned_minutes"])
        ratio = None
        if planned_minutes > 0:
            ratio = entry["seconds"] / 60 / planned_minutes * 100
        courses.append(
            {
                "course": course,
                "sessions": entry["sessions"],
                "seconds": entry["seconds"],
                "planned_minutes": planned_minutes,
                "planned_sessions": entry["planned_sessions"],
                "completion_ratio": ratio,
            }
        )

    days = [
        {"date": day, "seconds": seconds}
        for day, seconds in sorted(day_stats.items())
    ]
    sources = [
        {"source": source, **values}
        for source, values in sorted(source_stats.items())
    ]
    return {
        "total_seconds": total_seconds,
        "total_minutes": round(total_seconds / 60, 1),
        "total_sessions": total_sessions,
        "planned_minutes": round(total_planned_minutes, 1),
        "planned_sessions": planned_sessions,
        "completion_ratio": completion_ratio,
        "courses": courses,
        "days": days,
        "sources": sources,
    }


def _markdown_escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _render_markdown(
    stats: dict[str, Any],
    *,
    period_label: str,
    start_date: date | None,
    end_date: date | None,
    course_filter: str | None,
    target_minutes: float | None,
) -> str:
    lines = [f"# Study Report - {period_label}", ""]
    if start_date is not None and end_date is not None:
        lines.append(f"- Period: {start_date.isoformat()} to {end_date.isoformat()} exclusive")
    else:
        lines.append("- Period: all recorded sessions")
    if course_filter:
        lines.append(f"- Course filter: {course_filter}")
    lines.extend(
        [
            f"- Total study time: {_format_duration(stats['total_seconds'])}",
            f"- Sessions: {stats['total_sessions']}",
            f"- Planned time: {_format_number(stats['planned_minutes'])} minutes",
            f"- Planned completion: {_format_percent(stats['completion_ratio'])}",
        ]
    )
    if target_minutes is not None:
        target_seconds = _minutes_to_seconds(target_minutes)
        target_ratio = (
            stats["total_seconds"] / target_seconds * 100 if target_seconds else 0
        )
        lines.append(
            f"- Target: {_format_number(target_minutes)} minutes "
            f"({_format_percent(target_ratio)} achieved)"
        )
    lines.append("")

    if stats["total_sessions"] == 0:
        lines.extend(["No sessions in this period.", ""])
        return "\n".join(lines)

    lines.extend(
        [
            "## By Course",
            "",
            "| Course | Sessions | Actual | Planned | Completion |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for entry in stats["courses"]:
        planned = (
            f"{_format_number(entry['planned_minutes'])}m"
            if entry["planned_sessions"]
            else "n/a"
        )
        lines.append(
            f"| {_markdown_escape(entry['course'])} | {entry['sessions']} | "
            f"{_format_duration(entry['seconds'])} | {planned} | "
            f"{_format_percent(entry['completion_ratio'])} |"
        )

    lines.extend(["", "## By Day", "", "| Date | Study Time |", "|---|---:|"])
    for entry in stats["days"]:
        lines.append(f"| {entry['date']} | {_format_duration(entry['seconds'])} |")

    lines.extend(["", "## Sources", "", "| Source | Sessions | Study Time |", "|---|---:|---:|"])
    for entry in stats["sources"]:
        lines.append(
            f"| {_markdown_escape(entry['source'])} | {entry['sessions']} | "
            f"{_format_duration(entry['seconds'])} |"
        )
    lines.extend(
        [
            "",
            "Dates are based on the local calendar date when each session started.",
            "Manual entries are not evidence of platform attendance or playback.",
            "",
        ]
    )
    return "\n".join(lines)


def _period_from_args(args: argparse.Namespace) -> tuple[date | None, date | None, str]:
    anchor = _parse_date(args.anchor)
    return _period_bounds(args.period, anchor)


def _command_report(args: argparse.Namespace, data_file: Path) -> tuple[dict[str, Any], str]:
    target = _positive_number(args.target_minutes, "--target-minutes")
    start_date, end_date, period_label = _period_from_args(args)
    sessions = _filter_sessions(
        _load_sessions(data_file),
        start_date=start_date,
        end_date=end_date,
        course_filter=args.course,
    )
    stats = _build_stats(sessions)
    markdown = _render_markdown(
        stats,
        period_label=period_label,
        start_date=start_date,
        end_date=end_date,
        course_filter=args.course,
        target_minutes=target,
    )
    output_path: str | None = None
    if args.output:
        path = Path(args.output).expanduser().resolve()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(markdown, encoding="utf-8")
        except OSError as exc:
            raise TrackerError(f"Cannot write report at {path}: {exc}") from exc
        output_path = str(path)
        text = f"Study report written to {path}."
    else:
        text = markdown

    return {
        "status": "reported",
        "period": args.period,
        "period_label": period_label,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "course_filter": args.course,
        "target_minutes": target,
        "stats": stats,
        "output_path": output_path,
        "data_file": str(data_file),
    }, text


def _command_export(args: argparse.Namespace, data_file: Path) -> tuple[dict[str, Any], str]:
    start_date, end_date, period_label = _period_from_args(args)
    sessions = _filter_sessions(
        _load_sessions(data_file),
        start_date=start_date,
        end_date=end_date,
        course_filter=args.course,
    )
    output_path = Path(args.output).expanduser().resolve()
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise TrackerError(f"Cannot create export directory for {output_path}: {exc}") from exc
    columns = [
        "id",
        "course",
        "started_at",
        "ended_at",
        "duration_minutes",
        "planned_minutes",
        "source",
        "note",
    ]
    try:
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for record in sessions:
                planned = record.get("planned_minutes")
                writer.writerow(
                    {
                        "id": record["id"],
                        "course": record["course"],
                        "started_at": record["started_at"],
                        "ended_at": record["ended_at"],
                        "duration_minutes": _format_number(
                            _session_seconds(record) / 60
                        ),
                        "planned_minutes": (
                            _format_number(float(planned))
                            if planned is not None
                            else ""
                        ),
                        "source": record.get("source", "unknown"),
                        "note": record.get("note", ""),
                    }
                )
    except OSError as exc:
        raise TrackerError(f"Cannot write CSV at {output_path}: {exc}") from exc
    return {
        "status": "exported",
        "period": args.period,
        "period_label": period_label,
        "sessions": len(sessions),
        "output_path": str(output_path),
        "data_file": str(data_file),
    }, f"Exported {len(sessions)} sessions to {output_path}."


def _add_period_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--period",
        choices=("day", "week", "month", "all"),
        default="week",
        help="Report period. Weeks start on Monday.",
    )
    parser.add_argument(
        "--anchor",
        help="Reference date in YYYY-MM-DD. Defaults to today.",
    )
    parser.add_argument("--course", help="Filter by an exact course name.")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="study_tracker.py",
        description="Track real study sessions locally and generate reports.",
    )
    parser.add_argument(
        "--data-file",
        type=Path,
        help="Session JSONL file. Defaults to STUDY_TRACKER_DATA or "
        "~/.study-time-tracker/sessions.jsonl.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of human-readable text.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="Start a study timer.")
    start.add_argument("--course", required=True, help="Course or subject name.")
    start.add_argument("--plan-minutes", type=float, help="Optional target duration.")
    start.add_argument("--note", help="Optional session note.")
    start.add_argument("--at", help=argparse.SUPPRESS)

    stop = subparsers.add_parser("stop", help="Stop the active timer and save it.")
    stop.add_argument("--note", help="Override or add a session note.")
    stop.add_argument("--at", help=argparse.SUPPRESS)

    status = subparsers.add_parser("status", help="Show the active timer.")
    status.add_argument("--at", help=argparse.SUPPRESS)

    subparsers.add_parser("cancel", help="Discard the active timer without saving.")

    add = subparsers.add_parser("add", help="Record a completed session manually.")
    add.add_argument("--course", required=True, help="Course or subject name.")
    add.add_argument("--minutes", type=float, required=True, help="Actual study minutes.")
    add.add_argument("--planned-minutes", type=float, help="Optional planned minutes.")
    add.add_argument("--started-at", help="ISO 8601 start time.")
    add.add_argument("--note", help="Optional session note.")
    add.add_argument(
        "--allow-overlap",
        action="store_true",
        help="Allow an intentional overlap with another session.",
    )

    report = subparsers.add_parser("report", help="Generate a Markdown study report.")
    _add_period_arguments(report)
    report.add_argument("--target-minutes", type=float, help="Optional period target.")
    report.add_argument("--output", help="Optional Markdown output path.")

    export = subparsers.add_parser("export", help="Export sessions to CSV.")
    _add_period_arguments(export)
    export.add_argument("--output", required=True, help="CSV output path.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    data_file = _resolve_data_file(args.data_file)
    handlers = {
        "start": _command_start,
        "stop": _command_stop,
        "status": _command_status,
        "cancel": _command_cancel,
        "add": _command_add,
        "report": _command_report,
        "export": _command_export,
    }
    try:
        payload, text = handlers[args.command](args, data_file)
    except TrackerError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                {"ok": True, **payload},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
