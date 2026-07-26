from __future__ import annotations

import hashlib
import unittest

from bdo_midi.instruments import (
    BDO_INSTRUMENT_NAMES,
    GM_PROGRAM_NAMES,
    localized_bdo_instrument_name,
    localized_bdo_instrument_names,
    localized_gm_program_name,
)
from i18n import TRANSLATIONS
from gm_program_translations import GM_PROGRAM_TRANSLATIONS


class BdoInstrumentLocalizationTests(unittest.TestCase):
    def test_canonical_source_labels_match_game_terminology(self) -> None:
        florchestra_ids = {
            0x0A, 0x0B, 0x0D, 0x0F, 0x10,
            0x11, 0x12, 0x13, 0x27, 0x28,
        }
        self.assertTrue(
            all(
                BDO_INSTRUMENT_NAMES[instrument_id].startswith("弗洛凯斯特拉：")
                for instrument_id in florchestra_ids
            )
        )
        self.assertEqual("玛尔尼贝斯", BDO_INSTRUMENT_NAMES[0x0E])
        self.assertEqual("弗洛凯斯特拉：低音提琴", BDO_INSTRUMENT_NAMES[0x0F])
        self.assertEqual(
            "玛勒尼斯：电吉他 - 赫克赛格莱姆",
            BDO_INSTRUMENT_NAMES[0x26],
        )

    def test_one_name_translates_only_the_fixed_catalog_label(self) -> None:
        calls: list[str] = []

        def translate(source: str) -> str:
            calls.append(source)
            return f"localized:{source}"

        source = BDO_INSTRUMENT_NAMES[0x11]
        self.assertEqual(
            f"localized:{source}",
            localized_bdo_instrument_name(0x11, translate),
        )
        self.assertEqual([source], calls)

    def test_all_names_are_ordered_localized_copy(self) -> None:
        calls: list[str] = []

        def translate(source: str) -> str:
            calls.append(source)
            return source.upper()

        localized = localized_bdo_instrument_names(translate)

        self.assertIsNot(localized, BDO_INSTRUMENT_NAMES)
        self.assertEqual(list(BDO_INSTRUMENT_NAMES), list(localized))
        self.assertEqual(list(BDO_INSTRUMENT_NAMES.values()), calls)
        self.assertEqual(
            {key: value.upper() for key, value in BDO_INSTRUMENT_NAMES.items()},
            localized,
        )

        localized[0x00] = "changed only in localized copy"
        self.assertEqual("新手专用：吉他", BDO_INSTRUMENT_NAMES[0x00])

    def test_unknown_ids_use_stable_fallback_without_translation(self) -> None:
        def translate(_source: str) -> str:
            self.fail("unknown instrument IDs must not enter the catalog translator")

        self.assertEqual("BDO 0xFF", localized_bdo_instrument_name(0xFF, translate))
        self.assertEqual("BDO -1", localized_bdo_instrument_name(-1, translate))
        self.assertEqual("BDO 256", localized_bdo_instrument_name(256, translate))

    def test_all_128_generated_gm_names_are_localized_by_region(self) -> None:
        self.assertEqual(128, len(GM_PROGRAM_NAMES))
        for language, catalog in TRANSLATIONS.items():
            with self.subTest(language=language):
                names = tuple(
                    localized_gm_program_name(program, catalog.__getitem__)
                    for program in range(128)
                )
                self.assertEqual(128, len(names))
                self.assertTrue(all(name for name in names))
        self.assertEqual(
            "Acoustic Grand Piano",
            localized_gm_program_name(0, TRANSLATIONS["en_US"].__getitem__),
        )
        self.assertEqual(
            "バイオリン",
            localized_gm_program_name(40, TRANSLATIONS["ja_JP"].__getitem__),
        )
        self.assertEqual(
            "클라리넷",
            localized_gm_program_name(71, TRANSLATIONS["ko_KR"].__getitem__),
        )

    def test_gm1_program_order_and_regional_columns_are_locked(self) -> None:
        self.assertEqual(128, len(GM_PROGRAM_TRANSLATIONS))
        for column in range(3):
            values = tuple(row[column] for row in GM_PROGRAM_TRANSLATIONS)
            self.assertTrue(all(value.strip() for value in values))
            self.assertEqual(128, len(set(values)))
        english_order = "\n".join(
            row[0] for row in GM_PROGRAM_TRANSLATIONS
        ).encode("utf-8")
        self.assertEqual(
            "7eb4df9b2a52b26b98873dc7302bbef115a8b70357fc8128652f80c2e9633348",
            hashlib.sha256(english_order).hexdigest(),
        )

    def test_unknown_gm_program_is_neutral_and_not_translated(self) -> None:
        def translate(_source: str) -> str:
            self.fail("unknown GM programs must not enter the catalog translator")

        self.assertEqual("GM Program 128", localized_gm_program_name(128, translate))


if __name__ == "__main__":
    unittest.main()
