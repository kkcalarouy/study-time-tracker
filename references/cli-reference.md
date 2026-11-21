# Study Tracker CLI Reference

## Invocation

Place global options before the command:

```text
python scripts/study_tracker.py --data-file "D:\study\sessions.jsonl" --json start --course "Python"
```

Without `--data-file`, the tracker uses `STUDY_TRACKER_DATA` or
`~/.study-time-tracker/sessions.jsonl`.

On Windows, the following is equivalent and can fall back to a bundled Python
interpreter:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_study_tracker.ps1 status
```

## Commands

### Start

```text
python scripts/study_tracker.py start --course "Operating Systems" --plan-minutes 90
```

Only one timer can be active. A second start fails until the first session is
stopped or cancelled.

### Stop

```text
python scripts/study_tracker.py stop
```

The stopped session is appended to the JSONL history with `"source": "timer"`.

### Status

```text
python scripts/study_tracker.py status
```

The elapsed duration is calculated when the command runs. It is not persisted
until `stop`.

### Cancel

```text
python scripts/study_tracker.py cancel
```

This removes the active timer without creating a session record.

### Manual Add

```text
python scripts/study_tracker.py add --course "Statistics" --minutes 45 --note "Chapter 4"
```

If `--started-at` is omitted, the session is assumed to end now. The record uses
`"source": "manual"`. An overlap with another session is rejected unless
`--allow-overlap` is supplied.

### Report

```text
python scripts/study_tracker.py report --period week
python scripts/study_tracker.py report --period week --output weekly-report.md
python scripts/study_tracker.py report --period month --course "Python"
python scripts/study_tracker.py report --period all --target-minutes 600
```

Periods are `day`, `week`, `month`, or `all`. Weeks start on Monday. `--anchor`
selects the day, week, or month containing a specific `YYYY-MM-DD` date.

Sessions are grouped by the local calendar date on which they started.
`--target-minutes` compares actual time with a target for the selected period.

### CSV Export

```text
python scripts/study_tracker.py export --period month --output study-sessions.csv
```

The CSV includes session ID, course, start and end timestamps, actual minutes,
planned minutes, source, and note.

## Agent Conversation Tracking

Codex performs the semantic decision. `conversation_tracker.py` records the
timing and deep-focus evidence.

### Observe A Learning Turn

```text
python scripts/conversation_tracker.py observe --learning yes --topic-key "sql:indexes" --topic-label "SQL indexes"
```

Use the same `--topic-key` for follow-up turns on the same problem. Three
related turns mark the topic as deep learning. Use a different key for an
unrelated subject.

### Record A Non-Learning Turn

```text
python scripts/conversation_tracker.py observe --learning no
```

This closes the active conversation at its last learning activity.

### Update Activity Before Responding

```text
python scripts/conversation_tracker.py touch
```

If the gap from the previous activity exceeds 10 minutes, the previous session
is finalized at that previous activity timestamp before any new session state
is created.

### Inspect And Finalize

```text
python scripts/conversation_tracker.py status
python scripts/conversation_tracker.py finalize
python scripts/conversation_tracker.py idle-check
```

### Conversation Report

```text
python scripts/conversation_tracker.py report --period week
python scripts/conversation_tracker.py report --period month --output agent-learning.md
```

The report includes inferred learning duration, session count, learning turns,
deep sessions, deep time, deep-session ratio, and topic-level focus.

## Data Schema

Each JSONL line contains:

```json
{
  "id": "32-character hex string",
  "course": "Course name",
  "started_at": "2026-11-18T09:00:00+08:00",
  "ended_at": "2026-11-18T10:30:00+08:00",
  "duration_seconds": 5400,
  "planned_minutes": 90,
  "note": "Chapter 4",
  "source": "timer"
}
```

`source` is `timer` for the built-in timer and `manual` for backfilled records.
Conversation records use `"source": "conversation"` and add a `conversation`
object containing topic metadata, turn counts, deep-focus flags, and the
close reason. Full conversation text is not stored.
All writes are local. Invalid JSONL records are reported with a line number.
