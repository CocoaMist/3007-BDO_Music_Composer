from __future__ import annotations

import unittest

from bdo_music_composer.editor.bdo_articulation_profiles import PROFILES, profile_for
from bdo_music_composer.editor.bdo_instrument_adaptation import (
    ArrangementRole,
    GameInstrumentFamily,
    RouteEvidence,
    assess_game_draft,
    articulation_pairs_by_instrument,
    articulation_supports_pitch,
    articulation_trigger_pitches,
    instrument_editor_display_adaptation,
    instrument_editor_display_adaptations,
    load_instrument_editor_adaptations,
)
from bdo_midi import BDO_INSTRUMENT_NAMES, BDO_NOTE_MAX, BDO_NOTE_MIN, Note


class InstrumentEditorAdaptationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.adaptations = load_instrument_editor_adaptations()

    def test_every_editor_instrument_has_one_stable_adaptation(self) -> None:
        self.assertEqual(set(BDO_INSTRUMENT_NAMES), set(self.adaptations))
        self.assertEqual(26, len(self.adaptations))
        for instrument_id, adaptation in self.adaptations.items():
            with self.subTest(instrument_id=instrument_id):
                self.assertEqual(instrument_id, adaptation.instrument_id)
                self.assertEqual(
                    BDO_INSTRUMENT_NAMES[instrument_id],
                    adaptation.display_name,
                )
                self.assertIn(adaptation.primary_role, adaptation.roles)
                self.assertTrue(adaptation.visual_key)
                self.assertNotIn("/", adaptation.visual_key)
                self.assertNotIn("\\", adaptation.visual_key)

    def test_game_draft_check_is_read_only_and_reports_chunking(self) -> None:
        notes = tuple(
            Note(60, 96, index * 100.0, 80.0, 0)
            for index in range(731)
        )
        report = assess_game_draft(0x10, notes)
        self.assertTrue(report.ready)
        self.assertEqual(731, report.note_count)
        self.assertEqual(730, report.track_chunk_limit)
        self.assertEqual(2, report.track_chunk_count)
        self.assertTrue(report.pitch_evidence_known)
        self.assertEqual(60, notes[0].pitch)

    def test_game_draft_check_reports_without_rewriting_invalid_notes(self) -> None:
        notes = (
            Note(11, 140, -1.0, 0.0, 99),
            Note(60, 96, 0.0, 100.0, 0),
        )
        report = assess_game_draft(0x10, notes)
        self.assertFalse(report.ready)
        self.assertEqual((0,), report.invalid_pitch_indices)
        self.assertEqual((0,), report.unsupported_articulation_indices)
        self.assertEqual((0,), report.invalid_timing_indices)
        self.assertEqual((0,), report.invalid_velocity_indices)
        self.assertEqual(11, notes[0].pitch)

    def test_game_id_39_is_clarinet_not_recorder(self) -> None:
        # Game CSS calls instrument_39 클라리넷 and its SoundBank is named
        # midi_instrument_27_proclarinet.  Keep this distinct from the
        # beginner recorder at ID 0x02.
        self.assertEqual("弗洛凯斯特拉：单簧管", BDO_INSTRUMENT_NAMES[0x27])
        self.assertEqual(
            "wind.clarinet",
            self.adaptations[0x27].visual_key,
        )

    def test_verified_legal_pitches_are_never_cropped_by_display_guidance(self) -> None:
        for instrument_id, adaptation in self.adaptations.items():
            if adaptation.legal_pitches is None:
                continue
            low, high = adaptation.recommended_visible_range
            with self.subTest(instrument_id=instrument_id):
                self.assertTrue(adaptation.legal_pitches)
                self.assertGreaterEqual(low, BDO_NOTE_MIN)
                self.assertLessEqual(high, BDO_NOTE_MAX)
                self.assertLessEqual(low, min(adaptation.legal_pitches))
                self.assertGreaterEqual(high, max(adaptation.legal_pitches))
                for pitch in adaptation.legal_pitches:
                    self.assertTrue(adaptation.legal_pitch_support(pitch))
                    self.assertTrue(adaptation.should_render_pitch_row(pitch))

    def test_unknown_or_approximate_game_ranges_fail_open_for_note_display(self) -> None:
        adaptation = self.adaptations[0x13]
        self.assertIsNone(adaptation.legal_pitches)
        self.assertIsNone(adaptation.legal_pitch_support(0))
        self.assertTrue(adaptation.should_render_pitch_row(0))
        self.assertTrue(adaptation.should_render_pitch_row(127))
        self.assertFalse(adaptation.compress_invalid_pitches)

    def test_game_ui_hand_drum_and_cymbal_lanes_are_exact(self) -> None:
        hand_drum = self.adaptations[0x04]
        self.assertEqual(
            frozenset({60, 65, 66, 67, 72, 73, 74, 77, 78, 79}),
            hand_drum.legal_pitches,
        )
        self.assertEqual(hand_drum.legal_pitches, hand_drum.recommended_pitches)
        self.assertTrue(hand_drum.legal_pitch_support(60))
        self.assertFalse(hand_drum.legal_pitch_support(61))

        cymbals = self.adaptations[0x05]
        self.assertEqual(frozenset({60, 65, 71}), cymbals.legal_pitches)
        self.assertTrue(cymbals.legal_pitch_support(71))
        self.assertFalse(cymbals.legal_pitch_support(70))

    def test_drum_set_uses_canonical_lanes_and_ntype_99(self) -> None:
        drum_set = self.adaptations[0x0D]
        self.assertEqual(GameInstrumentFamily.PERCUSSION, drum_set.family)
        self.assertEqual(ArrangementRole.PERCUSSION, drum_set.primary_role)
        self.assertEqual(frozenset(range(48, 65)), drum_set.legal_pitches)
        self.assertTrue(drum_set.compress_invalid_pitches)
        self.assertEqual(99, drum_set.default_ntype)
        self.assertEqual(tuple(range(48, 65)), tuple(lane.pitch for lane in drum_set.drum_lanes))
        self.assertEqual("Kck", drum_set.drum_lane_label(48))
        self.assertEqual("SnrRollL", drum_set.drum_lane_label(64))
        self.assertIsNone(drum_set.drum_lane_label(65))
        self.assertFalse(drum_set.should_render_pitch_row(47))
        self.assertFalse(drum_set.should_render_pitch_row(65))
        self.assertEqual((99,), tuple(item.ntype for item in drum_set.articulations))

    def test_every_game_instrument_has_the_correct_basic_articulation_first(self) -> None:
        registry = articulation_pairs_by_instrument()
        for instrument_id, adaptation in self.adaptations.items():
            expected = 99 if instrument_id == 0x0D else 0
            with self.subTest(instrument_id=instrument_id):
                self.assertEqual(expected, adaptation.default_ntype)
                self.assertEqual(expected, registry[instrument_id][0][0])
                self.assertEqual(
                    "打击乐" if expected == 99 else "延音",
                    registry[instrument_id][0][1],
                )
        self.assertEqual(((0, "延音"),), registry[0x07])
        self.assertEqual(
            ((0, "延音"), (11, "延音踏板")),
            registry[0x11],
        )

    def test_non_drum_set_percussion_is_not_silently_rewritten_to_99(self) -> None:
        for instrument_id in (0x04, 0x05, 0x13):
            adaptation = self.adaptations[instrument_id]
            with self.subTest(instrument_id=instrument_id):
                self.assertEqual(0, adaptation.default_ntype)
                self.assertEqual((0,), tuple(item.ntype for item in adaptation.articulations))

    def test_native_partial_routes_are_explicit_and_pitch_bounded(self) -> None:
        for instrument_id in (0x24, 0x25, 0x26):
            fx = next(
                item
                for item in self.adaptations[instrument_id].articulations
                if item.ntype == 25
            )
            with self.subTest(instrument_id=instrument_id):
                self.assertEqual(RouteEvidence.PARTIAL, fx.route_evidence)
                self.assertEqual(frozenset(range(36, 44)), fx.native_route_pitches)
                self.assertTrue(fx.native_preview_supports(36))
                self.assertFalse(fx.native_preview_supports(44))

        horn_slide = next(
            item for item in self.adaptations[0x28].articulations if item.ntype == 3
        )
        self.assertEqual(RouteEvidence.PARTIAL, horn_slide.route_evidence)
        self.assertEqual(frozenset(range(24, 73)), horn_slide.native_route_pitches)

    def test_native_partial_routes_are_shared_authoring_constraints(self) -> None:
        for instrument_id in (0x24, 0x25, 0x26):
            with self.subTest(instrument_id=instrument_id):
                self.assertEqual(
                    frozenset(range(36, 44)),
                    articulation_trigger_pitches(instrument_id, 25),
                )
                self.assertTrue(
                    articulation_supports_pitch(instrument_id, 25, 36)
                )
                self.assertFalse(
                    articulation_supports_pitch(instrument_id, 25, 44)
                )
        self.assertTrue(articulation_supports_pitch(0x28, 3, 72))
        self.assertFalse(articulation_supports_pitch(0x28, 3, 73))
        self.assertTrue(articulation_supports_pitch(0x28, 0, 95))

    def test_game_draft_check_rejects_silent_partial_route_combinations(self) -> None:
        guitar = assess_game_draft(
            0x24,
            (Note(43, 96, 0.0, 100.0, 25), Note(44, 96, 100.0, 100.0, 25)),
        )
        self.assertEqual((1,), guitar.unsupported_articulation_indices)

        horn = assess_game_draft(
            0x28,
            (Note(72, 96, 0.0, 100.0, 3), Note(73, 96, 100.0, 100.0, 3)),
        )
        self.assertEqual((1,), horn.unsupported_articulation_indices)

    def test_wwise_route_does_not_claim_audible_game_ab_validation(self) -> None:
        route_count = 0
        for adaptation in self.adaptations.values():
            for articulation in adaptation.articulations:
                if articulation.route_evidence is not RouteEvidence.UNKNOWN:
                    route_count += 1
                self.assertFalse(articulation.audible_behavior_verified)
                self.assertFalse(articulation.auto_apply_allowed)
        self.assertGreater(route_count, 80)

    def test_missing_wwise_map_does_not_turn_preview_gaps_into_illegal_notes(self) -> None:
        adaptations = load_instrument_editor_adaptations(
            wwise_mapping_path=None,
        )
        piano = adaptations[0x11]
        self.assertFalse(piano.preview_pitches)
        self.assertEqual(frozenset(range(12, 108)), piano.legal_pitches)
        self.assertEqual(piano.legal_pitches, piano.recommended_pitches)
        self.assertTrue(piano.should_render_pitch_row(60))

        hand_drum = adaptations[0x04]
        self.assertEqual(
            frozenset({60, 65, 66, 67, 72, 73, 74, 77, 78, 79}),
            hand_drum.legal_pitches,
        )
        self.assertEqual(hand_drum.legal_pitches, hand_drum.recommended_pitches)
        # The profile now knows legality even without Wwise, while the current
        # piano-roll compression policy still remains drum-set-only.
        self.assertTrue(hand_drum.should_render_pitch_row(12))
        self.assertTrue(hand_drum.should_render_pitch_row(119))

    def test_display_api_is_cached_profile_only_and_read_only(self) -> None:
        first = instrument_editor_display_adaptations()
        second = instrument_editor_display_adaptations()
        self.assertIs(first, second)
        self.assertEqual(set(BDO_INSTRUMENT_NAMES), set(first))
        with self.assertRaises(TypeError):
            first[0x07] = first[0x07]  # type: ignore[index]

        piano = instrument_editor_display_adaptation(0x11)
        self.assertIsNotNone(piano)
        assert piano is not None
        self.assertFalse(piano.preview_pitches)
        self.assertEqual(frozenset(range(12, 108)), piano.recommended_pitches)
        self.assertTrue(all(
            item.route_evidence is RouteEvidence.UNKNOWN
            for item in piano.articulations
        ))

        drum_set = instrument_editor_display_adaptation(0x0D)
        self.assertIsNotNone(drum_set)
        assert drum_set is not None
        self.assertTrue(drum_set.compress_invalid_pitches)
        self.assertEqual((48, 64), drum_set.recommended_visible_range)
        self.assertEqual(99, drum_set.default_ntype)

    def test_approximate_profile_range_can_focus_without_becoming_legal(self) -> None:
        handpan = instrument_editor_display_adaptation(0x13)
        self.assertIsNotNone(handpan)
        assert handpan is not None
        self.assertIsNone(handpan.legal_pitches)
        self.assertEqual((45, 88), handpan.recommended_visible_range)
        self.assertTrue(handpan.should_render_pitch_row(12))
        self.assertTrue(handpan.should_render_pitch_row(119))

    def test_articulation_registry_is_exhaustive_ordered_and_duplicate_free(self) -> None:
        registry = articulation_pairs_by_instrument()
        self.assertEqual(set(BDO_INSTRUMENT_NAMES), set(registry))
        for instrument_id, pairs in registry.items():
            with self.subTest(instrument_id=instrument_id):
                ntypes = tuple(ntype for ntype, _label in pairs)
                self.assertEqual(len(ntypes), len(set(ntypes)))
                self.assertTrue(all(label for _ntype, label in pairs))
                if instrument_id == 0x0D:
                    self.assertEqual((99,), ntypes)
                else:
                    self.assertEqual(0, ntypes[0])

    def test_articulation_profiles_match_game_ui_registry(self) -> None:
        registry = {
            instrument_id: {ntype for ntype, _label in pairs}
            for instrument_id, pairs in articulation_pairs_by_instrument().items()
        }
        for profile in PROFILES:
            for instrument_id in profile.instrument_ids:
                with self.subTest(
                    instrument_id=instrument_id,
                    ntype=profile.ntype,
                ):
                    self.assertIn(profile.ntype, registry[instrument_id])

        # These two declarations previously leaked in from a shared profile,
        # despite having neither a game UI entry nor a Wwise route.
        self.assertIsNone(profile_for(0x27, 2))
        self.assertIsNone(profile_for(0x28, 2))

    def test_articulation_context_ranges_do_not_cross_instrument_limits(self) -> None:
        for profile in PROFILES:
            if profile.preferred_range is None:
                continue
            for instrument_id in profile.instrument_ids:
                adaptation = self.adaptations[instrument_id]
                legal = adaptation.legal_pitches
                if legal is None:
                    continue
                low, high = profile.preferred_range
                with self.subTest(
                    instrument_id=instrument_id,
                    ntype=profile.ntype,
                ):
                    self.assertGreaterEqual(low, min(legal))
                    self.assertLessEqual(high, max(legal))


if __name__ == "__main__":
    unittest.main()
