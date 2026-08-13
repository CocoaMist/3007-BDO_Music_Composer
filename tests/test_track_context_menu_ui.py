from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TrackContextMenuUiTests(unittest.TestCase):
    def test_common_instrument_change_is_first_and_conversion_check_is_absent(self) -> None:
        script = textwrap.dedent(
            """
            from PySide6.QtWidgets import QApplication

            from bdo_music_composer.editor.editor_models import TrackState
            from bdo_music_composer.ui.editor.timeline_canvas import TimelineCanvas

            app = QApplication([])
            tracks = [
                TrackState(i, [], 0, False, f"Track {i}", 0x12)
                for i in (1, 2)
            ]
            canvas = TimelineCanvas()
            canvas.set_tracks(tracks)

            menu, actions = canvas._build_track_context_menu(tracks[0])
            top = [
                action.text() for action in menu.actions()
                if not action.isSeparator()
            ]
            assert top == [
                "更换游戏乐器", "编辑音符…", "音高与力度",
                "优化此轨道", "轨道管理", "监听状态",
            ], top
            assert len([a for a in menu.actions() if a.isSeparator()]) == 2
            instrument = menu._instrument_menu
            assert instrument is not None
            instrument_text = [
                action.text() for action in instrument.actions()
                if not action.isSeparator()
            ]
            assert instrument_text == [
                "管乐器", "弦乐器", "键盘乐器", "打击乐器",
                "以此轨统一同乐器音量和 FX",
            ], instrument_text
            assert "转换检查" not in top + instrument_text
            sound = menu._sound_menu
            sound_text = [a.text() for a in sound.actions()]
            assert sound_text == ["轨道 FX", "轨道移调…", "轨道力度基数…"]
            assert set(actions) == {
                "edit_notes", "effects", "pitch", "velocity", "optimize",
                "create_track", "merge", "move_up", "move_down", "delete",
                "unify_mixer", "clear_solo", "unmute_all",
            }
            canvas.close()
            app.processEvents()
            print("track-context-menu-ok")
            """
        )
        environment = dict(os.environ)
        environment["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("track-context-menu-ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
