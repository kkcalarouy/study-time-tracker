# Study Time Tracker

A local-first Codex Skill for recording real study time, inferring
Agent-learning conversations, detecting deep focus, and producing
evidence-based reports.

This project is a personal Codex Skill, not an official OpenAI or Codex
project. It does not simulate playback, fake attendance, or bypass course
platform tracking.

## Features

- Start, stop, cancel, and inspect a local study timer.
- Backfill completed sessions manually.
- Distinguish timer (`timer`), manual (`manual`), and inferred conversation
  (`conversation`) records.
- Infer learning turns and close a conversation session after ten minutes of
  inactivity at its last activity timestamp.
- Mark a topic as deep learning after three related turns in one session.
- Provide Agent-learning reports with deep-session and topic-level feedback.
- Detect overlapping sessions.
- Store append-only session history in JSONL.
- Generate daily, weekly, monthly, and all-time Markdown reports.
- Export session-level CSV data.
- Report malformed JSONL records with a line number.
- Use only the Python standard library.
- Run without a database or network connection.

## Repository Structure

```text
.
|-- SKILL.md
|-- agents/
|   `-- openai.yaml
|-- references/
|   `-- cli-reference.md
|-- scripts/
|   |-- conversation_tracker.py
|   |-- run_conversation_tracker.ps1
|   |-- run_study_tracker.ps1
|   `-- study_tracker.py
`-- tests/
    |-- test_conversation_tracker.py
    `-- test_study_tracker.py
```

## Requirements

- Python 3.10 or newer.
- Codex, when installing this repository as a Skill.
- PowerShell is optional and only needed for the Windows launcher.

No third-party Python packages are required.

## Install As A Codex Skill

Clone the repository directly into your Codex skills directory:

```powershell
git clone https://github.com/kkcalarouy/study-time-tracker.git "$env:USERPROFILE\.codex\skills\study-time-tracker"
```

The repository root must remain the Skill directory, with `SKILL.md` directly
inside it. Restart Codex or open a new task after installation.

## Use With Codex

Invoke the Skill explicitly:

```text
Use $study-time-tracker to start a 60-minute study session for Operating Systems.
```

```text
Use $study-time-tracker to stop the current study timer.
```

```text
Use $study-time-tracker to generate this week's study report.
```

```text
Use $study-time-tracker to add a completed 45-minute Statistics session.
```

Codex selects the Skill from its `name` and `description`, then follows the
workflow in `SKILL.md`. The database is not used for trigger routing.

The conversation tracker can infer learning when the Skill is selected or
explicitly invoked:

```text
Use $study-time-tracker to track this learning conversation and tell me when
the current topic counts as deep learning.
```

Codex classifies whether each turn is learning. A repeated topic uses the same
topic key. Three related turns mark that topic as deep learning. If the next
activity is more than ten minutes later, the previous session ends at its last
activity instead of counting the idle gap.

This is not a global always-on hook across every chat. The Skill must be
selected or explicitly invoked for the current conversation.

## Run The Command Line Tool

Run the Python entry point directly:

```text
python scripts/study_tracker.py start --course "Operating Systems" --plan-minutes 60
python scripts/study_tracker.py status
python scripts/study_tracker.py stop
python scripts/study_tracker.py report --period week
python scripts/study_tracker.py export --period month --output sessions.csv
```

Track an Agent-learning turn and response:

```text
python scripts/conversation_tracker.py observe --learning yes --topic-key "sql:indexes" --topic-label "SQL indexes"
python scripts/conversation_tracker.py touch
python scripts/conversation_tracker.py report --period week
```

On Windows, the wrapper can locate a configured Python interpreter:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_study_tracker.ps1 status
powershell -ExecutionPolicy Bypass -File scripts/run_conversation_tracker.ps1 status
```

Set `STUDY_TRACKER_PYTHON` to a Python executable when automatic discovery is
not sufficient.

Place global options before the command:

```text
python scripts/study_tracker.py --data-file "D:\study\sessions.jsonl" --json status
```

See [references/cli-reference.md](references/cli-reference.md) for all
commands and the JSONL schema.

## Data And Privacy

By default, session history is stored at:

```text
~/.study-time-tracker/sessions.jsonl
```

The active timer state is stored next to it with the `.active.json` suffix.
The active conversation state uses the `.conversation-active.json` suffix.
You can override the history path with `STUDY_TRACKER_DATA` or `--data-file`.

The Skill does not upload study data. Do not commit personal session files,
active timer state, generated reports, or exported CSV files to this
repository.

## Test

```text
python -m unittest discover -s tests -v
```

The test suite covers timer recording, duplicate timers, manual entries,
overlap rejection, conversation deep-focus detection, idle-gap finalization,
non-learning turn closure, report generation, CSV export, and malformed JSONL
input.

## Current Limitations

- Designed for a single local user.
- Uses local files instead of a database.
- Does not provide cloud synchronization or multi-device access.
- Groups a session by the local date on which it started.
- Does not split sessions that cross midnight.
- Automatic learning inference is only active while this Skill is selected or
  explicitly invoked.
- Conversation tracking stores topic metadata and timestamps, not full message
  bodies.
- Does not integrate with course platforms or attendance systems.

## License

MIT License. See [LICENSE](LICENSE).
