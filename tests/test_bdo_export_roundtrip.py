from __future__ import annotations

import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from inspect_bdo import parse_bdo  # noqa: E402
from bdo_codec import decode_score  # noqa: E402
from bdo_midi import Note  # noqa: E402
from bdo_export import channel_groups_to_bdo  # noqa: E402
from bdo_music_composer.editor.velocity_curve import (  # noqa: E402
    VelocityEnvelopePoint,
    apply_velocity_level_envelope,
)
from bdo_music_composer.core.conversion_settings import ConversionSettings  # noqa: E402
from bdo_music_composer.editor.editor_import import (  # noqa: E402
    TrackImportPresentation,
    tracks_from_bdo_snapshot,
)
from bdo_music_composer.editor.pitch_transform import PitchTransformPlan  # noqa: E402
from bdo_music_composer.export.bdo_score import snapshot_from_bytes  # noqa: E402
from bdo_music_composer.export.export_workflow import (  # noqa: E402
    ExportRequest,
    freeze_export_tracks,
    prepare_export,
)
from bdo_music_composer.ui.main_window import BDO_ARTICULATIONS, copy_export_to_game  # noqa: E402


class BdoExportRoundTripTests(unittest.TestCase):
    def test_game_export_import_reexport_preserves_complete_wire_score(self) -> None:
        melodic = [
            Note(
                36 + index % 48,
                30 + index % 90,
                float(index * 37),
                25.0 + index % 11,
                (0, 1, 7, 11, 12, 13)[index % 6],
            )
            for index in range(733)
        ]
        drums = [
            Note(48 + index % 17, 70 + index, 60_000.0 + index * 120.0, 80.0, 99)
            for index in range(3)
        ]
        dual_velocity_records = {
            0: tuple(
                (
                    note.pitch,
                    note.vel,
                    note.start,
                    note.dur,
                    note.ntype,
                    max(0, note.vel - 9),
                )
                for note in melodic
            )
        }
        track_settings = {
            0: (11, 21, 31, 41, 51, 61, 71, 81),
            1: (12, 21, 32, 41, 52, 61, 71, 81),
        }
        source_data, _summary = channel_groups_to_bdo(
            143,
            4,
            [(melodic, 0, False), (drums, 0, True)],
            char_name="Complete RT",
            owner_id=0x12345678,
            instrument_map={0: 0x17, 1: 0x0D},
            preserve_note_types=True,
            track_volumes={0: 83, 1: 67},
            track_settings_map=track_settings,
            velocity_b_maps=dual_velocity_records,
        )
        source_document = decode_score(source_data)
        presentation = TrackImportPresentation(
            colors=("#111111", "#222222"),
            bdo_instrument_name=lambda instrument_id: f"BDO {instrument_id}",
            gm_program_name=lambda program: f"GM {program}",
            drum_track_name=lambda: "Drums",
            new_track_name=lambda track_id: f"Track {track_id + 1}",
        )
        imported_tracks = tracks_from_bdo_snapshot(
            snapshot_from_bytes(source_data),
            presentation,
        )

        self.assertEqual(len(imported_tracks), 2)
        self.assertEqual(imported_tracks[0].bdo_instrument_id, 0x14)
        self.assertEqual(imported_tracks[0].marnian_synth_mode, "superoct")
        self.assertEqual(imported_tracks[1].bdo_instrument_id, 0x0D)
        self.assertEqual(
            [len(track.notes) for track in source_document.groups[0].tracks],
            [730, 3, 0],
        )

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            request = ExportRequest(
                direct_tracks=freeze_export_tracks(imported_tracks),
                bpm=143,
                time_signature=4,
                out_path=root / "roundtrip.bdo",
                character_name="Complete RT",
                owner_id=0x12345678,
                conversion=ConversionSettings.bdo_import_defaults(),
                pitch_plan=PitchTransformPlan(0),
                reverb=21,
                delay=41,
                chorus=(61, 71, 81),
                game_dir=root / "game",
                track_volumes=tuple(
                    (index, track.bdo_track_volume)
                    for index, track in enumerate(imported_tracks)
                ),
                track_settings=tuple(
                    (index, track.bdo_track_settings)
                    for index, track in enumerate(imported_tracks)
                ),
                velocity_b_maps=tuple(
                    (index, track.bdo_source_note_records)
                    for index, track in enumerate(imported_tracks)
                ),
                source_document=source_document,
            )
            prepared = prepare_export(request)

        self.assertEqual(prepared.data, source_data)

    def test_free_point_velocity_envelope_survives_bdo_roundtrip(self) -> None:
        source = [
            Note(60, 40, 0.0, 100.0, 0),
            Note(64, 80, 1000.0, 100.0, 0),
        ]
        curved = apply_velocity_level_envelope(
            source,
            range(2),
            (
                VelocityEnvelopePoint(0.0, 50.0),
                VelocityEnvelopePoint(0.35, 90.0),
                VelocityEnvelopePoint(1.0, 150.0),
            ),
        )
        data, _summary = channel_groups_to_bdo(
            120,
            4,
            [(curved, 0, False)],
            instrument_map={0: 0x0B},
            preserve_note_types=True,
        )
        document = decode_score(data)
        exported = document.groups[0].tracks[0].notes
        self.assertEqual(
            [(note.velocity_a, note.velocity_b) for note in exported],
            [(50, 50), (127, 127)],
        )

    def test_same_game_instrument_is_one_performer_group(self) -> None:
        data, _summary = channel_groups_to_bdo(
            120,
            4,
            [
                ([Note(60, 90, 0.0, 100.0, 0)], 0, False),
                ([Note(64, 90, 200.0, 100.0, 0)], 1, False),
            ],
            instrument_map={0: 0x11, 1: 0x11},
            preserve_note_types=True,
        )

        document = decode_score(data)

        self.assertEqual(len(document.groups), 1)
        self.assertEqual(
            sum(len(track.notes) for track in document.groups[0].tracks),
            2,
        )

    def test_soft_10k_review_threshold_never_truncates_editor_notes(self) -> None:
        notes = [
            Note(60, 90, float(index), 1.0, 0)
            for index in range(10_001)
        ]

        data, summary = channel_groups_to_bdo(
            120,
            4,
            [(notes, 0, False)],
            instrument_map={0: 0x11},
            preserve_note_types=True,
        )
        document = decode_score(data)
        active_tracks = document.groups[0].tracks[:-1]

        self.assertEqual(10_001, summary["total_notes"])
        self.assertEqual(0, summary["notes_dropped"])
        self.assertEqual(10_001, sum(len(track.notes) for track in active_tracks))
        self.assertTrue(all(len(track.notes) <= 730 for track in active_tracks))

    def test_export_is_copied_to_game_folder_and_same_folder_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "out" / "score"
            output.parent.mkdir()
            output.write_bytes(b"score-data")
            game_dir = root / "game" / "music"

            installed = copy_export_to_game(output, game_dir)

            self.assertEqual(installed, game_dir / "score")
            self.assertEqual(installed.read_bytes(), b"score-data")
            self.assertEqual(copy_export_to_game(installed, game_dir), installed)

    def test_canonical_bdo_drums_are_not_mapped_as_gm_a_second_time(self) -> None:
        source = [Note(48, 90, 0.0, 100.0, 99), Note(64, 90, 200.0, 100.0, 99)]
        data, _summary = channel_groups_to_bdo(
            120, 4, [(source, 0, True)], instrument_map={0: 0x0D}, preserve_note_types=True
        )
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "canonical_drums"
            output.write_bytes(data)
            report = parse_bdo(output, sample_notes=10)
        notes = next(
            track["sample_notes"]
            for group in report["groups"] for track in group["tracks"]
            if track["note_count"]
        )
        self.assertEqual([item["pitch"] for item in notes], [48, 64])
        self.assertEqual([item["ntype"] for item in notes], [99, 99])

    def test_all_gui_articulations_survive_gui_export_core_roundtrip(self) -> None:
        channel_groups = []
        instrument_map = {}
        expected_by_instrument: dict[int, Counter[int]] = {}
        start_ms = 0.0
        for channel_index, (instrument_id, definitions) in enumerate(sorted(BDO_ARTICULATIONS.items())):
            notes = []
            expected = Counter()
            for ntype, _label in definitions:
                notes.append(Note(60, 96, start_ms, 400.0, ntype))
                expected[ntype] += 1
                start_ms += 450.0
            channel_groups.append((notes, 0, False))
            instrument_map[channel_index] = instrument_id
            expected_by_instrument[instrument_id] = expected

        bdo_data, summary = channel_groups_to_bdo(
            120,
            4,
            channel_groups,
            char_name="RoundTrip",
            instrument_map=instrument_map,
            vel_layered=True,
            preserve_note_types=True,
        )
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "articulation_roundtrip.bdo"
            output.write_bytes(bdo_data)
            report = parse_bdo(output, sample_notes=0)

        actual_by_instrument: dict[int, Counter[int]] = {}
        for group in report["groups"]:
            for track in group["tracks"]:
                if not track["note_count"]:
                    continue
                actual_by_instrument.setdefault(track["instrument_id"], Counter()).update(
                    {int(ntype): count for ntype, count in track["note_type_counts"].items()}
                )

        self.assertEqual(
            summary["total_notes"],
            sum(sum(counts.values()) for counts in expected_by_instrument.values()),
        )
        self.assertEqual(actual_by_instrument, expected_by_instrument)
        self.assertEqual(report["total_notes"], summary["total_notes"])


if __name__ == "__main__":
    unittest.main()
