from __future__ import annotations

from types import SimpleNamespace
import unittest

from bdo_music_composer.editor.editor_import import (
    TrackImportPresentation,
    tracks_from_bdo_snapshot,
)


PRESENTATION = TrackImportPresentation(
    colors=("#123456",),
    bdo_instrument_name=lambda instrument_id: f"BDO {instrument_id}",
    gm_program_name=lambda program: f"GM {program}",
    drum_track_name=lambda: "Drums",
    new_track_name=lambda track_id: f"Track {track_id}",
)


def track_states_from_bdo_score(snapshot: object) -> list[object]:
    return list(tracks_from_bdo_snapshot(snapshot, PRESENTATION))


def physical_track(
    group_index: int,
    track_index: int,
    *,
    instrument_id: int = 0x0B,
    volume: int = 70,
    settings: tuple[int, ...] = (10, 20, 30, 40, 50, 60, 70, 80),
) -> SimpleNamespace:
    return SimpleNamespace(
        group_index=group_index,
        track_index=track_index,
        instrument_id=instrument_id,
        volume=volume,
        settings=settings,
        notes=(),
    )


class BdoImportEffectConflictTests(unittest.TestCase):
    def test_consistent_physical_chunks_collapse_losslessly(self) -> None:
        first = physical_track(0, 0)
        second = physical_track(0, 1)
        states = track_states_from_bdo_score(
            SimpleNamespace(tracks=(first, second))
        )
        self.assertEqual(len(states), 1)
        self.assertEqual(states[0].bdo_track_volume, 70)
        self.assertEqual(states[0].bdo_track_settings, first.settings)

    def test_conflicting_chunk_volume_is_rejected(self) -> None:
        snapshot = SimpleNamespace(tracks=(
            physical_track(0, 0, volume=70),
            physical_track(0, 1, volume=71),
        ))
        with self.assertRaisesRegex(ValueError, "conflicting volumes"):
            track_states_from_bdo_score(snapshot)

    def test_conflicting_chunk_effect_settings_are_rejected(self) -> None:
        snapshot = SimpleNamespace(tracks=(
            physical_track(0, 0),
            physical_track(
                0,
                1,
                settings=(11, 20, 30, 40, 50, 60, 70, 80),
            ),
        ))
        with self.assertRaisesRegex(ValueError, "conflicting effect settings"):
            track_states_from_bdo_score(snapshot)

    def test_conflicting_shared_master_effects_are_rejected(self) -> None:
        snapshot = SimpleNamespace(tracks=(
            physical_track(0, 0),
            physical_track(
                1,
                0,
                instrument_id=0x0C,
                settings=(90, 21, 30, 40, 50, 60, 70, 80),
            ),
        ))
        with self.assertRaisesRegex(ValueError, "conflicting master"):
            track_states_from_bdo_score(snapshot)

    def test_different_per_instrument_sends_share_one_master(self) -> None:
        snapshot = SimpleNamespace(tracks=(
            physical_track(0, 0),
            physical_track(
                1,
                0,
                instrument_id=0x0C,
                settings=(90, 20, 31, 40, 51, 60, 70, 80),
            ),
        ))
        states = track_states_from_bdo_score(snapshot)
        self.assertEqual(len(states), 2)
        self.assertNotEqual(
            states[0].bdo_track_settings[0::2],
            states[1].bdo_track_settings[0::2],
        )


if __name__ == "__main__":
    unittest.main()
