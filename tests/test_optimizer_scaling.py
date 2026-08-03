from __future__ import annotations

from collections import namedtuple
import math
import random
from types import SimpleNamespace
import unittest

from bdo_music_composer.editor.bdo_music_theory import (
    HarmonyWindow,
    TheoryContext,
    TrackRole,
    _harmony_windows,
    _roles,
    is_non_chord_tone,
)
from bdo_music_composer.editor.bdo_lyrics import LyricExpressionMode, align_lyrics, lyric_onset_match
from optimization.builtin import (
    _detect_real_techniques,
    _ensemble_issues,
    _ensemble_track_facts,
)


Note = namedtuple("Note", "pitch vel start dur ntype", defaults=(0,))


_CHORD_PATTERNS = (
    ("major7", {0, 4, 7, 11}),
    ("dominant7", {0, 4, 7, 10}),
    ("minor7", {0, 3, 7, 10}),
    ("half_diminished7", {0, 3, 6, 10}),
    ("major", {0, 4, 7}),
    ("minor", {0, 3, 7}),
    ("diminished", {0, 3, 6}),
    ("sus4", {0, 5, 7}),
)


def _reference_roles(notes: list, beat_ms: float) -> tuple[str, ...]:
    result = []
    for index, note in enumerate(notes):
        same_onset = sum(
            abs(other.start - note.start) <= 12.0
            for other in notes
        )
        if same_onset >= 2:
            result.append("chord")
            continue
        nearby = notes[max(0, index - 2):index + 3]
        repeated = sum(item.pitch == note.pitch for item in nearby) >= 2
        ioi = (
            notes[index + 1].start - note.start
            if index + 1 < len(notes)
            else beat_ms
        )
        if note.pitch < 48 and repeated and ioi <= beat_ms * 1.2:
            result.append("bass_riff")
        elif note.dur <= beat_ms * 0.35 and repeated:
            result.append("rhythm")
        else:
            result.append("melody")
    return tuple(result)


def _reference_harmony(notes: list) -> tuple[HarmonyWindow, ...]:
    starts: list[float] = []
    for note in sorted(notes, key=lambda item: (item.start, item.pitch)):
        if not starts or abs(float(note.start) - starts[-1]) > 12.0:
            starts.append(float(note.start))
    windows = []
    for start in starts:
        group = [
            note
            for note in notes
            if float(note.start) <= start + 12.0 < float(note.start + note.dur)
        ]
        pitch_classes = frozenset(note.pitch % 12 for note in group)
        root = None
        quality = None
        if len(pitch_classes) >= 3:
            bass_pc = min(group, key=lambda note: note.pitch).pitch % 12
            candidates = (
                bass_pc,
                *(pc for pc in sorted(pitch_classes) if pc != bass_pc),
            )
            for candidate in candidates:
                match = next(
                    (
                        name
                        for name, intervals in _CHORD_PATTERNS
                        if {
                            (candidate + interval) % 12
                            for interval in intervals
                        }.issubset(pitch_classes)
                    ),
                    None,
                )
                if match:
                    root, quality = candidate, match
                    break
        windows.append(HarmonyWindow(start, pitch_classes, root, quality))
    return tuple(windows)


class _AccessProbeNote:
    start_reads = 0
    velocity_reads = 0

    def __init__(self, pitch: int, velocity: int, start: float, duration: float):
        self.pitch = pitch
        self._velocity = velocity
        self._start = start
        self.dur = duration
        self.ntype = 0

    @property
    def start(self) -> float:
        type(self).start_reads += 1
        return self._start

    @property
    def vel(self) -> int:
        type(self).velocity_reads += 1
        return self._velocity


class OptimizerScalingTests(unittest.TestCase):
    def test_sliding_role_and_harmony_analysis_matches_reference(self) -> None:
        for seed in range(30):
            rng = random.Random(seed)
            notes = [
                Note(
                    rng.randrange(30, 91),
                    rng.randrange(24, 122),
                    rng.randrange(-20, 2_000) + rng.choice((0.0, 0.1, 0.5)),
                    rng.randrange(-30, 600),
                    0,
                )
                for _ in range(rng.randrange(0, 90))
            ]
            self.assertEqual(_roles(notes, 500.0), _reference_roles(notes, 500.0))
            self.assertEqual(_harmony_windows(notes), _reference_harmony(notes))

    def test_non_chord_lookup_matches_first_window_reference_at_float_edges(self) -> None:
        harmony = tuple(
            HarmonyWindow(float(index) * 12.1, frozenset({0, 4, 7}), 0, "major")
            for index in range(500)
        )
        context = TheoryContext(
            120,
            4,
            500.0,
            0,
            "major",
            1.0,
            (),
            (),
            (),
            harmony,
        )
        for start in (0.0, 12.0, 12.1, 24.1, 2_000.5, 6_050.0):
            note = Note(61, 80, start, 100.0, 0)
            window = next(
                (
                    item
                    for item in harmony
                    if abs(item.start - note.start) <= 12.0
                ),
                None,
            )
            expected = bool(
                window
                and window.root is not None
                and note.pitch % 12 not in window.pitch_classes
            )
            self.assertEqual(is_non_chord_tone(note, context), expected)

    def test_role_and_harmony_start_access_is_subquadratic(self) -> None:
        notes = [
            _AccessProbeNote(
                36 + index % 48,
                80,
                float(index * 31 + index % 3),
                40.0 + index % 240,
            )
            for index in range(512)
        ]

        _AccessProbeNote.start_reads = 0
        _roles(notes, 500.0)
        self.assertLess(_AccessProbeNote.start_reads, len(notes) * 30)

        _AccessProbeNote.start_reads = 0
        _harmony_windows(notes)
        self.assertLess(_AccessProbeNote.start_reads, len(notes) * 30)

    def test_technique_velocity_median_is_computed_once(self) -> None:
        notes = [
            _AccessProbeNote(60 + index % 5, 80, index * 125.0, 90.0)
            for index in range(512)
        ]
        track = SimpleNamespace(
            track_id=1,
            bdo_instrument_id=0x0A,
            performance_controls=[],
        )

        _AccessProbeNote.velocity_reads = 0
        _detect_real_techniques(
            track,
            notes,
            TrackRole.ORNAMENT,
            set(),
            500.0,
        )

        self.assertLess(_AccessProbeNote.velocity_reads, len(notes) * 10)

    def test_ensemble_pair_facts_are_reused_without_changing_diagnostics(self) -> None:
        tracks = [
            SimpleNamespace(
                track_id=track_index,
                display_name=f"track-{track_index}",
                is_percussion=False,
                notes=[
                    Note(
                        42 + (note_index * 3 + track_index) % 24,
                        80,
                        note_index * 125.0,
                        90.0,
                        0,
                    )
                    for note_index in range(80)
                ],
            )
            for track_index in range(12)
        ]

        def reference(track, role):
            low = min(note.pitch for note in track.notes)
            high = max(note.pitch for note in track.notes)
            average = sum(note.pitch for note in track.notes) / len(track.notes)
            issues = []
            for other in tracks:
                if other is track or not other.notes or other.is_percussion:
                    continue
                other_low = min(note.pitch for note in other.notes)
                other_high = max(note.pitch for note in other.notes)
                overlap = max(
                    0,
                    min(high, other_high) - max(low, other_low) + 1,
                )
                union = max(high, other_high) - min(low, other_low) + 1
                onset_keys = {
                    (round(note.start / 12.0), note.pitch)
                    for note in track.notes
                }
                other_keys = {
                    (round(note.start / 12.0), note.pitch)
                    for note in other.notes
                }
                doubling = len(onset_keys & other_keys) / max(
                    1,
                    min(len(onset_keys), len(other_keys)),
                )
                if overlap / max(1, union) >= 0.7 and doubling < 0.2:
                    issues.append(
                        f"与 {other.display_name} 音区高度重叠，存在织体遮蔽风险"
                    )
                if doubling >= 0.45:
                    issues.append(
                        f"与 {other.display_name} 存在明显同度加倍，作为配器层保留"
                    )
            if role == TrackRole.BASS and any(
                other.notes
                and sum(note.pitch for note in other.notes) / len(other.notes)
                < average
                for other in tracks
            ):
                issues.append("低音平均音区高于其他旋律层，可能发生声部交叉")
            return list(dict.fromkeys(issues))

        facts = _ensemble_track_facts(tracks)
        for index, track in enumerate(tracks):
            role = TrackRole.BASS if index == 0 else TrackRole.HARMONY
            self.assertEqual(
                _ensemble_issues(track, tracks, role, facts),
                reference(track, role),
            )

    def test_lyric_nearest_onsets_match_linear_reference(self) -> None:
        rng = random.Random(91)
        notes = [
            Note(60 + index % 7, 80, index * 117.0, 90.0, 0)
            for index in range(300)
        ]
        events = [
            {
                "kind": "lyrics",
                "text": "la",
                "time": rng.uniform(-100.0, notes[-1].start + 100.0),
            }
            for _ in range(260)
        ]
        starts = sorted({float(note.start) for note in notes})
        times = [float(event["time"]) for event in events]
        tolerance = max(45.0, 500.0 * 0.22)
        distances = [
            min(abs(start - event_time) for start in starts)
            for event_time in times
        ]
        expected = (
            0.65
            * sum(distance <= tolerance for distance in distances)
            / len(distances)
            + 0.35
            * sum(math.exp(-distance / tolerance) for distance in distances)
            / len(distances)
        )
        self.assertAlmostEqual(
            lyric_onset_match(notes, events, 500.0),
            expected,
            places=12,
        )

        sorted_notes = sorted(notes, key=lambda note: (note.start, -note.pitch))
        cursor = 0
        expected_anchors = []
        for event in events:
            anchor = min(
                range(cursor, len(sorted_notes)),
                key=lambda index: abs(sorted_notes[index].start - event["time"]),
            )
            expected_anchors.append(anchor)
            cursor = min(len(sorted_notes) - 1, anchor + 1)
        aligned = align_lyrics(
            events,
            notes,
            500.0,
            LyricExpressionMode.SYLLABIC,
        )
        self.assertEqual(
            [item.note_indices[0] for item in aligned.alignments],
            expected_anchors,
        )

    def test_lyric_alignment_note_access_is_subquadratic(self) -> None:
        notes = [
            _AccessProbeNote(60 + index % 5, 80, index * 125.0, 90.0)
            for index in range(1_024)
        ]
        events = [
            {"kind": "lyrics", "text": "la", "time": index * 125.0 + 3.0}
            for index in range(1_024)
        ]

        _AccessProbeNote.start_reads = 0
        lyric_onset_match(notes, events, 500.0)
        self.assertLess(_AccessProbeNote.start_reads, len(notes) * 10)

        _AccessProbeNote.start_reads = 0
        align_lyrics(
            events,
            notes,
            500.0,
            LyricExpressionMode.SYLLABIC,
        )
        self.assertLess(_AccessProbeNote.start_reads, len(notes) * 10)


if __name__ == "__main__":
    unittest.main()
