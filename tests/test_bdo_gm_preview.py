from __future__ import annotations

import unittest

from bdo_midi import (
    BDO_INSTRUMENT_NAMES,
    BDO_TO_GM_PREVIEW_ROUTE,
    gm_preview_layers,
    gm_preview_pitch,
    gm_preview_route,
)


class BdoGmPreviewMappingTests(unittest.TestCase):
    def test_every_declared_bdo_instrument_has_exactly_one_route(self) -> None:
        self.assertEqual(
            set(BDO_TO_GM_PREVIEW_ROUTE),
            set(BDO_INSTRUMENT_NAMES),
        )
        for instrument_id, route in BDO_TO_GM_PREVIEW_ROUTE.items():
            with self.subTest(instrument_id=instrument_id):
                self.assertLessEqual(0, route.bank, 128)
                self.assertLessEqual(0, route.program, 127)
                self.assertEqual(
                    route.fallback_bank is None,
                    route.fallback_program is None,
                )
                if route.fallback_bank is not None:
                    self.assertLessEqual(0, route.fallback_bank, 128)
                    self.assertLessEqual(0, route.fallback_program, 127)

    def test_acoustic_electric_and_orchestral_routes_are_deliberate(self) -> None:
        self.assertEqual(gm_preview_route(0x00).program, 24)
        self.assertEqual(gm_preview_route(0x0A).program, 25)
        self.assertEqual(gm_preview_route(0x24).program, 27)
        self.assertEqual(gm_preview_route(0x25).program, 29)
        self.assertEqual(gm_preview_route(0x26).program, 30)
        self.assertEqual(gm_preview_route(0x0F).program, 43)
        self.assertEqual(gm_preview_route(0x13).program, 114)
        self.assertEqual(gm_preview_route(0x27).program, 71)
        self.assertEqual(gm_preview_route(0x28).program, 60)

    def test_marnian_waveforms_and_serialized_ids_resolve_to_base_routes(self) -> None:
        self.assertEqual(gm_preview_route(0x14).waveform, "saw")
        self.assertEqual(gm_preview_route(0x18).waveform, "sine")
        self.assertEqual(gm_preview_route(0x1C).waveform, "square")
        self.assertEqual(gm_preview_route(0x20).waveform, "triangle")
        self.assertEqual(gm_preview_route(0x17), gm_preview_route(0x14))
        self.assertEqual(gm_preview_route(0x1B), gm_preview_route(0x18))

    def test_marnian_modes_have_bounded_deterministic_layers(self) -> None:
        self.assertEqual(len(gm_preview_layers(0x14, "basic")), 1)
        self.assertEqual(len(gm_preview_layers(0x14, "stereo")), 2)
        self.assertEqual(len(gm_preview_layers(0x14, "super")), 3)
        superoct = gm_preview_layers(0x14, "superoct")
        self.assertEqual(len(superoct), 3)
        self.assertIn(12, {layer.semitones for layer in superoct})
        self.assertEqual(
            gm_preview_layers(0x14, "unknown"),
            gm_preview_layers(0x14, "basic"),
        )
        self.assertEqual(len(gm_preview_layers(0x11, "superoct")), 1)
        for mode in ("basic", "stereo", "super", "superoct"):
            for layer in gm_preview_layers(0x14, mode):
                self.assertLessEqual(abs(layer.cents), 12.0)
                self.assertLessEqual(abs(layer.pan), 1.0)
                self.assertGreater(layer.gain, 0.0)
                self.assertLessEqual(layer.gain, 1.0)

    def test_game_drum_lanes_map_to_semantic_gm_pitches(self) -> None:
        expected = {
            48: 36,
            49: 37,
            50: 38,
            53: 50,
            54: 42,
            56: 44,
            58: 46,
            61: 49,
            62: 51,
            63: 38,
            64: 38,
        }
        for bdo_pitch, gm_pitch in expected.items():
            with self.subTest(bdo_pitch=bdo_pitch):
                self.assertEqual(gm_preview_pitch(0x0D, bdo_pitch), gm_pitch)

    def test_cymbal_lanes_and_melodic_pitches_do_not_cross_semantics(self) -> None:
        self.assertEqual(gm_preview_pitch(0x05, 60), 49)
        self.assertEqual(gm_preview_pitch(0x05, 65), 51)
        self.assertEqual(gm_preview_pitch(0x05, 71), 57)
        self.assertEqual(gm_preview_pitch(0x13, 69), 69)
        self.assertEqual(gm_preview_pitch(0x11, 200), 127)

    def test_unknown_instrument_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "no General MIDI preview route"):
            gm_preview_route(0x7F)


if __name__ == "__main__":
    unittest.main()
