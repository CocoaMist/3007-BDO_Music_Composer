from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from bdo_transcription import (
    TranscriptionCandidate,
    TranscriptionResult,
    _candidates_from_basic_pitch,
    _load_cached_result,
    _write_cached_result,
    load_transcription_evidence,
    prune_transcription_cache,
    transcription_backend_message,
    transcription_backend_status,
    transcription_cache_key,
    transcribe_reference_audio,
)


class BdoTranscriptionTests(unittest.TestCase):
    def test_missing_backend_has_source_and_frozen_specific_guidance(self) -> None:
        with patch(
            "bdo_transcription.importlib.util.find_spec",
            return_value=None,
        ):
            available, source_message = transcription_backend_status()
            self.assertFalse(available)
            self.assertIn("install_transcription.ps1", source_message)
            with patch("bdo_transcription.sys.frozen", True, create=True):
                frozen_message = transcription_backend_message()
            self.assertIn("Standard", frozen_message)
            self.assertNotIn("install_transcription.ps1", frozen_message)

    def test_basic_pitch_notes_become_non_authoritative_candidates(self) -> None:
        notes = [
            SimpleNamespace(pitch=60, velocity=96, start=0.1, end=0.5),
            SimpleNamespace(pitch=64, velocity=80, start=0.6, end=1.25),
        ]
        midi = SimpleNamespace(instruments=[SimpleNamespace(notes=notes)])
        result = _candidates_from_basic_pitch(
            midi,
            [
                (0.1, 0.5, 60, 0.42, None),
                (0.6, 1.25, 64, 0.91, None),
            ],
        )
        self.assertEqual(
            result[0],
            TranscriptionCandidate(60, 96, 100.0, 400.0, 0.42),
        )
        self.assertEqual(result[1].source, "basic-pitch")
        self.assertAlmostEqual(result[1].confidence, 0.91)

    def test_same_pitch_events_are_matched_once_by_time(self) -> None:
        notes = [
            SimpleNamespace(pitch=60, velocity=80, start=0.1, end=0.3),
            SimpleNamespace(pitch=60, velocity=100, start=0.8, end=1.2),
        ]
        midi = SimpleNamespace(instruments=[SimpleNamespace(notes=notes)])
        result = _candidates_from_basic_pitch(
            midi,
            [
                (0.8, 1.2, 60, 0.87, None),
                (0.1, 0.3, 60, 0.41, None),
            ],
        )
        self.assertEqual(
            [round(candidate.confidence, 2) for candidate in result],
            [0.41, 0.87],
        )

    def test_cache_roundtrip_uses_memory_mapped_evidence_and_invalidates(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            audio = root / "reference.wav"
            audio.write_bytes(b"first")
            cache_root = root / "cache"
            cache_key = transcription_cache_key(audio)
            result = TranscriptionResult(
                (TranscriptionCandidate(69, 88, 10.0, 500.0, 0.75),),
                cache_key,
                ("frame", "onset", "contour"),
            )
            output = {
                # The real Basic Pitch 0.4 ONNX output calls this matrix
                # ``note``; the cache exposes the stable public name ``frame``.
                "note": np.ones((12, 88), dtype=np.float32),
                "onset": np.ones((12, 88), dtype=np.float32) * 0.5,
                "contour": np.ones((12, 264), dtype=np.float32) * 0.25,
            }
            _write_cached_result(result, output, cache_root)

            cached = _load_cached_result(audio, cache_root)
            self.assertIsNotNone(cached)
            self.assertTrue(cached.cache_hit)
            self.assertEqual(cached.candidates, result.candidates)
            evidence = load_transcription_evidence(
                cache_key, "contour", cache_root=cache_root
            )
            self.assertIsInstance(evidence, np.memmap)
            self.assertEqual(evidence.shape, (12, 264))
            evidence._mmap.close()
            del evidence
            frame = load_transcription_evidence(
                cache_key, "frame", cache_root=cache_root
            )
            self.assertIsInstance(frame, np.memmap)
            self.assertEqual(frame.shape, (12, 88))
            frame._mmap.close()
            del frame
            with patch(
                "bdo_transcription.transcription_backend_status",
                return_value=(False, "backend unavailable"),
            ):
                cache_only = transcribe_reference_audio(
                    audio,
                    cache_root=cache_root,
                )
            self.assertTrue(cache_only.cache_hit)
            self.assertEqual(cache_only.candidates, result.candidates)

            audio.write_bytes(b"changed-size")
            self.assertIsNone(_load_cached_result(audio, cache_root))

    def test_broken_manifest_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            audio = root / "reference.wav"
            audio.write_bytes(b"audio")
            folder = root / "cache" / transcription_cache_key(audio)
            folder.mkdir(parents=True)
            (folder / "manifest.json").write_text(
                json.dumps({"version": 999}),
                encoding="utf-8",
            )
            self.assertIsNone(_load_cached_result(audio, root / "cache"))

    def test_cache_pruning_is_bounded_and_ignores_unknown_entries(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            cache_root = Path(folder_name)
            keys = ("0" * 24, "1" * 24, "2" * 24)
            for index, key in enumerate(keys):
                folder = cache_root / key
                folder.mkdir()
                (folder / "evidence.bin").write_bytes(b"x" * 10)
                timestamp = 1_700_000_000 + index
                os.utime(folder, (timestamp, timestamp))
            unknown = cache_root / "do-not-delete"
            unknown.mkdir()
            (unknown / "user.bin").write_bytes(b"user")

            removed_entries, removed_bytes = prune_transcription_cache(
                cache_root,
                max_entries=1,
                max_bytes=15,
                keep_keys=(keys[2],),
            )

            self.assertEqual(removed_entries, 2)
            self.assertEqual(removed_bytes, 20)
            self.assertFalse((cache_root / keys[0]).exists())
            self.assertFalse((cache_root / keys[1]).exists())
            self.assertTrue((cache_root / keys[2]).is_dir())
            self.assertTrue(unknown.is_dir())

    def test_evidence_loader_rejects_non_cache_keys(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            self.assertIsNone(
                load_transcription_evidence(
                    "../outside",
                    "frame",
                    cache_root=Path(folder_name),
                )
            )


if __name__ == "__main__":
    unittest.main()
