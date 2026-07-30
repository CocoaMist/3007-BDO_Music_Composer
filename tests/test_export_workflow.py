import unittest
from dataclasses import dataclass
import tempfile
from pathlib import Path
from unittest.mock import patch

from bdo_midi import Note
from bdo_score import read_bdo_score
from conversion_settings import ConversionSettings
from export_workflow import (
    ExportRequest,
    execute_export,
    freeze_export_tracks,
    prepare_export,
)
from pitch_transform import PitchTransformPlan


@dataclass
class MutableTrack:
    notes: list
    track_id: int = 0
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
                "conversion_settings": ConversionSettings.bdo_import_defaults(),
                "char_name": "MIDI",
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

    def test_typed_request_applies_stable_per_track_octaves_once(self) -> None:
        snapshots = freeze_export_tracks(
            [
                MutableTrack(
                    [Note(60, 90, 0.0, 250.0, 0)],
                    track_id=7,
                ),
                MutableTrack(
                    [Note(72, 90, 300.0, 250.0, 0)],
                    track_id=9,
                ),
            ]
        )
        conversion = ConversionSettings.bdo_import_defaults().with_updates(
            transpose=-8
        )
        plan = (
            PitchTransformPlan(-8)
            .with_track_octave(7, 12)
            .with_track_octave(9, -12)
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "score.bdo"
            request = ExportRequest(
                direct_tracks=snapshots,
                bpm=120,
                time_signature=4,
                out_path=output,
                character_name="MIDI",
                owner_id=123,
                conversion=conversion,
                pitch_plan=plan,
                reverb=0,
                delay=0,
                chorus=None,
                game_dir=root / "game",
                track_volumes=((0, 70), (1, 70)),
                track_settings=((0, (0,) * 8), (1, (0,) * 8)),
            )

            prepared = prepare_export(request)

            self.assertFalse(output.exists())
            output.write_bytes(prepared.data)
            snapshot = read_bdo_score(output)
            pitches = sorted(
                note.pitch
                for track in snapshot.tracks
                for note in track.notes
            )
            self.assertEqual(pitches, [52, 64])

    def test_typed_request_rejects_divergent_global_pitch_sources(self) -> None:
        snapshot = freeze_export_tracks(
            [MutableTrack([Note(60, 90, 0.0, 250.0, 0)])]
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(ValueError):
                ExportRequest(
                    direct_tracks=snapshot,
                    bpm=120,
                    time_signature=4,
                    out_path=root / "score.bdo",
                    character_name="MIDI",
                    owner_id=123,
                    conversion=ConversionSettings.bdo_import_defaults(),
                    pitch_plan=PitchTransformPlan(12),
                    reverb=0,
                    delay=0,
                    chorus=None,
                    game_dir=root / "game",
                )


if __name__ == "__main__":
    unittest.main()
