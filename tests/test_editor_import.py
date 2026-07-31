from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from bdo_midi import Note
from conversion_settings import ConversionSettings
from bdo_music_composer.editor.editor_import import (
    EditorImportError,
    EditorImportErrorCode,
    TrackImportPresentation,
    prepare_midi_import,
    tracks_from_bdo_snapshot,
    tracks_from_project_payload,
)


PRESENTATION = TrackImportPresentation(
    colors=("#111111", "#222222"),
    bdo_instrument_name=lambda instrument_id: f"BDO {instrument_id}",
    gm_program_name=lambda program: f"GM {program}",
    drum_track_name=lambda: "Drums",
    new_track_name=lambda track_id: f"Track {track_id + 1}",
)


def project_track(**changes: object) -> dict[str, object]:
    result: dict[str, object] = {
        "track_id": 4,
        "display_name": "Edited lane",
        "gm_program": 12,
        "is_percussion": False,
        "bdo_instrument_id": 0x0B,
        "marnian_synth_mode": "basic",
        "volume_scale": 1.0,
        "duration_scale": 1.0,
        "bdo_track_volume": 83,
        "bdo_track_settings": [1, 2, 3, 4, 5, 6, 7, 8],
        "notes": [[60, 0, 10.5, 90.0, 11]],
        "bdo_source_note_records": [[60, 0, 10.5, 90.0, 11, 37]],
        "performance_controls": [{"kind": "cc", "value": 64}],
    }
    result.update(changes)
    return result


def physical_track(
    group_index: int,
    track_index: int,
    *,
    instrument_id: int = 0x0B,
    notes: tuple[object, ...] = (),
) -> SimpleNamespace:
    return SimpleNamespace(
        group_index=group_index,
        track_index=track_index,
        instrument_id=instrument_id,
        volume=70,
        settings=(1, 2, 3, 4, 5, 6, 7, 8),
        notes=notes,
    )


class ProjectEditorImportTests(unittest.TestCase):
    def test_valid_project_restores_zero_velocity_and_dual_wire_velocity(self) -> None:
        payload = {"tracks": [project_track()]}
        original = deepcopy(payload)

        tracks = tracks_from_project_payload(payload, PRESENTATION)

        self.assertEqual(payload, original)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].track_id, 4)
        self.assertEqual(tracks[0].notes, [Note(60, 0, 10.5, 90.0, 11)])
        self.assertEqual(
            tracks[0].bdo_source_note_records,
            ((60, 0, 10.5, 90.0, 11, 37),),
        )
        self.assertEqual(tracks[0].performance_controls[0]["value"], 64)

    def test_bad_track_or_note_rejects_the_complete_snapshot(self) -> None:
        cases = (
            ({"tracks": [project_track(), "bad-track"]}, "tracks[1]"),
            (
                {"tracks": [project_track(notes=[[60, 80, 0.0]])]},
                "tracks[0].notes[0]",
            ),
            (
                {"tracks": [project_track(notes=[[60, 128, 0.0, 1.0, 0]])]},
                "tracks[0].notes[0][1]",
            ),
            (
                {"tracks": [project_track(notes=[[60, 80, float("nan"), 1.0, 0]])]},
                "tracks[0].notes[0][2]",
            ),
            (
                {"tracks": [project_track(bdo_track_settings=[1, 2])]},
                "tracks[0].bdo_track_settings",
            ),
            (
                {"tracks": [project_track(marnian_synth_mode="unknown")]},
                "tracks[0].marnian_synth_mode",
            ),
            (
                {"tracks": [project_track(volume_scale=0.5)]},
                "tracks[0].volume_scale",
            ),
        )
        for payload, expected_path in cases:
            with self.subTest(path=expected_path):
                with self.assertRaises(EditorImportError) as raised:
                    tracks_from_project_payload(payload, PRESENTATION)
                self.assertEqual(raised.exception.path, expected_path)

    def test_duplicate_track_id_is_rejected(self) -> None:
        with self.assertRaises(EditorImportError) as raised:
            tracks_from_project_payload(
                {"tracks": [project_track(), project_track()]},
                PRESENTATION,
            )
        self.assertEqual(
            raised.exception.code,
            EditorImportErrorCode.DUPLICATE_TRACK_ID,
        )


class BdoEditorImportTests(unittest.TestCase):
    def test_physical_chunks_use_explicit_track_order_for_source_records(self) -> None:
        late = physical_track(
            0,
            1,
            notes=(SimpleNamespace(
                pitch=64,
                ntype=0,
                velocity_a=90,
                velocity_b=70,
                start_ms=100.0,
                duration_ms=80.0,
            ),),
        )
        early = physical_track(
            0,
            0,
            notes=(SimpleNamespace(
                pitch=60,
                ntype=11,
                velocity_a=80,
                velocity_b=60,
                start_ms=0.0,
                duration_ms=90.0,
            ),),
        )

        tracks = tracks_from_bdo_snapshot(
            SimpleNamespace(tracks=(late, early)),
            PRESENTATION,
        )

        self.assertEqual([note.pitch for note in tracks[0].notes], [60, 64])
        self.assertEqual(
            [record[0] for record in tracks[0].bdo_source_note_records],
            [60, 64],
        )
        self.assertEqual(
            tracks[0].effect_settings_placeholder["velocity_pair_mismatches"],
            2,
        )

    def test_duplicate_physical_chunk_index_is_rejected(self) -> None:
        snapshot = SimpleNamespace(tracks=(
            physical_track(0, 0),
            physical_track(0, 0),
        ))
        with self.assertRaisesRegex(
            EditorImportError,
            "duplicate physical track index",
        ):
            tracks_from_bdo_snapshot(snapshot, PRESENTATION)

    def test_marnian_wire_id_restores_logical_mode(self) -> None:
        tracks = tracks_from_bdo_snapshot(
            SimpleNamespace(tracks=(physical_track(0, 0, instrument_id=0x17),)),
            PRESENTATION,
        )
        self.assertEqual(tracks[0].bdo_instrument_id, 0x14)
        self.assertEqual(tracks[0].marnian_synth_mode, "superoct")


class MidiEditorImportTests(unittest.TestCase):
    def test_midi_transform_is_materialized_once_before_commit(self) -> None:
        parsed = (
            152,
            4,
            [([Note(60, 20, 0.0, 100.0, 7)], 12, False)],
            2,
            [[{"kind": "cc", "value": 64}]],
            [{"text": "hello", "time_ms": 0.0}],
        )
        settings = ConversionSettings(velocity_mode="layered")
        with (
            patch(
                "bdo_music_composer.editor.editor_import.parse_midi",
                return_value=parsed,
            ) as parser,
            patch(
                "bdo_music_composer.editor.editor_import."
                "read_midi_time_signature_denominator",
                return_value=8,
            ),
        ):
            imported = prepare_midi_import("source.mid", settings, PRESENTATION)

        self.assertEqual(imported.bpm, 152)
        self.assertEqual(imported.time_signature_denominator, 8)
        self.assertEqual(imported.tracks[0].display_name, "GM 12")
        self.assertNotEqual(imported.tracks[0].notes[0].vel, 20)
        self.assertEqual(imported.tracks[0].notes[0].ntype, 7)
        self.assertEqual(imported.conversion_settings.velocity_mode, "preserve")
        parser.assert_called_once_with(
            "source.mid",
            apply_sustain=True,
            flatten_tempo=False,
            include_controls=True,
            include_lyrics=True,
        )


if __name__ == "__main__":
    unittest.main()
