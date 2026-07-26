from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from bdo_instrument_samples import BDO_BANK_BY_ID
from tools import audit_bdo_sample_mapping as audit


def _row(
    bank: str,
    *,
    source_id: int,
    key_min: int,
    key_max: int,
    route_ntypes: tuple[int, ...],
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
        "wav_path": f"{bank}/{source_id}.wav",
        "route_ntypes": list(route_ntypes),
    }


class SampleMappingAuditTests(unittest.TestCase):
    def test_percussion_basic_uses_production_event_and_wwise_keys(self) -> None:
        instrument_id = 0x04
        bank = BDO_BANK_BY_ID[instrument_id]
        by_bank = {
            bank: [
                _row(
                    bank,
                    source_id=100,
                    key_min=60,
                    key_max=79,
                    route_ntypes=(99,),
                )
            ]
        }
        stdout = io.StringIO()

        with (
            patch.object(
                audit,
                "BDO_ARTICULATIONS",
                {instrument_id: [(0, "基本"), (99, "打击")]},
            ),
            patch.object(audit, "BDO_EDITOR_PITCH_RANGES", {}),
            redirect_stdout(stdout),
        ):
            problems = audit.audit_articulation_routes(by_bank)

        self.assertEqual(problems, [])
        self.assertIn("Native articulation routes: 2 (full-range 2", stdout.getvalue())

    def test_evidence_limited_partial_route_is_informational(self) -> None:
        instrument_id = 0x24
        bank = BDO_BANK_BY_ID[instrument_id]
        by_bank = {
            bank: [
                _row(
                    bank,
                    source_id=200,
                    key_min=24,
                    key_max=95,
                    route_ntypes=(0,),
                ),
                _row(
                    bank,
                    source_id=225,
                    key_min=36,
                    key_max=43,
                    route_ntypes=(25,),
                ),
            ]
        }
        stdout = io.StringIO()

        with (
            patch.object(
                audit,
                "BDO_ARTICULATIONS",
                {instrument_id: [(25, "FX")]},
            ),
            patch.object(
                audit,
                "BDO_EDITOR_PITCH_RANGES",
                {instrument_id: tuple(range(24, 96))},
            ),
            redirect_stdout(stdout),
        ):
            problems = audit.audit_articulation_routes(by_bank)

        self.assertEqual(problems, [])
        self.assertIn("native=36-43", stdout.getvalue())
        self.assertIn("playable=24-95 partial", stdout.getvalue())

    def test_unmapped_top_level_sample_is_non_blocking_information(self) -> None:
        bank = BDO_BANK_BY_ID[0x00]
        by_bank = {
            bank: [
                _row(
                    bank,
                    source_id=300,
                    key_min=60,
                    key_max=60,
                    route_ntypes=(0,),
                )
            ]
        }
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for suffix, extension in (("_WAV", ".wav"), ("_WEM", ".wem")):
                sample_root = root / f"private{suffix}"
                bank_root = sample_root / bank
                bank_root.mkdir(parents=True)
                (bank_root / f"300{extension}").write_bytes(b"sample")
                if suffix == "_WAV":
                    (sample_root / "unmapped.wav").write_bytes(b"extra")

            with redirect_stdout(stdout):
                problems = audit.audit_sample_root(root, by_bank)

        self.assertEqual(problems, [])
        self.assertIn("top_level_unmapped=1", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
