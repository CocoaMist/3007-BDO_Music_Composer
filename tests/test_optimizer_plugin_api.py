from __future__ import annotations

from collections import namedtuple
from dataclasses import dataclass
import unittest

from optimization.plugin_api import (
    CreateTrack,
    DeleteNote,
    EffectChange,
    InsertNote,
    InvalidOptimizationPreview,
    NoteSnapshot,
    OptimizationIntensity,
    OptimizationLimits,
    OptimizationPreview,
    ReplaceTrackNotes,
    ReplaceNote,
    SetTrackInstrument,
    apply_preview,
    build_request,
)


Note = namedtuple("Note", "pitch vel start dur ntype", defaults=(0,))


@dataclass
class Track:
    track_id: int
    notes: list
    gm_program: int = 0
    is_percussion: bool = False
    display_name: str = "track"
    bdo_instrument_id: int = 11
    articulation_type: int | None = None
    marnian_synth_mode: str = "basic"
    notes_optimized: bool = False


class OptimizerPluginApiTests(unittest.TestCase):
    def request(self, tracks, scope="global"):
        return build_request(
            tracks, 120, 4, frozenset({1}), {11: frozenset(range(36, 97))}, {},
            OptimizationIntensity.BALANCED, scope,
        )

    def test_preview_replaces_notes_without_mutating_source_and_rejects_stale_apply(self) -> None:
        track = Track(1, [Note(60, 80, 0, 400, 7)])
        request = self.request([track])
        after = (NoteSnapshot(72, 80, 0, 400, 7),)
        preview = OptimizationPreview(
            request.source_fingerprint, "test", "1",
            (ReplaceTrackNotes(1, request.tracks[0].notes, after),),
        )
        result, _effects = apply_preview([track], request, preview)
        self.assertEqual(track.notes[0].pitch, 60)
        self.assertEqual(result[0].notes[0], Note(72, 80, 0, 400, 7))
        track.notes[0] = track.notes[0]._replace(vel=81)
        with self.assertRaisesRegex(InvalidOptimizationPreview, "changed"):
            apply_preview([track], request, preview)

    def test_created_tracks_are_split_at_680_notes(self) -> None:
        track = Track(1, [Note(60, 80, 0, 400, 0)])
        request = self.request([track])
        notes = tuple(NoteSnapshot(60, 70, index * 100.0, 80, 0) for index in range(681))
        preview = OptimizationPreview(
            request.source_fingerprint, "test", "1",
            (CreateTrack("suggestion", 11, False, notes),),
        )
        result, _effects = apply_preview([track], request, preview)
        self.assertEqual([len(item.notes) for item in result[1:]], [680, 1])
        self.assertEqual(len({item.track_id for item in result}), 3)

    def test_single_track_scope_rejects_track_creation_and_illegal_drums(self) -> None:
        track = Track(1, [Note(60, 80, 0, 400, 0)])
        request = self.request([track], "single_track")
        preview = OptimizationPreview(
            request.source_fingerprint, "test", "1",
            (CreateTrack("drums", 13, True, (NoteSnapshot(36, 90, 0, 100, 0),)),),
        )
        with self.assertRaises(InvalidOptimizationPreview):
            apply_preview([track], request, preview)

    def test_plugin_cannot_invent_an_unsupported_articulation(self) -> None:
        track = Track(1, [Note(60, 80, 0, 400, 0)])
        request = build_request(
            [track], 120, 4, frozenset({1}), {11: frozenset(range(36, 97))},
            {11: ((0, "basic"), (4, "trill"))}, OptimizationIntensity.BALANCED, "global",
        )
        preview = OptimizationPreview(
            request.source_fingerprint, "test", "1",
            (ReplaceTrackNotes(
                1, request.tracks[0].notes, (NoteSnapshot(60, 80, 0, 400, 77),)
            ),),
        )
        with self.assertRaisesRegex(InvalidOptimizationPreview, "unsupported"):
            apply_preview([track], request, preview)

    def test_indexed_replace_insert_and_delete_are_applied_against_original_indices(self) -> None:
        track = Track(1, [Note(60, 80, 0, 300, 0), Note(62, 81, 400, 300, 0)])
        request = self.request([track])
        preview = OptimizationPreview(
            request.source_fingerprint, "test", "1", (
                InsertNote(1, 0, NoteSnapshot(55, 70, 0, 100, 0)),
                ReplaceNote(1, 0, request.tracks[0].notes[0], NoteSnapshot(61, 80, 100, 300, 0)),
                DeleteNote(1, 1, request.tracks[0].notes[1]),
            ),
        )
        result, _effects = apply_preview([track], request, preview)
        self.assertEqual([note.pitch for note in result[0].notes], [55, 61])

    def test_unknown_instruments_and_noncanonical_drum_tracks_are_rejected(self) -> None:
        track = Track(1, [Note(60, 80, 0, 300, 0)])
        request = build_request(
            [track], 120, 4, frozenset({1}), {11: frozenset(range(36, 97))}, {},
            OptimizationIntensity.BALANCED, "global",
            valid_instrument_ids=frozenset({11, 13}),
        )
        unknown = OptimizationPreview(
            request.source_fingerprint, "test", "1",
            (SetTrackInstrument(1, 11, 99),),
        )
        with self.assertRaisesRegex(InvalidOptimizationPreview, "unknown BDO instrument"):
            apply_preview([track], request, unknown)
        malformed_drums = OptimizationPreview(
            request.source_fingerprint, "test", "1",
            (CreateTrack("drums", 13, False, (NoteSnapshot(60, 80, 0, 100, 0),)),),
        )
        with self.assertRaisesRegex(InvalidOptimizationPreview, "canonical BDO drum-set"):
            apply_preview([track], request, malformed_drums)

    def test_request_limits_are_enforced_before_plugin_execution(self) -> None:
        track = Track(1, [Note(60, 80, 0, 300, 0), Note(62, 80, 400, 300, 0)])
        with self.assertRaisesRegex(InvalidOptimizationPreview, "note limit"):
            build_request(
                [track], 120, 4, frozenset({1}), {11: frozenset(range(36, 97))}, {},
                OptimizationIntensity.BALANCED, "global",
                limits=OptimizationLimits(max_song_notes=1),
            )
        long_track = Track(1, [Note(60, 80, 0, 61_000, 0)])
        with self.assertRaisesRegex(InvalidOptimizationPreview, "beat limit"):
            build_request(
                [long_track], 120, 4, frozenset({1}), {11: frozenset(range(36, 97))}, {},
                OptimizationIntensity.BALANCED, "global",
                limits=OptimizationLimits(max_song_beats=1),
            )

    def test_preview_may_write_global_effects_only_once(self) -> None:
        track = Track(1, [Note(60, 80, 0, 300, 0)])
        request = self.request([track])
        preview = OptimizationPreview(
            request.source_fingerprint, "test", "1",
            (EffectChange(1, 2, None), EffectChange(3, 4, None)),
        )
        with self.assertRaisesRegex(InvalidOptimizationPreview, "only one"):
            apply_preview([track], request, preview)


if __name__ == "__main__":
    unittest.main()
