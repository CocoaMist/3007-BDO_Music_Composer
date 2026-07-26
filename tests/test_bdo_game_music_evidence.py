from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BdoGameMusicEvidenceTests(unittest.TestCase):
    def test_authoring_mixer_contract_is_path_free_and_bounded(self) -> None:
        payload = json.loads(
            (ROOT / "data" / "codec" / "bdo_v9_evidence.json").read_text(
                encoding="utf-8"
            )
        )
        volume = payload["wire_fields"]["track_volume"]
        self.assertEqual([0, 100], volume["authoring_range"])
        self.assertEqual(70, volume["authoring_default"])
        self.assertEqual(1, volume["authoring_step"])

        settings = payload["wire_fields"]["track_settings"]
        self.assertEqual(8, settings["bytes"])
        self.assertEqual([0, 100], settings["authoring_range"])
        self.assertEqual(
            [
                "instrument_reverb_send",
                "master_reverb_time",
                "instrument_delay_send",
                "master_delay_feedback",
                "instrument_chorus_send",
                "master_chorus_feedback",
                "master_chorus_lfo_depth",
                "master_chorus_lfo_frequency",
            ],
            settings["inferred_layout"],
        )
        authoring = payload["authoring_ui"]
        self.assertEqual(757, authoring["meta_version"])
        self.assertEqual([0] * 8, authoring["effect_defaults"])
        serialized = json.dumps(authoring, ensure_ascii=True).lower()
        self.assertNotIn("f:\\", serialized)
        self.assertNotIn("users", serialized)

    def test_authoring_editor_contract_keeps_runtime_and_wire_claims_separate(self) -> None:
        payload = json.loads(
            (ROOT / "data" / "codec" / "bdo_v9_evidence.json").read_text(
                encoding="utf-8"
            )
        )
        contract = payload["authoring_ui"]["editor_contract"]

        self.assertEqual(
            ["3/4", "4/4", "6/8"],
            [item["label"] for item in contract["meters"]],
        )
        self.assertEqual([3, 4, 6], [item["xml_beat"] for item in contract["meters"]])
        self.assertEqual([4, 8, 16, 32, 64], contract["grid_divisions"])
        self.assertEqual(64, contract["internal_snap_division"])
        self.assertEqual(
            {"minimum": 20, "maximum": 200, "step": 10},
            contract["zoom_percent"],
        )

        limits = contract["runtime_limits"]
        self.assertEqual(["codeCount", "noteCount", "max_bpm"], limits["fields"])
        self.assertEqual("active instrument in the authoring UI", limits["note_count_scope"])
        self.assertFalse(limits["serialized_in_score_xml"])

        self.assertEqual(
            ["bpm", "newbpm", "startTime"],
            contract["transport_xml"]["header_fields"],
        )
        self.assertFalse(contract["view_state_serialized_in_score_xml"])
        self.assertIn("loop", contract["not_present_in_reviewed_authoring_resources"])
        self.assertIn("independent_track_mute", contract["not_present_in_reviewed_authoring_resources"])

        # This evidence file may be shipped, so it must contain no local source path.
        serialized = json.dumps(contract, ensure_ascii=True).lower()
        self.assertNotIn("f:\\", serialized)
        self.assertNotIn("users", serialized)


if __name__ == "__main__":
    unittest.main()
