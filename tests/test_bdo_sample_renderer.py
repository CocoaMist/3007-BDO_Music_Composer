from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import wave
from types import SimpleNamespace

import numpy as np

from bdo_music_composer.audio.bdo_instrument_samples import (
    BDO_BANK_BY_ID,
    bank_for_instrument,
    banks_for_instrument,
    resolve_bdo_pitch,
)
from bdo_midi import BDO_INSTRUMENT_NAMES, _GM_TO_BDO_DRUM
from bdo_music_composer.audio.bdo_realtime_audio import BANK_BY_ID
from bdo_music_composer.audio.bdo_sample_renderer import (
    BdoSampleMap,
    GM_TO_BDO_DRUM,
    SAMPLE_RATE,
    _resample_for_note,
    render_preview,
    sample_map_evidence_sha256,
    sample_map_velocity_boundaries,
    sample_map_supported_pitches,
    sample_map_supports_note,
)


def _row(
    bank: str,
    source_id: int,
    key_min: int,
    key_max: int,
) -> dict:
    return {
        "bank": bank,
        "source_id": source_id,
        "root_note": key_min,
        "key_min": key_min,
        "key_max": key_max,
        "velocity_min": 0,
        "velocity_max": 127,
        "wav_exists": True,
        "wav_path": f"{bank}/{source_id}.wav",
    }


class BdoSampleRendererTests(unittest.TestCase):
    def test_mapping_caches_reload_a_replaced_path(self) -> None:
        bank = bank_for_instrument(0x0A)
        first = _row(bank, 10, 36, 48)
        first.update({"velocity_min": 0, "velocity_max": 63})
        second = _row(bank, 20, 60, 72)
        second.update({"velocity_min": 0, "velocity_max": 95})
        with tempfile.TemporaryDirectory() as directory:
            mapping = Path(directory) / "mapping.json"
            mapping.write_text(json.dumps({
                "evidence_sha256": "first",
                "banks": {bank: [first]},
            }), encoding="utf-8")
            self.assertEqual(sample_map_evidence_sha256(mapping), "first")
            self.assertIn(40, sample_map_supported_pitches(mapping, 0x0A))
            self.assertEqual(
                sample_map_velocity_boundaries(mapping, 0x0A, 40),
                (),
            )

            mapping.write_text(json.dumps({
                "evidence_sha256": "second-revision",
                "banks": {bank: [second]},
            }), encoding="utf-8")
            self.assertEqual(
                sample_map_evidence_sha256(mapping),
                "second-revision",
            )
            pitches = sample_map_supported_pitches(mapping, 0x0A)
            self.assertNotIn(40, pitches)
            self.assertIn(64, pitches)
            self.assertEqual(
                sample_map_velocity_boundaries(mapping, 0x0A, 64),
                (),
            )

    def test_velocity_boundary_hint_uses_mapping_metadata_only(self) -> None:
        bank = bank_for_instrument(0x0A)
        rows = []
        for source_id, lower, upper in ((10, 0, 63), (11, 64, 127)):
            row = _row(bank, source_id, 36, 88)
            row.update({
                "velocity_min": lower,
                "velocity_max": upper,
                "selection_group_id": source_id,
                "wav_path": "Z:/definitely-unavailable/game-audio.wav",
            })
            rows.append(row)
        with tempfile.TemporaryDirectory() as directory:
            mapping = Path(directory) / "mapping.json"
            mapping.write_text(
                json.dumps({"banks": {bank: rows}}), encoding="utf-8"
            )
            self.assertEqual(
                sample_map_velocity_boundaries(mapping, 0x0A, 60),
                (64,),
            )

    @staticmethod
    def write_long_wav(path: Path, seconds: float = 6.0) -> None:
        frames = round(SAMPLE_RATE * seconds)
        pcm = np.full((frames, 2), 8_000, dtype="<i2")
        with wave.open(str(path), "wb") as target:
            target.setnchannels(2)
            target.setsampwidth(2)
            target.setframerate(SAMPLE_RATE)
            target.writeframes(pcm.tobytes())

    @staticmethod
    def write_constant_wav(
        path: Path,
        *,
        seconds: float,
        amplitude: float,
    ) -> None:
        frames = max(1, round(SAMPLE_RATE * seconds))
        value = round(max(-1.0, min(1.0, amplitude)) * 32767.0)
        pcm = np.full((frames, 2), value, dtype="<i2")
        with wave.open(str(path), "wb") as target:
            target.setnchannels(2)
            target.setsampwidth(2)
            target.setframerate(SAMPLE_RATE)
            target.writeframes(pcm.tobytes())

    @staticmethod
    def read_output(path: Path) -> np.ndarray:
        with wave.open(str(path), "rb") as source:
            return (
                np.frombuffer(
                    source.readframes(source.getnframes()),
                    dtype="<i2",
                )
                .reshape(-1, 2)
                .astype(np.float32)
                / 32768.0
            )

    @staticmethod
    def preview_track(instrument_id: int, ntype: int = 0):
        return SimpleNamespace(
            bdo_instrument_id=instrument_id,
            marnian_synth_mode="basic",
            volume_scale=1.0,
            duration_scale=1.0,
            articulation_type=None,
            notes=[
                SimpleNamespace(
                    pitch=60,
                    vel=100,
                    start=0.0,
                    dur=100.0,
                    ntype=ntype,
                )
            ],
        )

    def test_portable_mapping_path_resolves_from_configured_audio_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bank = BDO_BANK_BY_ID[0x0A]
            wav_path = root / "audio" / "乐器_WAV" / bank / "7.wav"
            wav_path.parent.mkdir(parents=True)
            wav_path.touch()
            mapping = root / "map.json"
            row = _row(bank, 7, 60, 60)
            mapping.write_text(
                json.dumps({"banks": {bank: [row]}}),
                encoding="utf-8",
            )

            sample_map = BdoSampleMap(mapping, root / "audio")
            selected = sample_map.choose(0x0A, 60, 100)

            self.assertIsNotNone(selected)
            self.assertEqual(Path(selected["wav_path"]), wav_path)
            self.assertTrue(sample_map.has_complete_media(0x0A))
            wav_path.unlink()
            self.assertFalse(sample_map.has_complete_media(0x0A))

    def test_checked_in_ranges_are_fully_covered_by_every_selected_bank(
        self,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        mapping = json.loads(
            (root / "data/mappings/bdo_wwise_midi_map.json").read_text(
                encoding="utf-8"
            )
        )["banks"]
        profile = json.loads(
            (root / "data/profiles/bdo_global_v9.json").read_text(
                encoding="utf-8"
            )
        )["instruments"]
        self.assertEqual(
            set(BDO_INSTRUMENT_NAMES),
            {
                instrument_id
                for instrument_id in BDO_INSTRUMENT_NAMES
                if banks_for_instrument(instrument_id)
            },
        )
        for instrument_id in BDO_INSTRUMENT_NAMES:
            config = profile[f"0x{instrument_id:02X}"]
            pitch_min = config.get("pitch_min")
            pitch_max = config.get("pitch_max")
            if pitch_min is None or pitch_max is None:
                continue
            legal_pitches = config.get("allowed_pitches")
            pitches = (
                [int(value) for value in legal_pitches]
                if legal_pitches
                else range(int(pitch_min), int(pitch_max) + 1)
            )
            for bank in banks_for_instrument(instrument_id):
                rows = [
                    row
                    for row in mapping[bank]
                    if row.get("wav_exists")
                ]
                for pitch in pitches:
                    intervals = sorted(
                        (
                            int(row["velocity_min"]),
                            int(row["velocity_max"]),
                        )
                        for row in rows
                        if int(row["key_min"])
                        <= pitch
                        <= int(row["key_max"])
                    )
                    high = -1
                    for low, upper in intervals:
                        if low > high + 1:
                            break
                        high = max(high, upper)
                    self.assertGreaterEqual(
                        high,
                        127,
                        f"0x{instrument_id:02X}/{bank}/pitch {pitch}",
                    )

    def test_realtime_and_offline_use_the_same_canonical_tables(self) -> None:
        self.assertIs(BANK_BY_ID, BDO_BANK_BY_ID)
        self.assertIs(GM_TO_BDO_DRUM, _GM_TO_BDO_DRUM)
        self.assertEqual(
            bank_for_instrument(0x20, "superoct"),
            "midi_instrument_synth_triangle_superoct",
        )

    def test_marnian_mode_uses_its_own_zone_range(self) -> None:
        basic = "midi_instrument_synth_saw_basic"
        stereo = "midi_instrument_synth_saw_stereo"
        with tempfile.TemporaryDirectory() as directory:
            mapping = Path(directory) / "map.json"
            mapping.write_text(
                json.dumps(
                    {
                        "banks": {
                            basic: [_row(basic, 1, 12, 100)],
                            stereo: [_row(stereo, 2, 12, 107)],
                        }
                    }
                ),
                encoding="utf-8",
            )
            sample_map = BdoSampleMap(mapping)
            self.assertEqual(
                sample_map.supported_pitches(0x14, "basic"),
                frozenset(range(12, 101)),
            )
            self.assertEqual(
                sample_map_supported_pitches(mapping, 0x14, "stereo"),
                frozenset(range(12, 108)),
            )
            selected = sample_map.choose(
                0x14, 105, 90, synth_mode="stereo"
            )
            self.assertIsNotNone(selected)
            self.assertEqual(selected["bank"], stereo)
            self.assertFalse(
                sample_map_supports_note(
                    mapping, 0x14, 105, 90, synth_mode="basic"
                )
            )

    def test_canonical_drum_notes_are_not_remapped_twice(self) -> None:
        bank = BDO_BANK_BY_ID[0x0D]
        with tempfile.TemporaryDirectory() as directory:
            mapping = Path(directory) / "map.json"
            mapping.write_text(
                json.dumps(
                    {
                        "banks": {
                            bank: [
                                _row(bank, 48, 48, 48),
                                _row(bank, 53, 53, 53),
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            sample_map = BdoSampleMap(mapping)
            self.assertEqual(resolve_bdo_pitch(0x0D, 48, 99), 48)
            self.assertEqual(resolve_bdo_pitch(0x0D, 41, 0), 53)
            self.assertEqual(resolve_bdo_pitch(0x0D, 127, 0), 48)
            self.assertEqual(
                sample_map.choose(0x0D, 48, 100, ntype=99)["source_id"],
                48,
            )
            self.assertEqual(
                sample_map.choose(0x0D, 41, 100, ntype=0)["source_id"],
                53,
            )

    def test_offline_renderer_uses_same_gated_and_natural_tail_boundaries(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wav_path = root / "long.wav"
            self.write_long_wav(wav_path)
            banks = {}
            for instrument_id in (0x01, 0x07):
                bank = BDO_BANK_BY_ID[instrument_id]
                row = _row(bank, instrument_id, 0, 127)
                row.update({"root_note": 60, "wav_path": str(wav_path)})
                banks[bank] = [row]
            mapping = root / "map.json"
            mapping.write_text(
                json.dumps({"banks": banks}),
                encoding="utf-8",
            )

            flute_output = root / "flute.wav"
            flute_result = render_preview(
                [self.preview_track(0x01)],
                mapping,
                flute_output,
            )
            with wave.open(str(flute_output), "rb") as source:
                flute_frames = source.getnframes()
            self.assertEqual(flute_frames, round(SAMPLE_RATE * 0.1))
            self.assertAlmostEqual(flute_result.duration_ms, 100.0, places=2)

            piano_output = root / "piano.wav"
            piano_result = render_preview(
                [self.preview_track(0x07)],
                mapping,
                piano_output,
            )
            with wave.open(str(piano_output), "rb") as source:
                piano_frames = source.getnframes()
            self.assertEqual(piano_frames, round(SAMPLE_RATE * 1.3))
            self.assertAlmostEqual(piano_result.duration_ms, 1_300.0, places=2)

    def test_loop_resampler_repeats_declared_region_and_honours_age(
        self,
    ) -> None:
        mono = np.arange(4, dtype=np.float32)
        sample = np.column_stack((mono, mono))
        rendered = _resample_for_note(
            sample,
            1.0,
            8,
            loop_points=(1, 4),
        )
        np.testing.assert_array_equal(
            rendered[:, 0],
            np.asarray((0, 1, 2, 3, 1, 2, 3, 1), dtype=np.float32),
        )
        resumed = _resample_for_note(
            sample,
            1.0,
            3,
            start_output_frame=5,
            loop_points=(1, 4),
        )
        np.testing.assert_array_equal(
            resumed[:, 0],
            np.asarray((2, 3, 1), dtype=np.float32),
        )

    def test_renderer_applies_recovered_row_volume(self) -> None:
        bank = BDO_BANK_BY_ID[0x01]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample_path = root / "sample.wav"
            self.write_constant_wav(
                sample_path,
                seconds=0.05,
                amplitude=0.25,
            )
            row = _row(bank, 1, 60, 60)
            row.update({
                "root_note": 60,
                "wav_path": str(sample_path),
                "volume_db": -6.0,
            })
            mapping = root / "map.json"
            mapping.write_text(
                json.dumps({"banks": {bank: [row]}}),
                encoding="utf-8",
            )
            output = root / "preview.wav"
            track = self.preview_track(0x01)
            track.bdo_track_volume = 40
            track.notes[0].vel = 127
            track.notes[0].dur = 20.0

            render_preview([track], mapping, output)

            peak = float(np.max(np.abs(self.read_output(output))))
            expected = 0.25 * 0.40 * (10.0 ** (-6.0 / 20.0))
            self.assertAlmostEqual(peak, expected, delta=0.002)

    def test_renderer_preserves_zero_velocity_as_silence(self) -> None:
        bank = BDO_BANK_BY_ID[0x01]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample_path = root / "sample.wav"
            self.write_constant_wav(
                sample_path,
                seconds=0.05,
                amplitude=0.25,
            )
            row = _row(bank, 1, 60, 60)
            row.update({"root_note": 60, "wav_path": str(sample_path)})
            mapping = root / "map.json"
            mapping.write_text(
                json.dumps({"banks": {bank: [row]}}),
                encoding="utf-8",
            )
            output = root / "preview.wav"
            track = self.preview_track(0x01)
            track.notes[0].vel = 0

            result = render_preview([track], mapping, output)

            self.assertEqual(result.notes_rendered, 1)
            self.assertEqual(float(np.max(np.abs(self.read_output(output)))), 0.0)

    def test_renderer_ignores_retired_hidden_velocity_scale(self) -> None:
        bank = BDO_BANK_BY_ID[0x01]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample_path = root / "sample.wav"
            self.write_constant_wav(
                sample_path,
                seconds=0.05,
                amplitude=0.25,
            )
            row = _row(bank, 1, 60, 60)
            row.update({"root_note": 60, "wav_path": str(sample_path)})
            mapping = root / "map.json"
            mapping.write_text(
                json.dumps({"banks": {bank: [row]}}),
                encoding="utf-8",
            )
            output = root / "preview.wav"
            track = self.preview_track(0x01)
            track.notes[0].vel = 127
            track.notes[0].dur = 20.0
            track.volume_scale = 0.01
            track.bdo_track_volume = 100

            render_preview([track], mapping, output)

            peak = float(np.max(np.abs(self.read_output(output))))
            self.assertAlmostEqual(peak, 0.25, delta=0.002)

    def test_renderer_rotates_containers_in_global_time_order(self) -> None:
        bank = BDO_BANK_BY_ID[0x01]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            quiet_path = root / "quiet.wav"
            loud_path = root / "loud.wav"
            self.write_constant_wav(
                quiet_path,
                seconds=0.05,
                amplitude=0.10,
            )
            self.write_constant_wav(
                loud_path,
                seconds=0.05,
                amplitude=0.20,
            )
            quiet = _row(bank, 10, 60, 60)
            quiet.update({
                "sound_id": 110,
                "selection_group_id": 500,
                "playlist_index": 0,
                "wav_path": str(quiet_path),
            })
            loud = _row(bank, 20, 60, 60)
            loud.update({
                "sound_id": 120,
                "selection_group_id": 500,
                "playlist_index": 1,
                "wav_path": str(loud_path),
            })
            mapping = root / "map.json"
            mapping.write_text(
                json.dumps({"banks": {bank: [loud, quiet]}}),
                encoding="utf-8",
            )
            later = self.preview_track(0x01)
            later.notes[0].start = 100.0
            later.notes[0].dur = 20.0
            earlier = self.preview_track(0x01)
            earlier.notes[0].start = 0.0
            earlier.notes[0].dur = 20.0
            output = root / "preview.wav"

            render_preview([later, earlier], mapping, output)

            pcm = self.read_output(output)
            early_level = float(abs(pcm[round(SAMPLE_RATE * 0.005), 0]))
            late_level = float(abs(pcm[round(SAMPLE_RATE * 0.105), 0]))
            self.assertGreater(early_level, 0.0)
            self.assertAlmostEqual(
                late_level / early_level,
                2.0,
                delta=0.05,
            )

    def test_native_loop_uses_note_plus_release_and_declared_points(
        self,
    ) -> None:
        bank = BDO_BANK_BY_ID[0x0B]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample_path = root / "loop.wav"
            self.write_constant_wav(
                sample_path,
                seconds=0.02,
                amplitude=0.20,
            )
            row = _row(bank, 1, 60, 60)
            row.update({
                "sound_id": 101,
                "selection_group_id": 500,
                "root_note": 60,
                "route_ntypes": [0],
                "wav_path": str(sample_path),
                "sample_loops": True,
                "loop_start_frame": round(SAMPLE_RATE * 0.005),
                "loop_end_frame": round(SAMPLE_RATE * 0.015),
                "release_ms": 20.0,
            })
            mapping = root / "map.json"
            mapping.write_text(
                json.dumps({"banks": {bank: [row]}}),
                encoding="utf-8",
            )
            output = root / "preview.wav"
            track = self.preview_track(0x0B)
            track.notes[0].dur = 100.0

            result = render_preview([track], mapping, output)

            with wave.open(str(output), "rb") as source:
                output_frames = source.getnframes()
            self.assertEqual(
                output_frames,
                round(SAMPLE_RATE * 0.120),
            )
            self.assertAlmostEqual(result.duration_ms, 120.0, places=2)
            pcm = self.read_output(output)
            self.assertGreater(
                float(abs(pcm[round(SAMPLE_RATE * 0.09), 0])),
                0.01,
            )
            self.assertAlmostEqual(float(pcm[-1, 0]), 0.0, places=4)

    def test_offline_renderer_applies_same_fallback_articulation_dsp(
        self,
    ) -> None:
        bank = BDO_BANK_BY_ID[0x01]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample_path = root / "sample.wav"
            self.write_constant_wav(
                sample_path,
                seconds=0.1,
                amplitude=0.1,
            )
            row = _row(bank, 1, 60, 60)
            row.update({
                "root_note": 60,
                "route_ntypes": [0],
                "wav_path": str(sample_path),
            })
            mapping = root / "map.json"
            mapping.write_text(
                json.dumps({"banks": {bank: [row]}}),
                encoding="utf-8",
            )
            basic_track = self.preview_track(0x01, 0)
            basic_track.notes[0].vel = 127
            basic_track.notes[0].dur = 50.0
            filtered_track = self.preview_track(0x01, 26)
            filtered_track.notes[0].vel = 127
            filtered_track.notes[0].dur = 50.0
            basic_output = root / "basic.wav"
            filtered_output = root / "filtered.wav"

            render_preview([basic_track], mapping, basic_output)
            render_preview([filtered_track], mapping, filtered_output)

            frame = round(SAMPLE_RATE * 0.01)
            basic_level = float(abs(self.read_output(basic_output)[frame, 0]))
            filtered_level = float(
                abs(self.read_output(filtered_output)[frame, 0])
            )
            self.assertAlmostEqual(
                filtered_level / basic_level,
                0.62,
                delta=0.02,
            )

    def test_offline_renderer_recreates_fallback_harp_chord_once(
        self,
    ) -> None:
        bank = BDO_BANK_BY_ID[0x10]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample_path = root / "sample.wav"
            self.write_constant_wav(
                sample_path,
                seconds=0.08,
                amplitude=0.1,
            )
            row = _row(bank, 1, 60, 60)
            row.update({
                "root_note": 60,
                "route_ntypes": [0],
                "wav_path": str(sample_path),
            })
            mapping = root / "map.json"
            mapping.write_text(
                json.dumps({"banks": {bank: [row]}}),
                encoding="utf-8",
            )
            basic_track = self.preview_track(0x10, 0)
            chord_track = self.preview_track(0x10, 9)
            for track in (basic_track, chord_track):
                track.notes[0].vel = 127
                track.notes[0].dur = 30.0
            basic_output = root / "basic.wav"
            chord_output = root / "chord.wav"

            render_preview([basic_track], mapping, basic_output)
            result = render_preview([chord_track], mapping, chord_output)

            frame = round(SAMPLE_RATE * 0.01)
            basic_level = float(abs(self.read_output(basic_output)[frame, 0]))
            chord_level = float(abs(self.read_output(chord_output)[frame, 0]))
            self.assertAlmostEqual(
                chord_level / basic_level,
                2.04,
                delta=0.04,
            )
            self.assertEqual(result.notes_rendered, 1)

    def test_marnian_native_layer_keeps_approximate_parent_dsp(
        self,
    ) -> None:
        bank = bank_for_instrument(0x14, "basic") or ""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample_path = root / "sample.wav"
            self.write_constant_wav(
                sample_path,
                seconds=0.1,
                amplitude=0.1,
            )
            row = _row(bank, 1, 60, 60)
            row.update({
                "root_note": 60,
                "route_ntypes": [26],
                "wav_path": str(sample_path),
            })
            mapping = root / "map.json"
            mapping.write_text(
                json.dumps({"banks": {bank: [row]}}),
                encoding="utf-8",
            )
            track = self.preview_track(0x14, 26)
            track.notes[0].vel = 127
            track.notes[0].dur = 50.0
            output = root / "synth.wav"

            render_preview([track], mapping, output)

            frame = round(SAMPLE_RATE * 0.01)
            level = float(abs(self.read_output(output)[frame, 0]))
            self.assertAlmostEqual(
                level,
                0.1 * 0.70 * 0.62,
                delta=0.003,
            )

    def test_offline_instance_limit_matches_per_track_oldest_policy(
        self,
    ) -> None:
        bank = BDO_BANK_BY_ID[0x01]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample_path = root / "sample.wav"
            self.write_constant_wav(
                sample_path,
                seconds=0.2,
                amplitude=0.1,
            )
            row = _row(bank, 1, 60, 60)
            row.update({
                "root_note": 60,
                "wav_path": str(sample_path),
                "instance_group_id": 77,
                "max_instances": 1,
                "kill_newest": False,
                "instance_limit_global": False,
                "instance_use_virtual_behavior": False,
            })
            mapping = root / "map.json"

            def write_mapping() -> None:
                mapping.write_text(
                    json.dumps({"banks": {bank: [row]}}),
                    encoding="utf-8",
                )

            write_mapping()
            same_track = self.preview_track(0x01)
            same_track.notes[0].vel = 127
            same_track.notes[0].dur = 100.0
            same_track.notes.append(SimpleNamespace(
                pitch=60,
                vel=127,
                start=20.0,
                dur=100.0,
                ntype=0,
            ))
            same_output = root / "same.wav"
            same_result = render_preview(
                [same_track], mapping, same_output
            )

            first_track = self.preview_track(0x01)
            first_track.notes[0].vel = 127
            first_track.notes[0].dur = 100.0
            second_track = self.preview_track(0x01)
            second_track.notes[0].vel = 127
            second_track.notes[0].start = 20.0
            second_track.notes[0].dur = 100.0
            separate_output = root / "separate.wav"
            render_preview(
                [first_track, second_track],
                mapping,
                separate_output,
            )

            frame = round(SAMPLE_RATE * 0.04)
            same_level = float(
                abs(self.read_output(same_output)[frame, 0])
            )
            separate_level = float(
                abs(self.read_output(separate_output)[frame, 0])
            )
            self.assertAlmostEqual(
                separate_level / same_level,
                2.0,
                delta=0.05,
            )
            self.assertEqual(same_result.notes_rendered, 2)
            self.assertAlmostEqual(
                same_result.duration_ms,
                120.0,
                places=2,
            )

            row["instance_limit_global"] = True
            write_mapping()
            global_output = root / "global.wav"
            render_preview(
                [first_track, second_track],
                mapping,
                global_output,
            )
            global_level = float(
                abs(self.read_output(global_output)[frame, 0])
            )
            self.assertAlmostEqual(
                global_level,
                same_level,
                delta=0.003,
            )

            row["kill_newest"] = True
            write_mapping()
            newest_output = root / "newest.wav"
            newest_result = render_preview(
                [same_track], mapping, newest_output
            )
            self.assertEqual(newest_result.notes_rendered, 1)
            self.assertAlmostEqual(
                newest_result.duration_ms,
                100.0,
                places=2,
            )


if __name__ == "__main__":
    unittest.main()
