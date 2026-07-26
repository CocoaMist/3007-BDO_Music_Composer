from __future__ import annotations

from collections import Counter, namedtuple
import unittest
from unittest.mock import patch

from optimization import OptimizerConfig
from optimization.plugin_api import OptimizationIntensity
from optimization.plugin_host import (
    HostAlgorithmDescriptor,
    HostOptimizationError,
    analyse_with_algorithm,
    discover_host_algorithms,
)
from pyside_bdo_gui import BDO_ARTICULATIONS, TrackState


Note = namedtuple("Note", "pitch vel start dur ntype", defaults=(0,))


class OptimizerPluginHostTests(unittest.TestCase):
    @staticmethod
    def _external_descriptor() -> HostAlgorithmDescriptor:
        return HostAlgorithmDescriptor(
            algorithm_id="third-party",
            version="1",
            display_name="Third Party",
            description="External test optimizer",
            scopes=("global",),
            capabilities=(),
            requires_safe_prepass=False,
            bundle=object(),  # type: ignore[arg-type]
        )

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

    def test_builtin_optimizer_does_not_fail_on_preexisting_mapping_issues(self) -> None:
        descriptor = discover_host_algorithms().algorithms[0]
        source = [
            TrackState(1, [Note(101, 72, 3, 397, 0)], 0, False, "lead", 0x0B),
            TrackState(2, [Note(36, 90, 0, 600, 0)], 0, True, "drums", 0x0D),
        ]
        config = OptimizerConfig(
            target_track_ids=frozenset({1, 2}),
            supported_pitches={
                0x0B: frozenset(range(36, 97)),
                0x0D: frozenset(range(48, 65)),
            },
        )
        session = analyse_with_algorithm(
            descriptor,
            source,
            120,
            4,
            BDO_ARTICULATIONS,
            config,
            OptimizationIntensity.BALANCED,
            "global",
            frozenset({0x0B, 0x0D}),
        )
        result, _effects = session.apply(source)
        self.assertEqual([note.pitch for note in result[0].notes], [101])
        self.assertEqual([(note.pitch, note.ntype) for note in result[1].notes], [(36, 0)])
        self.assertTrue(any("转换检查" in item for item in session.preview.diagnostics))

    def test_host_and_plugin_errors_keep_distinct_provenance(self) -> None:
        descriptor = self._external_descriptor()
        source = [
            TrackState(1, [Note(60, 72, 0, 400, 0)], 0, False, "lead", 0x0B),
        ]
        config = OptimizerConfig(target_track_ids=frozenset({1}))

        with self.assertRaises(HostOptimizationError):
            analyse_with_algorithm(
                descriptor,
                source,
                120,
                4,
                BDO_ARTICULATIONS,
                config,
                OptimizationIntensity.BALANCED,
                "single_track",
            )

        class ExplodingPlugin:
            def analyse(self, request, environment):
                # A plugin cannot forge host-owned provenance by importing
                # and raising the host marker itself.
                raise HostOptimizationError("song exceeds the optimizer note limit")

        with patch(
            "optimization.plugin_host.load_optimizer_bundle",
            return_value=(ExplodingPlugin(), object()),
        ):
            with self.assertRaises(RuntimeError) as raised:
                analyse_with_algorithm(
                    descriptor,
                    source,
                    120,
                    4,
                    BDO_ARTICULATIONS,
                    config,
                    OptimizationIntensity.BALANCED,
                    "global",
                )
        self.assertNotIsInstance(raised.exception, HostOptimizationError)
        self.assertEqual(
            str(raised.exception),
            "song exceeds the optimizer note limit",
        )


if __name__ == "__main__":
    unittest.main()
