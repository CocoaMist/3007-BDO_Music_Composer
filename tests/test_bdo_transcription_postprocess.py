from __future__ import annotations

from itertools import permutations
import unittest

import numpy as np

from bdo_music_composer.transcription.bdo_transcription_postprocess import (
    FrameNoteEvent,
    POSTPROCESS_VERSION,
    postprocess_frame_events,
    preview_frame_event_cleanup,
)


MIDI_MIN = 21
FRAME_COUNT = 80
BIN_COUNT = 88


def evidence() -> tuple[np.ndarray, np.ndarray]:
    return (
        np.zeros((FRAME_COUNT, BIN_COUNT), dtype=np.float32),
        np.zeros((FRAME_COUNT, BIN_COUNT), dtype=np.float32),
    )


def sustain(
    frame: np.ndarray,
    pitch: int,
    start: int,
    end: int,
    value: float = 0.8,
) -> None:
    frame[start:end, pitch - MIDI_MIN] = value


def onset_peak(
    onset: np.ndarray,
    pitch: int,
    at: int,
    value: float,
) -> None:
    onset[at, pitch - MIDI_MIN] = value


class FragmentPostprocessTests(unittest.TestCase):
    def test_selected_profile_directly_controls_automatic_actions(self) -> None:
        frame, onset = evidence()
        nms_events = (
            FrameNoteEvent(30, 50, 64, 0.75, ("nms-lower",)),
            FrameNoteEvent(31, 50, 64, 0.90, ("nms-winner",)),
        )
        weak = FrameNoteEvent(60, 65, 72, 0.2, ("weak",))
        sustain(frame, 72, 60, 65, 0.2)
        events = nms_events + (weak,)
        preserved = postprocess_frame_events(
            events,
            frame,
            onset,
        )
        self.assertFalse(preserved.automatic_actions_enabled)
        self.assertEqual(preserved.events, events)
        self.assertEqual(preserved.stats.nms_removed_count, 0)

        balanced = postprocess_frame_events(
            events,
            frame,
            onset,
            profile="balanced",
        )
        self.assertTrue(balanced.automatic_actions_enabled)
        self.assertEqual(len(balanced.events), 2)
        self.assertEqual(balanced.stats.nms_removed_count, 1)
        self.assertEqual(
            next(item for item in balanced.events if item.pitch == 64).lineage,
            ("nms-lower", "nms-winner"),
        )

        clean = postprocess_frame_events(
            events,
            frame,
            onset,
            profile="clean",
        )
        self.assertTrue(clean.automatic_actions_enabled)
        self.assertEqual(len(clean.events), 1)
        self.assertEqual(clean.events[0].pitch, 64)
        self.assertEqual(clean.suppressed, (weak,))
        self.assertEqual(clean.stats.suppressed_count, 1)
        hidden_audit = next(
            item for item in clean.audit if item.action == "suppressed"
        )
        self.assertIn("clean_suppressed", hidden_audit.flags)

    def test_explicit_preview_marks_actions_without_applying_them(self) -> None:
        frame, onset = evidence()
        sustain(frame, 60, 5, 22)
        events = (
            FrameNoteEvent(5, 12, 60, 0.72, ("split-left",)),
            FrameNoteEvent(14, 22, 60, 0.64, ("split-right",)),
        )

        preview = preview_frame_event_cleanup(
            events,
            frame,
            onset,
            profile="balanced",
        )

        self.assertFalse(preview.automatic_actions_enabled)
        self.assertEqual(preview.events, events)
        self.assertEqual(preview.stats.automatic_merge_count, 0)
        self.assertTrue(
            all(
                audit.action == "kept"
                and "cleanup_candidate" in audit.flags
                and "review_fragment" in audit.flags
                for audit in preview.audit
            )
        )

    def test_preserve_marks_false_split_continuity_without_merging(self) -> None:
        frame, onset = evidence()
        sustain(frame, 60, 5, 22)
        events = (
            FrameNoteEvent(5, 12, 60, 0.72, ("split-left",)),
            FrameNoteEvent(14, 22, 60, 0.64, ("split-right",)),
        )

        result = postprocess_frame_events(
            events,
            frame,
            onset,
            profile="preserve",
        )

        self.assertEqual(result.events, events)
        self.assertEqual(result.stats.automatic_merge_count, 0)
        self.assertFalse(result.automatic_actions_enabled)
        self.assertTrue(
            all(
                "cleanup_candidate" in item.flags
                for item in result.audit
                if item.action == "kept"
            )
        )

    def test_preserve_sorts_deduplicates_and_only_labels_short_notes(
        self,
    ) -> None:
        frame, onset = evidence()
        events = (
            FrameNoteEvent(20, 32, 64, 0.7, ("long",)),
            FrameNoteEvent(4, 10, 60, 0.4, ("short-a",)),
            FrameNoteEvent(4, 10, 60, 0.4, ("short-b",)),
        )

        result = postprocess_frame_events(
            reversed(events),
            frame,
            onset,
            profile="preserve",
        )

        self.assertEqual(
            [(item.start_frame, item.pitch) for item in result.events],
            [(4, 60), (20, 64)],
        )
        self.assertEqual(
            result.events[0].lineage,
            ("short-a", "short-b"),
        )
        self.assertEqual(result.stats.exact_duplicate_count, 1)
        self.assertEqual(result.stats.automatic_merge_count, 0)
        flags = next(
            item.flags
            for item in result.audit
            if item.action == "kept" and item.event.pitch == 60
        )
        self.assertIn("severe_fragment", flags)
        self.assertIn("review_fragment", flags)
        self.assertIn("short_density", flags)

    def test_preserve_reuses_a_unique_immutable_event(self) -> None:
        frame, onset = evidence()
        event = FrameNoteEvent(20, 32, 64, 0.7, ("unique",))

        result = postprocess_frame_events(
            (event,),
            frame,
            onset,
            profile="preserve",
        )

        self.assertIs(result.events[0], event)

    def test_balanced_same_pitch_nms_is_order_independent(self) -> None:
        frame, onset = evidence()
        events = (
            FrameNoteEvent(10, 30, 60, 0.75, ("lower",)),
            FrameNoteEvent(11, 30, 60, 0.90, ("winner",)),
            FrameNoteEvent(10, 30, 61, 0.80, ("other-pitch",)),
        )

        expected = None
        for order in permutations(events):
            result = postprocess_frame_events(
                order,
                frame,
                onset,
                profile="balanced",
            )
            signature = tuple(
                (
                    item.start_frame,
                    item.end_frame,
                    item.pitch,
                    item.confidence,
                    item.lineage,
                )
                for item in result.events
            )
            if expected is None:
                expected = signature
            self.assertEqual(signature, expected)
            self.assertEqual(result.stats.nms_removed_count, 1)

        survivor = next(item for item in result.events if item.pitch == 60)
        self.assertTrue(result.automatic_actions_enabled)
        self.assertEqual(survivor.confidence, 0.90)
        self.assertEqual(survivor.lineage, ("lower", "winner"))

    def test_balanced_merges_only_continuous_weak_same_pitch_split(self) -> None:
        frame, onset = evidence()
        sustain(frame, 60, 5, 22)
        events = (
            FrameNoteEvent(5, 12, 60, 0.72, ("left",)),
            FrameNoteEvent(14, 22, 60, 0.64, ("right",)),
        )

        result = postprocess_frame_events(
            events,
            frame,
            onset,
            profile="balanced",
            onset_threshold=0.5,
            frame_threshold=0.3,
        )

        self.assertEqual(
            result.events,
            (FrameNoteEvent(5, 22, 60, 0.72, ("left", "right")),),
        )
        self.assertEqual(result.stats.automatic_merge_count, 1)
        merged_audit = next(
            item for item in result.audit if item.action == "merged"
        )
        self.assertIn("auto_merged", merged_audit.flags)

    def test_threshold_crossing_weak_plateau_can_merge(self) -> None:
        frame, onset = evidence()
        sustain(frame, 60, 5, 22)
        onset_peak(onset, 60, 5, 0.80)
        onset[11:18, 60 - MIDI_MIN] = 0.50
        onset_peak(onset, 60, 14, 0.52)
        events = (
            FrameNoteEvent(5, 12, 60, 0.72, ("left",)),
            FrameNoteEvent(14, 22, 60, 0.64, ("right",)),
        )

        result = postprocess_frame_events(
            events,
            frame,
            onset,
            profile="balanced",
            onset_threshold=0.50,
        )

        self.assertEqual(result.stats.automatic_merge_count, 1)
        self.assertEqual(result.events[0].lineage, ("left", "right"))

    def test_locally_prominent_threshold_crossing_reattack_is_kept(
        self,
    ) -> None:
        frame, onset = evidence()
        sustain(frame, 60, 5, 22)
        onset_peak(onset, 60, 5, 0.80)
        onset_peak(onset, 60, 14, 0.52)
        events = (
            FrameNoteEvent(5, 12, 60, 0.72, ("left",)),
            FrameNoteEvent(14, 22, 60, 0.64, ("right",)),
        )

        result = postprocess_frame_events(
            events,
            frame,
            onset,
            profile="balanced",
            onset_threshold=0.50,
        )

        self.assertEqual(result.events, events)
        self.assertEqual(result.stats.automatic_merge_count, 0)

    def test_strong_or_locally_prominent_reattacks_are_preserved(self) -> None:
        for peak in (0.7, 0.2):
            with self.subTest(peak=peak):
                frame, onset = evidence()
                sustain(frame, 60, 5, 22)
                onset_peak(onset, 60, 14, peak)
                events = (
                    FrameNoteEvent(5, 12, 60, 0.7, ("left",)),
                    FrameNoteEvent(14, 22, 60, 0.7, ("right",)),
                )

                result = postprocess_frame_events(
                    events,
                    frame,
                    onset,
                    profile="balanced",
                    onset_threshold=0.5,
                )

                self.assertEqual(len(result.events), 2)
                self.assertEqual(result.stats.automatic_merge_count, 0)

    def test_frame_inferred_reattack_is_preserved(self) -> None:
        frame, onset = evidence()
        sustain(frame, 60, 5, 22, 0.35)
        frame[14:22, 60 - MIDI_MIN] = 0.8
        events = (
            FrameNoteEvent(5, 12, 60, 0.7, ("left",)),
            FrameNoteEvent(14, 22, 60, 0.7, ("right",)),
        )

        result = postprocess_frame_events(
            events,
            frame,
            onset,
            profile="balanced",
        )

        self.assertEqual(len(result.events), 2)
        self.assertEqual(result.stats.automatic_merge_count, 0)

    def test_chord_onset_and_regular_repeats_block_merge(self) -> None:
        frame, onset = evidence()
        sustain(frame, 60, 0, 38)
        sustain(frame, 64, 14, 22)
        chord_events = (
            FrameNoteEvent(5, 12, 60, 0.7, ("left",)),
            FrameNoteEvent(14, 22, 60, 0.7, ("right",)),
            FrameNoteEvent(14, 22, 64, 0.7, ("chord",)),
        )
        chord = postprocess_frame_events(
            chord_events,
            frame,
            onset,
            profile="balanced",
        )
        self.assertEqual(
            len([item for item in chord.events if item.pitch == 60]),
            2,
        )

        repeat_events = (
            FrameNoteEvent(0, 6, 60, 0.7, ("one",)),
            FrameNoteEvent(8, 14, 60, 0.7, ("two",)),
            FrameNoteEvent(16, 22, 60, 0.7, ("three",)),
            FrameNoteEvent(24, 30, 60, 0.7, ("four",)),
        )
        repeated = postprocess_frame_events(
            repeat_events,
            frame,
            onset,
            profile="balanced",
        )
        self.assertEqual(len(repeated.events), 4)
        self.assertEqual(repeated.stats.automatic_merge_count, 0)

    def test_short_adjacent_pitch_trill_blocks_cross_segment_merge(
        self,
    ) -> None:
        frame, onset = evidence()
        sustain(frame, 60, 0, 18)
        sustain(frame, 62, 7, 10)
        events = (
            FrameNoteEvent(0, 8, 60, 0.7, ("c-left",)),
            # Starts outside the chord-onset radius of the second C.  The
            # intervening C-D-C contour itself must protect the reattack.
            FrameNoteEvent(7, 10, 62, 0.5, ("d-trill",)),
            FrameNoteEvent(10, 18, 60, 0.7, ("c-right",)),
        )

        result = postprocess_frame_events(
            events,
            frame,
            onset,
            profile="balanced",
        )

        self.assertEqual(
            len([event for event in result.events if event.pitch == 60]),
            2,
        )
        self.assertEqual(result.stats.automatic_merge_count, 0)
        trill_audit = next(
            item
            for item in result.audit
            if item.event.pitch == 62 and item.action == "kept"
        )
        self.assertIn("pitch_flicker", trill_audit.flags)

    def test_clean_hides_only_isolated_weak_severe_fragment(self) -> None:
        frame, onset = evidence()
        sustain(frame, 72, 30, 35, 0.2)
        weak = FrameNoteEvent(30, 35, 72, 0.20, ("artifact",))

        result = postprocess_frame_events(
            (weak,),
            frame,
            onset,
            profile="clean",
            onset_threshold=0.5,
        )

        self.assertEqual(result.events, ())
        self.assertEqual(result.suppressed, (weak,))
        self.assertEqual(result.stats.suppressed_count, 1)
        hidden = next(
            item for item in result.audit if item.action == "suppressed"
        )
        self.assertIn("clean_suppressed", hidden.flags)
        self.assertIn("severe_fragment", hidden.flags)

    def test_sequence_support_uses_one_eight_frame_gap_only(self) -> None:
        frame, onset = evidence()
        sustain(frame, 72, 0, 5, 0.2)
        sustain(frame, 72, 20, 25, 0.2)
        events = (
            FrameNoteEvent(0, 5, 72, 0.2, ("first",)),
            # The 15-frame silence exceeds sequence_max_gap_frames.  It must
            # not be expanded on both sides into an accidental 16-frame gate.
            FrameNoteEvent(20, 25, 72, 0.2, ("second",)),
        )

        result = postprocess_frame_events(
            events,
            frame,
            onset,
            profile="clean",
        )

        self.assertEqual(result.events, ())
        self.assertEqual(result.stats.suppressed_count, 2)

    def test_clean_keeps_strong_chord_and_sequence_supported_short_notes(
        self,
    ) -> None:
        frame, onset = evidence()
        for pitch, start, end in (
            (60, 5, 10),
            (64, 5, 10),
            (67, 20, 25),
            (69, 29, 34),
            (72, 45, 50),
        ):
            sustain(frame, pitch, start, end, 0.2)
        onset_peak(onset, 72, 45, 0.8)
        events = (
            FrameNoteEvent(5, 10, 60, 0.2, ("chord-a",)),
            FrameNoteEvent(5, 10, 64, 0.2, ("chord-b",)),
            FrameNoteEvent(20, 25, 67, 0.2, ("phrase-a",)),
            FrameNoteEvent(29, 34, 69, 0.2, ("phrase-b",)),
            FrameNoteEvent(45, 50, 72, 0.2, ("strong",)),
        )

        result = postprocess_frame_events(
            events,
            frame,
            onset,
            profile="clean",
            onset_threshold=0.5,
        )

        self.assertEqual(result.suppressed, ())
        self.assertEqual(len(result.events), len(events))

    def test_pitch_flicker_is_labeled_but_never_absorbed_or_suppressed(
        self,
    ) -> None:
        frame, onset = evidence()
        sustain(frame, 60, 4, 20, 0.7)
        sustain(frame, 61, 20, 23, 0.2)
        events = (
            FrameNoteEvent(4, 20, 60, 0.8, ("stable",)),
            FrameNoteEvent(20, 23, 61, 0.2, ("flicker",)),
        )

        result = postprocess_frame_events(
            events,
            frame,
            onset,
            profile="clean",
        )

        self.assertEqual(len(result.events), 2)
        flicker = next(
            item
            for item in result.audit
            if item.event.pitch == 61 and item.action == "kept"
        )
        self.assertIn("pitch_flicker", flicker.flags)

    def test_output_is_idempotent_and_versioned(self) -> None:
        frame, onset = evidence()
        sustain(frame, 60, 5, 22)
        original = (
            FrameNoteEvent(14, 22, 60, 0.64, ("right",)),
            FrameNoteEvent(5, 12, 60, 0.72, ("left",)),
        )
        first = postprocess_frame_events(
            original,
            frame,
            onset,
            profile="balanced",
        )
        second = postprocess_frame_events(
            first.events,
            frame,
            onset,
            profile="balanced",
        )

        self.assertEqual(second.events, first.events)
        self.assertEqual(first.version, POSTPROCESS_VERSION)

    def test_invalid_input_fails_before_any_cleanup(self) -> None:
        frame, onset = evidence()
        with self.assertRaisesRegex(ValueError, "unsupported cleanup profile"):
            postprocess_frame_events(
                (),
                frame,
                onset,
                profile="aggressive",  # type: ignore[arg-type]
            )
        with self.assertRaisesRegex(ValueError, "shapes must match"):
            postprocess_frame_events(
                (),
                frame,
                onset[:-1],
            )
        with self.assertRaisesRegex(ValueError, "exceed"):
            postprocess_frame_events(
                (FrameNoteEvent(70, 90, 60, 0.5),),
                frame,
                onset,
            )


if __name__ == "__main__":
    unittest.main()
