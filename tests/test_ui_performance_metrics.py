from __future__ import annotations

import unittest

from bdo_music_composer.ui.performance_metrics import UiPerformanceRecorder


class UiPerformanceRecorderTests(unittest.TestCase):
    def test_input_latency_and_stalls_are_bounded_content_free_metrics(self) -> None:
        recorder = UiPerformanceRecorder(capacity=16, stall_threshold_ms=32.0)
        recorder.note_input(1_000_000_000)
        self.assertEqual(recorder.note_paint_complete(1_006_000_000), 6.0)
        recorder.heartbeat(2_000_000_000)
        recorder.heartbeat(2_016_000_000)
        recorder.heartbeat(2_066_000_000)

        snapshot = recorder.snapshot()

        self.assertEqual(snapshot.input_samples, 1)
        self.assertEqual(snapshot.input_to_paint_p95_ms, 6.0)
        self.assertEqual(snapshot.heartbeat_samples, 2)
        self.assertEqual(snapshot.stall_count, 1)
        self.assertNotIn("path", snapshot.to_dict())

        recorder.reset_interaction_window(3_000_000_000)
        self.assertEqual(recorder.snapshot().stall_count, 0)

    def test_first_pending_input_owns_the_visual_response_window(self) -> None:
        recorder = UiPerformanceRecorder()
        recorder.note_input(1_000_000)
        recorder.note_input(2_000_000)

        self.assertEqual(recorder.note_paint_complete(5_000_000), 4.0)
        self.assertIsNone(recorder.note_paint_complete(6_000_000))


if __name__ == "__main__":
    unittest.main()
