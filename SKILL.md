---
name: study-time-tracker
description: Track real study time with a local timer, manual backfills, JSONL history, and Markdown or CSV reports. Use for personal study planning, time logging, and progress reviews. Do not use to simulate attendance, playback, or platform watch time.
---

# Study Time Tracker

Record only time the user says they actually studied. Never simulate playback,
fake attendance, bypass course checks, or claim activity the user did not
perform.

## Defaults

- Session history: `STUDY_TRACKER_DATA`, otherwise
  `~/.study-time-tracker/sessions.jsonl`.
- Active timer marker: `<session history>.active.json`.
- The tracker is local-only and uses the Python standard library.
- Timestamps use ISO 8601. Naive timestamps use the machine's local timezone.
- Reports label manual entries separately from timer entries.

## Run The Tracker

Use a Python 3.10 or newer interpreter to run
`scripts/study_tracker.py`. If `python` is not on PATH, use the Python
interpreter available in the current Codex environment. On Windows, the
`scripts/run_study_tracker.ps1` wrapper can locate a configured or bundled
interpreter automatically.

Read [references/cli-reference.md](references/cli-reference.md) when command
syntax, period behavior, or the data schema is needed.

## Core Workflow

1. When the user begins studying, run:

   ```text
   python scripts/study_tracker.py start --course "<course>"
   ```

   Add `--plan-minutes <number>` when the user has a target for that session.

2. When the session ends, run:

   ```text
   python scripts/study_tracker.py stop
   ```

3. When the user reports a completed session instead of using the timer, run:

   ```text
   python scripts/study_tracker.py add --course "<course>" --minutes <number>
   ```

   Use `--started-at` when the user provides a start time. Confirm ambiguous
   course names or durations before recording them.

4. When the user asks about current progress, run:

   ```text
   python scripts/study_tracker.py status
   ```

5. For a daily, weekly, monthly, or all-time review, run:

   ```text
   python scripts/study_tracker.py report --period week
   ```

   Use `--output <path>` to save Markdown. Use `export --output <path>` for a
   session-level CSV.

6. If a timer was started by mistake, run:

   ```text
   python scripts/study_tracker.py cancel
   ```

## Data Rules

- Do not invent missing durations or silently round user-provided values.
- Do not infer study time from application usage unless the user explicitly
  supplies that evidence and asks to record it.
- Keep manual entries marked as `manual`; do not relabel them as timer data.
- If the data file contains an invalid record, report the line number and stop
  rather than skipping the record.
- Do not upload or transmit session data. It remains in the local data file.

## Verification

Run the tests after changing the tracker:

```text
python -m unittest discover -s tests -v
```
