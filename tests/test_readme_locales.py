from __future__ import annotations

from pathlib import Path
import unittest

from tools.check_readme_locales import (
    LOCALIZED_READMES,
    SECTION_MARKERS,
    validate_readmes,
)


ROOT = Path(__file__).resolve().parents[1]


class ReadmeLocaleTests(unittest.TestCase):
    def test_all_localized_readmes_are_complete_and_navigable(self) -> None:
        self.assertEqual(validate_readmes(ROOT), [])

    def test_locale_contract_covers_operational_sections(self) -> None:
        self.assertEqual(len(LOCALIZED_READMES), 4)
        self.assertGreaterEqual(len(SECTION_MARKERS), 12)
        for section in (
            "requirements",
            "workflow",
            "architecture",
            "testing",
            "packaging",
            "privacy",
            "license",
        ):
            self.assertIn(section, SECTION_MARKERS)


if __name__ == "__main__":
    unittest.main()
