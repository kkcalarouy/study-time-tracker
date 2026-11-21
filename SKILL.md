---
name: study-time-tracker
description: Track real study time with a local timer, manual backfills, and automatically inferred Agent-learning conversations. Use when the user studies, asks explanatory or follow-up questions, debugs to learn, deepens a topic, or requests progress reports. Includes 10-minute idle finalization and deep-focus feedback. Do not use to simulate attendance, playback, or platform watch time.
---

# Study Time Tracker

Record only time the user says they actually studied. Never simulate playback,
fake attendance, bypass course checks, or claim activity the user did not
perform.

## Defaults

- Session history: `STUDY_TRACKER_DATA`, otherwise
  `~/.study-time-tracker/sessions.jsonl`.
- Active timer marker: `<session history>.active.json`.
- Active conversation marker: `<session history>.conversation-active.json`.
- The tracker is local-only and uses the Python standard library.
- Timestamps use ISO 8601. Naive timestamps use the machine's local timezone.
- Reports label `timer`, `manual`, and `conversation` entries separately.
- Automatic conversation tracking applies only while this Skill is selected or
  explicitly invoked. Codex does not expose a global hook for every chat.

## Run The Tracker

Use a Python 3.10 or newer interpreter to run
`scripts/study_tracker.py` and `scripts/conversation_tracker.py`. If `python`
is not on PATH, use the Python interpreter available in the current Codex
environment. On Windows, `scripts/run_study_tracker.ps1` and
`scripts/run_conversation_tracker.ps1` can locate a configured or bundled
interpreter automatically.

Read [references/cli-reference.md](references/cli-reference.md) when command
syntax, period behavior, or the data schema is needed.

## Automatic Conversation Tracking

Use this flow on each user turn when the Skill is active.

1. Decide whether the user's current turn is part of learning or
   self-improvement. Learning includes asking for explanations, working through
   a problem, debugging to understand it, comparing concepts, practicing a
   skill, or repeatedly investigating the same topic.

2. For a learning turn, record the turn before answering:

   ```text
   python scripts/conversation_tracker.py observe --learning yes --topic-key "<stable-key>" --topic-label "<topic>"
   ```

   Use a stable topic key for the same ongoing problem. Use a different key for
   an unrelated subject. Do not store full chat text; pass only a short topic
   label and key.

3. Treat the third related turn on one topic key as deep learning. The tracker
   marks `deep_focus` automatically. When that threshold is first reached,
   briefly tell the user in their language that the topic was recorded as deep
   learning and how many related turns it contains. Do not repeat the notice on
   every turn.

4. Before sending the response, update the activity timestamp:

   ```text
   python scripts/conversation_tracker.py touch
   ```

5. If the current turn is not learning, pass:

   ```text
   python scripts/conversation_tracker.py observe --learning no
   ```

   This closes the active learning session at its last learning activity rather
   than counting unrelated conversation time.

6. Every `observe`, `touch`, `status`, and report call checks whether the gap
   from the last activity exceeds 10 minutes. If it does, the previous session
   ends at its last activity and a new session starts only when learning
   resumes. No background daemon is required.

7. For conversation learning feedback, run:

   ```text
   python scripts/conversation_tracker.py report --period week
   ```

   Use `--output <path>` to save Markdown. The report includes inferred learning
   time, learning turns, deep sessions, deep time, and topic-level focus.

Do not classify greetings, simple file operations, unrelated personal tasks,
or ordinary commands as learning. Do not store message bodies, secrets, or
private conversation contents in the tracker.

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

7. To inspect or finalize the inferred Agent-learning session:

   ```text
   python scripts/conversation_tracker.py status
   python scripts/conversation_tracker.py finalize
   python scripts/conversation_tracker.py idle-check
   ```

## Data Rules

- Do not invent missing durations or silently round user-provided values.
- Do not infer study time from application usage unless the user explicitly
  supplies that evidence and asks to record it.
- Keep manual entries marked as `manual`; do not relabel them as timer data.
- Keep inferred Agent-learning entries marked as `conversation`.
- Store only topic keys, topic labels, turn counts, timestamps, and timing
  metadata for conversation sessions.
- If the data file contains an invalid record, report the line number and stop
  rather than skipping the record.
- Do not upload or transmit session data. It remains in the local data file.

## Verification

Run the tests after changing the tracker:

```text
python -m unittest discover -s tests -v
```
