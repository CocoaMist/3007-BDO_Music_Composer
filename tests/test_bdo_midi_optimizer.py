from __future__ import annotations

from collections import namedtuple
from pathlib import Path
import tempfile
import unittest

import mido

from bdo_articulation_profiles import profile_for
from bdo_music_theory import TrackRole, analyse_music, analyse_song
from bdo_midi_optimizer import OptimizationLevel, OptimizerConfig, optimize_tracks
from bdo_lyrics import LyricExpressionMode, align_lyrics
from bdo_techniques import TECHNIQUE_PROFILES, TechniqueMap, TriggerKind
from pyside_bdo_gui import BDO_ARTICULATIONS, TrackState, build_filtered_midi, parse_midi


Note = namedtuple("Note", "pitch vel start dur ntype", defaults=(0,))


def track(instrument_id: int, notes: list[Note], *, track_fx: int | None = None) -> TrackState:
    return TrackState(
        track_id=1,
        notes=notes,
        gm_program=0,
        is_percussion=False,
        display_name="test",
        bdo_instrument_id=instrument_id,
        articulation_type=track_fx,
    )


def articulate(instrument_id: int, notes: list[Note], *, track_fx: int | None = None):
    config = OptimizerConfig(optimize_blocks=False, polish_velocity=False, soft_quantize=False)
    return optimize_tracks([track(instrument_id, notes, track_fx=track_fx)], 120, BDO_ARTICULATIONS, config)


class MidiOptimizerArticulationTests(unittest.TestCase):
    def test_every_non_default_ui_mapping_has_profile_metadata(self) -> None:
        for instrument_id, mappings in BDO_ARTICULATIONS.items():
            for ntype, _label in mappings:
                if ntype:
                    self.assertIsNotNone(profile_for(instrument_id, ntype), (instrument_id, ntype))

    def test_small_same_voice_ascent_is_suggestion_until_game_verified(self) -> None:
        result = articulate(0x0A, [Note(60, 96, 0, 180), Note(63, 96, 205, 160)])
        self.assertEqual(result.tracks[0].notes[0].ntype, 0)
        self.assertFalse(result.reports[0].suggestions[0].applied)
        self.assertFalse(result.reports[0].suggestions[0].auto_applicable)

    def test_verified_game_cell_allows_high_confidence_native_preview(self) -> None:
        result = optimize_tracks(
            [track(0x0A, [Note(60, 96, 0, 180), Note(63, 96, 205, 160)])],
            120, BDO_ARTICULATIONS,
            OptimizerConfig(
                optimize_blocks=False, polish_velocity=False, soft_quantize=False,
                verified_articulations=frozenset({(0x0A, 3)}),
            ),
        )
        self.assertEqual(result.tracks[0].notes[0].ntype, 3)

    def test_chord_does_not_create_cross_voice_slide(self) -> None:
        result = articulate(0x0A, [Note(60, 96, 0, 180), Note(64, 96, 0, 180), Note(65, 96, 205, 160)])
        self.assertTrue(all(note.ntype == 0 for note in result.tracks[0].notes))

    def test_minor_trill_requires_returning_neighbor(self) -> None:
        result = articulate(0x12, [Note(67, 90, 0, 520), Note(68, 90, 190, 120), Note(67, 90, 360, 140)])
        self.assertEqual(result.tracks[0].notes[0].ntype, 0)

    def test_repeated_detached_bass_riff_uses_mute(self) -> None:
        result = articulate(0x0E, [Note(40, 80, 0, 100), Note(40, 80, 250, 100), Note(40, 80, 500, 100)])
        self.assertEqual(result.tracks[0].notes[0].ntype, 0)

    def test_repeated_two_note_bass_motif_is_recognised_as_riff(self) -> None:
        result = articulate(0x0E, [
            Note(40, 80, 0, 100), Note(43, 80, 250, 100),
            Note(40, 80, 500, 100), Note(43, 80, 750, 100),
        ])
        self.assertTrue(any(item.ntype == 13 and "两音动机重复" in item.reason for item in result.reports[0].suggestions))

    def test_melodic_turnback_downgrades_second_slide_candidate(self) -> None:
        result = articulate(0x0A, [Note(60, 96, 0, 180), Note(62, 96, 205, 180), Note(60, 96, 410, 180)])
        turnback = next(item for item in result.reports[0].suggestions if item.ntype == 12)
        self.assertLess(turnback.confidence, 0.85)
        self.assertIn("旋律折返", turnback.reason)

    def test_harp_major_chord_is_a_group_level_candidate(self) -> None:
        result = articulate(0x10, [Note(60, 85, 0, 420), Note(64, 85, 0, 420), Note(67, 85, 0, 420)])
        self.assertTrue(all(note.ntype == 0 for note in result.tracks[0].notes))
        self.assertTrue(any(item.ntype == 9 and not item.applied for item in result.reports[0].suggestions))

    def test_harp_scale_run_is_a_non_destructive_gliss_suggestion(self) -> None:
        result = articulate(0x10, [Note(60, 85, 0, 80), Note(62, 85, 100, 80), Note(64, 85, 200, 80), Note(65, 85, 300, 80)])
        self.assertTrue(all(note.ntype == 0 for note in result.tracks[0].notes))
        self.assertTrue(any(item.ntype == 16 and not item.applied for item in result.reports[0].suggestions))

    def test_piano_pedal_is_limited_to_held_material(self) -> None:
        result = articulate(0x11, [Note(60, 85, 0, 800), Note(64, 85, 300, 180)])
        self.assertEqual(result.tracks[0].notes[0].ntype, 0)

    def test_wind_sustain_uses_velocity_layer(self) -> None:
        result = articulate(0x27, [Note(60, 108, 0, 600)])
        self.assertEqual(result.tracks[0].notes[0].ntype, 0)

    def test_unverified_marnian_candidate_is_suggestion_only(self) -> None:
        result = articulate(0x14, [Note(60, 80, 0, 900)])
        report = result.reports[0]
        self.assertEqual(result.tracks[0].notes[0].ntype, 0)
        self.assertEqual(report.suggestions_only, 1)
        self.assertFalse(report.suggestions[0].auto_applicable)

    def test_sparse_harmonic_is_suggestion_only_under_conservative_mode(self) -> None:
        result = articulate(0x0A, [Note(76, 75, 0, 300)])
        self.assertEqual(result.tracks[0].notes[0].ntype, 0)
        self.assertTrue(any(item.ntype == 14 and not item.applied for item in result.reports[0].suggestions))

    def test_electric_guitar_fx_is_never_generated(self) -> None:
        result = articulate(0x24, [Note(36, 120, 0, 120)])
        self.assertEqual(result.tracks[0].notes[0].ntype, 0)
        self.assertFalse(any(item.ntype == 25 for item in result.reports[0].suggestions))

    def test_manual_note_and_track_fx_are_not_overwritten(self) -> None:
        preserved = articulate(0x0A, [Note(60, 96, 0, 180, 14), Note(63, 96, 205, 160)])
        self.assertEqual(preserved.tracks[0].notes[0].ntype, 14)
        locked = articulate(0x0A, [Note(60, 96, 0, 180), Note(63, 96, 205, 160)], track_fx=3)
        self.assertEqual(locked.tracks[0].notes[0].ntype, 0)
        self.assertEqual(locked.reports[0].suggestions, [])

    def test_theory_context_marks_meter_phrase_and_texture(self) -> None:
        notes = [
            Note(60, 80, 0, 180), Note(64, 80, 0, 180),  # chord barrier
            Note(43, 80, 500, 100), Note(43, 80, 1000, 100),
            Note(60, 80, 1900, 180),
        ]
        context = analyse_music(notes, 120, 4, 420)
        self.assertEqual(context.roles[0], "chord")
        self.assertEqual(context.roles[2], "bass_riff")
        self.assertEqual(context.beat_strengths[0], 1.0)
        self.assertEqual(context.beat_strengths[3], 0.72)
        self.assertGreater(context.phrase_numbers[-1], context.phrase_numbers[-2])

    def test_tonal_analysis_is_enabled_only_for_stable_material(self) -> None:
        stable = [Note(pitch, 80, index * 200, 160) for index, pitch in enumerate((60, 62, 64, 65, 67, 69, 71, 72))]
        unstable = [Note(60 + index, 80, index * 200, 160) for index in range(12)]
        self.assertTrue(analyse_music(stable, 120, 4, 420).tonal)
        self.assertFalse(analyse_music(unstable, 120, 4, 420).tonal)

    def test_theory_toggle_and_time_signature_are_reported_without_rewriting_harmony(self) -> None:
        result = optimize_tracks(
            [track(0x0A, [Note(60, 96, 0, 180), Note(64, 96, 0, 180), Note(67, 96, 0, 180)])],
            120, BDO_ARTICULATIONS,
            OptimizerConfig(optimize_blocks=False, polish_velocity=False, soft_quantize=False, analyse_music_theory=True),
            time_sig=3,
        )
        self.assertTrue(all(note.ntype == 0 for note in result.tracks[0].notes))
        self.assertTrue(any("调性" in warning for warning in result.reports[0].warnings))


class ScopedAndEnsembleOptimizationTests(unittest.TestCase):
    def test_game_safe_mode_preserves_structure_and_instrument_mapping(self) -> None:
        source = track(0x12, [
            Note(60, 80, 0, 1200), Note(64, 82, 500, 700), Note(67, 84, 1000, 500),
        ])
        result = optimize_tracks(
            [source], 120, BDO_ARTICULATIONS,
            OptimizerConfig(game_safe_only=True, optimize_blocks=True, humanize=True),
        )
        self.assertEqual(len(result.tracks), 1)
        self.assertEqual(result.tracks[0].bdo_instrument_id, source.bdo_instrument_id)
        self.assertEqual(len(result.tracks[0].notes), len(source.notes))
        self.assertEqual(sorted(note.pitch for note in result.tracks[0].notes), sorted(note.pitch for note in source.notes))

    def test_game_safe_humanization_is_stable_and_keeps_chords_together(self) -> None:
        source = track(0x12, [
            Note(60, 80, 125, 180), Note(64, 80, 125, 180), Note(67, 80, 125, 180),
            Note(62, 82, 625, 180), Note(65, 82, 1125, 180),
        ])
        config = OptimizerConfig(
            game_safe_only=True, optimize_blocks=False, polish_velocity=False,
            apply_articulations=False, humanize=True,
        )
        first = optimize_tracks([source], 120, BDO_ARTICULATIONS, config)
        second = optimize_tracks([source], 120, BDO_ARTICULATIONS, OptimizerConfig(
            game_safe_only=True, optimize_blocks=False, polish_velocity=False,
            apply_articulations=False, humanize=True,
        ))
        first_notes, second_notes = first.tracks[0].notes, second.tracks[0].notes
        self.assertEqual(first_notes, second_notes)
        chord_offsets = {round(first_notes[index].start - source.notes[index].start, 3) for index in range(3)}
        self.assertEqual(len(chord_offsets), 1)
        self.assertTrue(all(note.start >= 0 for note in first_notes))
        self.assertEqual(sorted(note.start for note in first_notes), [note.start for note in first_notes])

    def test_game_safe_humanization_is_idempotent_after_apply(self) -> None:
        source = track(0x12, [Note(60 + index, 80, 125 + index * 500, 180) for index in range(5)])
        config = OptimizerConfig(
            game_safe_only=True, optimize_blocks=False, polish_velocity=False,
            apply_articulations=False, humanize=True,
        )
        first = optimize_tracks([source], 120, BDO_ARTICULATIONS, config)
        second = optimize_tracks([first.tracks[0]], 120, BDO_ARTICULATIONS, OptimizerConfig(
            game_safe_only=True, optimize_blocks=False, polish_velocity=False,
            apply_articulations=False, humanize=True,
        ))
        self.assertEqual(first.tracks[0].notes, second.tracks[0].notes)
        self.assertEqual(second.reports[0].humanized_notes, 0)

    def test_game_safe_preserves_existing_dynamic_curve_and_controls(self) -> None:
        source = track(0x12, [
            Note(60, 35, 0, 180), Note(62, 58, 500, 180),
            Note(64, 88, 1000, 180), Note(65, 112, 1500, 180),
        ])
        source.performance_controls = [
            {"time": 0, "kind": "control_change", "control": 11, "value": 25},
            {"time": 1500, "kind": "control_change", "control": 11, "value": 110},
            {"time": 700, "kind": "pitchwheel", "pitch": 400},
        ]
        result = optimize_tracks(
            [source], 120, BDO_ARTICULATIONS,
            OptimizerConfig(game_safe_only=True, polish_velocity=True, humanize=True, apply_articulations=False),
        )
        self.assertEqual([note.vel for note in result.tracks[0].notes], [35, 58, 88, 112])
        self.assertEqual(result.tracks[0].performance_controls, source.performance_controls)

    def test_effect_suggestion_is_bounded_stable_and_scope_aware(self) -> None:
        source = track(0x14, [Note(60, 82, index * 1000, 800) for index in range(8)])
        kwargs = dict(
            game_safe_only=True, current_reverb=7, current_delay=3,
            current_chorus=(1, 2, 3), optimize_effects=True,
            optimize_blocks=False, polish_velocity=False, apply_articulations=False, humanize=False,
        )
        global_result = optimize_tracks(
            [source], 120, BDO_ARTICULATIONS,
            OptimizerConfig(**kwargs, allow_global_effect_write=True),
        )
        repeated = optimize_tracks(
            [source], 120, BDO_ARTICULATIONS,
            OptimizerConfig(**kwargs, allow_global_effect_write=True),
        )
        suggestion = global_result.effect_suggestion
        self.assertEqual(suggestion, repeated.effect_suggestion)
        self.assertTrue(suggestion.writable)
        values = (suggestion.suggested_reverb, suggestion.suggested_delay, *(suggestion.suggested_chorus or (0, 0, 0)))
        self.assertTrue(all(0 <= value <= 127 for value in values))
        single_result = optimize_tracks(
            [source], 120, BDO_ARTICULATIONS,
            OptimizerConfig(**kwargs, target_track_ids=frozenset({1}), allow_global_effect_write=False),
        )
        self.assertFalse(single_result.effect_suggestion.writable)

    def test_pairing_analysis_is_read_only_and_prioritized(self) -> None:
        melody = track(0x12, [Note(72, 90, i * 500, 180) for i in range(6)])
        harmony = track(0x11, [Note(72, 76, i * 500, 180) for i in range(6)])
        harmony.track_id = 2
        before = [(item.track_id, item.bdo_instrument_id, list(item.notes)) for item in (melody, harmony)]
        result = optimize_tracks(
            [melody, harmony], 120, BDO_ARTICULATIONS,
            OptimizerConfig(
                game_safe_only=True, optimize_blocks=False, polish_velocity=False,
                apply_articulations=False, humanize=False,
            ),
        )
        after = [(item.track_id, item.bdo_instrument_id, list(item.notes)) for item in result.tracks]
        self.assertEqual(before, after)
        self.assertTrue(result.ensemble_suggestions)
        self.assertEqual(
            [item.priority for item in result.ensemble_suggestions],
            sorted((item.priority for item in result.ensemble_suggestions), reverse=True),
        )

    def test_extended_registry_covers_midi2_articulation_classes(self) -> None:
        classifications = {profile.midi2_classification for profile in TECHNIQUE_PROFILES.values()}
        self.assertTrue(set(range(0x10, 0x18)).issubset(classifications))
        self.assertIn("flutter_tongue", TECHNIQUE_PROFILES)
        self.assertIn("strum_down", TECHNIQUE_PROFILES)
        self.assertIn("rim_shot", TECHNIQUE_PROFILES)

    def test_vendor_technique_map_is_explicit_and_validated(self) -> None:
        mapping = TechniqueMap.from_dict({
            "map_id": "demo", "vendor": "Example", "product": "Strings",
            "mappings": {"pizzicato": [{"kind": "keyswitch", "number": 24}]},
        })
        self.assertEqual(mapping.mappings["pizzicato"][0].kind, TriggerKind.KEYSWITCH)
        with self.assertRaises(ValueError):
            TechniqueMap.from_dict({"mappings": {"not_a_technique": []}})

    def test_pitch_expression_and_cc11_create_semantic_candidates(self) -> None:
        source = track(0x14, [Note(60, 86, 0, 1000), Note(64, 88, 1100, 700)])
        source.performance_controls = [
            {"time": 100, "kind": "pitchwheel", "pitch": -500},
            {"time": 200, "kind": "pitchwheel", "pitch": 500},
            {"time": 300, "kind": "pitchwheel", "pitch": -600},
            {"time": 400, "kind": "pitchwheel", "pitch": 700},
            {"time": 0, "kind": "control_change", "control": 11, "value": 30},
            {"time": 900, "kind": "control_change", "control": 11, "value": 100},
            {"time": 0, "kind": "control_change", "control": 74, "value": 20},
            {"time": 900, "kind": "control_change", "control": 74, "value": 90},
        ]
        result = optimize_tracks([source], 120, BDO_ARTICULATIONS, OptimizerConfig())
        technique_ids = {item.technique_id for item in result.reports[0].technique_candidates}
        self.assertTrue({"vibrato", "crescendo", "timbre_sweep"}.issubset(technique_ids))

    def test_pitchwheel_and_aftertouch_survive_midi_round_trip(self) -> None:
        source = track(0x14, [Note(60, 90, 0, 600)])
        source.performance_controls = [
            {"time": 100, "kind": "pitchwheel", "pitch": 1234},
            {"time": 200, "kind": "aftertouch", "value": 73},
            {"time": 300, "kind": "polytouch", "note": 60, "value": 55},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "expressive.mid"
            build_filtered_midi([source], 120, 4, path)
            parsed = parse_midi(path, include_controls=True)
        events = parsed[-1][0]
        self.assertEqual({item.get("kind") for item in events}, {"pitchwheel", "aftertouch", "polytouch"})

    def test_lyric_timestamps_help_choose_primary_melody(self) -> None:
        vocal = track(0x12, [Note(65, 88, 0, 180), Note(67, 88, 500, 180), Note(69, 88, 1000, 180)])
        ornament = track(0x0B, [Note(84, 82, 180, 120), Note(86, 82, 680, 120), Note(88, 82, 1180, 120)])
        ornament.track_id = 2
        lyrics = [{"time": time, "kind": "lyrics", "text": text} for time, text in ((0, "你"), (500, "好"), (1000, "呀"))]
        context = analyse_song([vocal, ornament], 120, 4, lyric_events=lyrics)
        self.assertEqual(context.track_roles[1], TrackRole.PRIMARY_MELODY)

    def test_lyric_expression_preserves_pitch_and_count(self) -> None:
        source = track(0x12, [Note(72, 88, 0, 180), Note(74, 88, 500, 180), Note(76, 88, 1000, 180)])
        lyrics = [{"time": time, "kind": "lyrics", "text": text} for time, text in ((0, "春"), (500, "风"), (1000, "来"))]
        result = optimize_tracks(
            [source], 120, BDO_ARTICULATIONS,
            OptimizerConfig(
                level=OptimizationLevel.EXPRESSIVE, optimize_blocks=False, polish_velocity=False,
                apply_articulations=False, soft_quantize=False, lyric_events=lyrics,
                lyric_mode=LyricExpressionMode.LEGATO,
            ),
        )
        self.assertEqual([note.pitch for note in result.tracks[0].notes], [72, 74, 76])
        self.assertEqual(len(result.tracks[0].notes), 3)
        self.assertGreater(result.tracks[0].notes[0].dur, 180)
        self.assertEqual(result.lyric_context.mode, LyricExpressionMode.LEGATO)

    def test_lyric_meta_events_survive_filtered_midi_round_trip(self) -> None:
        source = track(0x12, [Note(60, 90, 0, 600)])
        lyrics = [{"time": 0.0, "kind": "lyrics", "text": "Hello"},
                  {"time": 500.0, "kind": "lyrics", "text": "world\r"}]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "lyrics.mid"
            build_filtered_midi([source], 120, 4, path, lyrics)
            parsed = parse_midi(path, include_controls=True, include_lyrics=True)
        self.assertEqual([item["text"] for item in parsed[-1]], ["Hello", "world\r"])

    def test_sustained_notes_participate_in_later_chord_window(self) -> None:
        notes = [Note(60, 80, 0, 1000), Note(64, 80, 0, 1000), Note(67, 80, 500, 300)]
        context = analyse_music(notes, 120, 4, 420)
        later = next(window for window in context.harmony if window.start == 500)
        self.assertEqual(later.quality, "major")

    def test_single_track_scope_reads_song_but_only_mutates_target(self) -> None:
        melody = track(0x0A, [Note(72, 85, 0, 180), Note(74, 85, 250, 180)])
        harmony = track(0x12, [Note(60, 90, 0, 1000)])
        harmony.track_id = 2
        result = optimize_tracks(
            [melody, harmony], 120, BDO_ARTICULATIONS,
            OptimizerConfig(target_track_ids=frozenset({1})),
        )
        self.assertIs(result.tracks[1], harmony)
        self.assertEqual(result.reports[1].scope, "只读上下文")
        self.assertEqual(set(result.song_context.track_roles), {1, 2})

    def test_safe_mode_preserves_note_count_and_pitch_multiset(self) -> None:
        source = track(0x12, [Note(60, 80, 0, 1200)])
        result = optimize_tracks(
            [source], 120, BDO_ARTICULATIONS,
            OptimizerConfig(level=OptimizationLevel.SAFE, optimize_blocks=False, soft_quantize=False),
        )
        self.assertEqual([note.pitch for note in result.tracks[0].notes], [60])
        self.assertEqual(len(result.tracks[0].notes), 1)

    def test_expressive_mode_splits_non_melody_sustain_with_cap(self) -> None:
        source = track(0x12, [Note(60, 80, 0, 1200)])
        result = optimize_tracks(
            [source], 120, BDO_ARTICULATIONS,
            OptimizerConfig(
                level=OptimizationLevel.EXPRESSIVE, optimize_blocks=False,
                polish_velocity=False, apply_articulations=False, soft_quantize=False,
            ),
        )
        self.assertGreater(len(result.tracks[0].notes), 1)
        self.assertLessEqual(len(result.tracks[0].notes), 4)
        self.assertEqual({note.pitch for note in result.tracks[0].notes}, {60})

    def test_expressive_mode_does_not_rewrite_primary_melody_pitch(self) -> None:
        source = track(0x12, [
            Note(72, 80, 0, 900), Note(74, 82, 1100, 180), Note(76, 84, 1400, 180),
        ])
        result = optimize_tracks(
            [source], 120, BDO_ARTICULATIONS,
            OptimizerConfig(level=OptimizationLevel.EXPRESSIVE, optimize_blocks=False, polish_velocity=False),
        )
        self.assertEqual([note.pitch for note in result.tracks[0].notes], [72, 74, 76])

    def test_arrange_mode_can_add_a_range_checked_doubling_track(self) -> None:
        melody = track(0x12, [Note(72, 90, 0, 180), Note(74, 92, 250, 180), Note(76, 94, 500, 180)])
        bass = track(0x0E, [Note(36, 82, 0, 220), Note(38, 82, 500, 220)])
        bass.track_id = 2
        result = optimize_tracks(
            [melody, bass], 120, BDO_ARTICULATIONS,
            OptimizerConfig(
                level=OptimizationLevel.ARRANGE,
                supported_pitches={0x0B: frozenset(range(48, 100))},
                optimize_blocks=False, polish_velocity=False, apply_articulations=False,
            ),
        )
        self.assertEqual(len(result.tracks), 3)
        self.assertEqual(result.tracks[-1].bdo_instrument_id, 0x0B)
        self.assertTrue(result.arrangement_changes)

    def test_arrange_mode_revoices_overlapping_accompaniment_by_octave(self) -> None:
        melody = track(0x12, [Note(72, 90, 0, 180), Note(74, 90, 500, 180), Note(76, 90, 1000, 180)])
        harmony = track(0x11, [
            Note(67, 76, 0, 450), Note(72, 74, 0, 450), Note(76, 72, 0, 450),
            Note(69, 76, 500, 450), Note(74, 74, 500, 450), Note(77, 72, 500, 450),
        ])
        harmony.track_id = 2
        original = [note.pitch for note in harmony.notes]
        result = optimize_tracks(
            [melody, harmony], 120, BDO_ARTICULATIONS,
            OptimizerConfig(
                level=OptimizationLevel.ARRANGE, allow_track_creation=False,
                supported_pitches={0x11: frozenset(range(12, 108))},
                optimize_blocks=False, polish_velocity=False, apply_articulations=False,
            ),
        )
        shifted = [note.pitch for note in result.tracks[1].notes]
        self.assertTrue(all(after - before in {-12, 12} for before, after in zip(original, shifted)))
        self.assertTrue(any("音区遮蔽" in change for change in result.arrangement_changes))

    def test_cross_track_context_assigns_primary_bass_and_style(self) -> None:
        melody = track(0x24, [Note(72, 90, 0, 180), Note(76, 90, 250, 180), Note(79, 90, 500, 180)])
        bass = track(0x0E, [Note(36, 85, 0, 120), Note(36, 85, 250, 120), Note(38, 85, 500, 120)])
        bass.track_id = 2
        context = analyse_song([melody, bass], 120, 4)
        self.assertEqual(context.track_roles[1], TrackRole.PRIMARY_MELODY)
        self.assertEqual(context.track_roles[2], TrackRole.BASS)
        self.assertTrue(any(tag.name == "rock" for tag in context.styles))

    def test_segment_roles_can_change_without_mutating_tracks(self) -> None:
        first = track(0x12, [Note(72, 90, 0, 180), Note(74, 90, 250, 180)])
        second = track(0x0B, [Note(76, 90, 1200, 180), Note(79, 90, 1450, 180)])
        second.track_id = 2
        context = analyse_song([first, second], 120, 4)
        self.assertGreaterEqual(len(context.segment_roles[1]), 2)
        self.assertEqual(context.segment_roles[1][-1], TrackRole.ORNAMENT)
        self.assertIn(context.segment_roles[2][-1], {TrackRole.PRIMARY_MELODY, TrackRole.SECONDARY_MELODY})

    def test_context_classifier_failure_is_deterministic_fallback(self) -> None:
        class BrokenClassifier:
            def classify(self, tracks, context):
                raise RuntimeError("offline")

        source = track(0x24, [Note(60, 80, 0, 180), Note(64, 80, 250, 180)])
        baseline = analyse_song([source], 120, 4)
        fallback = analyse_song([source], 120, 4, classifier=BrokenClassifier())
        self.assertEqual(baseline.track_roles, fallback.track_roles)
        self.assertEqual(baseline.styles, fallback.styles)

    def test_cc64_is_returned_aligned_with_parsed_track(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "pedal.mid"
            midi = mido.MidiFile(ticks_per_beat=480)
            midi_track = mido.MidiTrack()
            midi.tracks.append(midi_track)
            midi_track.append(mido.Message("program_change", channel=0, program=0, time=0))
            midi_track.append(mido.Message("control_change", channel=0, control=64, value=127, time=0))
            midi_track.append(mido.Message("note_on", channel=0, note=60, velocity=90, time=0))
            midi_track.append(mido.Message("note_off", channel=0, note=60, velocity=0, time=480))
            midi_track.append(mido.Message("control_change", channel=0, control=64, value=0, time=240))
            midi.save(path)
            _bpm, _sig, groups, _tempos, controls = parse_midi(path, include_controls=True)
        self.assertEqual(len(groups), 1)
        self.assertEqual([item["value"] for item in controls[0] if item["control"] == 64], [127, 0])

    def test_cc64_survives_filtered_midi_round_trip(self) -> None:
        source = track(0x11, [Note(60, 90, 0, 600)])
        source.performance_controls = [
            {"time": 0.0, "control": 64, "value": 127, "channel": 0},
            {"time": 500.0, "control": 64, "value": 0, "channel": 0},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "roundtrip.mid"
            build_filtered_midi([source], 120, 4, path)
            _bpm, _sig, _groups, _tempos, controls = parse_midi(path, include_controls=True)
        self.assertEqual([item["value"] for item in controls[0] if item["control"] == 64], [127, 0])


if __name__ == "__main__":
    unittest.main()
