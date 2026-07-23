import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pyside_bdo_gui as gui


class HomePageTests(unittest.TestCase):
    def test_scanners_sort_recent_first_without_exposing_identity_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            game_dir = root / "music"
            project_dir = root / "auto_save" / "demo"
            game_dir.mkdir()
            project_dir.mkdir(parents=True)
            older = game_dir / "older"
            newer = game_dir / "newer.bdo"
            older.write_bytes(b"first")
            newer.write_bytes(b"second")
            os.utime(older, (10, 10))
            os.utime(newer, (20, 20))
            (project_dir / "project.json").write_text(
                json.dumps(
                    {
                        "output_name": "Local Demo",
                        "owner_id": 123456,
                        "char_name": "Private Character",
                    }
                ),
                encoding="utf-8",
            )

            scores = gui.scan_game_scores(game_dir)
            projects = gui.scan_local_projects(root / "auto_save")

            self.assertEqual([item.label for item in scores], ["newer", "older"])
            self.assertEqual(projects[0].label, "Local Demo")
            visible = f"{projects[0].label} {projects[0].detail}"
            self.assertNotIn("123456", visible)
            self.assertNotIn("Private Character", visible)

    def test_window_starts_on_home_with_three_collections(self) -> None:
        script = textwrap.dedent(
            """
            import tempfile
            from pathlib import Path
            from unittest.mock import patch
            from PySide6.QtWidgets import QApplication
            import pyside_bdo_gui as gui

            app = QApplication([])
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                game_dir = root / "music"
                autosave_dir = root / "auto_save"
                game_dir.mkdir()
                autosave_dir.mkdir()
                (game_dir / "score-one").write_bytes(b"score")
                with patch.object(gui, "CONFIG_PATH", root / "config.json"), patch.object(
                    gui, "AUTO_SAVE_DIR", autosave_dir
                ), patch.object(gui, "default_game_music_dir", return_value=game_dir):
                    window = gui.MidiToBdoWindow()
                    assert window.page_stack.currentWidget() is window.home_page
                    assert window.game_score_list.count() == 1
                    assert window.project_list.count() >= 1
                    assert window.game_score_list.item(0).text().splitlines()[0] == "score-one"
                    assert window.toolbar_import_btn.isHidden()
                    assert window.convert_button.isHidden()
                    assert window.status_label.text() != "发现自动保存工程"
                    assert "发现自动保存工程" not in window.inspector_text.text()
                    window._show_workspace()
                    assert not window.toolbar_import_btn.isHidden()
                    assert not window.convert_button.isHidden()
                    window.close()
                    app.processEvents()
            app.quit()
            """
        )
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1], env=env,
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_same_title_projects_are_grouped_and_latest_project_is_open_target(self) -> None:
        root = Path("C:/virtual")
        entries = [
            gui.HomeEntry("project", "  Demo Song  ", root / "old" / "project.json", "old", 10),
            gui.HomeEntry("midi", "demo song", root / "source.mid", "recent", 30),
            gui.HomeEntry("project", "Ｄｅｍｏ Song", root / "new" / "project.json", "new", 20),
            gui.HomeEntry("project", "Other", root / "other" / "project.json", "other", 15),
        ]

        merged = gui.merge_home_project_entries(entries)

        self.assertEqual(len(merged), 2)
        demo = merged[0]
        self.assertEqual(demo.kind, "project")
        self.assertEqual(demo.path, root / "new" / "project.json")
        self.assertEqual(demo.modified_at, 30)
        self.assertEqual(demo.version_count, 3)
        self.assertIn("3 个版本", demo.detail)

    def test_repeated_recent_path_does_not_inflate_version_count(self) -> None:
        path = Path("C:/virtual/source.mid")
        merged = gui.merge_home_project_entries([
            gui.HomeEntry("midi", "Song", path, "first", 10),
            gui.HomeEntry("midi", "Song", path, "second", 20),
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].version_count, 1)
        self.assertEqual(merged[0].modified_at, 20)


if __name__ == "__main__":
    unittest.main()
