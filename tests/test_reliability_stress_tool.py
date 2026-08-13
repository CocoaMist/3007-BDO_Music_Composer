from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ReliabilityStressToolTests(unittest.TestCase):
    def test_bounded_adversarial_workload_passes(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "tools/stress_project_reliability.py",
                "--seed", "17", "--iterations", "20",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["autosave"]["malformed_rejected"], 3)


if __name__ == "__main__":
    unittest.main()
