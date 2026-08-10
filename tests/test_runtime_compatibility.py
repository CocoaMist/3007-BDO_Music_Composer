from __future__ import annotations

import json
import unittest

from bdo_music_composer.ui.runtime_compatibility import compatibility_report_json


class RuntimeCompatibilityTests(unittest.TestCase):
    def test_report_is_path_free_and_versioned(self) -> None:
        text = compatibility_report_json(include_qt=False)
        report = json.loads(text)
        self.assertEqual(report["schema"], 1)
        self.assertNotIn("path", text.casefold())


if __name__ == "__main__":
    unittest.main()
