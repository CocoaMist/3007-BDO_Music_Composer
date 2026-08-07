from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DenseUiBenchmarkTests(unittest.TestCase):
    def test_small_offscreen_workload_emits_complete_json(self) -> None:
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [
                sys.executable,
                "tools/benchmark_dense_ui.py",
                "--timeline-tracks",
                "4",
                "--notes-per-track",
                "32",
                "--piano-notes",
                "256",
                "--ghost-notes",
                "128",
                "--query-sizes",
                "128,512",
                "--iterations",
                "2",
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result["timeline"]["notes"], 128)
        self.assertEqual(result["piano_roll"]["notes"], 256)
        self.assertEqual(result["piano_roll"]["ghost_notes"], 128)
        self.assertEqual(set(result["piano_roll"]["queries"]), {"128", "512"})
        self.assertEqual(result["timeline"]["single_track_rebuild_count"], 1)
        self.assertGreaterEqual(result["timeline"]["single_track_update_ms"], 0.0)
        self.assertGreaterEqual(result["timeline"]["paint"]["p95_ms"], 0.0)
        self.assertGreaterEqual(result["piano_roll"]["paint"]["p95_ms"], 0.0)


if __name__ == "__main__":
    unittest.main()
