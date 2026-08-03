from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from bdo_music_composer.audio.bdo_instrument_samples import BDO_BANK_BY_ID
from bdo_music_composer.audio.bdo_sample_renderer import BdoSampleMap
from tools import audit_game_playback_coverage as audit


def _row(
    bank: str,
    *,
    source_id: int,
    key_min: int,
    key_max: int,
    ntype: int,
) -> dict:
    return {
        "bank": bank,
        "source_id": source_id,
        "sound_id": source_id,
        "root_note": key_min,
        "key_min": key_min,
        "key_max": key_max,
        "velocity_min": 0,
        "velocity_max": 127,
        "wav_exists": True,
        "wav_path": f"{source_id}.wav",
        "route_ntypes": [ntype],
    }


class GamePlaybackCoverageAuditTests(unittest.TestCase):
    def _write_map(self, directory: Path) -> Path:
        bank = BDO_BANK_BY_ID[0x0A]
        mapping = directory / "map.json"
        mapping.write_text(
            json.dumps({
                "banks": {
                    bank: [
                        _row(
                            bank,
                            source_id=100,
                            key_min=60,
                            key_max=60,
                            ntype=0,
                        ),
                        _row(
                            bank,
                            source_id=103,
                            key_min=61,
                            key_max=61,
                            ntype=3,
                        ),
                    ]
                }
            }),
            encoding="utf-8",
        )
        return mapping

    def test_route_coverage_uses_the_notes_ntype(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            mapping = self._write_map(Path(directory))
            sample_map = BdoSampleMap(mapping)

            missing, route = audit._route_coverage(
                sample_map,
                mapping,
                0x0A,
                {
                    "pitch": 60,
                    "velocity_a": 90,
                    "ntype": 3,
                    "synth_mode": "basic",
                },
            )
            native, _route = audit._route_coverage(
                sample_map,
                mapping,
                0x0A,
                {
                    "pitch": 61,
                    "velocity_a": 90,
                    "ntype": 3,
                    "synth_mode": "basic",
                },
            )
            approximate, _route = audit._route_coverage(
                sample_map,
                mapping,
                0x0A,
                {
                    "pitch": 60,
                    "velocity_a": 90,
                    "ntype": 13,
                    "synth_mode": "basic",
                },
            )

        self.assertEqual((missing, route), ("missing", 3))
        self.assertEqual(native, "native")
        self.assertEqual(approximate, "approximate")

    def test_report_separates_native_and_approximate_routes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            mapping = self._write_map(Path(directory))
            report, _blockers = audit.build_report(
                map_path=mapping,
                saved_notes={
                    0x0A: [
                        {
                            "pitch": 61,
                            "velocity_a": 90,
                            "ntype": 3,
                            "synth_mode": "basic",
                        },
                        {
                            "pitch": 60,
                            "velocity_a": 90,
                            "ntype": 13,
                            "synth_mode": "basic",
                        },
                    ]
                },
                parsed_count=1,
                failure_types=Counter(),
            )

        self.assertIn("原生 1 / 近似 1", report)
        self.assertIn("共享近似处理", report)
        self.assertNotIn("奏法 DSP 未由离线渲染器实现", report)
        self.assertNotIn("1:1", report)

    def test_score_parse_failure_retains_only_anonymous_error_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            music_dir = Path(directory) / "Private Music"
            music_dir.mkdir()
            private_score = music_dir / "Alice-secret-composition"
            private_score.write_bytes(b"private")
            private_message = f"{private_score}: Owner Alice"

            with patch.object(
                audit,
                "parse_bdo",
                side_effect=ValueError(private_message),
            ):
                notes, parsed_count, failures = audit.parse_scores(music_dir)

        aggregate = repr((notes, parsed_count, failures))
        self.assertEqual(parsed_count, 0)
        self.assertEqual(failures, Counter({"ValueError": 1}))
        self.assertNotIn("Alice", aggregate)
        self.assertNotIn("secret-composition", aggregate)
        self.assertNotIn(str(music_dir), aggregate)

    def test_main_returns_nonzero_and_keeps_failure_output_path_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            music_dir = root / "Private Music"
            music_dir.mkdir()
            private_score = music_dir / "Alice-secret-composition"
            private_score.write_bytes(b"private")
            mapping = self._write_map(root)
            output = root / "coverage.md"
            stdout = io.StringIO()
            stderr = io.StringIO()

            with (
                patch.object(
                    audit,
                    "parse_bdo",
                    side_effect=ValueError(
                        f"{private_score}: Owner Alice"
                    ),
                ),
                patch.object(sys, "argv", [
                    "audit_game_playback_coverage.py",
                    "--music-dir",
                    str(music_dir),
                    "--map",
                    str(mapping),
                    "--output",
                    str(output),
                ]),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                exit_code = audit.main()

            combined = stdout.getvalue() + stderr.getvalue() + output.read_text(
                encoding="utf-8"
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("ValueError: 1", combined)
        self.assertNotIn("Alice", combined)
        self.assertNotIn("secret-composition", combined)
        self.assertNotIn(str(music_dir), combined)
        self.assertNotIn("1:1", combined)

    def test_invalid_map_returns_hard_failure_without_path_echo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            music_dir = root / "Music"
            music_dir.mkdir()
            mapping = root / "private-map.json"
            mapping.write_text("not json", encoding="utf-8")
            output = root / "coverage.md"
            stderr = io.StringIO()

            with (
                patch.object(sys, "argv", [
                    "audit_game_playback_coverage.py",
                    "--music-dir",
                    str(music_dir),
                    "--map",
                    str(mapping),
                    "--output",
                    str(output),
                ]),
                redirect_stderr(stderr),
            ):
                exit_code = audit.main()

        self.assertEqual(exit_code, 2)
        self.assertIn("could not be parsed", stderr.getvalue())
        self.assertNotIn(str(mapping), stderr.getvalue())

    def test_route_blocker_also_returns_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            music_dir = root / "Music"
            music_dir.mkdir()
            mapping = self._write_map(root)
            output = root / "coverage.md"

            with (
                patch.object(
                    audit,
                    "parse_scores",
                    return_value=(
                        {
                            0x0A: [{
                                "pitch": 60,
                                "velocity_a": 90,
                                "ntype": 3,
                                "synth_mode": "basic",
                            }]
                        },
                        1,
                        Counter(),
                    ),
                ),
                patch.object(
                    audit,
                    "BDO_INSTRUMENT_NAMES",
                    {0x0A: "guitar"},
                ),
                patch.object(sys, "argv", [
                    "audit_game_playback_coverage.py",
                    "--music-dir",
                    str(music_dir),
                    "--map",
                    str(mapping),
                    "--output",
                    str(output),
                ]),
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()),
            ):
                exit_code = audit.main()

        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
