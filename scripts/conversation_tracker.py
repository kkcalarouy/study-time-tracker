#!/usr/bin/env python3
"""Track inferred Agent-learning conversations and deep-focus feedback."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import study_tracker as core


TrackerError = core.TrackerError
ACTIVE_SUFFIX = ".conversation-active.json"
DEFAULT_IDLE_TIMEOUT_MINUTES = 10
DEFAULT_DEEP_THRESHOLD = 3


def _active_file(data_file: Path) -> Path:
    return data_file.with_name(data_file.name + ACTIVE_SUFFIX)


def _positive_int(value: int, field: str) -> int:
    number = int(value)
    if number <= 0:
        raise TrackerError(f"{field} must be a positive integer.")
    return number


def _topic_key(value: str) -> str:
    normalized = value.strip().casefold()
    if not normalized:
        raise TrackerError("--topic-key cannot be empty when the turn is learning.")
    return normalized[:160]


def _topic_label(value: str | None, key: str) -> str:
    label = (value or key).strip()
    return (label or key)[:240]


def _read_active(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrackerError(
            f"Cannot read active conversation state at {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise TrackerError(
            f"Active conversation state at {path} is not a JSON object."
        )
    required = (
        "id",
        "started_at",
        "last_activity_at",
        "topic_counts",
        "topic_labels",
        "learning_turns",
    )
    missing = [key for key in required if key not in payload]
    if missing:
        raise TrackerError(
            f"Active conversation state at {path} is missing: {', '.join(missing)}."
        )
    return payload


def _save_active(path: Path, payload: dict[str, Any]) -> None:
    core._atomic_write_json(path, payload)


def _remove_active(path: Path) -> None:
    path.unlink(missing_ok=True)


def _deep_topics(active: dict[str, Any]) -> list[dict[str, Any]]:
    threshold = _positive_int(
        int(active.get("deep_threshold", DEFAULT_DEEP_THRESHOLD)),
        "deep_threshold",
    )
    labels = active.get("topic_labels", {})
    topics = []
    for key, turns in sorted(
        active.get("topic_counts", {}).items(),
        key=lambda item: (-int(item[1]), item[0]),
    ):
        if int(turns) >= threshold:
            topics.append(
                {
                    "topic_key": key,
                    "topic_label": str(labels.get(key, key)),
                    "turns": int(turns),
                }
            )
    return topics


def _primary_topic(active: dict[str, Any]) -> tuple[str, str]:
    counts = active.get("topic_counts", {})
    labels = active.get("topic_labels", {})
    if not counts:
        return "general", "Agent learning"
    key = sorted(
        counts,
        key=lambda item: (-int(counts[item]), str(labels.get(item, item)).casefold()),
    )[0]
    return key, str(labels.get(key, key))


def _finalize_active(
    active: dict[str, Any],
    *,
    data_file: Path,
    active_file: Path,
    reason: str,
) -> dict[str, Any]:
    started_at = core._parse_datetime(str(active["started_at"]), "started_at")
    ended_at = core._parse_datetime(
        str(active["last_activity_at"]), "last_activity_at"
    )
    if ended_at < started_at:
        raise TrackerError("Conversation last activity cannot precede its start.")
    duration_seconds = max(0, int(round((ended_at - started_at).total_seconds())))
    primary_key, primary_label = _primary_topic(active)
    labels = active.get("topic_labels", {})
    topic_breakdown = [
        {
            "topic_key": key,
            "topic_label": str(labels.get(key, key)),
            "turns": int(turns),
        }
        for key, turns in sorted(
            active.get("topic_counts", {}).items(),
            key=lambda item: (-int(item[1]), item[0]),
        )
    ]
    deep_topics = _deep_topics(active)
    deep_topic_keys = [item["topic_key"] for item in deep_topics]
    record = core._session_record(
        course=primary_label,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=duration_seconds,
        planned_minutes=None,
        note="Agent learning conversation",
        source="conversation",
    )
    record["conversation"] = {
        "primary_topic_key": primary_key,
        "topics": topic_breakdown,
        "learning_turns": int(active.get("learning_turns", 0)),
        "assistant_touches": int(active.get("assistant_touches", 0)),
        "deep_focus": bool(deep_topics),
        "deep_topics": deep_topics,
        "deep_topic_keys": deep_topic_keys,
        "deep_threshold": int(
            active.get("deep_threshold", DEFAULT_DEEP_THRESHOLD)
        ),
        "idle_timeout_minutes": int(
            active.get("idle_timeout_minutes", DEFAULT_IDLE_TIMEOUT_MINUTES)
        ),
        "close_reason": reason,
    }
    core._append_session(data_file, record)
    _remove_active(active_file)
    return record


def _is_idle(active: dict[str, Any], current: datetime, timeout_minutes: int) -> bool:
    last_activity = core._parse_datetime(
        str(active["last_activity_at"]), "last_activity_at"
    )
    return current - last_activity > timedelta(minutes=timeout_minutes)


def _close_if_idle(
    data_file: Path,
    active_file: Path,
    current: datetime,
    timeout_minutes: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    active = _read_active(active_file)
    if active is None:
        return None, None
    if _is_idle(active, current, timeout_minutes):
        record = _finalize_active(
            active,
            data_file=data_file,
            active_file=active_file,
            reason="idle_timeout",
        )
        return None, record
    return active, None


def _new_active(
    current: datetime,
    *,
    idle_timeout_minutes: int,
    deep_threshold: int,
) -> dict[str, Any]:
    timestamp = core._format_datetime(current)
    return {
        "id": uuid.uuid4().hex,
        "started_at": timestamp,
        "last_activity_at": timestamp,
        "topic_counts": {},
        "topic_labels": {},
        "learning_turns": 0,
        "assistant_touches": 0,
        "idle_timeout_minutes": idle_timeout_minutes,
        "deep_threshold": deep_threshold,
    }


def _deep_payload(active: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    deep_topics = _deep_topics(active)
    return bool(deep_topics), deep_topics


def _command_observe(
    args: argparse.Namespace, data_file: Path
) -> tuple[dict[str, Any], str]:
    current = core._parse_datetime(args.at, "--at") if args.at else core._local_now()
    timeout_minutes = _positive_int(
        args.idle_timeout_minutes, "--idle-timeout-minutes"
    )
    deep_threshold = _positive_int(args.deep_threshold, "--deep-threshold")
    active_file = _active_file(data_file)
    active, idle_record = _close_if_idle(
        data_file, active_file, current, timeout_minutes
    )

    if args.learning == "no":
        closed_record = idle_record
        if active is not None:
            closed_record = _finalize_active(
                active,
                data_file=data_file,
                active_file=active_file,
                reason="non_learning_turn",
            )
        return {
            "status": "not_tracking",
            "closed_session": closed_record,
            "data_file": str(data_file),
        }, "Current turn was classified as non-learning; no conversation timer is active."

    if active is None:
        active = _new_active(
            current,
            idle_timeout_minutes=timeout_minutes,
            deep_threshold=deep_threshold,
        )
        new_session = True
    else:
        new_session = False
        active["idle_timeout_minutes"] = timeout_minutes
        active["deep_threshold"] = deep_threshold

    key = _topic_key(args.topic_key or "general")
    label = _topic_label(args.topic_label, key)
    active["topic_counts"][key] = int(active["topic_counts"].get(key, 0)) + 1
    active["topic_labels"][key] = label
    active["learning_turns"] = int(active["learning_turns"]) + 1
    active["last_activity_at"] = core._format_datetime(current)
    _save_active(active_file, active)

    deep_focus, deep_topics = _deep_payload(active)
    topic_turns = int(active["topic_counts"][key])
    feedback = (
        f' Deep learning detected for "{label}" after {topic_turns} related turns.'
        if deep_focus and topic_turns >= deep_threshold
        else ""
    )
    text = (
        f'Tracking Agent learning conversation on "{label}". '
        f"Learning turns: {active['learning_turns']}; topic turns: {topic_turns}.{feedback}"
    )
    return {
        "status": "tracking",
        "new_session": new_session,
        "closed_idle_session": idle_record,
        "topic_key": key,
        "topic_label": label,
        "topic_turns": topic_turns,
        "learning_turns": int(active["learning_turns"]),
        "deep_focus": deep_focus,
        "deep_topics": deep_topics,
        "active_session": active,
        "data_file": str(data_file),
    }, text


def _command_touch(
    args: argparse.Namespace, data_file: Path
) -> tuple[dict[str, Any], str]:
    current = core._parse_datetime(args.at, "--at") if args.at else core._local_now()
    timeout_minutes = _positive_int(
        args.idle_timeout_minutes, "--idle-timeout-minutes"
    )
    active_file = _active_file(data_file)
    active, idle_record = _close_if_idle(
        data_file, active_file, current, timeout_minutes
    )
    if active is None:
        return {
            "status": "idle_finalized" if idle_record else "idle",
            "closed_session": idle_record,
            "data_file": str(data_file),
        }, (
            "Conversation had been idle for more than the allowed interval and was finalized."
            if idle_record
            else "No active Agent learning conversation."
        )

    active["last_activity_at"] = core._format_datetime(current)
    active["assistant_touches"] = int(active.get("assistant_touches", 0)) + 1
    active["idle_timeout_minutes"] = timeout_minutes
    _save_active(active_file, active)
    started_at = core._parse_datetime(str(active["started_at"]), "started_at")
    elapsed_seconds = max(0, int(round((current - started_at).total_seconds())))
    return {
        "status": "touched",
        "elapsed_seconds": elapsed_seconds,
        "assistant_touches": int(active["assistant_touches"]),
        "active_session": active,
        "data_file": str(data_file),
    }, f"Updated conversation activity. Current duration: {core._format_duration(elapsed_seconds)}."


def _command_finalize(
    args: argparse.Namespace, data_file: Path
) -> tuple[dict[str, Any], str]:
    active_file = _active_file(data_file)
    active = _read_active(active_file)
    if active is None:
        return {"status": "idle", "data_file": str(data_file)}, (
            "No active Agent learning conversation."
        )
    record = _finalize_active(
        active,
        data_file=data_file,
        active_file=active_file,
        reason=args.reason,
    )
    return {
        "status": "finalized",
        "session": record,
        "data_file": str(data_file),
    }, (
        f'Finalized Agent learning session for "{record["course"]}" with duration '
        f"{core._format_duration(int(record['duration_seconds']))}."
    )


def _command_status(
    args: argparse.Namespace, data_file: Path
) -> tuple[dict[str, Any], str]:
    current = core._parse_datetime(args.at, "--at") if args.at else core._local_now()
    timeout_minutes = _positive_int(
        args.idle_timeout_minutes, "--idle-timeout-minutes"
    )
    active, idle_record = _close_if_idle(
        data_file, _active_file(data_file), current, timeout_minutes
    )
    if active is None:
        return {
            "status": "idle",
            "closed_session": idle_record,
            "data_file": str(data_file),
        }, (
            "Conversation was finalized after an idle interval."
            if idle_record
            else "No active Agent learning conversation."
        )
    started_at = core._parse_datetime(str(active["started_at"]), "started_at")
    last_activity = core._parse_datetime(
        str(active["last_activity_at"]), "last_activity_at"
    )
    elapsed_seconds = max(0, int(round((last_activity - started_at).total_seconds())))
    deep_focus, deep_topics = _deep_payload(active)
    return {
        "status": "tracking",
        "elapsed_seconds": elapsed_seconds,
        "learning_turns": int(active.get("learning_turns", 0)),
        "assistant_touches": int(active.get("assistant_touches", 0)),
        "deep_focus": deep_focus,
        "deep_topics": deep_topics,
        "active_session": active,
        "data_file": str(data_file),
    }, (
        f"Agent learning conversation is active for "
        f"{core._format_duration(elapsed_seconds)} with "
        f"{active.get('learning_turns', 0)} learning turns."
    )


def _command_idle_check(
    args: argparse.Namespace, data_file: Path
) -> tuple[dict[str, Any], str]:
    current = core._parse_datetime(args.at, "--at") if args.at else core._local_now()
    timeout_minutes = _positive_int(
        args.idle_timeout_minutes, "--idle-timeout-minutes"
    )
    _, record = _close_if_idle(
        data_file, _active_file(data_file), current, timeout_minutes
    )
    return {
        "status": "finalized" if record else "active_or_idle",
        "closed_session": record,
        "data_file": str(data_file),
    }, (
        "Idle conversation finalized."
        if record
        else "No idle conversation required finalization."
    )


def _conversation_sessions(
    data_file: Path,
    *,
    period: str,
    anchor: str | None,
) -> tuple[list[dict[str, Any]], date | None, date | None, str]:
    anchor_date = core._parse_date(anchor)
    start_date, end_date, period_label = core._period_bounds(period, anchor_date)
    sessions = [
        record
        for record in core._load_sessions(data_file)
        if record.get("source") == "conversation"
    ]
    return (
        core._filter_sessions(
            sessions,
            start_date=start_date,
            end_date=end_date,
            course_filter=None,
        ),
        start_date,
        end_date,
        period_label,
    )


def _build_report_stats(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    topic_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "topic_key": "",
            "topic_label": "",
            "sessions": 0,
            "seconds": 0,
            "learning_turns": 0,
            "deep_sessions": 0,
        }
    )
    total_seconds = 0
    total_turns = 0
    deep_sessions = 0
    deep_seconds = 0
    for record in sessions:
        seconds = core._session_seconds(record)
        conversation = record.get("conversation", {})
        turns = int(conversation.get("learning_turns", 0))
        deep_focus = bool(conversation.get("deep_focus", False))
        total_seconds += seconds
        total_turns += turns
        if deep_focus:
            deep_sessions += 1
            deep_seconds += seconds
        deep_keys = set(conversation.get("deep_topic_keys", []))
        topics = conversation.get("topics", [])
        topic_turn_total = sum(int(topic.get("turns", 0)) for topic in topics)
        for topic in topics:
            key = str(topic.get("topic_key", "general"))
            entry = topic_stats[key]
            turns_for_topic = int(topic.get("turns", 0))
            topic_seconds = (
                int(round(seconds * turns_for_topic / topic_turn_total))
                if topic_turn_total
                else 0
            )
            entry["topic_key"] = key
            entry["topic_label"] = str(topic.get("topic_label", key))
            entry["sessions"] += 1
            entry["seconds"] += topic_seconds
            entry["learning_turns"] += turns_for_topic
            if key in deep_keys:
                entry["deep_sessions"] += 1
    topics = sorted(
        topic_stats.values(),
        key=lambda item: (-item["seconds"], -item["learning_turns"], item["topic_key"]),
    )
    return {
        "total_seconds": total_seconds,
        "total_minutes": round(total_seconds / 60, 1),
        "sessions": len(sessions),
        "learning_turns": total_turns,
        "deep_sessions": deep_sessions,
        "deep_seconds": deep_seconds,
        "deep_minutes": round(deep_seconds / 60, 1),
        "deep_session_ratio": (
            deep_sessions / len(sessions) * 100 if sessions else None
        ),
        "topics": topics,
    }


def _render_report(
    stats: dict[str, Any],
    *,
    period_label: str,
    start_date: date | None,
    end_date: date | None,
) -> str:
    lines = [f"# Agent Learning Report - {period_label}", ""]
    if start_date is not None and end_date is not None:
        lines.append(
            f"- Period: {start_date.isoformat()} to {end_date.isoformat()} exclusive"
        )
    else:
        lines.append("- Period: all recorded Agent learning sessions")
    lines.extend(
        [
            f"- Inferred learning time: {core._format_duration(stats['total_seconds'])}",
            f"- Sessions: {stats['sessions']}",
            f"- Learning turns: {stats['learning_turns']}",
            f"- Deep learning sessions: {stats['deep_sessions']}",
            f"- Deep learning time: {core._format_duration(stats['deep_seconds'])}",
            "- Deep session ratio: "
            + core._format_percent(stats["deep_session_ratio"]),
            "",
        ]
    )
    if not stats["sessions"]:
        lines.extend(["No Agent learning sessions in this period.", ""])
        return "\n".join(lines)
    lines.extend(
        [
            "## Topics",
            "",
            "| Topic | Sessions | Turns | Time | Deep Sessions |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for topic in stats["topics"]:
        lines.append(
            f"| {core._markdown_escape(topic['topic_label'])} | "
            f"{topic['sessions']} | {topic['learning_turns']} | "
            f"{core._format_duration(topic['seconds'])} | "
            f"{topic['deep_sessions']} |"
        )
    lines.extend(
        [
            "",
            "A topic becomes deep learning after three related turns in one session.",
            "Idle gaps longer than ten minutes close the previous session at its last activity.",
            "Only topic metadata and timing are stored; full conversation content is not saved.",
            "",
        ]
    )
    return "\n".join(lines)


def _command_report(
    args: argparse.Namespace, data_file: Path
) -> tuple[dict[str, Any], str]:
    current = core._parse_datetime(args.at, "--at") if args.at else core._local_now()
    timeout_minutes = _positive_int(
        args.idle_timeout_minutes, "--idle-timeout-minutes"
    )
    _, idle_record = _close_if_idle(
        data_file, _active_file(data_file), current, timeout_minutes
    )
    sessions, start_date, end_date, period_label = _conversation_sessions(
        data_file, period=args.period, anchor=args.anchor
    )
    stats = _build_report_stats(sessions)
    markdown = _render_report(
        stats,
        period_label=period_label,
        start_date=start_date,
        end_date=end_date,
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
        text = f"Agent learning report written to {path}."
    else:
        text = markdown
    return {
        "status": "reported",
        "period": args.period,
        "period_label": period_label,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "stats": stats,
        "closed_idle_session": idle_record,
        "output_path": output_path,
        "data_file": str(data_file),
    }, text


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
    parser.add_argument("--output", help="Optional Markdown output path.")
    parser.add_argument("--at", help=argparse.SUPPRESS)
    parser.add_argument(
        "--idle-timeout-minutes",
        type=int,
        default=DEFAULT_IDLE_TIMEOUT_MINUTES,
        help=argparse.SUPPRESS,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="conversation_tracker.py",
        description="Track inferred Agent learning conversations and deep focus.",
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

    observe = subparsers.add_parser(
        "observe", help="Record one user turn as learning or non-learning."
    )
    observe.add_argument("--learning", choices=("yes", "no"), required=True)
    observe.add_argument("--topic-key", help="Stable key for the current topic.")
    observe.add_argument("--topic-label", help="Human-readable topic name.")
    observe.add_argument("--at", help=argparse.SUPPRESS)
    observe.add_argument(
        "--idle-timeout-minutes",
        type=int,
        default=DEFAULT_IDLE_TIMEOUT_MINUTES,
        help=argparse.SUPPRESS,
    )
    observe.add_argument(
        "--deep-threshold",
        type=int,
        default=DEFAULT_DEEP_THRESHOLD,
        help=argparse.SUPPRESS,
    )

    touch = subparsers.add_parser(
        "touch", help="Update activity after an assistant response."
    )
    touch.add_argument("--at", help=argparse.SUPPRESS)
    touch.add_argument(
        "--idle-timeout-minutes",
        type=int,
        default=DEFAULT_IDLE_TIMEOUT_MINUTES,
        help=argparse.SUPPRESS,
    )

    finalize = subparsers.add_parser(
        "finalize", help="Finalize and store the active conversation session."
    )
    finalize.add_argument(
        "--reason",
        default="manual_finalize",
        help=argparse.SUPPRESS,
    )

    status = subparsers.add_parser("status", help="Show the active conversation.")
    status.add_argument("--at", help=argparse.SUPPRESS)
    status.add_argument(
        "--idle-timeout-minutes",
        type=int,
        default=DEFAULT_IDLE_TIMEOUT_MINUTES,
        help=argparse.SUPPRESS,
    )

    idle_check = subparsers.add_parser(
        "idle-check", help="Finalize a conversation that has exceeded the idle limit."
    )
    idle_check.add_argument("--at", help=argparse.SUPPRESS)
    idle_check.add_argument(
        "--idle-timeout-minutes",
        type=int,
        default=DEFAULT_IDLE_TIMEOUT_MINUTES,
        help=argparse.SUPPRESS,
    )

    report = subparsers.add_parser(
        "report", help="Generate an Agent learning report."
    )
    _add_period_arguments(report)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    data_file = core._resolve_data_file(args.data_file)
    handlers = {
        "observe": _command_observe,
        "touch": _command_touch,
        "finalize": _command_finalize,
        "status": _command_status,
        "idle-check": _command_idle_check,
        "report": _command_report,
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
