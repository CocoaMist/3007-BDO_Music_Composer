from __future__ import annotations

from contextlib import redirect_stderr
import io
from pathlib import Path
import tempfile
import unittest
import wave

from bdo_music_composer.audio.reference_audio_format import (
    INVALID_REFERENCE_AUDIO_SOURCE,
    MISMATCHED_REFERENCE_AUDIO_SOURCE,
    ReferenceAudioFormatError,
    detect_reference_audio_format,
    validate_reference_audio_file,
)
from bdo_music_composer.transcription import bdo_transcription
from bdo_music_composer.ui.transcription.bdo_spectrogram_qt import (
    SpectrogramTileController,
)


def _write_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8_000)
        output.writeframes(b"\0\0" * 800)


def _write_two_frame_mp3_probe(path: Path) -> None:
    header = b"\xff\xfb\x90\x64"
    frame_length = 144 * 128_000 // 44_100
    frame = header + bytes(frame_length - len(header))
    path.write_bytes(frame + frame)


class ReferenceAudioFormatTests(unittest.TestCase):
    def test_detects_supported_containers_from_content(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            wav_path = root / "reference.wav"
            mp3_path = root / "reference.mp3"
            _write_wav(wav_path)
            _write_two_frame_mp3_probe(mp3_path)

            self.assertEqual(detect_reference_audio_format(wav_path), "wav")
            self.assertEqual(detect_reference_audio_format(mp3_path), "mp3")
            self.assertEqual(validate_reference_audio_file(wav_path), "wav")
            self.assertEqual(validate_reference_audio_file(mp3_path), "mp3")

    def test_rejects_junk_and_extension_mismatch_with_safe_copy(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            junk_path = root / "download.mp3"
            junk_path.write_bytes(b"<html>not audio</html>" + bytes(70_000))
            with self.assertRaisesRegex(
                ReferenceAudioFormatError,
                "WAV/MP3",
            ) as junk_error:
                validate_reference_audio_file(junk_path)
            self.assertEqual(
                str(junk_error.exception),
                INVALID_REFERENCE_AUDIO_SOURCE,
            )
            self.assertNotIn(str(root), str(junk_error.exception))

            mismatch_path = root / "renamed.mp3"
            _write_wav(mismatch_path)
            with self.assertRaises(ReferenceAudioFormatError) as mismatch_error:
                validate_reference_audio_file(mismatch_path)
            self.assertEqual(
                str(mismatch_error.exception),
                MISMATCHED_REFERENCE_AUDIO_SOURCE,
            )

    def test_analysis_rejects_junk_before_native_mpg_decoder(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            junk_path = root / "broken.mp3"
            junk_path.write_bytes(bytes(70_000))
            workspace = root / "workspace"
            workspace.mkdir()
            native_stderr = io.StringIO()
            with redirect_stderr(native_stderr):
                with self.assertRaisesRegex(
                    bdo_transcription.TranscriptionError,
                    "WAV/MP3",
                ):
                    bdo_transcription._stream_decode_reference_audio(
                        junk_path,
                        workspace,
                        target_sample_rate=22_050,
                    )
            self.assertEqual(native_stderr.getvalue(), "")

            controller = SpectrogramTileController()
            with self.assertRaises(ReferenceAudioFormatError):
                controller.begin_source(junk_path, duration_ms=1_000.0)
            controller.close()


if __name__ == "__main__":
    unittest.main()
