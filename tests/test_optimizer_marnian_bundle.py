from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from optimization import OptimizerConfig
from optimization.plugin_api import OptimizationIntensity
from optimization.plugin_host import analyse_with_algorithm, discover_host_algorithms
from pyside_bdo_gui import BDO_ARTICULATIONS, Note, TrackState, channel_groups_to_bdo

try:
    from marnian_muse.plugin_bundle import build_plugin_bundle
except ImportError:
    build_plugin_bundle = None


@unittest.skipIf(build_plugin_bundle is None, "Marnian Muse builder is not installed")
class MarnianBundleIntegrationTests(unittest.TestCase):
    def source(self) -> list[TrackState]:
        notes = []
        for beat in range(0, 16, 4):
            notes.extend(Note(pitch, 84, beat * 500, 1800, 4) for pitch in (48, 52, 55))
            notes.extend(Note(72 + offset, 100, (beat + offset) * 500, 340, 4) for offset in (0, 2, 4, 5))
        return [TrackState(1, notes, 0, False, "melody", 0x0B)]

    def test_real_bundle_is_discovered_lazily_and_runs_all_intensity_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugins = root / "plugins"
            plugins.mkdir()
            build_plugin_bundle(plugins / "marnian-muse.bdoopt")
            with patch.dict(os.environ, {
                "BDO_OPTIMIZER_DIR": str(plugins),
                "BDO_OPTIMIZER_CACHE": str(root / "cache"),
            }):
                descriptor = next(
                    item for item in discover_host_algorithms().algorithms
                    if item.algorithm_id == "marnian-muse"
                )
                self.assertEqual(descriptor.scopes, ("global",))
                self.assertFalse((root / "cache").exists())
                previews = []
                for intensity in OptimizationIntensity:
                    tracks = self.source()
                    config = OptimizerConfig(
                        target_track_ids=frozenset({1}),
                        supported_pitches={0x0B: frozenset(range(36, 85))},
                    )
                    session = analyse_with_algorithm(
                        descriptor, tracks, 120, 4, BDO_ARTICULATIONS, config, intensity, "global"
                    )
                    previews.append(session.preview)
                    result, _effect = session.apply(tracks)
                    self.assertEqual(result[0].notes[0].ntype, 4)
                self.assertTrue((root / "cache").exists())
                self.assertGreaterEqual(len(previews[1].operations), len(previews[0].operations))
                self.assertGreater(len(session.apply(self.source())[0]), 1)

                result = session.apply(self.source())[0]
                data, summary = channel_groups_to_bdo(
                    120, 4,
                    [(item.notes, item.gm_program, item.is_percussion) for item in result],
                    char_name="MarnianBundle",
                    instrument_map={index: item.bdo_instrument_id for index, item in enumerate(result)},
                    preserve_note_types=True,
                )
                self.assertTrue(data)
                self.assertEqual(summary["total_notes"], sum(len(item.notes) for item in result))


if __name__ == "__main__":
    unittest.main()
