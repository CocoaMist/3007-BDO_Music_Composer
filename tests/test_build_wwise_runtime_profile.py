from __future__ import annotations

import unittest
from pathlib import Path
import tempfile

from tools.build_wwise_runtime_profile import (
    atomic_text_output,
    bank_sections,
    build_bank_profile,
    parse_modulators,
    parse_bank_dump,
    parse_rtpc_bindings,
    runtime_profile_document,
)


SYNTHETIC_SECTION = """
                   obj  CAkEnvelopeModulator[0]
00000000              sid  ulID = 700
00000001                   u8   pID = 0x09 [Envelope_AttackTime]
00000002                   uni  pValue = 0.05
00000003                   u8   pID = 0x0B [Envelope_DecayTime]
00000004                   uni  pValue = 0.5
00000005                   u8   pID = 0x0C [Envelope_SustainLevel]
00000006                   uni  pValue = 55.0
00000007                   u8   pID = 0x0E [Envelope_ReleaseTime]
00000008                   uni  pValue = 0.2
                   obj  CAkLFOModulator[1]
00000009              sid  ulID = 701
0000000a                   u8   pID = 0x05 [Lfo_Depth]
0000000b                   uni  pValue = 100.0
0000000c                   u8   pID = 0x07 [Lfo_Frequency]
0000000d                   uni  pValue = 6.0
                   obj  CAkLayerCntr[2]
0000000e              sid  ulID = 800
                         obj  InitialRTPC
0000000f                    u16  uNumCurves = 2
                               lst  pRTPCMgr
                                  obj  RTPC[0]
00000010                             tid  RTPCID = 129
00000011                             u8   rtpcType = 0x01 [MIDIParameter]
00000012                             u8   rtpcAccum = 0x02 [Additive]
00000013                             var  ParamID = 0x00 [Volume]
00000014                             sid  rtpcCurveID = 900
00000015                             u8   eScaling = 0x02 [dB]
00000016                             u16  ulSize = 2
                                        obj  AkRTPCGraphPoint[0]
00000017                                   f32  From = 0.0
00000018                                   f32  To = -1.0
00000019                                   u32  Interp = 0x04 [Linear]
                                        obj  AkRTPCGraphPoint[1]
0000001a                                   f32  From = 127.0
0000001b                                   f32  To = 0.0
0000001c                                   u32  Interp = 0x04 [Linear]
                                  obj  RTPC[1]
0000001d                             tid  RTPCID = 701
0000001e                             u8   rtpcType = 0x04 [Modulator]
0000001f                             u8   rtpcAccum = 0x01 [Filter]
00000020                             var  ParamID = 0x02 [LPF]
00000021                             sid  rtpcCurveID = 901
00000022                             u8   eScaling = 0x00 [None]
00000023                             u16  ulSize = 2
                                        obj  AkRTPCGraphPoint[0]
00000024                                   f32  From = 0.0
00000025                                   f32  To = 100.0
00000026                                   u32  Interp = 0x04 [Linear]
                                        obj  AkRTPCGraphPoint[1]
00000027                                   f32  From = 1.0
00000028                                   f32  To = 0.0
00000029                                   u32  Interp = 0x04 [Linear]
                         obj  Children
0000002a                    u32  ulNumChilds = 0
"""


def sample_zone() -> dict:
    return {
        "source_id": 10,
        "key_min": 48,
        "key_max": 72,
        "velocity_min": 0,
        "velocity_max": 127,
        "route_ntypes": [0, 3],
        "sample_loops": 1,
        "release_ms": 200.0,
        "selection_group_id": 800,
        "selection_mode": "random",
        "avoid_repeat": 1,
        "selection_continuous": False,
        "selection_global": True,
        "selection_reset_playlist": True,
        "instance_group_id": 800,
        "max_instances": 2,
        "kill_newest": False,
        "instance_limit_global": False,
        "instance_use_virtual_behavior": False,
    }


class WwiseRuntimeProfileTests(unittest.TestCase):
    def test_bank_sections_are_named_without_filename_suffix(self) -> None:
        text = (
            " bank v145 midi_instrument_a.bnk\nA\n"
            " bank v145 midi_instrument_b.bnk\nB\n"
        )

        sections = bank_sections(text)

        self.assertEqual({"midi_instrument_a", "midi_instrument_b"}, set(sections))
        self.assertIn("A", sections["midi_instrument_a"])
        self.assertIn("B", sections["midi_instrument_b"])

    def test_bank_dump_preserves_versions_and_rejects_duplicates(self) -> None:
        sections, versions = parse_bank_dump(
            " bank v145 midi_instrument_a.bnk\nA\n"
        )

        self.assertEqual({"midi_instrument_a": 145}, versions)
        self.assertIn("A", sections["midi_instrument_a"])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_bank_dump(
                " bank v145 midi_instrument_a.bnk\nA\n"
                " bank v146 midi_instrument_a.bnk\nB\n"
            )

    def test_modulator_properties_remain_raw_audit_evidence(self) -> None:
        modulators = parse_modulators(SYNTHETIC_SECTION)

        self.assertEqual(["envelope", "lfo"], [item["type"] for item in modulators])
        self.assertEqual(0.05, modulators[0]["properties"]["Envelope_AttackTime"])
        self.assertEqual(55.0, modulators[0]["properties"]["Envelope_SustainLevel"])
        self.assertEqual(6.0, modulators[1]["properties"]["Lfo_Frequency"])

    def test_rtpc_bindings_keep_scaling_interpolation_and_points(self) -> None:
        bindings = parse_rtpc_bindings(SYNTHETIC_SECTION)

        self.assertEqual(2, len(bindings))
        velocity = bindings[0]
        self.assertEqual("MIDIParameter", velocity["rtpc_type"])
        self.assertEqual("Volume", velocity["parameter"])
        self.assertEqual("dB", velocity["scaling"])
        self.assertEqual(
            [
                {"x": 0.0, "y": -1.0, "interpolation": "Linear"},
                {"x": 127.0, "y": 0.0, "interpolation": "Linear"},
            ],
            velocity["points"],
        )
        low_pass = bindings[1]
        self.assertEqual("Filter", low_pass["accumulation"])
        self.assertEqual("LPF", low_pass["parameter"])

    def test_profile_summarizes_runtime_facts_without_private_path(self) -> None:
        bank = "midi_instrument_test"
        mapping = {"banks": {bank: [sample_zone()]}}

        document = runtime_profile_document(
            mapping,
            {bank: SYNTHETIC_SECTION},
            dump_name=r"C:\private\machine\wwiser-dump.txt",
        )
        profile = document["banks"][bank]

        self.assertEqual(2, document["format"])
        self.assertEqual("wwiser-dump.txt", document["source_dump_name"])
        self.assertNotIn("private", str(document))
        self.assertEqual([[48, 72]], [list(value) for value in profile["key_ranges"]])
        self.assertEqual([0, 3], [item["ntype"] for item in profile["articulation_routes"]])
        self.assertEqual(1, profile["sample_loop_rows"])
        self.assertEqual(2, profile["instance_groups"][0]["max_instances"])
        self.assertEqual(2, len(profile["hirc"]["rtpc_bindings"]))

    def test_build_bank_profile_is_deterministic(self) -> None:
        first = build_bank_profile("bank", [sample_zone()], SYNTHETIC_SECTION)
        second = build_bank_profile("bank", [sample_zone()], SYNTHETIC_SECTION)

        self.assertEqual(first, second)

    def test_group_metadata_conflicts_fail_closed(self) -> None:
        first = sample_zone()
        second = sample_zone()
        second["selection_mode"] = "sequence"

        with self.assertRaisesRegex(ValueError, "conflicting"):
            build_bank_profile("bank", [first, second], SYNTHETIC_SECTION)

    def test_atomic_profile_output_preserves_previous_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "profile.json"
            target.write_text("old", encoding="utf-8")

            with self.assertRaises(RuntimeError):
                with atomic_text_output(target) as output:
                    output.write("partial")
                    raise RuntimeError("stop")

            self.assertEqual("old", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
