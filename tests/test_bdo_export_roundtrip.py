from __future__ import annotations

import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from inspect_bdo import parse_bdo  # noqa: E402
from bdo_midi import Note  # noqa: E402
from bdo_export import channel_groups_to_bdo  # noqa: E402
from pyside_bdo_gui import BDO_ARTICULATIONS, copy_export_to_game  # noqa: E402


class BdoExportRoundTripTests(unittest.TestCase):
    def test_export_is_copied_to_game_folder_and_same_folder_is_safe(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "out" / "score"
            output.parent.mkdir()
            output.write_bytes(b"score-data")
            game_dir = root / "game" / "music"

            installed = copy_export_to_game(output, game_dir)

            self.assertEqual(installed, game_dir / "score")
            self.assertEqual(installed.read_bytes(), b"score-data")
            self.assertEqual(copy_export_to_game(installed, game_dir), installed)

    def test_canonical_bdo_drums_are_not_mapped_as_gm_a_second_time(self) -> None:
        source = [Note(48, 90, 0.0, 100.0, 99), Note(64, 90, 200.0, 100.0, 99)]
        data, _summary = channel_groups_to_bdo(
            120, 4, [(source, 0, True)], instrument_map={0: 0x0D}, preserve_note_types=True
        )
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "canonical_drums"
            output.write_bytes(data)
            report = parse_bdo(output, sample_notes=10)
        notes = next(
            track["sample_notes"]
            for group in report["groups"] for track in group["tracks"]
            if track["note_count"]
        )
        self.assertEqual([item["pitch"] for item in notes], [48, 64])
        self.assertEqual([item["ntype"] for item in notes], [99, 99])

    def test_all_gui_articulations_survive_gui_export_core_roundtrip(self) -> None:
        channel_groups = []
        instrument_map = {}
        expected_by_instrument: dict[int, Counter[int]] = {}
        start_ms = 0.0
        for channel_index, (instrument_id, definitions) in enumerate(sorted(BDO_ARTICULATIONS.items())):
            notes = []
            expected = Counter()
            for ntype, _label in definitions:
                notes.append(Note(60, 96, start_ms, 400.0, ntype))
                expected[ntype] += 1
                start_ms += 450.0
            channel_groups.append((notes, 0, False))
            instrument_map[channel_index] = instrument_id
            expected_by_instrument[instrument_id] = expected

        bdo_data, summary = channel_groups_to_bdo(
            120,
            4,
            channel_groups,
            char_name="RoundTrip",
            instrument_map=instrument_map,
            vel_layered=True,
            preserve_note_types=True,
        )
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "articulation_roundtrip.bdo"
            output.write_bytes(bdo_data)
            report = parse_bdo(output, sample_notes=0)

        actual_by_instrument: dict[int, Counter[int]] = {}
        for group in report["groups"]:
            for track in group["tracks"]:
                if not track["note_count"]:
                    continue
                actual_by_instrument.setdefault(track["instrument_id"], Counter()).update(
                    {int(ntype): count for ntype, count in track["note_type_counts"].items()}
                )

        self.assertEqual(
            summary["total_notes"],
            sum(sum(counts.values()) for counts in expected_by_instrument.values()),
        )
        self.assertEqual(actual_by_instrument, expected_by_instrument)
        self.assertEqual(report["total_notes"], summary["total_notes"])


if __name__ == "__main__":
    unittest.main()
