from __future__ import annotations

from types import SimpleNamespace
import unittest

from bdo_music_composer.transcription.bdo_transcription import TranscriptionCandidate
from bdo_music_composer.transcription.bdo_transcription_melody_lines import (
    BASS_ROLE,
    CHORD_SPAN_KIND,
    CONNECTOR_KIND,
    CONTOUR_KIND,
    DETAIL_LOD,
    HARMONY_ROLE,
    NOTE_KIND,
    OVERVIEW_LOD,
    PHRASE_LOD,
    PRIMARY_ROLE,
    build_melody_line_segments,
    melody_line_kind_visible,
    melody_line_lod,
    melody_line_width,
)


def _candidate(
    candidate_id: str,
    pitch: int,
    start_ms: float,
    confidence: float,
) -> TranscriptionCandidate:
    return TranscriptionCandidate(
        pitch,
        90,
        start_ms,
        180.0,
        confidence,
        candidate_id=candidate_id,
    )


class MelodyLineProjectionTests(unittest.TestCase):
    def test_lod_is_zoom_bounded_and_weak_branches_are_detail_only(self) -> None:
        self.assertEqual(melody_line_lod(30), OVERVIEW_LOD)
        self.assertEqual(melody_line_lod(92), PHRASE_LOD)
        self.assertEqual(melody_line_lod(180), DETAIL_LOD)
        self.assertFalse(
            melody_line_kind_visible(
                CONTOUR_KIND,
                branch=False,
                lod=OVERVIEW_LOD,
            )
        )
        self.assertFalse(
            melody_line_kind_visible(
                NOTE_KIND,
                branch=False,
                lod=OVERVIEW_LOD,
            )
        )
        self.assertFalse(
            melody_line_kind_visible(
                CONNECTOR_KIND,
                branch=True,
                lod=PHRASE_LOD,
            )
        )
        self.assertTrue(
            melody_line_kind_visible(
                CONNECTOR_KIND,
                branch=True,
                lod=DETAIL_LOD,
            )
        )
        self.assertFalse(
            melody_line_kind_visible(
                NOTE_KIND,
                branch=False,
                lod=DETAIL_LOD,
            )
        )

    def test_line_width_is_monotonic_confidence_encoding(self) -> None:
        widths = [
            melody_line_width(value)
            for value in (0.0, 0.3, 0.7, 1.0)
        ]
        self.assertEqual(widths, sorted(widths))
        self.assertLess(widths[0], widths[-1])
        self.assertLessEqual(widths[-1], 1.6)

    def test_voice_connectors_do_not_cross_large_gaps_or_pitch_jumps(self) -> None:
        def connectors_for(second_start: float, second_pitch: int):
            candidates = (
                _candidate("first", 60, 0.0, 0.9),
                _candidate("second", second_pitch, second_start, 0.9),
            )
            group = SimpleNamespace(
                group_id="lead",
                candidate_ids=("first", "second"),
                role="primary_melody",
                confidence=0.9,
            )
            return tuple(
                item
                for item in build_melody_line_segments(
                    candidates,
                    ("first", "second"),
                    voice_groups=(group,),
                    beat_ms=500.0,
                )
                if item.kind in {CONNECTOR_KIND, CONTOUR_KIND}
                and item.start_pitch != item.end_pitch
            )

        self.assertTrue(connectors_for(300.0, 65))
        self.assertFalse(connectors_for(300.0, 68))
        self.assertFalse(connectors_for(500.0, 65))

    def test_voice_roles_create_lead_bass_and_harmony_paths(self) -> None:
        candidates = (
            _candidate("lead-1", 72, 0.0, 0.25),
            _candidate("bass-1", 43, 0.0, 0.65),
            _candidate("chord-1", 60, 0.0, 0.55),
            _candidate("lead-2", 76, 300.0, 0.92),
            _candidate("bass-2", 45, 300.0, 0.70),
            _candidate("chord-2", 64, 300.0, 0.60),
        )
        groups = (
            SimpleNamespace(
                group_id="lead",
                candidate_ids=("lead-1", "lead-2"),
                role="primary_melody",
                confidence=0.9,
            ),
            SimpleNamespace(
                group_id="bass",
                candidate_ids=("bass-1", "bass-2"),
                role="bass",
                confidence=0.8,
            ),
            SimpleNamespace(
                group_id="chord",
                candidate_ids=("chord-1", "chord-2"),
                role="harmony",
                confidence=0.7,
            ),
        )
        segments = build_melody_line_segments(
            candidates,
            tuple(item.candidate_id for item in candidates),
            voice_groups=groups,
            beat_ms=500.0,
        )

        self.assertEqual(
            {item.role for item in segments},
            {PRIMARY_ROLE, BASS_ROLE, HARMONY_ROLE},
        )
        lead_notes = [
            item
            for item in segments
            if item.group_id == "lead"
            and item.start_pitch == item.end_pitch
        ]
        self.assertEqual(len(lead_notes), 2)
        self.assertLess(lead_notes[0].confidence, lead_notes[1].confidence)
        self.assertTrue(
            any(
                item.start_pitch != item.end_pitch
                for item in segments
                if item.group_id == "lead"
            )
        )

    def test_projection_is_deterministic_and_input_order_independent(self) -> None:
        candidates = (
            _candidate("a", 72, 0.0, 0.8),
            _candidate("b", 74, 250.0, 0.7),
            _candidate("c", 48, 0.0, 0.6),
        )
        groups = (
            SimpleNamespace(
                group_id="lead",
                candidate_ids=("a", "b"),
                role="primary_melody",
                confidence=0.8,
            ),
            SimpleNamespace(
                group_id="bass",
                candidate_ids=("c",),
                role="bass",
                confidence=0.6,
            ),
        )
        expected = build_melody_line_segments(
            candidates,
            ("a", "b", "c"),
            voice_groups=groups,
        )
        actual = build_melody_line_segments(
            tuple(reversed(candidates)),
            ("c", "b", "a"),
            voice_groups=tuple(reversed(groups)),
        )
        self.assertEqual(actual, expected)

    def test_candidate_only_fallback_is_bounded_and_empty_is_safe(self) -> None:
        self.assertEqual(build_melody_line_segments(()), ())
        candidates = (
            _candidate("low-1", 43, 0.0, 0.8),
            _candidate("mid-1", 60, 0.0, 0.7),
            _candidate("high-1", 72, 0.0, 0.9),
            _candidate("low-2", 45, 300.0, 0.75),
            _candidate("mid-2", 64, 300.0, 0.65),
            _candidate("high-2", 74, 300.0, 0.85),
        )
        segments = build_melody_line_segments(
            candidates,
            tuple(item.candidate_id for item in candidates),
        )
        self.assertEqual(
            {item.role for item in segments},
            {PRIMARY_ROLE, BASS_ROLE, HARMONY_ROLE},
        )
        harmony_groups = {
            item.group_id
            for item in segments
            if item.role == HARMONY_ROLE
        }
        self.assertLessEqual(len(harmony_groups), 3)

    def test_harmony_sidecar_adds_only_supported_unassigned_candidates(self) -> None:
        candidates = (
            _candidate("lead", 72, 0.0, 0.8),
            _candidate("third", 64, 0.0, 0.7),
            _candidate("outside", 66, 0.0, 0.9),
        )
        groups = (
            SimpleNamespace(
                group_id="lead",
                candidate_ids=("lead",),
                role="primary_melody",
                confidence=0.8,
            ),
        )
        harmony = SimpleNamespace(
            chord_segments=(
                SimpleNamespace(
                    segment_id="c-major",
                    start_audio_ms=0.0,
                    end_audio_ms=500.0,
                    root_pc=0,
                    quality="major",
                ),
            )
        )
        segments = build_melody_line_segments(
            candidates,
            ("lead", "third", "outside"),
            voice_groups=groups,
            harmony_analysis=harmony,
        )
        harmony_pitches = {
            item.start_pitch
            for item in segments
            if item.role == HARMONY_ROLE
        }
        self.assertEqual(harmony_pitches, {64.0})

    def test_fallback_prefers_a_continuous_lead_over_high_weak_noise(self) -> None:
        candidates = (
            _candidate("lead-a", 72, 0.0, 0.90),
            _candidate("noise-a", 98, 0.0, 0.20),
            _candidate("bass-a", 43, 0.0, 0.80),
            _candidate("lead-b", 74, 300.0, 0.86),
            _candidate("noise-b", 101, 300.0, 0.24),
            _candidate("bass-b", 45, 300.0, 0.78),
            _candidate("lead-c", 76, 600.0, 0.88),
            _candidate("noise-c", 95, 600.0, 0.22),
            _candidate("bass-c", 47, 600.0, 0.79),
        )
        segments = build_melody_line_segments(
            candidates,
            tuple(item.candidate_id for item in candidates),
        )
        lead_notes = [
            item
            for item in segments
            if item.role == PRIMARY_ROLE
            and item.group_id == "fallback-primary"
            and item.kind == NOTE_KIND
        ]
        self.assertEqual(
            [item.start_pitch for item in lead_notes],
            [72.0, 74.0, 76.0],
        )
        self.assertEqual(
            [item.source_candidate_ids for item in lead_notes],
            [("lead-a",), ("lead-b",), ("lead-c",)],
        )

    def test_chord_span_is_labelled_and_keeps_bounded_source_lineage(self) -> None:
        candidates = (
            _candidate("lead", 72, 0.0, 0.9),
            _candidate("root", 60, 0.0, 0.8),
            _candidate("third", 64, 0.0, 0.75),
            _candidate("fifth", 67, 0.0, 0.7),
        )
        harmony = SimpleNamespace(
            chord_segments=(
                SimpleNamespace(
                    segment_id="c-major",
                    start_audio_ms=0.0,
                    end_audio_ms=500.0,
                    root_pc=0,
                    quality="major",
                    confidence=0.82,
                ),
            )
        )
        segments = build_melody_line_segments(
            candidates,
            tuple(item.candidate_id for item in candidates),
            harmony_analysis=harmony,
        )
        chord_spans = [
            item for item in segments if item.kind == CHORD_SPAN_KIND
        ]
        self.assertEqual(len(chord_spans), 1)
        self.assertEqual(chord_spans[0].label, "C")
        self.assertTrue(chord_spans[0].source_candidate_ids)
        self.assertLessEqual(len(chord_spans[0].source_candidate_ids), 12)

    def test_song_long_note_cannot_reverse_later_overview_time(self) -> None:
        candidates = (
            TranscriptionCandidate(
                60,
                90,
                0.0,
                300_000.0,
                0.9,
                candidate_id="song-long",
            ),
            TranscriptionCandidate(
                61,
                90,
                250.0,
                10.0,
                0.8,
                candidate_id="later-short",
            ),
            TranscriptionCandidate(
                62,
                90,
                500.0,
                10.0,
                0.8,
                candidate_id="last-short",
            ),
        )
        segments = build_melody_line_segments(
            candidates,
            tuple(item.candidate_id for item in candidates),
            beat_ms=500.0,
        )
        contours = [
            item
            for item in segments
            if item.role == PRIMARY_ROLE
            and item.kind == CONTOUR_KIND
            and not item.branch
        ]
        self.assertTrue(contours)
        self.assertTrue(
            all(item.start_audio_ms <= item.end_audio_ms for item in contours)
        )
        self.assertEqual(
            [item.start_audio_ms for item in contours],
            sorted(item.start_audio_ms for item in contours),
        )

    def test_single_overview_bucket_uses_full_phrase_time_envelope(self) -> None:
        candidates = (
            TranscriptionCandidate(
                60,
                90,
                0.0,
                300_000.0,
                0.9,
                candidate_id="song-long",
            ),
            TranscriptionCandidate(
                62,
                90,
                20.0,
                10.0,
                0.7,
                candidate_id="short-overlap",
            ),
        )
        groups = (
            SimpleNamespace(
                group_id="manual-lead",
                candidate_ids=("song-long", "short-overlap"),
                role="primary_melody",
                confidence=0.8,
            ),
        )
        segments = build_melody_line_segments(
            candidates,
            ("song-long", "short-overlap"),
            voice_groups=groups,
            beat_ms=500.0,
        )
        contour = next(
            item
            for item in segments
            if item.group_id == "manual-lead"
            and item.kind == CONTOUR_KIND
        )
        self.assertEqual(contour.start_audio_ms, 0.0)
        self.assertEqual(contour.end_audio_ms, 300_000.0)


if __name__ == "__main__":
    unittest.main()
