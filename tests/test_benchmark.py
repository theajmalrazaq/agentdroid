"""Unit tests for the AgentDroid competitor-aligned benchmark harness."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.benchmark import (
    BASELINES_PATH,
    TASKS,
    compute_vision_tokens,
    load_baselines,
    nearest_rank_p90,
    record_trials,
    summarize_samples,
    summarize_track,
    write_csv_artifacts,
)


class BenchmarkHarnessTests(unittest.TestCase):
    def test_nearest_rank_p90_and_failure_preservation(self) -> None:
        self.assertEqual(nearest_rank_p90([10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]), 90.0)
        samples = [
            {"ok": True, "duration_ms": 10.0, "error": ""},
            {"ok": True, "duration_ms": 20.0, "error": ""},
            {"ok": False, "duration_ms": 999.0, "error": "timeout"},
            {"ok": True, "duration_ms": 30.0, "error": ""},
        ]
        s = summarize_samples(samples)
        self.assertEqual(s["n"], 4)
        self.assertEqual(s["failed"], 1)
        self.assertEqual(s["median_ms"], 20.0)
        self.assertEqual(s["p90_ms"], 30.0)
        self.assertEqual(s["samples_ms"], [10.0, 20.0, 30.0])

    def test_record_trials_captures_exceptions(self) -> None:
        def _fn(idx: int) -> None:
            if idx == 1:
                raise RuntimeError("boom")

        summary, rows = record_trials("tap", 3, _fn)
        self.assertEqual(summary["n"], 3)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(len(rows), 3)
        self.assertIn("RuntimeError: boom", rows[1]["error"])

    def test_compute_vision_tokens_1080x2400(self) -> None:
        tok = compute_vision_tokens(1080, 2400)
        self.assertEqual(tok["openai_tiles"], "2x4=8")
        self.assertEqual(tok["openai_high_detail_tokens"], 1445)
        self.assertEqual(tok["anthropic_scaled"], "706x1568")
        self.assertEqual(tok["anthropic_vision_tokens"], 1477)

    def test_baselines_json_schema(self) -> None:
        self.assertTrue(BASELINES_PATH.is_file())
        data = load_baselines()
        self.assertIn("infrastructure_competitors", data)
        self.assertIn("agent_competitors", data)
        self.assertIn("vostride_matched_tasks", data)
        providers = {row["provider"] for row in data["infrastructure_competitors"]}
        self.assertIn("Mobilebox", providers)
        self.assertIn("Limrun", providers)

    def test_task_registry_and_summarize_track(self) -> None:
        self.assertEqual(len(TASKS), 13)
        fake_rows = [
            {
                "task_id": "t1",
                "app": "Clock",
                "tier": "Simple",
                "mode": "compound",
                "ok": True,
                "crashes": False,
                "wall_clock_sec": 1.0,
                "steps_executed": 4,
                "llm_turns_required": 1,
                "prompt_est_tokens": 400,
                "vision_loop_equiv_tokens": 5780,
                "baseline_source": "Vostride / AndroidWorld",
                "baseline_sec": 38.0,
                "speedup_x": 38.0,
                "verification": "ok",
            },
            {
                "task_id": "t2",
                "app": "Markor",
                "tier": "Complex",
                "mode": "compound",
                "ok": True,
                "crashes": False,
                "wall_clock_sec": 4.0,
                "steps_executed": 10,
                "llm_turns_required": 1,
                "prompt_est_tokens": 500,
                "vision_loop_equiv_tokens": 14450,
                "baseline_source": None,
                "baseline_sec": None,
                "speedup_x": None,
                "verification": "ok",
            },
        ]
        summary = summarize_track(fake_rows)
        self.assertEqual(summary["overall"]["passed"], 2)
        self.assertEqual(summary["overall"]["success_rate_pct"], 100.0)
        self.assertEqual(summary["overall"]["matched_speedup_x"], 38.0)

    def test_write_csv_artifacts_mobilebox_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            report = {
                "runtime": {
                    "container_cold_restart": {
                        "ready": {"n": 3, "failed": 0, "median_ms": 9500.0, "p90_ms": 9900.0}
                    },
                    "micro_benchmarks": {
                        "tap": {"n": 100, "failed": 0, "median_ms": 0.9, "p90_ms": 1.2}
                    },
                },
                "e2e_modes": {
                    "compound": {
                        "tasks": [
                            {
                                "task_id": "ClockStopWatchRunning",
                                "app": "Clock",
                                "tier": "Simple",
                                "ok": True,
                                "wall_clock_sec": 0.5,
                                "steps_executed": 5,
                                "llm_turns_required": 1,
                                "prompt_est_tokens": 420,
                                "vision_loop_equiv_tokens": 7225,
                                "baseline_source": "Vostride / AndroidWorld",
                                "baseline_sec": 38.0,
                                "speedup_x": 76.0,
                                "crashes": False,
                                "verification": "pause=True",
                            }
                        ]
                    }
                },
            }
            samples = [
                {
                    "provider": "AgentDroid",
                    "metric": "tap",
                    "sample_index": 1,
                    "ok": True,
                    "duration_ms": 0.9,
                    "error": "",
                    "timestamp_utc": "2026-11-19T00:00:00+00:00",
                }
            ]
            write_csv_artifacts(tmp_dir, report, samples, "Local host", "local")
            with (tmp_dir / "summary.csv").open(encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(rows[0]["provider"], "AgentDroid")
            self.assertEqual(rows[0]["metric"], "ready")
            self.assertEqual(rows[1]["metric"], "tap")
            self.assertTrue((tmp_dir / "samples.csv").is_file())
            self.assertTrue((tmp_dir / "tasks.csv").is_file())


if __name__ == "__main__":
    unittest.main()
