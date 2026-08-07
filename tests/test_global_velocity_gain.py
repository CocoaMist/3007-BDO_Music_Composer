from __future__ import annotations

import unittest

from bdo_music_composer.editor.global_velocity_gain import base_velocity_map


class GlobalVelocityGainTests(unittest.TestCase):
    def test_selected_b_mapping_scales_positive_overflow_from_zero(self) -> None:
        source = [20, 50, 80]
        mapping = base_velocity_map(source, 100, 0, equalize=True)

        self.assertEqual([mapping[value] for value in source], [85, 106, 127])

    def test_equalize_keeps_in_range_addition_unchanged(self) -> None:
        mapping = base_velocity_map([20, 50, 80], 10, 0, equalize=True)

        self.assertEqual([mapping[value] for value in (20, 50, 80)], [30, 60, 90])

    def test_negative_overflow_uses_symmetric_lower_boundary_mapping(self) -> None:
        source = [20, 50, 80]
        mapping = base_velocity_map(source, -50, 0, equalize=True)
        scaled = [mapping[value] for value in source]

        self.assertEqual(scaled[0], 0)
        self.assertLess(scaled[0], scaled[1])
        self.assertLess(scaled[1], scaled[2])

    def test_unchecked_mode_uses_game_boundary_clipping(self) -> None:
        mapping = base_velocity_map([20, 50, 80], 100, 0, equalize=False)

        self.assertEqual([mapping[value] for value in (20, 50, 80)], [120, 127, 127])

    def test_reference_base_applies_only_the_new_delta(self) -> None:
        mapping = base_velocity_map([30, 40], 120, 100, equalize=True)

        self.assertEqual([mapping[30], mapping[40]], [50, 60])

    def test_zero_level_is_adjustable_like_every_other_note_block(self) -> None:
        mapping = base_velocity_map([0, 20], 100, 0, equalize=True)

        self.assertEqual([mapping[0], mapping[20]], [100, 120])


if __name__ == "__main__":
    unittest.main()
