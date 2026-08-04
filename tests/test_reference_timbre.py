from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import mido

from bdo_music_composer.transcription.bdo_transcription import (
    TranscriptionCandidate,
)
from bdo_music_composer.transcription.bdo_transcription_instruments import (
    TimbreFeatureProfile,
    VoiceGroup,
)
from bdo_music_composer.transcription.muscriptor_backend import (
    gm_program_family,
    parse_instrument_midi,
)
from bdo_music_composer.transcription.reference_timbre import (
    UNKNOWN_TIMBRE_COLOR,
    ReferenceInstrumentEvent,
    build_reference_timbre_analysis,
    build_reference_timbre_prediction,
    merge_reference_timbre_evidence,
)


def _candidate(candidate_id: str, pitch: int, start_ms: float):
    return TranscriptionCandidate(
        pitch,
        90,
        start_ms,
        240.0,
        0.9,
        candidate_id=candidate_id,
    )


def _profile(key: str, values: tuple[float, float]):
    return TimbreFeatureProfile(
        key,
        ("mfcc_0", "spectral_centroid"),
        values,
        3,
        0.9,
    )


def _single_profile(key: str, values: tuple[float, float]):
    return TimbreFeatureProfile(
        key,
        ("mfcc_0", "spectral_centroid"),
        values,
        1,
        0.75,
    )


class ReferenceTimbreTests(unittest.TestCase):
    def test_structural_prediction_is_immediate_bounded_and_explicit(self) -> None:
        candidates = (
            _candidate("lead-a", 67, 0.0),
            _candidate("lead-b", 69, 420.0),
            _candidate("orphan", 52, 900.0),
        )
        result = build_reference_timbre_prediction(
            cache_key="cache",
            candidates=candidates,
            voice_groups=(
                VoiceGroup(
                    "voice-lead",
                    ("lead-a", "lead-b"),
                    0.0,
                    700.0,
                    "primary_melody",
                    0.84,
                ),
            ),
        )

        self.assertEqual(result.evidence_stage, "predictive")
        self.assertEqual(result.profiled_candidate_count, 0)
        self.assertEqual(
            {item for group in result.groups for item in group.candidate_ids},
            {"lead-a", "lead-b", "orphan"},
        )
        predicted = result.groups[0]
        self.assertEqual(predicted.group_id, "voice-lead")
        self.assertLessEqual(predicted.confidence, 0.58)
        self.assertTrue(dict(predicted.candidate_confidences))
        self.assertEqual(result.groups[-1].group_id, "timbre-unknown")

    def test_prediction_joins_adjacent_same_voice_fragments(self) -> None:
        candidates = (
            _candidate("lead-a", 67, 0.0),
            _candidate("lead-b", 69, 620.0),
            _candidate("bass", 45, 1_600.0),
        )
        result = build_reference_timbre_prediction(
            cache_key="cache",
            candidates=candidates,
            voice_groups=(
                VoiceGroup(
                    "lead-left",
                    ("lead-a",),
                    0.0,
                    240.0,
                    "primary_melody",
                    0.84,
                ),
                VoiceGroup(
                    "lead-right",
                    ("lead-b",),
                    620.0,
                    860.0,
                    "primary_melody",
                    0.82,
                ),
                VoiceGroup(
                    "bass",
                    ("bass",),
                    1_600.0,
                    1_840.0,
                    "bass",
                    0.88,
                ),
            ),
        )

        coloured = tuple(
            group
            for group in result.groups
            if group.group_id != "timbre-unknown"
        )
        self.assertEqual(len(coloured), 2)
        self.assertIn(
            frozenset(("lead-a", "lead-b")),
            {frozenset(group.candidate_ids) for group in coloured},
        )

    def test_prediction_keeps_overlapping_voices_separate(self) -> None:
        candidates = (
            _candidate("upper", 67, 0.0),
            _candidate("lower", 64, 120.0),
        )
        result = build_reference_timbre_prediction(
            cache_key="cache",
            candidates=candidates,
            voice_groups=(
                VoiceGroup(
                    "upper",
                    ("upper",),
                    0.0,
                    420.0,
                    "harmony",
                    0.84,
                ),
                VoiceGroup(
                    "lower",
                    ("lower",),
                    120.0,
                    540.0,
                    "harmony",
                    0.82,
                ),
            ),
        )

        coloured = tuple(
            group
            for group in result.groups
            if group.group_id != "timbre-unknown"
        )
        self.assertEqual(len(coloured), 2)
        self.assertEqual(
            {frozenset(group.candidate_ids) for group in coloured},
            {frozenset(("upper",)), frozenset(("lower",))},
        )

    def test_acoustic_unknowns_keep_structural_groups_for_guidance(self) -> None:
        candidates = (
            _candidate("verified", 67, 0.0),
            _candidate("unknown-a", 60, 4_100.0),
            _candidate("unknown-b", 62, 8_200.0),
        )
        prediction = build_reference_timbre_prediction(
            cache_key="cache",
            candidates=candidates,
            voice_groups=(
                VoiceGroup(
                    "voice-lead",
                    ("verified",),
                    0.0,
                    240.0,
                    "primary_melody",
                    0.9,
                ),
                VoiceGroup(
                    "voice-harmony",
                    ("unknown-a", "unknown-b"),
                    4_100.0,
                    8_440.0,
                    "harmony",
                    0.8,
                ),
            ),
        )
        acoustic = build_reference_timbre_analysis(
            cache_key="cache",
            candidates=candidates,
            voice_groups=(
                VoiceGroup(
                    "voice-lead",
                    ("verified",),
                    0.0,
                    240.0,
                    "primary_melody",
                    0.9,
                ),
                VoiceGroup(
                    "voice-harmony",
                    ("unknown-a", "unknown-b"),
                    4_100.0,
                    8_440.0,
                    "harmony",
                    0.8,
                ),
            ),
            group_profiles={"voice-lead": _profile("verified", (1.0, 1.0))},
        )

        hybrid = merge_reference_timbre_evidence(acoustic, prediction)

        self.assertEqual(hybrid.evidence_stage, "hybrid")
        groups_by_id = {group.group_id: group for group in hybrid.groups}
        self.assertIn("voice-harmony", groups_by_id)
        self.assertEqual(
            groups_by_id["voice-harmony"].candidate_ids,
            ("unknown-a", "unknown-b"),
        )
        self.assertNotIn(
            "unknown-a",
            next(
                (
                    group.candidate_ids
                    for group in hybrid.groups
                    if group.group_id == "timbre-unknown"
                ),
                (),
            ),
        )

    def test_similar_voices_merge_but_distinct_prototype_stays_separate(self) -> None:
        candidates = (
            _candidate("a", 60, 0.0),
            _candidate("b", 62, 400.0),
            _candidate("c", 48, 800.0),
        )
        groups = (
            VoiceGroup("v-a", ("a",), 0.0, 240.0, "harmony", 0.9),
            VoiceGroup("v-b", ("b",), 400.0, 640.0, "harmony", 0.9),
            VoiceGroup("v-c", ("c",), 800.0, 1040.0, "bass", 0.9),
        )
        profiles = {
            "v-a": _profile("p-a", (1.0, 1.0)),
            "v-b": _profile("p-b", (1.02, 0.99)),
            "v-c": _profile("p-c", (9.0, -7.0)),
        }

        first = build_reference_timbre_analysis(
            cache_key="cache",
            candidates=candidates,
            voice_groups=groups,
            group_profiles=profiles,
        )
        second = build_reference_timbre_analysis(
            cache_key="cache",
            candidates=candidates,
            voice_groups=groups,
            group_profiles=profiles,
        )

        self.assertEqual(first, second)
        self.assertEqual(len(first.groups), 2)
        self.assertIn(
            frozenset(("a", "b")),
            {frozenset(group.candidate_ids) for group in first.groups},
        )
        self.assertEqual(len({group.color for group in first.groups}), 2)

    def test_below_floor_evidence_remains_neutral_and_unlabelled(self) -> None:
        candidate = _candidate("only", 64, 0.0)
        group = VoiceGroup(
            "voice", ("only",), 0.0, 240.0, "harmony", 0.8
        )
        sparse = TimbreFeatureProfile(
            "sparse",
            ("mfcc_0",),
            (1.0,),
            1,
            0.1,
        )
        result = build_reference_timbre_analysis(
            cache_key="cache",
            candidates=(candidate,),
            voice_groups=(group,),
            group_profiles={"voice": sparse},
        )

        self.assertEqual(result.profiled_candidate_count, 0)
        self.assertEqual(result.groups[0].group_id, "timbre-unknown")
        self.assertEqual(result.groups[0].color, UNKNOWN_TIMBRE_COLOR)
        self.assertEqual(result.groups[0].label_family, "")

    def test_single_clean_profile_forms_provisional_group(self) -> None:
        candidate = _candidate("only", 64, 0.0)
        group = VoiceGroup(
            "voice", ("only",), 0.0, 240.0, "harmony", 0.8
        )
        result = build_reference_timbre_analysis(
            cache_key="cache",
            candidates=(candidate,),
            voice_groups=(group,),
            group_profiles={
                "voice": TimbreFeatureProfile(
                    "single",
                    ("mfcc_0", "spectral_centroid"),
                    (1.0, 1.0),
                    1,
                    0.42,
                )
            },
        )

        self.assertEqual(result.profiled_candidate_count, 1)
        self.assertNotEqual(result.groups[0].group_id, "timbre-unknown")
        self.assertAlmostEqual(result.groups[0].confidence, 0.42)
        self.assertEqual(dict(result.groups[0].candidate_confidences), {"only": 0.42})

    def test_sparse_voice_inherits_clear_prototype_with_confidence(self) -> None:
        candidates = (
            _candidate("a", 60, 0.0),
            _candidate("b", 62, 400.0),
            _candidate("c", 64, 800.0),
            _candidate("d", 65, 1_200.0),
        )
        groups = (
            VoiceGroup(
                "reliable",
                ("a", "b"),
                0.0,
                640.0,
                "harmony",
                0.9,
            ),
            VoiceGroup(
                "short",
                ("c", "d"),
                800.0,
                1_440.0,
                "harmony",
                0.8,
            ),
        )
        result = build_reference_timbre_analysis(
            cache_key="cache",
            candidates=candidates,
            voice_groups=groups,
            group_profiles={
                "reliable": _profile("core", (1.0, 1.0)),
                "short": _single_profile("short", (1.01, 1.02)),
            },
            candidate_profiles={
                "c": _single_profile("candidate-c", (1.01, 1.02)),
            },
        )

        self.assertEqual(len(result.groups), 1)
        self.assertEqual(
            frozenset(result.groups[0].candidate_ids),
            frozenset(("a", "b", "c", "d")),
        )
        confidences = dict(result.groups[0].candidate_confidences)
        self.assertGreater(confidences["c"], 0.7)
        self.assertGreater(confidences["d"], 0.5)
        self.assertEqual(result.profiled_candidate_count, 4)

    def test_sparse_group_profile_inherits_reliable_prototype(self) -> None:
        candidates = (
            _candidate("a", 60, 0.0),
            _candidate("b", 62, 300.0),
            _candidate("c", 64, 700.0),
        )
        groups = (
            VoiceGroup("core", ("a", "b"), 0.0, 540.0, "harmony", 0.9),
            VoiceGroup("short", ("c",), 700.0, 940.0, "harmony", 0.8),
        )
        result = build_reference_timbre_analysis(
            cache_key="cache",
            candidates=candidates,
            voice_groups=groups,
            group_profiles={
                "core": _profile("core-profile", (1.0, 1.0)),
                "short": _single_profile("short-profile", (1.02, 0.99)),
            },
        )

        self.assertEqual(len(result.groups), 1)
        self.assertEqual(
            frozenset(result.groups[0].candidate_ids),
            frozenset(("a", "b", "c")),
        )
        self.assertGreater(
            dict(result.groups[0].candidate_confidences)["c"],
            0.5,
        )

    def test_temporal_continuity_merges_moderate_same_role_timbres(self) -> None:
        candidates = (
            _candidate("a", 60, 0.0),
            _candidate("b", 62, 500.0),
        )
        groups = (
            VoiceGroup("left", ("a",), 0.0, 240.0, "harmony", 0.9),
            VoiceGroup("right", ("b",), 500.0, 740.0, "harmony", 0.9),
        )
        profiles = {
            "left": _profile("left-profile", (1.0, 1.0)),
            "right": _profile("right-profile", (1.45, 1.45)),
        }

        nearby = build_reference_timbre_analysis(
            cache_key="nearby",
            candidates=candidates,
            voice_groups=groups,
            group_profiles=profiles,
        )
        remote = build_reference_timbre_analysis(
            cache_key="remote",
            candidates=(candidates[0], _candidate("b", 62, 4_000.0)),
            voice_groups=(
                groups[0],
                VoiceGroup("right", ("b",), 4_000.0, 4_240.0, "harmony", 0.9),
            ),
            group_profiles=profiles,
        )

        self.assertEqual(len(nearby.groups), 1)
        self.assertEqual(len(remote.groups), 2)

    def test_external_label_requires_note_alignment_and_group_consensus(self) -> None:
        candidates = (
            _candidate("a", 60, 0.0),
            _candidate("b", 62, 400.0),
        )
        group = VoiceGroup(
            "voice", ("a", "b"), 0.0, 640.0, "harmony", 0.9
        )
        events = (
            ReferenceInstrumentEvent(60, 0.0, 240.0, "piano"),
            ReferenceInstrumentEvent(62, 400.0, 240.0, "piano"),
            # Wrong pitch and remote timing must not influence the vote.
            ReferenceInstrumentEvent(70, 8_000.0, 240.0, "guitar"),
        )
        result = build_reference_timbre_analysis(
            cache_key="cache",
            candidates=candidates,
            voice_groups=(group,),
            group_profiles={"voice": _profile("piano", (1.0, 1.0))},
            instrument_events=events,
            label_backend="muscriptor-small",
            label_status="ready",
        )

        self.assertEqual(result.groups[0].label_family, "piano")
        self.assertGreater(result.groups[0].label_confidence, 0.9)
        self.assertEqual(result.groups[0].label_source, "muscriptor-small")

    def test_standard_midi_programs_become_timed_family_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            midi_path = Path(temp_dir) / "labels.mid"
            midi = mido.MidiFile(ticks_per_beat=480)
            track = mido.MidiTrack()
            midi.tracks.append(track)
            track.append(mido.Message("program_change", program=24, time=0))
            track.append(mido.Message("note_on", note=64, velocity=90, time=0))
            track.append(mido.Message("note_off", note=64, velocity=0, time=480))
            midi.save(midi_path)

            events = parse_instrument_midi(midi_path)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].family, "guitar")
        self.assertAlmostEqual(events[0].start_ms, 0.0)
        self.assertAlmostEqual(events[0].duration_ms, 500.0)
        self.assertEqual(gm_program_family(0), "piano")
        self.assertEqual(gm_program_family(127), "sound_effect")


if __name__ == "__main__":
    unittest.main()
