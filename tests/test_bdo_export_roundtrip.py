from __future__ import annotations

import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "midi-to-bdo"))
sys.path.insert(0, str(ROOT / "scripts"))

from inspect_bdo import parse_bdo  # noqa: E402
from midi2bdo import Note, channel_groups_to_bdo  # noqa: E402
from pyside_bdo_gui import BDO_ARTICULATIONS  # noqa: E402


class BdoExportRoundTripTests(unittest.TestCase):
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
