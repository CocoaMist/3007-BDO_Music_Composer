from __future__ import annotations

from collections import namedtuple
import unittest

from bdo_articulation_profiles import profile_for
from bdo_music_theory import analyse_music
from bdo_midi_optimizer import OptimizerConfig, optimize_tracks
from pyside_bdo_gui import BDO_ARTICULATIONS, TrackState


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


if __name__ == "__main__":
    unittest.main()
