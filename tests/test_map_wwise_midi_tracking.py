from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.map_wwise_midi_tracking import (
    Node,
    atomic_write_text,
    effective_props,
    instance_limit_metadata,
    lineage_release_ms,
    lineage_volume_db,
    mapping_document,
    main,
    parse_nodes,
    portable_media_path,
    read_wem_sample_loops,
    recover_event_routes,
    selection_metadata,
    wwise_fnv1,
)


class WwiseMidiMappingTests(unittest.TestCase):
    def test_event_hash_recovers_proguitar_routes_without_swap(self) -> None:
        bank = "midi_instrument_10_proguitar"
        basic_event = wwise_fnv1(f"{bank}_00")
        staccato_event = wwise_fnv1(f"{bank}_03")
        nodes = {
            basic_event: Node(
                basic_event,
                "CAkEvent",
                None,
                None,
                action_ids=(101,),
            ),
            staccato_event: Node(
                staccato_event,
                "CAkEvent",
                None,
                None,
                action_ids=(102,),
            ),
            101: Node(
                101,
                "CAkActionPlay",
                None,
                None,
                target_id=542847829,
            ),
            102: Node(
                102,
                "CAkActionPlay",
                None,
                None,
                target_id=765268389,
            ),
            542847829: Node(
                542847829,
                "CAkLayerCntr",
                None,
                None,
            ),
            765268389: Node(
                765268389,
                "CAkLayerCntr",
                None,
                None,
            ),
        }

        routes = recover_event_routes(bank, nodes)
        by_ntype = {route.ntype: route for route in routes}

        self.assertEqual(1778814687, basic_event)
        self.assertEqual(1778814684, staccato_event)
        self.assertEqual(542847829, by_ntype[0].target_id)
        self.assertEqual(765268389, by_ntype[3].target_id)

    def test_event_routes_keep_multiple_ntypes_for_one_target(self) -> None:
        bank = "midi_instrument_test"
        target_id = 900
        nodes = {
            target_id: Node(
                target_id,
                "CAkLayerCntr",
                None,
                None,
            ),
        }
        for ntype, action_id in ((0, 100), (99, 199)):
            event_id = wwise_fnv1(
                f"{bank}_{ntype:02d}" if ntype < 10 else f"{bank}_{ntype}"
            )
            nodes[event_id] = Node(
                event_id,
                "CAkEvent",
                None,
                None,
                action_ids=(action_id,),
            )
            nodes[action_id] = Node(
                action_id,
                "CAkActionPlay",
                None,
                None,
                target_id=target_id,
            )

        routes = recover_event_routes(bank, nodes)

        self.assertEqual([0, 99], [route.ntype for route in routes])
        self.assertTrue(all(route.target_id == target_id for route in routes))

    def test_parent_midi_ranges_are_intersected(self) -> None:
        root = Node(
            1,
            "CAkLayerCntr",
            None,
            None,
            props={
                "MidiTrackingRootNote": 60,
                "MidiKeyRangeMin": 40,
                "MidiKeyRangeMax": 80,
                "MidiVelocityRangeMin": 20,
                "MidiVelocityRangeMax": 100,
            },
        )
        child = Node(
            2,
            "CAkRanSeqCntr",
            1,
            None,
            props={
                "MidiKeyRangeMin": 50,
                "MidiKeyRangeMax": 70,
                "MidiVelocityRangeMin": 30,
                "MidiVelocityRangeMax": 90,
            },
        )
        sound = Node(
            3,
            "CAkSound",
            2,
            4,
            props={
                "MidiKeyRangeMin": 55,
                "MidiVelocityRangeMax": 80,
            },
        )

        props = effective_props(sound, {1: root, 2: child, 3: sound})

        self.assertEqual(60, props["MidiTrackingRootNote"])
        self.assertEqual(1, props["MidiTrackingRootNoteOwnerID"])
        self.assertEqual(
            2,
            props["MidiTrackingRootNoteInheritanceDepth"],
        )
        self.assertEqual(0, props["MidiTrackingRootNoteInferred"])
        self.assertEqual((55, 70), (
            props["MidiKeyRangeMin"],
            props["MidiKeyRangeMax"],
        ))
        self.assertEqual((30, 80), (
            props["MidiVelocityRangeMin"],
            props["MidiVelocityRangeMax"],
        ))

    def test_missing_root_records_midpoint_inference_provenance(self) -> None:
        sound = Node(
            3,
            "CAkSound",
            None,
            4,
            props={
                "MidiKeyRangeMin": 55,
                "MidiKeyRangeMax": 60,
            },
        )

        props = effective_props(sound, {3: sound})

        self.assertEqual(57, props["MidiTrackingRootNote"])
        self.assertIsNone(props["MidiTrackingRootNoteOwnerID"])
        self.assertIsNone(
            props["MidiTrackingRootNoteInheritanceDepth"]
        )
        self.assertEqual(1, props["MidiTrackingRootNoteInferred"])

    def test_playlist_index_uses_authored_order_and_voice_settings(self) -> None:
        container = Node(
            10,
            "CAkRanSeqCntr",
            None,
            None,
            avoid_repeat=2,
            selection_mode="sequence",
            playlist_ids=(30, 20),
            playlist_weights=(40000, 60000),
            container_loop_count=3,
            continuous=True,
            global_scope=True,
            reset_playlist_each_play=True,
            max_instances=4,
            kill_newest=True,
        )
        sound = Node(20, "CAkSound", 10, 200)

        metadata = selection_metadata((sound, container))

        self.assertEqual(1, metadata["playlist_index"])
        self.assertEqual([30, 20], metadata["playlist_order"])
        self.assertEqual(60000, metadata["playlist_weight"])
        self.assertEqual(3, metadata["container_loop_count"])
        self.assertTrue(metadata["selection_continuous"])
        self.assertTrue(metadata["selection_global"])
        self.assertTrue(metadata["selection_reset_playlist"])
        self.assertEqual(4, metadata["selection_max_instances"])
        self.assertTrue(metadata["selection_kill_newest"])

    def test_parent_instance_limit_is_emitted_with_its_group(self) -> None:
        root = Node(
            10,
            "CAkLayerCntr",
            None,
            None,
            max_instances=3,
            kill_newest=False,
        )
        sound = Node(20, "CAkSound", 10, 200)

        metadata = instance_limit_metadata((sound, root))

        self.assertEqual(10, metadata["instance_group_id"])
        self.assertEqual(3, metadata["max_instances"])
        self.assertFalse(metadata["kill_newest"])
        self.assertEqual(
            [{
                "group_id": 10,
                "max_instances": 3,
                "kill_newest": False,
                "global_scope": False,
                "use_virtual_behavior": False,
            }],
            metadata["instance_limits"],
        )

    def test_ignore_parent_instance_limit_cuts_off_higher_group(self) -> None:
        parent = Node(
            10,
            "CAkLayerCntr",
            None,
            None,
            max_instances=5,
        )
        child = Node(
            20,
            "CAkLayerCntr",
            10,
            None,
            max_instances=1,
            ignore_parent_max_instances=True,
        )
        sound = Node(30, "CAkSound", 20, 300)

        metadata = instance_limit_metadata((sound, child, parent))

        self.assertEqual(20, metadata["instance_group_id"])
        self.assertEqual(1, metadata["max_instances"])
        self.assertEqual(1, len(metadata["instance_limits"]))

    def test_parser_reads_ranseq_gain_loop_and_modulator_evidence(self) -> None:
        section = """
                   obj  CAkEnvelopeModulator[0]
00000000              sid  ulID = 700
00000001                   u8   pID = 0x0E [Envelope_ReleaseTime]
00000002                   uni  pValue = 0.25
                   obj  CAkRanSeqCntr[1]
00000003              sid  ulID = 10
00000004              tid  DirectParentID = 0
00000005                   u8   pID = 0x00 [Volume]
00000006                   uni  pValue = -3.0
00000007                   u8   pID = 0x36 [MakeUpGain]
00000008                   uni  pValue = 1.5
00000009              u16  sLoopCount = 2
0000000a              u16  wAvoidRepeatCount = 1
0000000b              u8   eMode = 0x01 [Sequence]
                         obj  AdvSettingsParams
0000000b              u8   byBitVector = 0x0C
                    bit0 bKillNewest = 1
                    bit3 bIgnoreParentMaxNumInst = 1
                    bit1 bResetPlayListAtEachPlay = 1
                    bit3 bIsContinuous = 1
                    bit4 bIsGlobal = 1
0000000c              u16  u16MaxNumInstance = 5
                               obj  RTPC[0]
0000000d                         tid  RTPCID = 700
0000000e                         u8   rtpcType = 0x04 [Modulator]
0000000f                         var  ParamID = 0x00 [Volume]
                               obj  AkRTPCGraphPoint[0]
00000010                         f32  From = 0.0
                         obj  CAkPlayList
00000011                    tid  ulPlayID = 30
00000012                    s32  weight = 40000
00000013                    tid  ulPlayID = 20
00000014                    s32  weight = 60000
                   obj  CAkSound[2]
00000015              sid  ulID = 20
00000016              tid  sourceID = 200
00000017              tid  DirectParentID = 10
00000018                   u8   pID = 0x0F [Loop]
00000019                   uni  pValue = 0
                    bit5 bIsMidiBreakLoopOnNoteOff = 1
"""

        nodes = parse_nodes(section)
        container = nodes[10]
        sound = nodes[20]

        self.assertEqual(-3.0, container.volume_db)
        self.assertEqual(1.5, container.makeup_gain_db)
        self.assertEqual((30, 20), container.playlist_ids)
        self.assertEqual((40000, 60000), container.playlist_weights)
        self.assertEqual((700,), container.volume_envelope_modulator_ids)
        self.assertTrue(container.ignore_parent_max_instances)
        self.assertTrue(container.instance_limit_global)
        self.assertFalse(container.use_virtual_behavior)
        self.assertAlmostEqual(250.0, nodes[700].envelope_release_ms)
        self.assertEqual(0, sound.sound_loop_count)
        self.assertTrue(sound.midi_break_loop_on_note_off)
        self.assertAlmostEqual(
            -1.5,
            lineage_volume_db((sound, container)),
        )
        self.assertAlmostEqual(
            250.0,
            lineage_release_ms((sound, container), nodes),
        )

    def test_parser_preserves_unmodeled_pitch_rtpc_identity(self) -> None:
        section = """
                   obj  CAkSound[0]
00000000              sid  ulID = 20
00000001              tid  sourceID = 200
00000002              tid  DirectParentID = 0
                               obj  RTPC[0]
00000003                         tid  RTPCID = 701
00000004                         u8   rtpcType = 0x00 [GameParameter]
00000005                         var  ParamID = 0x02 [Pitch]
"""

        sound = parse_nodes(section)[20]

        self.assertEqual((701,), sound.pitch_rtpc_ids)

    def test_release_is_none_without_unambiguous_dump_evidence(self) -> None:
        sound = Node(1, "CAkSound", None, 2)
        missing = Node(
            2,
            "CAkLayerCntr",
            None,
            None,
            volume_envelope_modulator_ids=(99,),
        )
        mod_a = Node(
            3,
            "CAkEnvelopeModulator",
            None,
            None,
            envelope_release_ms=100.0,
        )
        mod_b = Node(
            4,
            "CAkEnvelopeModulator",
            None,
            None,
            envelope_release_ms=200.0,
        )
        conflicting = Node(
            5,
            "CAkLayerCntr",
            None,
            None,
            volume_envelope_modulator_ids=(3, 4),
        )

        self.assertIsNone(lineage_release_ms((sound,), {1: sound}))
        self.assertIsNone(
            lineage_release_ms((sound, missing), {1: sound, 2: missing})
        )
        self.assertIsNone(
            lineage_release_ms(
                (sound, conflicting),
                {1: sound, 3: mod_a, 4: mod_b, 5: conflicting},
            )
        )

    def test_reads_standard_smpl_loop_with_exclusive_end(self) -> None:
        smpl_header = struct.pack(
            "<9I",
            0,
            0,
            0,
            60,
            0,
            0,
            0,
            1,
            0,
        )
        loop = struct.pack("<6I", 0, 0, 100, 299, 0, 0)
        payload = smpl_header + loop
        wave = b"WAVE" + b"smpl" + struct.pack("<I", len(payload)) + payload
        riff = b"RIFF" + struct.pack("<I", len(wave)) + wave
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.wem"
            path.write_bytes(riff)

            loops = read_wem_sample_loops(path)

        self.assertEqual(1, len(loops))
        self.assertEqual(100, loops[0].start_frame)
        self.assertEqual(300, loops[0].end_frame)
        self.assertEqual(0, loops[0].play_count)

    def test_mapping_document_remains_additive_format_two(self) -> None:
        banks = {"midi_instrument_test": [{"source_id": 1}]}

        document = mapping_document(
            banks,
            bank_versions={145},
            dump_sha256="dump",
            evidence_sha256="evidence",
        )

        self.assertEqual(2, document["format"])
        self.assertIs(banks, document["banks"])
        self.assertEqual(
            "exclusive",
            document["loop_end_frame_semantics"],
        )
        self.assertEqual(145, document["wwise_bank_version"])
        self.assertEqual([145], document["wwise_bank_versions"])
        self.assertEqual("dump", document["source_dump_sha256"])
        self.assertEqual("evidence", document["evidence_sha256"])

    def test_portable_media_paths_are_platform_independent(self) -> None:
        self.assertEqual(
            "midi_instrument_test/123.wav",
            portable_media_path("midi_instrument_test", 123, "wav"),
        )

    def test_atomic_text_write_replaces_complete_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "mapping.json"
            target.write_text("old", encoding="utf-8")

            atomic_write_text(target, "new\n")

            self.assertEqual("new\n", target.read_text(encoding="utf-8"))

    def test_unsupported_bank_version_does_not_replace_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dump = root / "dump.txt"
            dump.write_text(
                "bank v146 midi_instrument_test.bnk\n",
                encoding="utf-8",
            )
            wem_root = root / "wem"
            wem_root.mkdir()
            tsv = root / "map.tsv"
            json_path = root / "map.json"
            tsv.write_text("old-tsv", encoding="utf-8")
            json_path.write_text("old-json", encoding="utf-8")

            with patch.object(sys, "argv", [
                "map_wwise_midi_tracking.py",
                str(dump),
                str(wem_root),
                "--tsv",
                str(tsv),
                "--json",
                str(json_path),
            ]):
                result = main()

            self.assertEqual(1, result)
            self.assertEqual("old-tsv", tsv.read_text(encoding="utf-8"))
            self.assertEqual("old-json", json_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
