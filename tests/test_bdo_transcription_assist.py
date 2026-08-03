from __future__ import annotations

from dataclasses import dataclass
import json
import unittest

from bdo_music_composer.transcription.bdo_transcription_assist import (
    KeyReviewOverride,
    LockedChordReview,
    ManualVoiceGroupReview,
    TranscriptionAssistReviewState,
    candidate_overlap_score,
    isolate_assist_review_for_audio,
    recover_assist_review,
)


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    pitch: int
    start_ms: float
    duration_ms: float


@dataclass(frozen=True)
class Segment:
    segment_id: str
    start_audio_ms: float
    end_audio_ms: float


@dataclass(frozen=True)
class Group:
    group_id: str
    candidate_ids: tuple[str, ...]
    start_audio_ms: float
    end_audio_ms: float
    role: str = "harmony"


class TranscriptionAssistReviewTests(unittest.TestCase):
    def state(self, fingerprint: str = "a" * 64) -> TranscriptionAssistReviewState:
        return TranscriptionAssistReviewState(
            audio_fingerprint=fingerprint,
            key_override=KeyReviewOverride(0, "major"),
            locked_chord_segments=(
                LockedChordReview(
                    "chord-review-b",
                    "auto-b",
                    1000.0,
                    2000.0,
                    9,
                    "min7",
                    0,
                    ("old-b", "old-a", "old-a"),
                ),
                LockedChordReview(
                    "chord-review-a",
                    "auto-a",
                    0.0,
                    900.0,
                    0,
                    "major",
                    4,
                    ("old-a",),
                ),
            ),
            voice_groups=(
                ManualVoiceGroupReview(
                    "voice-review-b",
                    "voice-old-b",
                    ("old-b",),
                    1000.0,
                    2000.0,
                    "bass",
                    120,
                ),
                ManualVoiceGroupReview(
                    "voice-review-a",
                    "voice-old-a",
                    ("old-a",),
                    0.0,
                    900.0,
                    "melody",
                    110,
                ),
            ),
        )

    def test_payload_round_trip_is_stable_lightweight_and_path_free(self) -> None:
        state = self.state()
        payload = state.to_payload()
        self.assertEqual(
            [item["review_id"] for item in payload["locked_chord_segments"]],
            ["chord-review-a", "chord-review-b"],
        )
        self.assertEqual(
            [item["review_id"] for item in payload["voice_groups"]],
            ["voice-review-a", "voice-review-b"],
        )
        self.assertEqual(
            payload["locked_chord_segments"][1]["candidate_ids"],
            ["old-a", "old-b"],
        )
        restored = TranscriptionAssistReviewState.from_payload(
            json.loads(json.dumps(payload))
        )
        self.assertEqual(restored, state)
        flattened = json.dumps(payload, sort_keys=True)
        for forbidden in (
            "audio_path",
            "sample_path",
            "feature_matrix",
            "frame_matrix",
            "evidence_layers",
            "waveform",
        ):
            self.assertNotIn(forbidden, flattened)

    def test_bad_payload_fails_closed_without_rejecting_valid_neighbors(self) -> None:
        state = TranscriptionAssistReviewState.from_payload(
            {
                "version": 1,
                "audio_fingerprint": r"D:\private\song.wav",
                "key_override": {"root_pc": 99, "mode": "major"},
                "locked_chord_segments": [
                    {
                        "review_id": "bad",
                        "segment_id": "bad",
                        "start_audio_ms": float("nan"),
                        "end_audio_ms": 10,
                        "root_pc": 0,
                        "quality": "major",
                    },
                    {
                        "review_id": "good",
                        "segment_id": "good",
                        "start_audio_ms": 0,
                        "end_audio_ms": 100,
                        "root_pc": 0,
                        "quality": "major",
                    },
                ],
                "voice_groups": [
                    {
                        "review_id": "bad",
                        "candidate_ids": "not-a-list",
                        "start_audio_ms": 0,
                        "end_audio_ms": 100,
                    }
                ],
            }
        )
        self.assertEqual(state.audio_fingerprint, "")
        self.assertIsNone(state.key_override)
        self.assertEqual(len(state.locked_chord_segments), 1)
        self.assertTrue(state.locked_chord_segments[0].orphaned)
        self.assertEqual(state.voice_groups, ())
        self.assertEqual(
            TranscriptionAssistReviewState.from_payload({"version": 99}),
            TranscriptionAssistReviewState(),
        )

    def test_duplicate_review_ids_decode_independently_of_payload_order(self) -> None:
        first = LockedChordReview(
            "same", "later", 100.0, 200.0, 0, "major"
        )
        second = LockedChordReview(
            "same", "earlier", 0.0, 100.0, 9, "minor"
        )
        left = TranscriptionAssistReviewState(
            audio_fingerprint="fp",
            locked_chord_segments=(first, second),
        )
        right = TranscriptionAssistReviewState(
            audio_fingerprint="fp",
            locked_chord_segments=(second, first),
        )
        self.assertEqual(left, right)
        self.assertEqual(left.to_payload(), right.to_payload())

    def test_overlapping_chord_reviews_are_orphaned_fail_closed(self) -> None:
        state = TranscriptionAssistReviewState(
            audio_fingerprint="f" * 64,
            locked_chord_segments=(
                LockedChordReview(
                    "first",
                    "first-segment",
                    0.0,
                    1000.0,
                    0,
                    "major",
                ),
                LockedChordReview(
                    "overlap",
                    "overlap-segment",
                    500.0,
                    1500.0,
                    7,
                    "7",
                ),
                LockedChordReview(
                    "later",
                    "later-segment",
                    1500.0,
                    2000.0,
                    9,
                    "minor",
                ),
            ),
        )
        self.assertEqual(
            tuple(item.review_id for item in state.active_chord_segments),
            ("first", "later"),
        )
        overlap = next(
            item
            for item in state.locked_chord_segments
            if item.review_id == "overlap"
        )
        self.assertTrue(overlap.orphaned)

    def test_audio_identity_change_orphans_every_decision(self) -> None:
        state = self.state()
        self.assertIs(isolate_assist_review_for_audio(state, "a" * 64), state)
        isolated = isolate_assist_review_for_audio(state, "b" * 64)
        self.assertEqual(isolated.audio_fingerprint, "b" * 64)
        self.assertIsNone(isolated.active_key_override)
        self.assertEqual(isolated.active_chord_segments, ())
        self.assertEqual(isolated.active_voice_groups, ())
        self.assertTrue(isolated.has_orphaned_reviews)
        self.assertTrue(isolated.key_override.orphaned)
        self.assertTrue(
            all(item.orphaned for item in isolated.locked_chord_segments)
        )
        self.assertTrue(all(item.orphaned for item in isolated.voice_groups))

    def test_candidate_overlap_uses_stable_ids_or_conservative_geometry(self) -> None:
        old = (
            Candidate("old-a", 60, 0.0, 400.0),
            Candidate("old-b", 64, 500.0, 400.0),
        )
        same_geometry = (
            Candidate("new-a", 60, 2.0, 398.0),
            Candidate("new-b", 64, 505.0, 395.0),
        )
        far_away = (
            Candidate("new-a", 60, 5000.0, 400.0),
            Candidate("new-b", 64, 5500.0, 400.0),
        )
        self.assertEqual(candidate_overlap_score(old, old), 1.0)
        self.assertEqual(candidate_overlap_score(old, same_geometry), 1.0)
        self.assertEqual(candidate_overlap_score(old, far_away), 0.0)

    def test_same_audio_candidate_revision_can_force_review_reanchoring(
        self,
    ) -> None:
        state = TranscriptionAssistReviewState(
            audio_fingerprint="same-audio",
            voice_groups=(
                ManualVoiceGroupReview(
                    "review",
                    "old-group",
                    ("old-a", "old-b"),
                    0.0,
                    1000.0,
                    "primary_melody",
                    11,
                ),
            ),
        )
        old_candidates = (
            Candidate("old-a", 60, 50.0, 350.0),
            Candidate("old-b", 64, 500.0, 350.0),
        )
        new_candidates = (
            Candidate("new-a", 60, 55.0, 345.0),
            Candidate("new-b", 64, 505.0, 350.0),
        )
        result = recover_assist_review(
            state,
            audio_fingerprint="same-audio",
            old_candidates=old_candidates,
            new_candidates=new_candidates,
            voice_groups=(
                Group(
                    "new-group",
                    ("new-a", "new-b"),
                    0.0,
                    1020.0,
                ),
            ),
            force_reanchor=True,
        )
        self.assertEqual(
            result.recovered_voice_review_ids, ("review",)
        )
        recovered = result.state.voice_groups[0]
        self.assertEqual(recovered.group_id, "new-group")
        self.assertEqual(recovered.candidate_ids, ("new-a", "new-b"))
        self.assertEqual(recovered.confirmed_instrument_id, 11)

    def test_recovery_requires_candidate_and_time_overlap_and_preserves_human_values(
        self,
    ) -> None:
        state = TranscriptionAssistReviewState(
            audio_fingerprint="old-fingerprint",
            key_override=KeyReviewOverride(2, "minor", manual=True, locked=True),
            locked_chord_segments=(
                LockedChordReview(
                    "chord-review",
                    "old-segment",
                    0.0,
                    1000.0,
                    2,
                    "min7",
                    9,
                    ("old-a", "old-b"),
                ),
                LockedChordReview(
                    "orphan-chord",
                    "old-orphan",
                    3000.0,
                    4000.0,
                    7,
                    "major",
                    candidate_ids=("old-c",),
                ),
            ),
            voice_groups=(
                ManualVoiceGroupReview(
                    "voice-review",
                    "old-voice",
                    ("old-a", "old-b"),
                    0.0,
                    1000.0,
                    "bass",
                    321,
                ),
            ),
        )
        old_candidates = (
            Candidate("old-a", 50, 50.0, 350.0),
            Candidate("old-b", 57, 500.0, 350.0),
        )
        new_candidates = (
            Candidate("new-a", 50, 55.0, 345.0),
            Candidate("new-b", 57, 505.0, 350.0),
        )
        result = recover_assist_review(
            state,
            audio_fingerprint="new-fingerprint",
            old_candidates=old_candidates,
            new_candidates=new_candidates,
            chord_segments=(
                Segment("new-segment", 0.0, 1020.0),
                Segment("far-segment", 6900.0, 7500.0),
            ),
            voice_groups=(
                Group("new-voice", ("new-a", "new-b"), 0.0, 1020.0),
            ),
        )
        self.assertTrue(result.key_recovered)
        self.assertEqual(result.recovered_chord_review_ids, ("chord-review",))
        self.assertEqual(result.recovered_voice_review_ids, ("voice-review",))
        self.assertEqual(result.orphaned_chord_review_ids, ("orphan-chord",))

        recovered_chord = result.state.locked_chord_segments[0]
        self.assertEqual(recovered_chord.review_id, "chord-review")
        self.assertEqual(recovered_chord.segment_id, "new-segment")
        self.assertEqual(recovered_chord.root_pc, 2)
        self.assertEqual(recovered_chord.quality, "min7")
        self.assertEqual(recovered_chord.bass_pc, 9)
        self.assertFalse(recovered_chord.orphaned)

        recovered_voice = result.state.voice_groups[0]
        self.assertEqual(recovered_voice.group_id, "new-voice")
        self.assertEqual(recovered_voice.role, "bass")
        self.assertEqual(recovered_voice.confirmed_instrument_id, 321)
        self.assertFalse(recovered_voice.orphaned)

    def test_time_overlap_alone_never_silently_recovers(self) -> None:
        state = TranscriptionAssistReviewState(
            audio_fingerprint="old",
            locked_chord_segments=(
                LockedChordReview(
                    "review",
                    "old-segment",
                    0.0,
                    1000.0,
                    0,
                    "major",
                    candidate_ids=("old",),
                ),
            ),
        )
        result = recover_assist_review(
            state,
            audio_fingerprint="new",
            old_candidates=(Candidate("old", 60, 100.0, 200.0),),
            new_candidates=(Candidate("new", 72, 100.0, 200.0),),
            chord_segments=(Segment("same-time", 0.0, 1000.0),),
        )
        self.assertEqual(result.recovered_chord_review_ids, ())
        self.assertEqual(result.orphaned_chord_review_ids, ("review",))
        self.assertTrue(result.state.locked_chord_segments[0].orphaned)

    def test_manual_n_chord_normalises_root_and_bass(self) -> None:
        value = LockedChordReview(
            "",
            "segment",
            0.0,
            100.0,
            3,
            "N",
            7,
        )
        self.assertTrue(value.review_id.startswith("chord-"))
        self.assertIsNone(value.root_pc)
        self.assertIsNone(value.bass_pc)


if __name__ == "__main__":
    unittest.main()
