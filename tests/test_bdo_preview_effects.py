from __future__ import annotations

from unittest.mock import patch
import unittest

import numpy as np

from bdo_music_composer.audio.bdo_preview_effects import (
    MAX_EFFECT_TAIL_SECONDS,
    PREVIEW_DELAY_SECONDS,
    PreviewEffectProcessor,
    PreviewEffectSettings,
    preview_send_gain,
)


class PreviewEffectProcessorTests(unittest.TestCase):
    def test_send_gain_uses_authoring_range_without_mutating_wire_values(self) -> None:
        self.assertEqual(preview_send_gain(0), 0.0)
        self.assertEqual(preview_send_gain(25), 0.25)
        self.assertEqual(preview_send_gain(100), 1.0)
        self.assertEqual(preview_send_gain(255), 1.0)

    def test_disabled_processor_leaves_output_unchanged(self) -> None:
        processor = PreviewEffectProcessor(8_000)
        output = np.full((64, 2), 0.125, dtype=np.float32)
        silent = np.zeros_like(output)
        processor.process(output, silent, silent, silent, len(output))
        np.testing.assert_array_equal(
            output,
            np.full((64, 2), 0.125, dtype=np.float32),
        )

    def test_delay_send_produces_bounded_feedback_tail(self) -> None:
        rate = 8_000
        processor = PreviewEffectProcessor(rate)
        processor.configure(
            PreviewEffectSettings(delay_feedback=50),
            reverb_send=False,
            delay_send=True,
            chorus_send=False,
        )
        frames = round(rate * PREVIEW_DELAY_SECONDS) * 2 + 8
        source = np.zeros((frames, 2), dtype=np.float32)
        source[0] = 1.0
        output = np.zeros_like(source)
        silent = np.zeros_like(source)
        processor.process(output, silent, source, silent, frames)

        first_echo = round(rate * PREVIEW_DELAY_SECONDS)
        self.assertGreater(float(output[first_echo, 0]), 0.4)
        self.assertGreater(float(output[first_echo * 2, 0]), 0.1)
        self.assertLessEqual(
            processor.tail_frames(),
            round(rate * MAX_EFFECT_TAIL_SECONDS),
        )

    def test_reset_clears_delay_and_modulation_state(self) -> None:
        processor = PreviewEffectProcessor(8_000)
        processor.configure(
            PreviewEffectSettings(50, 50, 30, 60, 40),
            reverb_send=True,
            delay_send=True,
            chorus_send=True,
        )
        impulse = np.zeros((512, 2), dtype=np.float32)
        impulse[0] = 1.0
        output = np.zeros_like(impulse)
        processor.process(output, impulse, impulse, impulse, len(impulse))
        processor.reset()

        silent = np.zeros_like(impulse)
        after_reset = np.zeros_like(impulse)
        processor.process(
            after_reset,
            silent,
            silent,
            silent,
            len(silent),
        )
        self.assertTrue(np.allclose(after_reset, 0.0))

    def test_hot_process_path_does_not_allocate_numpy_buffers(self) -> None:
        processor = PreviewEffectProcessor(8_000)
        processor.configure(
            PreviewEffectSettings(50, 50, 30, 60, 40),
            reverb_send=True,
            delay_send=True,
            chorus_send=True,
        )
        output = np.zeros((128, 2), dtype=np.float32)
        source = np.zeros_like(output)
        source[0] = 0.5
        with (
            patch(
                "bdo_music_composer.audio.bdo_preview_effects.np.empty",
                side_effect=AssertionError("callback allocation"),
            ),
            patch(
                "bdo_music_composer.audio.bdo_preview_effects.np.zeros",
                side_effect=AssertionError("callback allocation"),
            ),
            patch(
                "bdo_music_composer.audio.bdo_preview_effects.np.asarray",
                side_effect=AssertionError("callback allocation"),
            ),
            patch(
                "bdo_music_composer.audio.bdo_preview_effects.np.arange",
                side_effect=AssertionError("callback allocation"),
            ),
            patch(
                "bdo_music_composer.audio.bdo_preview_effects.math.sin",
                side_effect=AssertionError("per-frame scalar modulation"),
            ),
        ):
            processor.process(output, source, source, source, len(output))
        self.assertTrue(np.isfinite(output).all())

    def test_processing_is_block_size_invariant_and_feedback_stays_finite(self) -> None:
        settings = PreviewEffectSettings(75, 60, 0, 70, 55)
        frames = 4_096
        source = np.zeros((frames, 2), dtype=np.float32)
        source[0] = (0.6, -0.4)
        source[777] = (-0.2, 0.3)

        whole = PreviewEffectProcessor(8_000)
        whole.configure(
            settings,
            reverb_send=True,
            delay_send=True,
            chorus_send=True,
        )
        whole_output = np.zeros_like(source)
        whole.process(
            whole_output,
            source,
            source,
            source,
            frames,
        )

        chunked = PreviewEffectProcessor(8_000)
        chunked.configure(
            settings,
            reverb_send=True,
            delay_send=True,
            chorus_send=True,
        )
        chunked_output = np.zeros_like(source)
        start = 0
        for size in (17, 64, 257, 31, 1_024, 503, 2_200):
            if start >= frames:
                break
            end = min(frames, start + size)
            chunked.process(
                chunked_output[start:end],
                source[start:end],
                source[start:end],
                source[start:end],
                end - start,
            )
            start = end
        if start < frames:
            chunked.process(
                chunked_output[start:],
                source[start:],
                source[start:],
                source[start:],
                frames - start,
            )

        self.assertTrue(np.isfinite(whole_output).all())
        np.testing.assert_allclose(
            chunked_output,
            whole_output,
            rtol=0.0,
            atol=1.0e-7,
        )


if __name__ == "__main__":
    unittest.main()
