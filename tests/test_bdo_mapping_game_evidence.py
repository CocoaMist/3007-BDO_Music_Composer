from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

from bdo_music_composer.audio.bdo_instrument_samples import (
    preview_route_ntype,
    select_zone_variants,
)


ROOT = Path(__file__).resolve().parents[1]
MAPPING_PATH = ROOT / "data" / "mappings" / "bdo_wwise_midi_map.json"


class CheckedInGameEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mapping = json.loads(
            MAPPING_PATH.read_text(encoding="utf-8")
        )
        cls.banks = cls.mapping["banks"]

    def test_four_native_routes_have_game_authored_partial_ranges(self) -> None:
        expected = {
            ("midi_instrument_24_proguitarelectricclean", 25): range(36, 44),
            ("midi_instrument_25_proguitarelectricdrive", 25): range(36, 44),
            ("midi_instrument_26_proguitarelectricdist", 25): range(36, 44),
            ("midi_instrument_28_prohorn", 3): range(24, 73),
        }
        for (bank, ntype), pitch_range in expected.items():
            with self.subTest(bank=bank, ntype=ntype):
                covered = {
                    pitch
                    for row in self.banks[bank]
                    if ntype in row["route_ntypes"]
                    for pitch in range(row["key_min"], row["key_max"] + 1)
                }
                self.assertEqual(set(pitch_range), covered)

    def test_partial_route_does_not_fall_through_to_sustain(self) -> None:
        for bank in (
            "midi_instrument_24_proguitarelectricclean",
            "midi_instrument_25_proguitarelectricdrive",
            "midi_instrument_26_proguitarelectricdist",
        ):
            with self.subTest(bank=bank):
                self.assertTrue(
                    select_zone_variants(
                        self.banks[bank],
                        36,
                        100,
                        ntype=25,
                    )
                )
                self.assertEqual(
                    (),
                    select_zone_variants(
                        self.banks[bank],
                        44,
                        100,
                        ntype=25,
                    ),
                )
        horn = self.banks["midi_instrument_28_prohorn"]
        self.assertTrue(select_zone_variants(horn, 72, 100, ntype=3))
        self.assertEqual((), select_zone_variants(horn, 73, 100, ntype=3))

    def test_percussion_neutral_event_routes_match_bank_evidence(self) -> None:
        shared_zero_and_99 = {
            "midi_instrument_04_handdrum",
            "midi_instrument_05_piatticymbals",
        }
        event_99_only = {
            "midi_instrument_13_prodrumset",
            "midi_instrument_19_propandrum",
        }
        for bank in shared_zero_and_99:
            self.assertEqual(
                {(0, 99)},
                {tuple(row["route_ntypes"]) for row in self.banks[bank]},
            )
        for bank in event_99_only:
            self.assertEqual(
                {(99,)},
                {tuple(row["route_ntypes"]) for row in self.banks[bank]},
            )
        for instrument_id in (0x04, 0x05, 0x0D, 0x13):
            self.assertEqual(99, preview_route_ntype(instrument_id, 0))

    def test_synth_modes_expose_the_same_native_event_routes(self) -> None:
        expected = set(range(9)) | set(range(17, 24))
        for waveform in ("saw", "sine", "square", "triangle"):
            for mode in ("basic", "stereo", "super", "superoct"):
                bank = f"midi_instrument_synth_{waveform}_{mode}"
                routes = {
                    ntype
                    for row in self.banks[bank]
                    for ntype in row["route_ntypes"]
                }
                with self.subTest(bank=bank):
                    self.assertEqual(expected, routes)

    def test_recovered_instance_limits_are_per_game_object(self) -> None:
        expected = {
            ("midi_instrument_04_handdrum", 165708636): 1,
            ("midi_instrument_04_handdrum", 753561898): 1,
            ("midi_instrument_04_handdrum", 838226382): 1,
            ("midi_instrument_04_handdrum", 999535842): 1,
            ("midi_instrument_05_piatticymbals", 735589647): 3,
            ("midi_instrument_06_harp", 1035980451): 5,
            ("midi_instrument_13_prodrumset", 329730497): 1,
            ("midi_instrument_13_prodrumset", 517050749): 1,
        }
        actual: dict[tuple[str, int], int] = {}
        for bank, rows in self.banks.items():
            for row in rows:
                limit = int(row.get("max_instances", 0) or 0)
                if not limit:
                    continue
                key = (bank, int(row["instance_group_id"]))
                actual[key] = limit
                self.assertFalse(row["instance_limit_global"])
                self.assertFalse(row["instance_use_virtual_behavior"])
                self.assertFalse(row["kill_newest"])
        self.assertEqual(expected, actual)

    def test_v782_mapping_preserves_explicit_root_and_pitch_rtpc_provenance(self) -> None:
        rows = [row for bank_rows in self.banks.values() for row in bank_rows]
        self.assertEqual(3579, len(rows))
        self.assertTrue(all(row["root_note_owner_id"] is not None for row in rows))
        self.assertFalse(any(row["root_note_inferred"] for row in rows))
        self.assertEqual(
            1024,
            sum(bool(row["unmodeled_pitch_rtpc"]) for row in rows),
        )
        self.assertTrue(all(
            bool(row["pitch_rtpc_bindings"])
            == bool(row["unmodeled_pitch_rtpc"])
            for row in rows
        ))

    def test_checked_in_mapping_evidence_hash_covers_new_provenance(self) -> None:
        rows = [row for bank_rows in self.banks.values() for row in bank_rows]
        semantic_rows = [
            {
                key: value
                for key, value in row.items()
                if key not in {"wem_path", "wav_path", "evidence_sha256"}
            }
            for row in rows
        ]
        digest = hashlib.sha256(json.dumps(
            {
                "bank_versions": self.mapping["wwise_bank_versions"],
                "rows": semantic_rows,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        self.assertEqual(self.mapping["evidence_sha256"], digest)
        self.assertTrue(all(row["evidence_sha256"] == digest for row in rows))


if __name__ == "__main__":
    unittest.main()
