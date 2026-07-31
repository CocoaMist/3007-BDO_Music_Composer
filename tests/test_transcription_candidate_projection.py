from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TranscriptionCandidateProjectionTests(unittest.TestCase):
    def test_dense_review_setter_keeps_full_index_and_bounds_guide_work(self) -> None:
        script = textwrap.dedent(
            """
            import time
            from unittest.mock import patch

            from PySide6.QtWidgets import QApplication, QWidget

            from bdo_transcription import TranscriptionCandidate
            import bdo_music_composer.ui.editor.piano_roll_canvas as piano_roll_canvas
            import pyside_bdo_gui
            from pyside_bdo_gui import PianoRollCanvas


            class Track:
                track_id = 7


            class Editor(QWidget):
                bpm = 120
                time_sig = 4
                beat_origin_ms = 0.0
                transcription_mode_enabled = True
                track = Track()

                def _candidate_invalid_for_current_track(self, candidate):
                    return False


            app = QApplication([])
            editor = Editor()
            canvas = PianoRollCanvas(editor)
            candidates = (
                TranscriptionCandidate(
                    60,
                    90,
                    0.0,
                    800_000.0,
                    0.95,
                    candidate_id="candidate-long",
                ),
                *(
                    TranscriptionCandidate(
                        40 + index % 48,
                        80,
                        float(index * 25),
                        10.0,
                        0.55 + (index % 20) * 0.02,
                        candidate_id=f"candidate-{index}",
                    )
                    for index in range(1, 28_215)
                ),
            )

            original_builder = piano_roll_canvas.build_melody_line_segments
            guide_sources = []

            def recording_builder(values, candidate_ids, **kwargs):
                guide_sources.append((tuple(values), tuple(candidate_ids)))
                return original_builder(values, candidate_ids, **kwargs)

            with patch.object(
                piano_roll_canvas,
                "build_melody_line_segments",
                side_effect=recording_builder,
            ):
                started = time.perf_counter()
                canvas.set_transcription_review(
                    candidates,
                    lambda candidate: candidate.candidate_id,
                    selected_ids={"candidate-28000"},
                )
                elapsed = time.perf_counter() - started
                canvas.set_transcription_review(
                    candidates,
                    lambda candidate: candidate.candidate_id,
                    selected_ids={"candidate-27999"},
                )

            assert elapsed < 0.65, elapsed
            assert len(canvas.transcription_candidates) == 28_215
            assert len(canvas._transcription_candidate_ids) == 28_215
            assert len(canvas._transcription_candidate_id_to_index) == 28_215
            assert len(canvas._candidate_starts) == 28_215
            assert canvas.selected_candidate_ids == frozenset(
                {"candidate-27999"}
            )

            # Review-only changes reuse the identity-stable candidate source.
            assert len(guide_sources) == 1
            guide_values, guide_ids = guide_sources[0]
            assert 0 < len(guide_values) <= (
                canvas.MAX_MELODY_LINE_SOURCE_CANDIDATES
            )
            assert len(guide_values) == len(guide_ids)
            assert guide_ids[0] == "candidate-long"
            assert guide_ids[-1] == "candidate-28214"

            visible = canvas._visible_candidate_pairs(
                700_000.0,
                701_000.0,
            )
            visible_ids = {candidate_id for candidate_id, _ in visible}
            assert "candidate-long" in visible_ids
            assert all(
                candidate.start_ms <= 701_000.0
                and candidate.start_ms + candidate.duration_ms
                >= 700_000.0 - 4.0 / canvas.px_per_ms
                for _candidate_id, candidate in visible
            )
            assert canvas._last_candidate_query_inspections <= (
                canvas.CANDIDATE_QUERY_BLOCK_SIZE * 4
            )

            canvas.close()
            editor.close()
            app.processEvents()
            app.quit()
            """
        )
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
