from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ConversationTrackerCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.data_file = self.root / "sessions.jsonl"
        self.script = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "conversation_tracker.py"
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(self.script),
                "--data-file",
                str(self.data_file),
                *args,
            ],
            cwd=self.root,
            text=True,
            encoding="utf-8",
            capture_output=True,
        )

    def read_sessions(self) -> list[dict]:
        if not self.data_file.exists():
            return []
        return [
            json.loads(line)
            for line in self.data_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_three_related_turns_become_deep_learning(self) -> None:
        observations = [
            ("09:00:00", "observe", "yes"),
            ("09:02:00", "touch", None),
            ("09:05:00", "observe", "yes"),
            ("09:07:00", "touch", None),
            ("09:09:00", "observe", "yes"),
            ("09:10:00", "touch", None),
        ]
        for time, command, learning in observations:
            args = [command, "--at", f"2026-11-18T{time}+08:00"]
            if command == "observe":
                args.extend(
                    [
                        "--learning",
                        learning or "no",
                        "--topic-key",
                        "python:decorators",
                        "--topic-label",
                        "Python decorators",
                    ]
                )
            result = self.run_cli(*args)
            self.assertEqual(result.returncode, 0, result.stderr)

        finalized = self.run_cli(
            "finalize",
            "--reason",
            "test_complete",
        )
        self.assertEqual(finalized.returncode, 0, finalized.stderr)
        sessions = self.read_sessions()
        self.assertEqual(len(sessions), 1)
        record = sessions[0]
        self.assertEqual(record["source"], "conversation")
        self.assertEqual(record["duration_seconds"], 600)
        self.assertEqual(record["conversation"]["learning_turns"], 3)
        self.assertEqual(record["conversation"]["assistant_touches"], 3)
        self.assertTrue(record["conversation"]["deep_focus"])
        self.assertEqual(record["conversation"]["topics"][0]["turns"], 3)

        report = self.run_cli(
            "--json",
            "report",
            "--period",
            "day",
            "--anchor",
            "2026-11-18",
        )
        self.assertEqual(report.returncode, 0, report.stderr)
        payload = json.loads(report.stdout)
        self.assertEqual(payload["stats"]["sessions"], 1)
        self.assertEqual(payload["stats"]["deep_sessions"], 1)
        self.assertEqual(payload["stats"]["learning_turns"], 3)

        report_file = self.root / "agent-learning.md"
        markdown = self.run_cli(
            "report",
            "--period",
            "day",
            "--anchor",
            "2026-11-18",
            "--output",
            str(report_file),
        )
        self.assertEqual(markdown.returncode, 0, markdown.stderr)
        report_text = report_file.read_text(encoding="utf-8")
        self.assertIn("Deep learning sessions: 1", report_text)
        self.assertIn("Python decorators", report_text)

    def test_idle_gap_closes_previous_session_at_last_activity(self) -> None:
        first = self.run_cli(
            "observe",
            "--learning",
            "yes",
            "--topic-key",
            "database-index",
            "--topic-label",
            "Database indexes",
            "--at",
            "2026-11-18T09:00:00+08:00",
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        touched = self.run_cli(
            "touch",
            "--at",
            "2026-11-18T09:05:00+08:00",
        )
        self.assertEqual(touched.returncode, 0, touched.stderr)

        next_turn = self.run_cli(
            "observe",
            "--learning",
            "yes",
            "--topic-key",
            "database-index",
            "--topic-label",
            "Database indexes",
            "--at",
            "2026-11-18T09:16:00+08:00",
        )
        self.assertEqual(next_turn.returncode, 0, next_turn.stderr)
        sessions = self.read_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["duration_seconds"], 300)
        self.assertEqual(
            sessions[0]["conversation"]["close_reason"], "idle_timeout"
        )

        # The next turn started a fresh active conversation.
        active_file = Path(str(self.data_file) + ".conversation-active.json")
        active = json.loads(active_file.read_text(encoding="utf-8"))
        self.assertEqual(active["started_at"], "2026-11-18T09:16:00+08:00")

    def test_non_learning_turn_stops_without_starting_timer(self) -> None:
        started = self.run_cli(
            "observe",
            "--learning",
            "yes",
            "--topic-key",
            "statistics",
            "--topic-label",
            "Statistics",
            "--at",
            "2026-11-18T09:00:00+08:00",
        )
        self.assertEqual(started.returncode, 0, started.stderr)
        touched = self.run_cli(
            "touch",
            "--at",
            "2026-11-18T09:04:00+08:00",
        )
        self.assertEqual(touched.returncode, 0, touched.stderr)

        stopped = self.run_cli(
            "observe",
            "--learning",
            "no",
            "--at",
            "2026-11-18T09:06:00+08:00",
        )
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        sessions = self.read_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["duration_seconds"], 240)
        self.assertEqual(
            sessions[0]["conversation"]["close_reason"], "non_learning_turn"
        )
        self.assertFalse(
            Path(str(self.data_file) + ".conversation-active.json").exists()
        )


if __name__ == "__main__":
    unittest.main()
