from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from bdo_midi import BDO_INSTRUMENTS, Note
from bdo_realtime_audio import BdoRealtimeAudioEngine


def track_with(notes: list[Note], *, percussion: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        track_id=7,
        notes=notes,
        bdo_instrument_id=0x0D if percussion else 0x0B,
        is_percussion=percussion,
        duration_scale=1.0,
        volume_scale=1.0,
        bdo_track_volume=70,
        articulation_type=None,
    )


class ProceduralPreviewTests(unittest.TestCase):
    def test_every_logical_instrument_has_a_bounded_file_free_voice(self) -> None:
        engine = BdoRealtimeAudioEngine(None, {})
        percussion_ids = {0x04, 0x05, 0x0D}
        tracks = []
        for track_id, instrument_id in enumerate(
            sorted(set(BDO_INSTRUMENTS.values()))
        ):
            track = track_with(
                [Note(60, 96, float(track_id * 100), 250.0, 0)],
                percussion=instrument_id in percussion_ids,
            )
            track.track_id = track_id
            track.bdo_instrument_id = instrument_id
            tracks.append(track)

        with patch.object(
            Path,
            "read_text",
            side_effect=AssertionError("built-in voices must not read files"),
        ):
            events, cache, cache_bytes, *_rest = (
                engine._prepare_procedural_project(
                    tracks, 0.0, 0, 0, None
                )
            )

        self.assertEqual(
            {event.instrument_id for event in events},
            set(BDO_INSTRUMENTS.values()),
        )
        self.assertEqual(len(cache), len(set(BDO_INSTRUMENTS.values())))
        self.assertLess(cache_bytes, 32 * 1024 * 1024)

    def test_instrument_families_have_distinct_bounded_timbres(self) -> None:
        engine = BdoRealtimeAudioEngine(None, {})
        piano = engine._procedural_sample(0x11, percussion=False)
        flute = engine._procedural_sample(0x0B, percussion=False)
        violin = engine._procedural_sample(0x12, percussion=False)

        self.assertEqual(piano.pcm.shape[1], 2)
        self.assertFalse(piano.pcm.flags.writeable)
        self.assertFalse(np.allclose(piano.pcm[:1000], flute.pcm[:1000]))
        self.assertFalse(np.allclose(flute.pcm[:1000], violin.pcm[:1000]))
        for sample in (piano, flute, violin):
            self.assertTrue(np.isfinite(sample.pcm).all())
            self.assertLessEqual(float(np.max(np.abs(sample.pcm))), 0.21)

    def test_generic_preview_preserves_pitch_timing_and_needs_no_files(self) -> None:
        engine = BdoRealtimeAudioEngine(None, {})
        track = track_with([
            Note(69, 100, 0.0, 400.0, 0),
            Note(81, 80, 500.0, 300.0, 0),
        ])

        with patch.object(
            Path,
            "read_text",
            side_effect=AssertionError("fallback must not read files"),
        ):
            events, cache, cache_bytes, unverified, duration = (
                engine._prepare_procedural_project(
                    [track], 0.0, 0, 0, None
                )
            )

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].frame, 0)
        self.assertEqual(events[1].frame, round(engine._sample_rate * 0.5))
        self.assertAlmostEqual(events[0].ratio, 1.0)
        self.assertAlmostEqual(events[1].ratio, 2.0)
        self.assertGreater(duration, events[1].frame)
        self.assertEqual(len(cache), 1)
        self.assertEqual(cache_bytes, next(iter(cache.values())).pcm.nbytes)
        self.assertFalse(next(iter(cache.values())).pcm.flags.writeable)
        self.assertTrue(any("generic MIDI fallback" in item for item in unverified))

    def test_generic_percussion_is_bounded_non_looping_noise(self) -> None:
        engine = BdoRealtimeAudioEngine(None, {})
        events, cache, cache_bytes, _unverified, _duration = (
            engine._prepare_procedural_project(
                [track_with([Note(48, 127, 0.0, 80.0, 99)], percussion=True)],
                0.0,
                0,
                0,
                None,
            )
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].ratio, 1.0)
        self.assertEqual(events[0].loop_end_frame, 0)
        self.assertLess(cache_bytes, 1024 * 1024)
        sample = next(iter(cache.values()))
        self.assertTrue(np.isfinite(sample.pcm).all())
        self.assertGreater(float(np.max(np.abs(sample.pcm))), 0.01)

    def test_drum_pieces_are_distinct_and_handpan_remains_pitched(self) -> None:
        engine = BdoRealtimeAudioEngine(None, {})
        drum_track = track_with(
            [
                Note(48, 120, 0.0, 80.0, 99),
                Note(61, 110, 100.0, 100.0, 99),
            ],
            percussion=True,
        )
        events, cache, *_rest = engine._prepare_procedural_project(
            [drum_track], 0.0, 0, 0, None
        )
        self.assertEqual(len(cache), 2)
        self.assertEqual([event.ratio for event in events], [1.0, 1.0])
        self.assertFalse(
            np.allclose(events[0].sample.pcm[:1000], events[1].sample.pcm[:1000])
        )

        handpan = track_with(
            [Note(57, 100, 0.0, 300.0, 0), Note(69, 100, 400.0, 300.0, 0)]
        )
        handpan.bdo_instrument_id = 0x13
        handpan.is_percussion = False
        handpan_events, handpan_cache, *_rest = engine._prepare_procedural_project(
            [handpan], 0.0, 0, 0, None
        )
        self.assertEqual(len(handpan_cache), 1)
        self.assertAlmostEqual(
            handpan_events[1].ratio / handpan_events[0].ratio,
            2.0,
        )
        self.assertTrue(all(event.loop_end_frame == 0 for event in handpan_events))


if __name__ == "__main__":
    unittest.main()
