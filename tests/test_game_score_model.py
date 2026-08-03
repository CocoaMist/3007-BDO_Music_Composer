from __future__ import annotations

from collections import namedtuple
from dataclasses import dataclass, field
import unittest

from bdo_music_composer.core.conversion_settings import ConversionSettings
from bdo_midi import (
    MARNIAN_SYNTH_INSTRUMENT_IDS,
    MARNIAN_SYNTH_MODE_OFFSETS,
)
from bdo_common.bdo_track_effects import (
    TRACK_CHORUS_SEND_INDEX,
    TRACK_DELAY_SEND_INDEX,
    TRACK_REVERB_SEND_INDEX,
)
from bdo_music_composer.editor.game_score_model import (
    GameInstrumentMix,
    bake_game_velocity_transform,
    bake_legacy_velocity_scale,
    decode_serialized_game_instrument_id,
    formal_score_tracks,
    inherit_game_instrument_mix,
    normalize_legacy_track_velocity,
    preview_tracks,
    propagate_game_instrument_mix,
    scaled_game_velocity,
    serialized_game_instrument_id,
)


Note = namedtuple("Note", "pitch vel start dur ntype", defaults=(0,))


@dataclass
class Track:
    track_id: int
    bdo_instrument_id: int = 0x11
    marnian_synth_mode: str = "basic"
    muted: bool = False
    solo: bool = False
    notes: list[Note] = field(default_factory=list)
    volume_scale: object = 1.0
    bdo_track_volume: object = 70
    bdo_track_settings: object = (0,) * 8


class GameInstrumentIdentityTests(unittest.TestCase):
    def test_marnian_mode_is_part_of_the_serialized_instrument_key(self) -> None:
        expected_ids = {
            "basic": 0x14,
            "stereo": 0x15,
            "super": 0x16,
            "superoct": 0x17,
        }
        for mode, expected_id in expected_ids.items():
            with self.subTest(mode=mode):
                self.assertEqual(
                    serialized_game_instrument_id(
                        Track(1, bdo_instrument_id=0x14, marnian_synth_mode=mode)
                    ),
                    expected_id,
                )

        # A mode label only changes the wire identity of a Marnian base ID.
        self.assertEqual(
            serialized_game_instrument_id(
                Track(2, bdo_instrument_id=0x11, marnian_synth_mode="superoct")
            ),
            0x11,
        )

    def test_every_marnian_wire_mode_round_trips(self) -> None:
        for base_id in MARNIAN_SYNTH_INSTRUMENT_IDS:
            for mode, offset in MARNIAN_SYNTH_MODE_OFFSETS.items():
                with self.subTest(base_id=base_id, mode=mode):
                    wire_id = serialized_game_instrument_id(
                        Track(
                            1,
                            bdo_instrument_id=base_id,
                            marnian_synth_mode=mode,
                        )
                    )
                    self.assertEqual(wire_id, base_id + offset)
                    self.assertEqual(
                        decode_serialized_game_instrument_id(wire_id),
                        (base_id, mode),
                    )

    def test_unknown_marnian_mode_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported Marnian"):
            serialized_game_instrument_id(
                Track(
                    1,
                    bdo_instrument_id=0x14,
                    marnian_synth_mode="future-mode",
                )
            )

    def test_formal_score_ignores_mute_and_solo_while_preview_applies_them(self) -> None:
        normal = Track(1)
        muted = Track(2, muted=True, solo=True)
        soloed = Track(3, solo=True)
        tracks = [normal, muted, soloed]

        self.assertEqual(formal_score_tracks(tracks), tuple(tracks))
        self.assertEqual(preview_tracks(tracks), (soloed,))

        muted.solo = False
        soloed.solo = False
        self.assertEqual(preview_tracks(tracks), (normal, soloed))
        self.assertEqual(formal_score_tracks(tracks), tuple(tracks))


class GameVelocityModelTests(unittest.TestCase):
    def test_legacy_scale_is_baked_and_clamped_in_the_game_velocity_field(self) -> None:
        self.assertEqual(scaled_game_velocity(91, 0.5), 46)
        self.assertEqual(scaled_game_velocity(100, 2), 127)
        self.assertEqual(scaled_game_velocity(-20, 1), 0)
        self.assertEqual(scaled_game_velocity(91, "invalid"), 91)

        notes = (
            Note(60, 100, 0, 100, 14),
            Note(64, 30, 100, 100, 0),
        )
        baked = bake_legacy_velocity_scale(notes, 0.5)
        self.assertEqual([note.vel for note in baked], [50, 15])
        self.assertEqual([note.ntype for note in baked], [14, 0])
        self.assertEqual(bake_legacy_velocity_scale(notes, 1.0), notes)

    def test_velocity_transform_materializes_policy_and_restores_note_types(self) -> None:
        notes = (
            Note(60, 10, 0, 100, 14),
            Note(64, 110, 100, 100, 3),
        )
        result = bake_game_velocity_transform(
            notes,
            ConversionSettings(velocity_mode="rescale", vel_range=(20, 100)),
        )
        self.assertEqual([note.vel for note in result], [20, 100])
        self.assertEqual([note.ntype for note in result], [14, 3])

        preserved = bake_game_velocity_transform(
            notes,
            ConversionSettings(velocity_mode="preserve"),
            legacy_scale=0.5,
        )
        self.assertEqual([note.vel for note in preserved], [5, 55])
        self.assertEqual([note.ntype for note in preserved], [14, 3])

    def test_normalization_neutralizes_legacy_state_exactly_once(self) -> None:
        track = Track(
            1,
            notes=[Note(60, 90, 0, 100, 0)],
            volume_scale=0.5,
        )
        self.assertTrue(normalize_legacy_track_velocity(track))
        self.assertEqual(track.notes, [Note(60, 45, 0, 100, 0)])
        self.assertEqual(track.volume_scale, 1.0)
        self.assertFalse(normalize_legacy_track_velocity(track))

        invalid = Track(
            2,
            notes=[Note(64, 80, 0, 100, 0)],
            volume_scale="invalid",
        )
        self.assertTrue(normalize_legacy_track_velocity(invalid))
        self.assertEqual(invalid.notes, [Note(64, 80, 0, 100, 0)])
        self.assertEqual(invalid.volume_scale, 1.0)


class GameInstrumentMixTests(unittest.TestCase):
    def test_mix_reads_only_volume_and_aux_fields(self) -> None:
        track = Track(
            1,
            bdo_track_volume=88,
            bdo_track_settings=(11, 201, 22, 202, 33, 203, 204, 205),
        )
        self.assertEqual(
            GameInstrumentMix.from_track(track),
            GameInstrumentMix(88, 11, 22, 33),
        )

    def test_field_level_aux_patch_preserves_volume_other_aux_and_master(self) -> None:
        target = Track(
            1,
            bdo_track_volume=64,
            bdo_track_settings=(1, 201, 2, 202, 3, 203, 204, 205),
        )
        mix = GameInstrumentMix(88, 11, 22, 33)

        self.assertTrue(
            mix.apply_to(
                target,
                volume=False,
                send_indices=(TRACK_DELAY_SEND_INDEX,),
            )
        )
        self.assertEqual(target.bdo_track_volume, 64)
        self.assertEqual(
            target.bdo_track_settings,
            (1, 201, 22, 202, 3, 203, 204, 205),
        )

    def test_full_mix_patch_still_preserves_every_master_field(self) -> None:
        target = Track(
            1,
            bdo_track_volume=64,
            bdo_track_settings=(1, 201, 2, 202, 3, 203, 204, 205),
        )
        self.assertTrue(GameInstrumentMix(88, 11, 22, 33).apply_to(target))
        self.assertEqual(target.bdo_track_volume, 88)
        self.assertEqual(
            target.bdo_track_settings,
            (11, 201, 22, 202, 33, 203, 204, 205),
        )

    def test_invalid_aux_index_fails_before_volume_or_settings_change(self) -> None:
        target = Track(
            1,
            bdo_track_volume=64,
            bdo_track_settings=(1, 201, 2, 202, 3, 203, 204, 205),
        )
        before = (target.bdo_track_volume, target.bdo_track_settings)
        with self.assertRaisesRegex(ValueError, "Aux send indices"):
            GameInstrumentMix(88, 11, 22, 33).apply_to(
                target,
                send_indices=(TRACK_REVERB_SEND_INDEX, 1),
            )
        self.assertEqual(
            (target.bdo_track_volume, target.bdo_track_settings),
            before,
        )

    def test_invalid_source_wire_volume_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "v9 byte"):
            GameInstrumentMix.from_track(
                Track(1, bdo_track_volume=256)
            )

    def test_invalid_aux_selection_is_rejected_even_without_peers(self) -> None:
        source = Track(1)
        with self.assertRaisesRegex(ValueError, "Aux send indices"):
            propagate_game_instrument_mix(
                [source],
                source,
                send_indices=(1,),
            )

    def test_propagation_uses_serialized_marnian_identity(self) -> None:
        source = Track(
            1,
            bdo_instrument_id=0x14,
            marnian_synth_mode="basic",
            bdo_track_volume=88,
            bdo_track_settings=(11, 1, 22, 2, 33, 3, 4, 5),
        )
        same_wire_instrument = Track(
            2,
            bdo_instrument_id=0x14,
            marnian_synth_mode="basic",
            bdo_track_volume=60,
            bdo_track_settings=(1, 11, 2, 12, 3, 13, 14, 15),
        )
        different_marnian_mode = Track(
            3,
            bdo_instrument_id=0x14,
            marnian_synth_mode="stereo",
            bdo_track_volume=40,
            bdo_track_settings=(4, 21, 5, 22, 6, 23, 24, 25),
        )

        changed = propagate_game_instrument_mix(
            [source, same_wire_instrument, different_marnian_mode],
            source,
        )
        self.assertEqual(changed, (2,))
        self.assertEqual(same_wire_instrument.bdo_track_volume, 88)
        self.assertEqual(
            same_wire_instrument.bdo_track_settings,
            (11, 11, 22, 12, 33, 13, 14, 15),
        )
        self.assertEqual(different_marnian_mode.bdo_track_volume, 40)
        self.assertEqual(
            different_marnian_mode.bdo_track_settings,
            (4, 21, 5, 22, 6, 23, 24, 25),
        )

    def test_propagation_preflight_prevents_partial_writes(self) -> None:
        source = Track(
            1,
            bdo_track_volume=88,
            bdo_track_settings=(11, 1, 22, 2, 33, 3, 4, 5),
        )
        first_peer = Track(
            2,
            bdo_track_volume=60,
            bdo_track_settings=(1, 11, 2, 12, 3, 13, 14, 15),
        )
        invalid_peer = Track(
            3,
            bdo_track_volume=40,
            bdo_track_settings=(1, 2),
        )
        before = (first_peer.bdo_track_volume, first_peer.bdo_track_settings)

        with self.assertRaisesRegex(ValueError, "exactly eight bytes"):
            propagate_game_instrument_mix(
                [source, first_peer, invalid_peer],
                source,
            )
        self.assertEqual(
            (first_peer.bdo_track_volume, first_peer.bdo_track_settings),
            before,
        )

    def test_propagation_reuses_one_shot_aux_selection_for_every_peer(self) -> None:
        source = Track(
            1,
            bdo_track_settings=(11, 1, 22, 2, 33, 3, 4, 5),
        )
        peers = [
            Track(
                track_id,
                bdo_track_settings=(1, 11, 2, 12, 3, 13, 14, 15),
            )
            for track_id in (2, 3)
        ]

        changed = propagate_game_instrument_mix(
            [source, *peers],
            source,
            volume=False,
            send_indices=(index for index in (TRACK_DELAY_SEND_INDEX,)),
        )
        self.assertEqual(changed, (2, 3))
        for peer in peers:
            self.assertEqual(
                peer.bdo_track_settings,
                (1, 11, 22, 12, 3, 13, 14, 15),
            )

    def test_conflicting_inheritance_is_fail_closed(self) -> None:
        first = Track(
            1,
            bdo_track_volume=60,
            bdo_track_settings=(11, 1, 22, 2, 33, 3, 4, 5),
        )
        second = Track(
            2,
            bdo_track_volume=61,
            bdo_track_settings=(11, 6, 22, 7, 33, 8, 9, 10),
        )
        target = Track(
            3,
            bdo_track_volume=40,
            bdo_track_settings=(1, 21, 2, 22, 3, 23, 24, 25),
        )
        before = (target.bdo_track_volume, target.bdo_track_settings)

        with self.assertRaisesRegex(ValueError, "conflicting mixer states"):
            inherit_game_instrument_mix([first, target, second], target)
        self.assertEqual((target.bdo_track_volume, target.bdo_track_settings), before)

    def test_consistent_inheritance_preserves_target_master_fields(self) -> None:
        first = Track(
            1,
            bdo_track_volume=88,
            bdo_track_settings=(11, 1, 22, 2, 33, 3, 4, 5),
        )
        second = Track(
            2,
            bdo_track_volume=88,
            bdo_track_settings=(11, 6, 22, 7, 33, 8, 9, 10),
        )
        target = Track(
            3,
            bdo_track_volume=40,
            bdo_track_settings=(1, 21, 2, 22, 3, 23, 24, 25),
        )

        self.assertEqual(
            inherit_game_instrument_mix([first, target, second], target),
            1,
        )
        self.assertEqual(target.bdo_track_volume, 88)
        self.assertEqual(
            target.bdo_track_settings,
            (11, 21, 22, 22, 33, 23, 24, 25),
        )


if __name__ == "__main__":
    unittest.main()
