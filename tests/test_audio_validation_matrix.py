from __future__ import annotations

import copy
import unittest

from bdo_music_composer.audio.bdo_audio_validation import (
    verified_instrument_articulations,
)
from bdo_music_composer.audio.bdo_instrument_samples import (
    preview_route_ntype,
    select_zone_variants,
)
from tools.generate_audio_validation_matrix import build_validation_matrix


def _row(
    source_id: int,
    key_min: int,
    key_max: int,
    root_note: int,
    group_id: int,
) -> dict:
    return {
        "sound_id": source_id + 1000,
        "source_id": source_id,
        "root_note": root_note,
        "key_min": key_min,
        "key_max": key_max,
        "velocity_min": 0,
        "velocity_max": 127,
        "route_ntypes": [0],
        "selection_group_id": group_id,
        "wav_exists": True,
    }


class AudioValidationMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bank = "midi_instrument_16_proharp"
        self.rows = [
            _row(101, 55, 60, 12, 1),
            _row(102, 61, 64, 64, 2),
        ]
        self.mapping = {
            "format": 2,
            "evidence_sha256": "evidence-revision",
            "banks": {self.bank: self.rows},
        }
        self.matrix = build_validation_matrix(
            self.mapping,
            {0x10: "harp"},
            {0x10: ((0, "sustain"),)},
        )

    def test_probes_are_inside_actual_selected_runtime_segments(self) -> None:
        cells = self.matrix["cells"]

        self.assertEqual(self.matrix["format"], 2)
        self.assertTrue(cells)
        self.assertNotIn(12, {cell["pitch"] for cell in cells})
        for cell in cells:
            self.assertLessEqual(cell["key_min"], cell["pitch"])
            self.assertLessEqual(cell["pitch"], cell["key_max"])
            variants = select_zone_variants(
                self.rows,
                cell["pitch"],
                cell["velocity"],
                preview_route_ntype(0x10, cell["requested_ntype"]),
                bank=self.bank,
            )
            self.assertEqual(
                set(cell["source_ids"]),
                {row["source_id"] for row in variants},
            )

    def test_pair_requires_every_current_selection_valid_probe(self) -> None:
        pair = (0x10, 0)

        self.assertEqual(
            verified_instrument_articulations(
                self.matrix,
                "evidence-revision",
            ),
            frozenset(),
        )
        verified = copy.deepcopy(self.matrix)
        for cell in verified["cells"]:
            cell["verification"] = "verified"
        self.assertEqual(
            verified_instrument_articulations(
                verified,
                "evidence-revision",
            ),
            frozenset({pair}),
        )

        verified["cells"][0]["selection_valid"] = False
        self.assertEqual(
            verified_instrument_articulations(
                verified,
                "evidence-revision",
            ),
            frozenset(),
        )

        incomplete = copy.deepcopy(self.matrix)
        incomplete["cells"] = incomplete["cells"][1:]
        for cell in incomplete["cells"]:
            cell["verification"] = "verified"
        self.assertEqual(
            verified_instrument_articulations(
                incomplete,
                "evidence-revision",
            ),
            frozenset(),
        )

    def test_stale_and_legacy_matrices_fail_closed(self) -> None:
        verified = copy.deepcopy(self.matrix)
        for cell in verified["cells"]:
            cell["verification"] = "verified"

        self.assertEqual(
            verified_instrument_articulations(verified, "other-revision"),
            frozenset(),
        )
        verified["format"] = 1
        self.assertEqual(
            verified_instrument_articulations(
                verified,
                "evidence-revision",
            ),
            frozenset(),
        )

    def test_unmodeled_pitch_rtpc_probe_cannot_be_verified(self) -> None:
        mapping = copy.deepcopy(self.mapping)
        for row in mapping["banks"][self.bank]:
            row["unmodeled_pitch_rtpc"] = True
        matrix = build_validation_matrix(
            mapping,
            {0x10: "harp"},
            {0x10: ((0, "sustain"),)},
        )
        for cell in matrix["cells"]:
            cell["verification"] = "verified"

        self.assertTrue(matrix["cells"])
        self.assertTrue(
            all(not cell["selection_valid"] for cell in matrix["cells"])
        )
        self.assertEqual(
            verified_instrument_articulations(
                matrix,
                "evidence-revision",
            ),
            frozenset(),
        )


if __name__ == "__main__":
    unittest.main()
