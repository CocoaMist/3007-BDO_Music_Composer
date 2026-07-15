from __future__ import annotations

from collections import Counter, namedtuple
import unittest

from optimization import OptimizerConfig
from optimization.plugin_api import OptimizationIntensity
from optimization.plugin_host import analyse_with_algorithm, discover_host_algorithms
from pyside_bdo_gui import BDO_ARTICULATIONS, TrackState


Note = namedtuple("Note", "pitch vel start dur ntype", defaults=(0,))


class OptimizerPluginHostTests(unittest.TestCase):
    def test_builtin_intensities_remain_deterministic_and_game_safe(self) -> None:
        source = [
            TrackState(1, [Note(60, 72, 3, 397, 4), Note(64, 101, 503, 360, 0)], 0, False, "lead", 0x0B),
            TrackState(2, [Note(48, 80, 0, 900, 0)], 32, False, "bass", 0x0E),
        ]
        descriptor = discover_host_algorithms().algorithms[0]
        config = OptimizerConfig(
            target_track_ids=frozenset({1}),
            supported_pitches={0x0B: frozenset(range(36, 97)), 0x0E: frozenset(range(36, 97))},
        )
        for intensity in OptimizationIntensity:
            first = analyse_with_algorithm(
                descriptor, source, 120, 4, BDO_ARTICULATIONS, config, intensity, "single_track"
            )
            second = analyse_with_algorithm(
                descriptor, source, 120, 4, BDO_ARTICULATIONS, config, intensity, "single_track"
            )
            self.assertEqual(first.preview, second.preview)
            result, effects = first.apply(source)
            self.assertEqual(len(result[0].notes), len(source[0].notes))
            self.assertEqual(Counter(note.pitch for note in result[0].notes), Counter(note.pitch for note in source[0].notes))
            self.assertEqual(result[0].bdo_instrument_id, source[0].bdo_instrument_id)
            self.assertEqual(result[1].notes, source[1].notes)
            self.assertIsNone(effects)


if __name__ == "__main__":
    unittest.main()
