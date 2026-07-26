from __future__ import annotations

import random
from types import SimpleNamespace
import unittest

from bdo_music_theory import TrackRole
from bdo_transcription import TranscriptionCandidate
from bdo_transcription_instruments import (
    BdoInstrumentDescriptor,
    InstrumentAnalysisCancelled,
    NO_TIMBRE_CONFIDENCE_CAP,
    VoiceGroup,
    build_timbre_feature_profile,
    group_voice_candidates,
    match_bdo_instruments,
    normalize_track_role,
    overlay_manual_voice_groups,
    refine_voice_groups_by_timbre,
)


def candidate(
    candidate_id: str,
    pitch: int,
    start_ms: float,
    duration_ms: float = 240.0,
    confidence: float = 0.9,
) -> TranscriptionCandidate:
    return TranscriptionCandidate(
        pitch,
        96,
        start_ms,
        duration_ms,
        confidence,
        candidate_id=candidate_id,
    )


class VoiceGroupingTests(unittest.TestCase):
    def test_manual_overlay_preserves_residual_and_ignores_stale_review(
        self,
    ) -> None:
        values = [
            candidate("a", 60, 0.0),
            candidate("b", 62, 400.0),
            candidate("c", 64, 800.0),
        ]
        automatic = (
            VoiceGroup(
                "automatic",
                ("a", "b", "c"),
                0.0,
                1040.0,
                "primary_melody",
                0.8,
            ),
        )
        manual = SimpleNamespace(
            group_id="manual",
            candidate_ids=("a", "b"),
            start_audio_ms=0.0,
            end_audio_ms=700.0,
            role="harmony",
            orphaned=False,
        )
        overlaid = overlay_manual_voice_groups(
            automatic, values, (manual,)
        )
        self.assertEqual(
            {group.candidate_ids for group in overlaid},
            {("a", "b"), ("c",)},
        )
        self.assertEqual(
            next(
                group for group in overlaid
                if group.candidate_ids == ("a", "b")
            ).role,
            "harmony",
        )

        stale = SimpleNamespace(
            group_id="stale",
            candidate_ids=("a", "missing"),
            start_audio_ms=0.0,
            end_audio_ms=700.0,
            role="harmony",
            orphaned=False,
        )
        self.assertEqual(
            overlay_manual_voice_groups(automatic, values, (stale,)),
            automatic,
        )

    def test_simultaneous_candidates_use_distinct_nearest_voices(self) -> None:
        values = [
            candidate("low-1", 48, 0.0),
            candidate("high-1", 72, 20.0),
            candidate("low-2", 50, 500.0),
            candidate("high-2", 71, 520.0),
        ]

        groups = group_voice_candidates(values, beat_ms=500.0)

        self.assertEqual(len(groups), 2)
        memberships = {group.candidate_ids for group in groups}
        self.assertEqual(
            memberships,
            {("low-1", "low-2"), ("high-1", "high-2")},
        )
        by_membership = {group.candidate_ids: group for group in groups}
        self.assertEqual(by_membership[("low-1", "low-2")].role, "bass")
        self.assertEqual(
            by_membership[("high-1", "high-2")].role, "primary_melody"
        )

    def test_onset_cluster_uses_anchor_and_does_not_chain(self) -> None:
        values = [
            candidate("a", 60, 0.0, 40.0),
            candidate("b", 64, 34.0, 40.0),
            candidate("c", 67, 68.0, 40.0),
        ]

        groups = group_voice_candidates(values, beat_ms=500.0)

        # a/b are simultaneous by the locked 35 ms tolerance. c is a new
        # onset cluster and may continue one of those two voices.
        self.assertEqual(len(groups), 2)
        self.assertTrue(any(group.candidate_ids == ("a",) for group in groups))
        self.assertTrue(any("c" in group.candidate_ids for group in groups))

    def test_same_pitch_overlapping_hypotheses_do_not_create_fake_voices(
        self,
    ) -> None:
        values = [
            candidate("weaker", 60, 0.0, 400.0, 0.70),
            candidate("primary", 60, 10.0, 380.0, 0.95),
            candidate("next", 62, 500.0, 240.0, 0.85),
        ]

        groups = group_voice_candidates(values, beat_ms=500.0)

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].candidate_ids, ("primary", "next"))
        self.assertNotIn(
            "weaker",
            {
                candidate_id
                for group in groups
                for candidate_id in group.candidate_ids
            },
        )

    def test_silence_greater_than_one_and_a_half_beats_splits_phrase(self) -> None:
        values = [
            candidate("first", 60, 0.0, 100.0),
            candidate("at-limit", 62, 850.0, 100.0),
            candidate("after-gap", 64, 1701.0, 100.0),
        ]

        groups = group_voice_candidates(values, beat_ms=500.0)

        self.assertEqual(len(groups), 2)
        self.assertIn(("first", "at-limit"), {item.candidate_ids for item in groups})
        self.assertIn(("after-gap",), {item.candidate_ids for item in groups})

    def test_effective_bpm_changes_beat_relative_phrase_boundaries(self) -> None:
        values = [
            candidate("first", 60, 0.0, 100.0),
            candidate("second", 62, 1000.0, 100.0),
        ]

        at_120_bpm = group_voice_candidates(values, beat_ms=500.0)
        at_60_bpm = group_voice_candidates(values, beat_ms=1000.0)

        self.assertEqual(len(at_120_bpm), 2)
        self.assertEqual(len(at_60_bpm), 1)
        self.assertEqual(
            at_60_bpm[0].candidate_ids,
            ("first", "second"),
        )

    def test_assignment_and_group_ids_are_input_order_independent(self) -> None:
        values = [
            candidate("a", 48, 0.0),
            candidate("b", 72, 10.0),
            candidate("c", 50, 400.0),
            candidate("d", 71, 410.0),
            candidate("e", 52, 800.0),
            candidate("f", 69, 810.0),
        ]
        shuffled = list(values)
        random.Random(42).shuffle(shuffled)

        first = group_voice_candidates(values, beat_ms=500.0)
        second = group_voice_candidates(shuffled, beat_ms=500.0)

        self.assertEqual(first, second)
        self.assertTrue(all(group.group_id.startswith("voice-") for group in first))

    def test_invalid_candidates_are_ignored_and_duplicate_ids_are_stable(self) -> None:
        values = [
            candidate("same", 60, 0.0),
            candidate("same", 62, 400.0),
            candidate("bad", 64, 900.0, -1.0),
        ]

        groups = group_voice_candidates(values, beat_ms=500.0)

        ids = {item for group in groups for item in group.candidate_ids}
        self.assertEqual(ids, {"same", "same~2"})

    def test_track_role_enum_and_string_are_compatible(self) -> None:
        self.assertEqual(
            normalize_track_role(TrackRole.PRIMARY_MELODY), "primary_melody"
        )
        self.assertEqual(normalize_track_role("secondary-melody"), "secondary_melody")
        with self.assertRaises(ValueError):
            normalize_track_role("unknown")

    def test_grouping_honours_cooperative_cancellation(self) -> None:
        values = [
            candidate(f"candidate-{index}", 60 + index % 8, index * 50.0)
            for index in range(100)
        ]
        checks = 0

        def cancelled() -> bool:
            nonlocal checks
            checks += 1
            return checks >= 12

        with self.assertRaises(InstrumentAnalysisCancelled):
            group_voice_candidates(
                values,
                beat_ms=500.0,
                cancelled=cancelled,
            )
        self.assertLess(checks, len(values))

    def test_stable_timbre_change_splits_phrase_but_alternation_does_not(
        self,
    ) -> None:
        values = [
            candidate(f"n{index}", 60 + index, index * 300.0)
            for index in range(6)
        ]
        group = VoiceGroup(
            "whole",
            tuple(item.candidate_id for item in values),
            0.0,
            1740.0,
            "primary_melody",
            0.9,
        )
        dark = build_timbre_feature_profile(({"mfcc": 0.0},))
        bright = build_timbre_feature_profile(({"mfcc": 100.0},))
        stable_profiles = {
            item.candidate_id: dark if index < 3 else bright
            for index, item in enumerate(values)
        }

        refined = refine_voice_groups_by_timbre(
            (group,),
            values,
            stable_profiles,
        )

        self.assertEqual(
            {item.candidate_ids for item in refined},
            {("n0", "n1", "n2"), ("n3", "n4", "n5")},
        )
        alternating = {
            item.candidate_id: dark if index % 2 == 0 else bright
            for index, item in enumerate(values)
        }
        self.assertEqual(
            refine_voice_groups_by_timbre(
                (group,),
                values,
                alternating,
            ),
            (group,),
        )


class InstrumentMatchingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidates = [
            candidate("a", 60, 0.0, 200.0),
            candidate("b", 64, 500.0, 200.0),
            candidate("c", 67, 1000.0, 200.0),
        ]
        self.group = VoiceGroup(
            "voice-main",
            ("a", "b", "c"),
            0.0,
            1200.0,
            TrackRole.PRIMARY_MELODY,
            0.9,
        )

    def test_top_three_are_ranked_by_locked_weights(self) -> None:
        instruments = [
            BdoInstrumentDescriptor(
                10,
                available_pitches=frozenset({60, 64, 67}),
                preferred_roles=frozenset({TrackRole.PRIMARY_MELODY}),
                articulation_profile="short",
            ),
            BdoInstrumentDescriptor(
                11,
                available_pitches=frozenset({60, 64}),
                preferred_roles=frozenset({TrackRole.PRIMARY_MELODY}),
                articulation_profile="short",
            ),
            BdoInstrumentDescriptor(
                12,
                available_pitches=frozenset({60, 64, 67}),
                preferred_roles=frozenset({TrackRole.HARMONY}),
                articulation_profile="short",
            ),
            BdoInstrumentDescriptor(
                13,
                available_pitches=frozenset({60}),
                preferred_roles=frozenset({TrackRole.HARMONY}),
                articulation_profile="sustain",
            ),
        ]

        analysis = match_bdo_instruments(
            (self.group,), self.candidates, instruments, beat_ms=500.0
        )
        matches = analysis.matches_for_group("voice-main")

        self.assertEqual([item.instrument_id for item in matches], [10, 11, 12])
        self.assertEqual(len(matches), 3)
        self.assertAlmostEqual(matches[0].pitch_coverage, 1.0)
        self.assertAlmostEqual(matches[0].role_score, 1.0)
        self.assertIsNone(matches[0].timbre_score)
        self.assertLessEqual(matches[0].total_score, NO_TIMBRE_CONFIDENCE_CAP)

    def test_timbre_is_fifty_percent_and_changes_ranking(self) -> None:
        instruments = [
            BdoInstrumentDescriptor(
                10,
                48,
                84,
                preferred_roles=frozenset({"primary_melody"}),
                articulation_profile="short",
            ),
            BdoInstrumentDescriptor(
                11,
                48,
                84,
                preferred_roles=frozenset({"primary_melody"}),
                articulation_profile="short",
            ),
        ]
        group_profile = build_timbre_feature_profile(
            ({"mfcc1": 0.0, "centroid": 0.0},)
        )
        exact_profile = build_timbre_feature_profile(
            ({"mfcc1": 0.0, "centroid": 0.0},)
        )
        distant_profile = build_timbre_feature_profile(
            ({"mfcc1": 1.0, "centroid": 1.0},)
        )

        analysis = match_bdo_instruments(
            (self.group,),
            self.candidates,
            instruments,
            group_timbre_profiles={self.group.group_id: group_profile},
            instrument_timbre_profiles={10: distant_profile, 11: exact_profile},
            sample_profile_key=r"C:\private\game_samples",
            beat_ms=500.0,
        )
        matches = analysis.matches_for_group(self.group.group_id)

        self.assertEqual([item.instrument_id for item in matches], [11, 10])
        self.assertAlmostEqual(matches[0].timbre_score or 0.0, 1.0)
        self.assertAlmostEqual(matches[0].total_score, 1.0)
        self.assertAlmostEqual(matches[1].total_score, 0.5)
        self.assertNotIn("private", analysis.sample_profile_key)
        self.assertNotIn("game_samples", analysis.sample_profile_key)
        self.assertEqual(len(analysis.sample_profile_key), 24)

    def test_pitch_aware_profiles_override_misleading_aggregate_centroid(
        self,
    ) -> None:
        instruments = [
            BdoInstrumentDescriptor(
                10,
                48,
                84,
                preferred_roles=frozenset({"primary_melody"}),
                articulation_profile="short",
            ),
            BdoInstrumentDescriptor(
                11,
                48,
                84,
                preferred_roles=frozenset({"primary_melody"}),
                articulation_profile="short",
            ),
        ]
        aggregate = build_timbre_feature_profile(({"mfcc1": 0.5},))
        group_pitch = build_timbre_feature_profile(({"mfcc1": 0.0},))
        wrong_pitch = build_timbre_feature_profile(({"mfcc1": 1.0},))
        exact_pitch = build_timbre_feature_profile(({"mfcc1": 0.0},))
        class PitchAwareMap(dict):
            pass

        group_profiles = PitchAwareMap(
            {self.group.group_id: aggregate}
        )
        group_profiles.pitch_profiles = {
            self.group.group_id: {
                60: group_pitch,
                64: group_pitch,
                67: group_pitch,
            },
        }
        instrument_profiles = PitchAwareMap(
            {
                10: aggregate,
                11: aggregate,
            }
        )
        instrument_profiles.pitch_profiles = {
            10: {
                60: wrong_pitch,
                64: wrong_pitch,
                67: wrong_pitch,
            },
            11: {
                60: exact_pitch,
                64: exact_pitch,
                67: exact_pitch,
            },
        }

        analysis = match_bdo_instruments(
            (self.group,),
            self.candidates,
            instruments,
            group_timbre_profiles=group_profiles,
            instrument_timbre_profiles=instrument_profiles,
            sample_profile_key="pitch-aware",
        )
        matches = analysis.matches_for_group(self.group.group_id)

        self.assertEqual([item.instrument_id for item in matches], [11, 10])
        self.assertIn("timbre:pitch:", matches[0].reasons[-1])
        self.assertIn("exact=3", matches[0].reasons[-1])

    def test_distant_sample_roots_do_not_claim_timbre_evidence(self) -> None:
        instrument = BdoInstrumentDescriptor(
            10,
            48,
            84,
            preferred_roles=frozenset({"primary_melody"}),
            articulation_profile="short",
        )
        profile = build_timbre_feature_profile(({"mfcc1": 0.0},))

        class PitchAwareMap(dict):
            pass

        group_profiles = PitchAwareMap({self.group.group_id: profile})
        group_profiles.pitch_profiles = {
            self.group.group_id: {60: profile, 64: profile, 67: profile},
        }
        instrument_profiles = PitchAwareMap({10: profile})
        instrument_profiles.pitch_profiles = {10: {36: profile}}

        match = match_bdo_instruments(
            (self.group,),
            self.candidates,
            (instrument,),
            group_timbre_profiles=group_profiles,
            instrument_timbre_profiles=instrument_profiles,
        ).matches_for_group(self.group.group_id)[0]

        self.assertIsNone(match.timbre_score)
        self.assertLessEqual(match.total_score, NO_TIMBRE_CONFIDENCE_CAP)
        self.assertIn("timbre:no_local_evidence", match.reasons)

    def test_matching_honours_cooperative_cancellation(self) -> None:
        instruments = tuple(
            BdoInstrumentDescriptor(
                instrument_id,
                48,
                84,
            )
            for instrument_id in range(64)
        )
        checks = 0

        def cancelled() -> bool:
            nonlocal checks
            checks += 1
            return checks >= 16

        with self.assertRaises(InstrumentAnalysisCancelled):
            match_bdo_instruments(
                (self.group,),
                self.candidates,
                instruments,
                cancelled=cancelled,
            )
        self.assertLess(checks, len(instruments) * 2)

    def test_low_reliability_timbre_is_treated_as_no_evidence(self) -> None:
        instrument = BdoInstrumentDescriptor(
            10,
            48,
            84,
            preferred_roles=frozenset({"primary_melody"}),
            articulation_profile="short",
        )
        unreliable = build_timbre_feature_profile(
            ({"mfcc1": 0.0},), reliability=0.2
        )
        reliable = build_timbre_feature_profile(({"mfcc1": 0.0},))

        analysis = match_bdo_instruments(
            (self.group,),
            self.candidates,
            (instrument,),
            group_timbre_profiles={self.group.group_id: unreliable},
            instrument_timbre_profiles={10: reliable},
        )
        match = analysis.matches_for_group(self.group.group_id)[0]

        self.assertIsNone(match.timbre_score)
        self.assertEqual(match.total_score, NO_TIMBRE_CONFIDENCE_CAP)
        self.assertIn("timbre:no_local_evidence", match.reasons)

    def test_unapproved_programmatic_timbre_cannot_raise_confidence(self) -> None:
        instrument = BdoInstrumentDescriptor(
            0x14,
            48,
            84,
            preferred_roles=frozenset({"primary_melody"}),
            articulation_profile="short",
            timbre_evidence_approved=False,
        )
        profile = build_timbre_feature_profile(({"mfcc1": 0.0},))

        analysis = match_bdo_instruments(
            (self.group,),
            self.candidates,
            (instrument,),
            group_timbre_profiles={self.group.group_id: profile},
            instrument_timbre_profiles={0x14: profile},
        )
        match = analysis.matches_for_group(self.group.group_id)[0]

        self.assertIsNone(match.timbre_score)
        self.assertEqual(match.total_score, NO_TIMBRE_CONFIDENCE_CAP)

    def test_zero_pitch_coverage_and_percussion_conflicts_are_excluded(self) -> None:
        instruments = [
            BdoInstrumentDescriptor(10, 20, 40),
            BdoInstrumentDescriptor(
                13,
                48,
                84,
                is_percussion=True,
                preferred_roles=frozenset({"percussion"}),
            ),
            BdoInstrumentDescriptor(17, 48, 84),
        ]

        analysis = match_bdo_instruments(
            (self.group,), self.candidates, instruments
        )

        self.assertEqual(
            [item.instrument_id for item in analysis.matches_for_group("voice-main")],
            [17],
        )

    def test_pitch_offset_checks_the_actual_exported_pitch_and_changes_cache_key(
        self,
    ) -> None:
        transposed_only = BdoInstrumentDescriptor(
            17,
            available_pitches=frozenset({72, 76, 79}),
        )

        without_transpose = match_bdo_instruments(
            (self.group,),
            self.candidates,
            (transposed_only,),
        )
        with_transpose = match_bdo_instruments(
            (self.group,),
            self.candidates,
            (transposed_only,),
            pitch_offset=12,
        )

        self.assertEqual(
            without_transpose.matches_for_group(self.group.group_id),
            (),
        )
        self.assertEqual(
            [
                item.instrument_id
                for item in with_transpose.matches_for_group(
                    self.group.group_id
                )
            ],
            [17],
        )
        self.assertAlmostEqual(
            with_transpose.matches_for_group(
                self.group.group_id
            )[0].pitch_coverage,
            1.0,
        )
        self.assertNotEqual(
            without_transpose.cache_key,
            with_transpose.cache_key,
        )

    def test_pitch_offset_keeps_source_profile_pitch_and_shifts_game_profile_pitch(
        self,
    ) -> None:
        instrument = BdoInstrumentDescriptor(17, 48, 96)
        profile = build_timbre_feature_profile(({"mfcc1": 0.0},))

        class PitchAwareMap(dict):
            pass

        group_profiles = PitchAwareMap(
            {self.group.group_id: profile}
        )
        group_profiles.pitch_profiles = {
            self.group.group_id: {
                60: profile,
                64: profile,
                67: profile,
            },
        }
        instrument_profiles = PitchAwareMap({17: profile})
        instrument_profiles.pitch_profiles = {
            17: {
                72: profile,
                76: profile,
                79: profile,
            },
        }

        without_transpose = match_bdo_instruments(
            (self.group,),
            self.candidates,
            (instrument,),
            group_timbre_profiles=group_profiles,
            instrument_timbre_profiles=instrument_profiles,
        ).matches_for_group(self.group.group_id)[0]
        with_transpose = match_bdo_instruments(
            (self.group,),
            self.candidates,
            (instrument,),
            group_timbre_profiles=group_profiles,
            instrument_timbre_profiles=instrument_profiles,
            pitch_offset=12,
        ).matches_for_group(self.group.group_id)[0]

        self.assertIsNone(without_transpose.timbre_score)
        self.assertAlmostEqual(with_transpose.timbre_score or 0.0, 1.0)
        self.assertIn("pitch_offset:+12", with_transpose.reasons)

    def test_percussion_group_only_accepts_percussion_descriptor(self) -> None:
        group = VoiceGroup(
            "drums", ("a",), 0.0, 200.0, TrackRole.PERCUSSION, 0.8
        )
        instruments = [
            BdoInstrumentDescriptor(10, 48, 84),
            BdoInstrumentDescriptor(
                13,
                available_pitches=frozenset({60}),
                preferred_roles=frozenset({"percussion"}),
                articulation_profile="short",
                is_percussion=True,
            ),
        ]

        analysis = match_bdo_instruments((group,), self.candidates, instruments)

        self.assertEqual(
            [item.instrument_id for item in analysis.matches_for_group("drums")],
            [13],
        )

    def test_match_order_and_cache_key_are_deterministic(self) -> None:
        instruments = [
            BdoInstrumentDescriptor(12, 48, 84),
            BdoInstrumentDescriptor(10, 48, 84),
            BdoInstrumentDescriptor(11, 48, 84),
        ]
        shuffled_candidates = list(reversed(self.candidates))

        first = match_bdo_instruments(
            (self.group,), self.candidates, instruments, top_k=3
        )
        second = match_bdo_instruments(
            (self.group,),
            shuffled_candidates,
            tuple(reversed(instruments)),
            top_k=3,
        )

        self.assertEqual(first, second)
        self.assertEqual(
            [item.instrument_id for item in first.matches_for_group("voice-main")],
            [10, 11, 12],
        )

    def test_feature_profile_is_order_independent_and_path_free(self) -> None:
        samples = [
            {"mfcc1": 0.0, "centroid": 0.2, "private_path": float("nan")},
            {"mfcc1": 1.0, "centroid": 0.4},
            {"mfcc1": 2.0, "centroid": 0.6},
        ]

        first = build_timbre_feature_profile(samples)
        second = build_timbre_feature_profile(reversed(samples))

        self.assertEqual(first, second)
        self.assertEqual(first.feature_names, ("centroid", "mfcc1"))
        self.assertEqual(first.values, (0.4, 1.0))
        self.assertEqual(len(first.profile_key), 24)


if __name__ == "__main__":
    unittest.main()
