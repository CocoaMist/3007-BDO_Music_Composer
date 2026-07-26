from __future__ import annotations

import json
import math
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import wave

import bdo_transcription_timbre as timbre
from bdo_transcription import TranscriptionCandidate
from bdo_transcription_instruments import TimbreFeatureProfile, VoiceGroup


def _feature_row(seed: float = 1.0) -> dict[str, float]:
    return {
        name: float(seed + index / 100.0)
        for index, name in enumerate(timbre._FEATURE_NAMES)
    }


def _write_sample_map(
    path: Path,
    banks: dict[str, list[dict[str, object]]],
) -> None:
    path.write_text(
        json.dumps({"format": 1, "banks": banks}, ensure_ascii=False),
        encoding="utf-8",
    )


def _make_empty_samples(
    audio_root: Path,
    bank: str,
    source_ids: range | list[int],
) -> list[dict[str, object]]:
    bank_root = audio_root / "乐器_WAV" / bank
    bank_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for source_id in source_ids:
        (bank_root / f"{source_id}.wav").write_bytes(b"sample-" + str(source_id).encode())
        rows.append(
            {
                "source_id": source_id,
                "root_note": 36 + (source_id % 49),
                "velocity_min": (source_id % 4) * 32,
                "velocity_max": min(127, (source_id % 4) * 32 + 31),
                # Historical absolute paths are deliberately non-authoritative.
                "wav_path": f"C:\\private\\game\\{source_id}.wav",
                "wav_exists": True,
            }
        )
    return rows


def _candidate(
    candidate_id: str,
    pitch: int,
    start_ms: float,
    duration_ms: float = 160.0,
    confidence: float = 0.9,
) -> TranscriptionCandidate:
    return TranscriptionCandidate(
        pitch,
        100,
        start_ms,
        duration_ms,
        confidence,
        candidate_id=candidate_id,
    )


def _group(
    group_id: str,
    candidate_ids: tuple[str, ...],
    start_ms: float,
    end_ms: float,
) -> VoiceGroup:
    return VoiceGroup(
        group_id,
        candidate_ids,
        start_ms,
        end_ms,
        "primary_melody",
        0.9,
    )


class TimbreProfileCacheTests(unittest.TestCase):
    def test_representatives_are_deterministic_bounded_and_cache_is_path_free(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio_root = root / "audio"
            bank = "midi_instrument_07_piano"
            rows = _make_empty_samples(audio_root, bank, list(range(40)))
            map_path = root / "map.json"
            cache = root / "cache"
            _write_sample_map(map_path, {bank: list(reversed(rows))})

            def fake_extract(path: Path) -> dict[str, float]:
                return _feature_row(float(path.stem))

            with patch.object(
                timbre, "_extract_file_features", side_effect=fake_extract
            ) as extract:
                first = timbre.load_or_build_timbre_profile_index(
                    map_path, audio_root, cache_dir=cache
                )

            self.assertEqual(extract.call_count, 32)
            self.assertFalse(first.cache_hit)
            profile = first.profile_for_instrument(0x07)
            self.assertIsNotNone(profile)
            assert profile is not None
            self.assertEqual(profile.sample_count, 32)
            self.assertLessEqual(len(first.pitch_profiles), 32)
            self.assertTrue(first.pitch_profiles)
            nearest = first.nearest_pitch_profile(0x07, 60)
            self.assertIsNotNone(nearest)
            assert nearest is not None
            self.assertIn(nearest[0], range(36, 76))
            self.assertLessEqual(
                first.estimated_size_bytes, timbre.PROFILE_INDEX_MEMORY_LIMIT
            )

            with patch.object(
                timbre,
                "_extract_file_features",
                side_effect=AssertionError("cache hit must not decode audio"),
            ):
                second = timbre.load_or_build_timbre_profile_index(
                    map_path, audio_root, cache_dir=cache
                )

            self.assertTrue(second.cache_hit)
            self.assertEqual(first.cache_key, second.cache_key)
            self.assertEqual(first.profiles, second.profiles)
            self.assertEqual(first.pitch_profiles, second.pitch_profiles)
            self.assertEqual(
                first.as_mapping().pitch_profiles,
                second.as_mapping().pitch_profiles,
            )
            manifest = (
                cache / first.cache_key / "manifest.json"
            ).read_text(encoding="ascii")
            self.assertNotIn(str(root), manifest)
            self.assertNotIn("private", manifest.casefold())
            self.assertNotIn("wav_path", manifest)

    def test_content_change_invalidates_cache_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio_root = root / "audio"
            bank = "midi_instrument_01_flute"
            rows = _make_empty_samples(audio_root, bank, [1, 2])
            map_path = root / "map.json"
            cache = root / "cache"
            _write_sample_map(map_path, {bank: rows})
            with patch.object(
                timbre, "_extract_file_features", return_value=_feature_row()
            ):
                first = timbre.load_or_build_timbre_profile_index(
                    map_path, audio_root, cache_dir=cache
                )
            (audio_root / "乐器_WAV" / bank / "1.wav").write_bytes(b"changed")
            with patch.object(
                timbre, "_extract_file_features", return_value=_feature_row()
            ):
                second = timbre.load_or_build_timbre_profile_index(
                    map_path, audio_root, cache_dir=cache
                )
            self.assertNotEqual(first.cache_key, second.cache_key)

    def test_corrupt_manifest_is_rejected_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio_root = root / "audio"
            bank = "midi_instrument_08_violin"
            rows = _make_empty_samples(audio_root, bank, [101])
            map_path = root / "map.json"
            cache = root / "cache"
            _write_sample_map(map_path, {bank: rows})
            with patch.object(
                timbre, "_extract_file_features", return_value=_feature_row()
            ):
                index = timbre.load_or_build_timbre_profile_index(
                    map_path, audio_root, cache_dir=cache
                )
            manifest_path = cache / index.cache_key / "manifest.json"
            payload = json.loads(manifest_path.read_text(encoding="ascii"))
            payload["profiles"][0]["values"][0] = 999999.0
            manifest_path.write_text(json.dumps(payload), encoding="ascii")

            self.assertIsNone(
                timbre.load_cached_timbre_profile_index(
                    index.cache_key, cache_dir=cache
                )
            )

    def test_absolute_and_traversal_paths_are_not_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio_root = root / "audio"
            bank = "midi_instrument_06_harp"
            safe_rows = _make_empty_samples(audio_root, bank, [1])
            outside = root / "outside.wav"
            outside.write_bytes(b"private")
            rows = safe_rows + [
                {
                    "source_id": 999,
                    "root_note": 60,
                    "velocity_min": 0,
                    "velocity_max": 127,
                    "wav_path": str(outside),
                    "wav_exists": True,
                },
                {
                    "source_id": 998,
                    "root_note": 60,
                    "velocity_min": 0,
                    "velocity_max": 127,
                    "wav_path": "..\\outside.wav",
                    "wav_exists": True,
                },
            ]
            map_path = root / "map.json"
            _write_sample_map(map_path, {bank: rows})
            decoded: list[str] = []

            def fake_extract(path: Path) -> dict[str, float]:
                decoded.append(path.name)
                return _feature_row()

            with patch.object(
                timbre, "_extract_file_features", side_effect=fake_extract
            ):
                index = timbre.load_or_build_timbre_profile_index(
                    map_path, audio_root, cache_dir=root / "cache"
                )
            self.assertEqual(decoded, ["1.wav"])
            self.assertEqual(index.profile_for_instrument(0x06).sample_count, 1)

    def test_marnian_profiles_cannot_be_high_confidence_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio_root = root / "audio"
            bank = "midi_instrument_synth_saw_basic"
            rows = _make_empty_samples(audio_root, bank, list(range(8)))
            map_path = root / "map.json"
            _write_sample_map(map_path, {bank: rows})
            with patch.object(
                timbre, "_extract_file_features", return_value=_feature_row()
            ):
                index = timbre.load_or_build_timbre_profile_index(
                    map_path, audio_root, cache_dir=root / "cache"
                )
            profile = index.profile_for_instrument(0x14)
            self.assertIsNotNone(profile)
            assert profile is not None
            self.assertLessEqual(
                profile.reliability, timbre.MARNIAN_TIMBRE_RELIABILITY_CAP
            )
            self.assertLess(profile.reliability, 0.35)
            self.assertTrue(index.pitch_profiles)
            self.assertTrue(
                all(
                    pitch_profile.reliability
                    <= timbre.MARNIAN_TIMBRE_RELIABILITY_CAP
                    for _instrument_id, _pitch, pitch_profile
                    in index.pitch_profiles
                )
            )

    def test_index_enforces_sixteen_mebibyte_bound(self) -> None:
        profile = TimbreFeatureProfile(
            "a" * 24,
            ("only",),
            (1.0,),
            1,
            1.0,
        )
        key = "b" * 32
        with patch.object(
            timbre,
            "estimate_profile_index_bytes",
            return_value=timbre.PROFILE_INDEX_MEMORY_LIMIT + 1,
        ):
            with self.assertRaises(timbre.TimbreProfileError):
                timbre.TimbreProfileIndex(
                    key,
                    ((1, profile),),
                    timbre.PROFILE_INDEX_MEMORY_LIMIT + 1,
                )

    def test_cancellation_after_first_decode_stops_without_writing_cache(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio_root = root / "audio"
            bank = "midi_instrument_07_piano"
            rows = _make_empty_samples(audio_root, bank, [1, 2, 3])
            map_path = root / "map.json"
            cache = root / "cache"
            _write_sample_map(map_path, {bank: rows})
            cancel_requested = False

            def fake_extract(
                _path: Path,
                *,
                cancelled: object = None,
            ) -> dict[str, float]:
                nonlocal cancel_requested
                cancel_requested = True
                return _feature_row()

            with patch.object(
                timbre,
                "_extract_file_features",
                side_effect=fake_extract,
            ) as extract:
                with self.assertRaises(timbre.TimbreAnalysisCancelled):
                    timbre.load_or_build_timbre_profile_index(
                        map_path,
                        audio_root,
                        cache_dir=cache,
                        cancelled=lambda: cancel_requested,
                    )

            self.assertEqual(extract.call_count, 1)
            self.assertFalse(any(cache.rglob("manifest.json")))


class TimbreFeatureExtractionTests(unittest.TestCase):
    def test_extracts_fixed_finite_feature_vector(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tone.wav"
            sample_rate = timbre.ANALYSIS_SAMPLE_RATE
            frames = []
            for index in range(sample_rate // 2):
                envelope = min(1.0, index / (sample_rate * 0.02))
                value = int(
                    12000
                    * envelope
                    * math.sin(2.0 * math.pi * 440.0 * index / sample_rate)
                )
                frames.append(struct.pack("<h", value))
            with wave.open(str(path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(sample_rate)
                output.writeframes(b"".join(frames))

            features = timbre._extract_file_features(path)

            self.assertEqual(tuple(features), timbre._FEATURE_NAMES)
            self.assertTrue(all(math.isfinite(value) for value in features.values()))
            self.assertGreaterEqual(features["attack_ms"], 0.0)
            self.assertGreaterEqual(features["decay_ms"], 0.0)


class GroupTimbreProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        import numpy as np

        self.audio = np.ones(timbre.ANALYSIS_SAMPLE_RATE * 8, dtype=np.float32)

    def test_selection_is_deterministic_and_limited_to_eight_segments(self) -> None:
        candidates = [
            _candidate(f"c{index}", 60 + index % 3, index * 600.0)
            for index in range(10)
        ]
        first_group = _group(
            "lead",
            tuple(candidate.candidate_id for candidate in candidates),
            0.0,
            6000.0,
        )
        second_group = _group(
            "lead",
            tuple(reversed(first_group.candidate_ids)),
            0.0,
            6000.0,
        )
        with (
            patch.object(
                timbre,
                "_load_reference_audio",
                return_value=(self.audio, timbre.ANALYSIS_SAMPLE_RATE),
            ),
            patch.object(
                timbre,
                "_extract_signal_features",
                side_effect=lambda signal, _rate: _feature_row(float(len(signal))),
            ) as extract,
        ):
            first = timbre.extract_group_timbre_profiles(
                "C:\\private\\reference.wav",
                candidates,
                [first_group],
            )
            second = timbre.extract_group_timbre_profiles(
                "D:\\different\\private.wav",
                list(reversed(candidates)),
                [second_group],
            )

        self.assertEqual(extract.call_count, 16)
        self.assertEqual(first["lead"].sample_count, 8)
        self.assertEqual(first["lead"], second["lead"])
        self.assertIn(60, first.pitch_profiles["lead"])
        self.assertNotIn("private", repr(first))
        self.assertNotIn("reference", repr(first))

    def test_local_polyphonic_pollution_reduces_reliability(self) -> None:
        clean = _candidate("clean", 60, 0.0, 200.0)
        polluted = _candidate("polluted", 64, 1000.0, 200.0)
        competitor = _candidate("competitor", 67, 1020.0, 200.0)
        groups = [
            _group("clean-group", ("clean",), 0.0, 200.0),
            _group("polluted-group", ("polluted",), 1000.0, 1200.0),
        ]
        with (
            patch.object(
                timbre,
                "_load_reference_audio",
                return_value=(self.audio, timbre.ANALYSIS_SAMPLE_RATE),
            ),
            patch.object(
                timbre,
                "_extract_signal_features",
                return_value=_feature_row(),
            ),
        ):
            profiles = timbre.extract_group_timbre_profiles(
                "reference.wav",
                [clean, polluted, competitor],
                groups,
            )

        self.assertIn("clean-group", profiles)
        self.assertIn("polluted-group", profiles)
        self.assertGreater(
            profiles["clean-group"].reliability,
            profiles["polluted-group"].reliability,
        )
        self.assertGreaterEqual(profiles["clean-group"].reliability, 0.35)
        self.assertLess(profiles["polluted-group"].reliability, 0.35)

    def test_dense_same_onset_mix_is_skipped(self) -> None:
        target = _candidate("target", 60, 500.0, 300.0)
        competitors = [
            _candidate("third", 64, 510.0, 300.0),
            _candidate("fifth", 67, 520.0, 300.0),
        ]
        with (
            patch.object(
                timbre,
                "_load_reference_audio",
                return_value=(self.audio, timbre.ANALYSIS_SAMPLE_RATE),
            ),
            patch.object(
                timbre,
                "_extract_signal_features",
                return_value=_feature_row(),
            ) as extract,
        ):
            profiles = timbre.extract_group_timbre_profiles(
                "reference.wav",
                [target, *competitors],
                [_group("chord-tone", ("target",), 500.0, 800.0)],
            )

        self.assertEqual(profiles, {})
        extract.assert_not_called()

    def test_frame_target_energy_share_rejects_polluted_segment(self) -> None:
        import numpy as np

        target = _candidate("target", 60, 0.0, 200.0)
        group = _group("lead", ("target",), 0.0, 200.0)
        times = np.arange(0.0, 220.0, 20.0)
        weak = np.zeros((len(times), 88), dtype=np.float32)
        weak[:, 60 - 21] = 0.01
        weak[:, 72 - 21] = 0.90
        strong = weak.copy()
        strong[:, 60 - 21] = 0.90
        strong[:, 72 - 21] = 0.05
        with (
            patch.object(
                timbre,
                "_load_reference_audio",
                return_value=(self.audio, timbre.ANALYSIS_SAMPLE_RATE),
            ),
            patch.object(
                timbre,
                "_extract_signal_features",
                return_value=_feature_row(),
            ),
        ):
            rejected = timbre.extract_group_timbre_profiles(
                "reference.wav",
                [target],
                [group],
                frame_evidence=timbre.FramePitchEvidence(times, weak),
            )
            accepted = timbre.extract_group_timbre_profiles(
                "reference.wav",
                [target],
                [group],
                frame_evidence={
                    "times_ms": times,
                    "frame": strong,
                    "midi_min": 21,
                    "bins_per_semitone": 1,
                },
            )

        self.assertEqual(rejected, {})
        self.assertIn("lead", accepted)
        self.assertGreaterEqual(accepted["lead"].reliability, 0.35)

    def test_cancellation_after_reference_decode_skips_feature_work(
        self,
    ) -> None:
        target = _candidate("target", 60, 0.0, 200.0)
        cancel_requested = False

        def load_audio(
            _path: str,
            *,
            cancelled: object = None,
        ) -> tuple[object, int]:
            nonlocal cancel_requested
            cancel_requested = True
            return self.audio, timbre.ANALYSIS_SAMPLE_RATE

        with (
            patch.object(
                timbre,
                "_load_reference_audio",
                side_effect=load_audio,
            ),
            patch.object(
                timbre,
                "_extract_signal_features",
                return_value=_feature_row(),
            ) as extract,
        ):
            with self.assertRaises(timbre.TimbreAnalysisCancelled):
                timbre.extract_group_timbre_profiles(
                    "reference.wav",
                    [target],
                    [_group("lead", ("target",), 0.0, 200.0)],
                    cancelled=lambda: cancel_requested,
                )

        extract.assert_not_called()


if __name__ == "__main__":
    unittest.main()
