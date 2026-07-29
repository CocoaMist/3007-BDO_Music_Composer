import unittest
from dataclasses import dataclass
import tempfile
from pathlib import Path
from unittest.mock import patch

from bdo_midi import Note
from bdo_score import read_bdo_score
from export_workflow import execute_export, freeze_export_tracks


@dataclass
class MutableTrack:
    notes: list
    gm_program: int = 0
    is_percussion: bool = False
    bdo_instrument_id: int = 0x0B
    marnian_synth_mode: str = "basic"
    duration_scale: float = 1.0
    volume_scale: float = 1.0
    articulation_type: int | None = None
    bdo_track_volume: int = 70
    bdo_track_settings: tuple[int, ...] = (0,) * 8
    bdo_source_group_index: int | None = None
    bdo_source_note_records: tuple[tuple, ...] = ()


class ExportWorkflowTests(unittest.TestCase):
    def test_snapshot_is_detached_from_editor_note_container(self) -> None:
        original = Note(60, 90, 0.0, 250.0, 0)
        track = MutableTrack([original])
        snapshot = freeze_export_tracks([track])

        track.notes.clear()
        track.duration_scale = 2.0

        self.assertEqual(snapshot[0].notes, (original,))
        self.assertEqual(snapshot[0].duration_scale, 1.0)

    def test_execute_export_publishes_verified_output_and_game_copy(self) -> None:
        snapshot = freeze_export_tracks([
            MutableTrack([Note(60, 90, 0.0, 250.0, 0)])
        ])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "out" / "score.bdo"
            result = execute_export({
                "direct_tracks": snapshot,
                "bdo_source_document": None,
                "bpm_for_temp": 120,
                "time_sig_for_temp": 4,
                "bpm_override": None,
                "char_name": "MIDI",
                "vel_range": None,
                "vel_floor": None,
                "vel_step": None,
                "vel_layered": False,
                "transpose": 0,
                "owner_id": 123,
                "reverb": 0,
                "delay": 0,
                "chorus": None,
                "vel_scales": None,
                "articulation_map": None,
                "track_volumes": {0: 70},
                "track_settings_map": {0: (0,) * 8},
                "velocity_b_maps": None,
                "out_path": str(output),
                "game_dir": str(root / "game"),
            })

            self.assertEqual(Path(result[0]), output)
            self.assertEqual(read_bdo_score(output).total_notes, 1)
            self.assertEqual((root / "game" / "score.bdo").read_bytes(), output.read_bytes())
            self.assertEqual(result[4], "")

    def test_game_install_failure_reports_partial_success(self) -> None:
        snapshot = freeze_export_tracks([
            MutableTrack([Note(60, 90, 0.0, 250.0, 0)])
        ])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "out" / "score.bdo"
            params = {
                "direct_tracks": snapshot,
                "bdo_source_document": None,
                "bpm_for_temp": 120,
                "time_sig_for_temp": 4,
                "bpm_override": None,
                "char_name": "MIDI",
                "vel_range": None,
                "vel_floor": None,
                "vel_step": None,
                "vel_layered": False,
                "transpose": 0,
                "owner_id": 123,
                "reverb": 0,
                "delay": 0,
                "chorus": None,
                "vel_scales": None,
                "articulation_map": None,
                "track_volumes": {0: 70},
                "track_settings_map": {0: (0,) * 8},
                "velocity_b_maps": None,
                "out_path": str(output),
                "game_dir": str(root / "game"),
            }

            with patch(
                "export_workflow.install_export_to_game",
                side_effect=PermissionError("game directory is read-only"),
            ):
                result = execute_export(params)

            self.assertTrue(output.is_file())
            self.assertEqual(read_bdo_score(output).total_notes, 1)
            self.assertEqual(result[0], str(output))
            self.assertEqual(result[3], "")
            self.assertIn("PermissionError", result[4])


if __name__ == "__main__":
    unittest.main()
