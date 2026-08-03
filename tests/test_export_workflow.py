import unittest
from dataclasses import dataclass, replace
import tempfile
from pathlib import Path
from unittest.mock import patch

from bdo_codec import decode_score
from bdo_export import channel_groups_to_bdo
from bdo_midi import Note
from bdo_music_composer.export.bdo_score import read_bdo_score
from bdo_common.bdo_track_effects import MasterEffects
from bdo_music_composer.core.conversion_settings import ConversionSettings
from bdo_music_composer.export.export_workflow import (
    ExportRequest,
    ExportRequestSpec,
    build_export_request,
    execute_export,
    freeze_export_tracks,
    prepare_export,
)
from bdo_music_composer.editor.pitch_transform import PitchTransformPlan


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
    muted: bool = False
    solo: bool = False


class ExportWorkflowTests(unittest.TestCase):
    def test_request_factory_derives_one_lossless_game_projection(self) -> None:
        source_record = (60, 91, 72, 11, 0.0, 250.0)
        first_settings = (11, 201, 22, 202, 33, 203, 204, 205)
        second_settings = (44, 91, 55, 92, 66, 93, 94, 95)
        tracks = [
            MutableTrack(
                [Note(60, 91, 0.0, 250.0, 11)],
                articulation_type=11,
                bdo_track_volume=83,
                bdo_track_settings=first_settings,
                bdo_source_note_records=(source_record,),
                muted=True,
            ),
            MutableTrack(
                [Note(64, 80, 250.0, 250.0, 0)],
                bdo_track_volume=64,
                bdo_track_settings=second_settings,
                solo=True,
            ),
        ]
        source_document = object()
        conversion = ConversionSettings().with_updates(transpose=5)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request = build_export_request(
                tracks,
                ExportRequestSpec(
                    bpm=120,
                    time_signature=4,
                    out_path=root / "score.bdo",
                    character_name="Name",
                    owner_id=123,
                    conversion=conversion,
                    pitch_plan=PitchTransformPlan(-12),
                    master_effects=MasterEffects(151, 152, 153, 154, 155),
                    game_dir=root / "game",
                    source_path="source.bdo",
                    source_document=source_document,
                ),
            )

        self.assertEqual(len(request.direct_tracks), 2)
        self.assertEqual(request.pitch_plan.global_semitones, 5)
        self.assertEqual(request.articulation_map, ((0, 11),))
        self.assertEqual(request.track_volumes, ((0, 83), (1, 64)))
        self.assertEqual(
            request.track_settings,
            (
                (0, (11, 151, 22, 152, 33, 153, 154, 155)),
                (1, (44, 151, 55, 152, 66, 153, 154, 155)),
            ),
        )
        self.assertEqual(request.velocity_b_maps, ((0, (source_record,)),))
        self.assertEqual(
            (request.reverb, request.delay, request.chorus),
            (151, 152, (153, 154, 155)),
        )
        self.assertIs(request.source_document, source_document)
        self.assertEqual(tracks[0].bdo_track_settings, first_settings)
        self.assertEqual(tracks[1].bdo_track_settings, second_settings)

    def test_request_factory_rejects_malformed_settings_without_mutation(
        self,
    ) -> None:
        track = MutableTrack(
            [Note(60, 90, 0.0, 250.0, 0)],
            bdo_track_settings=(1, 2),
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec = ExportRequestSpec(
                bpm=120,
                time_signature=4,
                out_path=root / "score.bdo",
                character_name="Name",
                owner_id=123,
                conversion=ConversionSettings(),
                pitch_plan=PitchTransformPlan(0),
                master_effects=MasterEffects(),
                game_dir=root / "game",
            )
            with self.assertRaisesRegex(ValueError, "exactly eight bytes"):
                build_export_request([track], spec)

        self.assertEqual(track.bdo_track_settings, (1, 2))

    def test_lossless_reuse_and_canonical_export_share_one_summary_contract(
        self,
    ) -> None:
        note = Note(60, 91, 1.25, 300.5, 11)
        source_data, canonical_summary = channel_groups_to_bdo(
            120,
            4,
            [([note], 0, False)],
            char_name="Name",
            owner_id=123,
            instrument_map={0: 0x0B},
            preserve_note_types=True,
            track_volumes={0: 70},
            track_settings_map={0: (0,) * 8},
        )
        snapshots = freeze_export_tracks([
            MutableTrack(
                [note],
                bdo_source_group_index=0,
            )
        ])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prepared = prepare_export(ExportRequest(
                direct_tracks=snapshots,
                bpm=120,
                time_signature=4,
                out_path=root / "score.bdo",
                character_name="Name",
                owner_id=123,
                conversion=ConversionSettings(),
                pitch_plan=PitchTransformPlan(0),
                reverb=0,
                delay=0,
                chorus=None,
                game_dir=root / "game",
                track_volumes=((0, 70),),
                track_settings=((0, (0,) * 8),),
                source_document=decode_score(source_data),
            ))

        self.assertEqual(prepared.data, source_data)
        self.assertEqual(prepared.summary, canonical_summary)

    def test_snapshot_is_detached_from_editor_note_container(self) -> None:
        original = Note(60, 90, 0.0, 250.0, 0)
        track = MutableTrack([original])
        snapshot = freeze_export_tracks([track])

        track.notes.clear()
        track.duration_scale = 2.0

        self.assertEqual(snapshot[0].notes, (original,))
        self.assertEqual(snapshot[0].duration_scale, 1.0)

    def test_all_export_entry_points_reject_retired_hidden_velocity_scale(
        self,
    ) -> None:
        track = MutableTrack(
            [Note(60, 90, 0.0, 250.0, 0)],
            volume_scale=0.5,
        )
        with self.assertRaisesRegex(ValueError, "must be baked"):
            freeze_export_tracks([track])

        neutral_snapshot = freeze_export_tracks([
            MutableTrack([Note(60, 90, 0.0, 250.0, 0)])
        ])[0]
        bad_snapshot = replace(neutral_snapshot, volume_scale=0.5)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(ValueError, "must be baked"):
                ExportRequest(
                    direct_tracks=(bad_snapshot,),
                    bpm=120,
                    time_signature=4,
                    out_path=root / "score.bdo",
                    character_name="MIDI",
                    owner_id=123,
                    conversion=ConversionSettings(),
                    pitch_plan=PitchTransformPlan(0),
                    reverb=0,
                    delay=0,
                    chorus=None,
                    game_dir=root / "game",
                )

            with self.assertRaisesRegex(ValueError, "must be baked"):
                ExportRequest.from_parameters({
                    "direct_tracks": [track],
                    "bpm_for_temp": 120,
                    "time_sig_for_temp": 4,
                    "conversion_settings": {"velocity_mode": "preserve"},
                    "char_name": "MIDI",
                    "owner_id": 123,
                    "out_path": str(root / "compat.bdo"),
                    "game_dir": str(root / "game"),
                })

    def test_compat_export_parses_nested_velocity_policy_and_blocks_it(
        self,
    ) -> None:
        snapshot = freeze_export_tracks([
            MutableTrack([Note(60, 90, 0.0, 250.0, 0)])
        ])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(ValueError, "materialized"):
                ExportRequest.from_parameters({
                    "direct_tracks": snapshot,
                    "bpm_for_temp": 120,
                    "time_sig_for_temp": 4,
                    "conversion_settings": {"velocity_mode": "layered"},
                    "char_name": "MIDI",
                    "owner_id": 123,
                    "out_path": str(root / "compat.bdo"),
                    "game_dir": str(root / "game"),
                })

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
                "bdo_music_composer.export.export_workflow.install_export_to_game",
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

    def test_typed_request_rejects_hidden_velocity_processing(self) -> None:
        snapshot = freeze_export_tracks(
            [MutableTrack([Note(60, 90, 0.0, 250.0, 0)])]
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            common = dict(
                direct_tracks=snapshot,
                bpm=120,
                time_signature=4,
                out_path=root / "score.bdo",
                character_name="MIDI",
                owner_id=123,
                pitch_plan=PitchTransformPlan(0),
                reverb=0,
                delay=0,
                chorus=None,
                game_dir=root / "game",
            )
            with self.assertRaisesRegex(ValueError, "materialized"):
                ExportRequest(
                    **common,
                    conversion=ConversionSettings(velocity_mode="layered"),
                )
            with self.assertRaisesRegex(ValueError, "not game fields"):
                ExportRequest(
                    **common,
                    conversion=ConversionSettings(),
                    velocity_scales=((0, 0.8),),
                )

    def test_mixer_only_export_preserves_imported_dual_velocity(self) -> None:
        source_record = (60, 91, 1.25, 300.5, 11, 72)
        snapshot = freeze_export_tracks([
            MutableTrack(
                [Note(60, 91, 1.25, 300.5, 11)],
                bdo_track_volume=83,
                bdo_track_settings=(10, 1, 20, 2, 30, 3, 4, 5),
                bdo_source_note_records=(source_record,),
            )
        ])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "dual-velocity.bdo"
            request = ExportRequest(
                direct_tracks=snapshot,
                bpm=120,
                time_signature=4,
                out_path=output,
                character_name="MIDI",
                owner_id=123,
                conversion=ConversionSettings(),
                pitch_plan=PitchTransformPlan(0),
                reverb=1,
                delay=2,
                chorus=(3, 4, 5),
                game_dir=root / "game",
                track_volumes=((0, 83),),
                track_settings=((0, (10, 1, 20, 2, 30, 3, 4, 5)),),
                velocity_b_maps=((0, (source_record,)),),
            )
            output.write_bytes(prepare_export(request).data)
            score = read_bdo_score(output)
        active_track = next(track for track in score.tracks if track.notes)
        self.assertEqual(active_track.volume, 83)
        self.assertEqual(active_track.settings, (10, 1, 20, 2, 30, 3, 4, 5))
        self.assertEqual(
            (active_track.notes[0].velocity_a, active_track.notes[0].velocity_b),
            (91, 72),
        )

    def test_bdo_drum_target_never_uses_melodic_transpose_or_serialization(self) -> None:
        snapshots = freeze_export_tracks([
            MutableTrack(
                [Note(48, 90, 0.0, 250.0, 99)],
                track_id=7,
                is_percussion=False,
                bdo_instrument_id=0x0D,
            )
        ])
        conversion = ConversionSettings.bdo_import_defaults().with_updates(
            transpose=-8
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "drums.bdo"
            request = ExportRequest(
                direct_tracks=snapshots,
                bpm=120,
                time_signature=4,
                out_path=output,
                character_name="MIDI",
                owner_id=123,
                conversion=conversion,
                pitch_plan=PitchTransformPlan(-8),
                reverb=0,
                delay=0,
                chorus=None,
                game_dir=root / "game",
                track_volumes=((0, 70),),
                track_settings=((0, (0,) * 8),),
            )

            output.write_bytes(prepare_export(request).data)
            notes = [
                note
                for track in read_bdo_score(output).tracks
                for note in track.notes
            ]

        self.assertEqual(
            [(note.pitch, note.ntype) for note in notes],
            [(48, 99)],
        )


if __name__ == "__main__":
    unittest.main()
