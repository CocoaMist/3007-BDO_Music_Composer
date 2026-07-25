from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
WINDOWS_ABSOLUTE_PATH = re.compile(r"[A-Za-z]:\\")


class MappingPathHygieneTests(unittest.TestCase):
    def test_tracked_mapping_metadata_has_no_windows_absolute_paths(self) -> None:
        offenders: list[str] = []
        for folder in (ROOT / "data" / "mappings", ROOT / "data" / "manifests"):
            for path in folder.iterdir():
                if path.suffix.lower() not in {".json", ".tsv"}:
                    continue
                if WINDOWS_ABSOLUTE_PATH.search(path.read_text(encoding="utf-8")):
                    offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
