from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class StudyTrackerCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.data_file = self.root / "sessions.jsonl"
        self.script = (
            Path(__file__).resolve().parents[1] / "scripts" / "study_tracker.py"
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(self.script),
            "--data-file",
            str(self.data_file),
            *args,
        ]
        return subprocess.run(
            command,
            cwd=self.root,
            text=True,
            encoding="utf-8",
            capture_output=True,
        )

    def test_timer_records_actual_elapsed_time(self) -> None:
        started = self.run_cli(
            "start",
            "--course",
            "Operating Systems",
            "--plan-minutes",
            "60",
            "--at",
            "2026-11-18T09:00:00+08:00",
        )
        self.assertEqual(started.returncode, 0, started.stderr)

        status = self.run_cli(
            "status",
            "--at",
            "2026-11-18T09:35:00+08:00",
        )
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn("Elapsed: 35m", status.stdout)

        stopped = self.run_cli(
            "stop",
            "--at",
            "2026-11-18T09:40:00+08:00",
            "--note",
            "Chapter 2",
        )
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        self.assertIn("40m", stopped.stdout)

        records = [
            json.loads(line)
            for line in self.data_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["duration_seconds"], 2400)
        self.assertEqual(records[0]["source"], "timer")
        self.assertEqual(records[0]["note"], "Chapter 2")
        self.assertFalse(Path(str(self.data_file) + ".active.json").exists())

    def test_manual_entries_and_reports_are_labeled(self) -> None:
        first = self.run_cli(
            "add",
            "--course",
            "Statistics",
            "--minutes",
            "45",
            "--planned-minutes",
            "60",
            "--started-at",
            "2026-11-18T10:00:00+08:00",
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.run_cli(
            "add",
            "--course",
            "Python",
            "--minutes",
            "30",
            "--planned-minutes",
            "45",
            "--started-at",
            "2026-11-18T11:00:00+08:00",
        )
        self.assertEqual(second.returncode, 0, second.stderr)

        report_json = self.run_cli(
            "--json",
            "report",
            "--period",
            "week",
            "--anchor",
            "2026-11-18",
        )
        self.assertEqual(report_json.returncode, 0, report_json.stderr)
        payload = json.loads(report_json.stdout)
        self.assertEqual(payload["stats"]["total_minutes"], 75.0)
        self.assertEqual(payload["stats"]["total_sessions"], 2)
        self.assertEqual(payload["stats"]["sources"][0]["source"], "manual")

        report_file = self.root / "weekly.md"
        markdown = self.run_cli(
            "report",
            "--period",
            "week",
            "--anchor",
            "2026-11-18",
            "--target-minutes",
            "120",
            "--output",
            str(report_file),
        )
        self.assertEqual(markdown.returncode, 0, markdown.stderr)
        report_text = report_file.read_text(encoding="utf-8")
        self.assertIn("Total study time: 1h 15m", report_text)
        self.assertIn("Manual entries are not evidence", report_text)
        self.assertIn("Target: 120 minutes", report_text)

        csv_file = self.root / "sessions.csv"
        exported = self.run_cli(
            "export",
            "--period",
            "week",
            "--anchor",
            "2026-11-18",
            "--output",
            str(csv_file),
        )
        self.assertEqual(exported.returncode, 0, exported.stderr)
        with csv_file.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["source"] for row in rows}, {"manual"})
        self.assertEqual({row["duration_minutes"] for row in rows}, {"30", "45"})
        self.assertEqual({row["planned_minutes"] for row in rows}, {"45", "60"})

    def test_overlap_is_rejected_without_explicit_override(self) -> None:
        first = self.run_cli(
            "add",
            "--course",
            "Math",
            "--minutes",
            "60",
            "--started-at",
            "2026-11-18T09:00:00+08:00",
        )
        self.assertEqual(first.returncode, 0, first.stderr)

        overlap = self.run_cli(
            "add",
            "--course",
            "Physics",
            "--minutes",
            "20",
            "--started-at",
            "2026-11-18T09:30:00+08:00",
        )
        self.assertEqual(overlap.returncode, 2)
        self.assertIn("overlaps", overlap.stderr)
        self.assertEqual(len(self.data_file.read_text(encoding="utf-8").splitlines()), 1)

        allowed = self.run_cli(
            "add",
            "--course",
            "Physics",
            "--minutes",
            "20",
            "--started-at",
            "2026-11-18T09:30:00+08:00",
            "--allow-overlap",
        )
        self.assertEqual(allowed.returncode, 0, allowed.stderr)

    def test_duplicate_timer_and_cancel(self) -> None:
        start = self.run_cli(
            "start",
            "--course",
            "Databases",
            "--at",
            "2026-11-18T09:00:00+08:00",
        )
        self.assertEqual(start.returncode, 0, start.stderr)

        duplicate = self.run_cli(
            "start",
            "--course",
            "Networks",
            "--at",
            "2026-11-18T09:10:00+08:00",
        )
        self.assertEqual(duplicate.returncode, 2)
        self.assertIn("already active", duplicate.stderr)

        cancelled = self.run_cli("cancel")
        self.assertEqual(cancelled.returncode, 0, cancelled.stderr)
        self.assertFalse(self.data_file.exists())
        self.assertFalse(Path(str(self.data_file) + ".active.json").exists())

    def test_invalid_jsonl_reports_line_number(self) -> None:
        self.data_file.write_text("{not valid json}\n", encoding="utf-8")
        result = self.run_cli("report", "--period", "all")
        self.assertEqual(result.returncode, 2)
        self.assertIn("line 1", result.stderr)


if __name__ == "__main__":
    unittest.main()
