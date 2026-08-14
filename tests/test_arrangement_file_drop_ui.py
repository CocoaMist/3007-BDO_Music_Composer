from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ArrangementFileDropUiTests(unittest.TestCase):
    def test_drop_routes_open_append_close_and_safe_save(self) -> None:
        with tempfile.TemporaryDirectory() as folder_name:
            root = Path(folder_name)
            environment = dict(os.environ)
            environment["QT_QPA_PLATFORM"] = "offscreen"
            environment["BDO_USER_DATA_DIR"] = str(root / "data")
            script = textwrap.dedent(
                f"""
                from pathlib import Path

                from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
                from PySide6.QtGui import QDragEnterEvent, QDropEvent
                from PySide6.QtWidgets import QApplication, QMessageBox
                from bdo_music_composer.editor.editor_models import TrackState
                from bdo_music_composer.ui.arrangement_import_qt import (
                    arrangement_source_type,
                )
                from bdo_music_composer.ui.main_window import MidiToBdoWindow

                root = Path({str(root)!r})
                midi = root / "layer.MIDI"
                bdo = root / "score.bdo"
                unsupported = root / "notes.txt"
                for path in (midi, bdo, unsupported):
                    path.write_bytes(b"test")

                assert arrangement_source_type(midi) == "midi"
                assert arrangement_source_type(bdo) == "bdo"
                assert arrangement_source_type(unsupported) is None

                app = QApplication([])
                window = MidiToBdoWindow()
                assert window.acceptDrops()
                track = TrackState(1, [], 0, False, "Track", 0x12)
                window.tracks = [track]

                # The real checkpoint path must finish its background write
                # before replacement is allowed.
                window.autosave_project_dir = root / "real-save"
                assert window._save_project_before_dropped_open(midi)
                assert (root / "real-save" / "project.json").is_file()

                opened = []
                appended = []
                prompts = []
                warnings = []
                window._open_dropped_arrangement_source = (
                    lambda path, kind: opened.append((path, kind))
                )
                window._append_arrangement_source = (
                    lambda path, kind: appended.append((path, kind))
                )
                QMessageBox.warning = staticmethod(
                    lambda _parent, title, message: warnings.append((title, message))
                )

                window._prompt_dropped_arrangement_action = (
                    lambda path: prompts.append(path) or "append"
                )
                assert window._handle_dropped_arrangement_paths((midi,))
                assert appended == [(midi, "midi")]
                assert opened == []

                window._prompt_dropped_arrangement_action = lambda _path: "save_open"
                window._save_project_before_dropped_open = lambda _path: True
                assert window._handle_dropped_arrangement_paths((bdo,))
                assert opened == [(bdo, "bdo")]

                window._save_project_before_dropped_open = lambda _path: False
                assert window._handle_dropped_arrangement_paths((midi,))
                assert opened == [(bdo, "bdo")]

                window._prompt_dropped_arrangement_action = lambda _path: "close"
                assert window._handle_dropped_arrangement_paths((midi,))
                assert appended == [(midi, "midi")]
                assert opened == [(bdo, "bdo")]

                window.tracks = []
                assert window._handle_dropped_arrangement_paths((midi,))
                assert opened[-1] == (midi, "midi")

                assert not window._handle_dropped_arrangement_paths((midi, bdo))
                assert not window._handle_dropped_arrangement_paths((unsupported,))
                assert len(warnings) == 2
                window.worker = object()
                assert not window._handle_dropped_arrangement_paths((midi,))
                assert len(warnings) == 3
                window.worker = None

                mime = QMimeData()
                mime.setUrls([QUrl.fromLocalFile(str(midi))])
                drag = QDragEnterEvent(
                    QPoint(10, 10), Qt.CopyAction, mime,
                    Qt.LeftButton, Qt.NoModifier,
                )
                window.dragEnterEvent(drag)
                assert drag.isAccepted()
                assert drag.dropAction() == Qt.CopyAction
                window.tracks = []
                drop = QDropEvent(
                    QPointF(10.0, 10.0), Qt.CopyAction, mime,
                    Qt.LeftButton, Qt.NoModifier,
                )
                window.dropEvent(drop)
                assert drop.isAccepted()
                assert opened[-1] == (midi, "midi")

                # The real prompt exposes exactly the three requested choices;
                # append is the non-destructive default and Close is Escape.
                window.tracks = [track]
                del window._prompt_dropped_arrangement_action
                original_exec = QMessageBox.exec
                chosen = []
                def choose_append(dialog):
                    labels = {{button.text() for button in dialog.buttons()}}
                    assert labels == {{"保存并打开", "追加", "关闭"}}, labels
                    assert dialog.defaultButton().text() == "追加"
                    assert dialog.escapeButton().text() == "关闭"
                    button = next(
                        button for button in dialog.buttons()
                        if button.text() == "追加"
                    )
                    button.click()
                    chosen.append((
                        dialog.clickedButton().text(),
                        dialog.buttonRole(dialog.clickedButton()),
                    ))
                    return 0
                QMessageBox.exec = choose_append
                try:
                    prompt_action = window._prompt_dropped_arrangement_action(midi)
                    assert prompt_action == "append", (prompt_action, chosen)
                finally:
                    QMessageBox.exec = original_exec

                # A failed checkpoint blocks replacement even if an older
                # project.json exists.
                del window._save_project_before_dropped_open
                project_dir = root / "project"
                project_dir.mkdir()
                (project_dir / "project.json").write_text("old", encoding="utf-8")
                window.autosave_project_dir = project_dir
                window._autosave_project = lambda *_args, **_kwargs: False
                window._wait_for_autosave_idle = lambda *_args, **_kwargs: True
                window._autosave_retry_request = None
                assert not window._save_project_before_dropped_open(midi)

                recents = []
                window._autosave_project = lambda *_args, **_kwargs: True
                window._record_recent = lambda *args: recents.append(args)
                assert window._save_project_before_dropped_open(midi)
                assert recents and recents[0][0] == "project"

                window.autosave_timer.stop()
                window.tracks = []
                window._final_autosave_queued = True
                window.close()
                app.processEvents()
                print("arrangement-file-drop-ui-ok")
                """
            )
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                timeout=90,
                check=False,
            )
        self.assertEqual(
            result.returncode,
            0,
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        self.assertIn("arrangement-file-drop-ui-ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
