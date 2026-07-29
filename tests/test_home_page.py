import json
import logging
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pyside_bdo_gui as gui
from home_catalog import GAME_SCORE_METADATA_MAX_BYTES, game_score_instrument_ids


class HomePageTests(unittest.TestCase):
    def test_oversized_game_score_is_bounded_before_structural_decode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "oversized-score"
            path.write_bytes(b"x" * (GAME_SCORE_METADATA_MAX_BYTES + 1))
            with patch(
                "home_catalog.score_instrument_ids",
                side_effect=AssertionError("oversized score must not decode"),
            ):
                self.assertEqual(game_score_instrument_ids(path), ())

    def test_home_ensemble_count_folds_modes_and_caps_party_size(self) -> None:
        modes = gui.HomeEntry(
            "game", "Modes", Path("C:/virtual/modes"), "", 1.0,
            instrument_ids=(0x14, 0x15, 0x16, 0x17, 0x11),
        )
        self.assertEqual(modes.performance_instrument_ids, (0x14, 0x11))
        self.assertEqual(modes.instrument_count, 2)
        self.assertEqual(modes.required_players, 2)
        self.assertFalse(modes.exceeds_ensemble_limit)

        oversized = gui.HomeEntry(
            "game", "Oversized", Path("C:/virtual/oversized"), "", 1.0,
            instrument_ids=(0x00, 0x01, 0x02, 0x04, 0x05, 0x06, 0x07, 0x08),
        )
        self.assertEqual(oversized.instrument_count, 8)
        self.assertEqual(oversized.required_players, 5)
        self.assertTrue(oversized.exceeds_ensemble_limit)

    def test_crash_log_redacts_machine_local_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            log_path = Path(temp) / "crash.log"
            private_path = r"C:\Users\Private Name\Music\reference.wav"
            with patch.object(gui, "CRASH_LOG_PATH", log_path):
                gui.append_crash_log(
                    f"Could not read {private_path}",
                    f'Traceback:\n  File "{private_path}", line 4\n{private_path}',
                )

            content = log_path.read_text(encoding="utf-8")
            self.assertNotIn(private_path, content)
            self.assertNotIn("C:\\Users", content)
            self.assertIn("<private-path>", content)

    def test_transcription_logger_persists_exception_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            log_path = Path(temp) / "crash.log"
            with patch.object(gui, "CRASH_LOG_PATH", log_path):
                gui.install_crash_logging()
                try:
                    raise ModuleNotFoundError(
                        "No module named 'unittest'",
                        name="unittest",
                    )
                except ModuleNotFoundError:
                    logging.getLogger("bdo_transcription").warning(
                        "backend import failed",
                        exc_info=True,
                    )
            content = log_path.read_text(encoding="utf-8")
            self.assertIn("backend import failed", content)
            self.assertIn("ModuleNotFoundError", content)
            self.assertIn("unittest", content)

    def test_conversion_failure_log_redacts_drive_and_unc_paths(self) -> None:
        script = textwrap.dedent(
            r"""
            import tempfile
            from pathlib import Path
            from unittest.mock import patch

            from PySide6.QtWidgets import QApplication
            import pyside_bdo_gui as gui

            app = QApplication([])
            with tempfile.TemporaryDirectory() as temp:
                output_dir = Path(temp) / "out"
                crash_log = Path(temp) / "crash.log"
                drive_path = r"C:\Users\Private Name\Music\reference.wav"
                unc_path = r"\\private-server\music\score.bdo"
                message = (
                    f"Could not convert {drive_path}\n"
                    f"Destination: {unc_path}"
                )
                with (
                    patch.object(gui, "DEFAULT_OUTDIR", output_dir),
                    patch.object(gui, "CRASH_LOG_PATH", crash_log),
                    patch.object(gui.QMessageBox, "critical") as critical,
                ):
                    window = gui.MidiToBdoWindow()
                    window._autosave_project = lambda *_args, **_kwargs: None
                    window._flush_autosave = lambda: None
                    window._on_convert_failed(message)
                    window.close()
                    app.processEvents()

                content = (
                    output_dir / "last_convert_error.log"
                ).read_text(encoding="utf-8")
                shown = str(critical.call_args.args[-1])
                for private_value in (drive_path, unc_path):
                    assert private_value not in content
                    assert private_value not in shown
                assert content.count("<private-path>") >= 2
            app.quit()
            """
        )
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

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
            ensemble = game_dir / "ensemble.bdo"
            encoded, _summary = gui.channel_groups_to_bdo(
                120,
                4,
                [
                    ([gui.Note(60, 90, 0.0, 250.0, 0)], 0, False),
                    ([gui.Note(64, 90, 0.0, 250.0, 0)], 1, False),
                ],
                instrument_map={0: 0x0B, 1: 0x11},
            )
            ensemble.write_bytes(encoded)
            os.utime(older, (10, 10))
            os.utime(newer, (20, 20))
            os.utime(ensemble, (30, 30))
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

            self.assertEqual(
                [item.label for item in scores],
                ["ensemble", "newer", "older"],
            )
            self.assertEqual(scores[0].instrument_ids, (0x0B, 0x11))
            self.assertEqual(scores[0].required_players, 2)
            self.assertEqual(projects[0].label, "Local Demo")
            visible = f"{projects[0].label} {projects[0].detail}"
            self.assertNotIn("123456", visible)
            self.assertNotIn("Private Character", visible)

    def test_dense_autosave_is_compact_utf8_and_roundtrips(self) -> None:
        script = textwrap.dedent(
            """
            import json
            import tempfile
            from pathlib import Path
            from unittest.mock import patch

            from PySide6.QtWidgets import QApplication
            import pyside_bdo_gui as gui

            app = QApplication([])
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                autosave_dir = root / "auto_save"
                autosave_dir.mkdir()
                with patch.object(gui, "AUTO_SAVE_DIR", autosave_dir):
                    window = gui.MidiToBdoWindow()
                    window.autosave_timer.stop()
                    window.source_format = "project"
                    window.autosave_project_dir = autosave_dir / "dense"
                    notes = [
                        gui.Note(
                            36 + index % 60,
                            40 + index % 80,
                            float(index * 25),
                            20.0,
                            index % 4,
                        )
                        for index in range(30000)
                    ]
                    window.tracks = [
                        gui.TrackState(
                            7,
                            notes,
                            0,
                            False,
                            "密集轨道",
                            0x0B,
                        )
                    ]
                    window._autosave_project(
                        "dense compact regression",
                        immediate=True,
                    )
                    assert window._wait_for_autosave_idle()
                    project_path = (
                        window.autosave_project_dir / "project.json"
                    )
                    raw = project_path.read_bytes()
                    text = raw.decode("utf-8")
                    payload = json.loads(text)
                    assert payload["schema_version"] == gui.CURRENT_PROJECT_SCHEMA
                    assert payload["tracks"][0]["display_name"] == "密集轨道"
                    assert len(payload["tracks"][0]["notes"]) == 30000
                    assert payload["tracks"][0]["notes"][-1] == [
                        int(notes[-1].pitch),
                        int(notes[-1].vel),
                        float(notes[-1].start),
                        float(notes[-1].dur),
                        int(notes[-1].ntype),
                    ]
                    assert "密集轨道" in text
                    assert '"schema_version":' in text
                    assert '"schema_version": ' not in text
                    assert not project_path.with_suffix(".json.tmp").exists()
                    pretty = json.dumps(
                        payload,
                        ensure_ascii=False,
                        indent=2,
                    )
                    assert len(raw) < len(pretty.encode("utf-8")) * 0.4
                    window.close()
                    app.processEvents()
            app.quit()
            """
        )
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_window_starts_on_home_with_three_collections(self) -> None:
        script = textwrap.dedent(
            """
            import json
            import math
            import struct
            import tempfile
            import time
            import wave
            import mido
            from pathlib import Path
            from unittest.mock import patch
            from PySide6.QtCore import QEvent
            from PySide6.QtTest import QTest
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
                    print("checkpoint:window-created", flush=True)
                    assert window.page_stack.currentWidget() is window.home_page
                    assert window.game_score_list.count() == 1
                    assert window.project_list.count() >= 1
                    assert window.game_score_list.item(0).text().splitlines()[0] == "score-one"
                    window.home_search.setText("score-one")
                    app.processEvents()
                    assert not window.game_score_list.item(0).isHidden()
                    assert window.game_score_count.text() == "1"
                    assert window.project_count.text() == "0"
                    window.home_search.clear()
                    assert not window.toolbar_import_btn.isHidden()
                    assert not window.convert_button.isHidden()
                    assert not window.convert_button.isEnabled()
                    assert window.status_label.text() != "发现自动保存工程"
                    assert "发现自动保存工程" not in window.inspector_text.text()
                    window._show_workspace()
                    assert not window.toolbar_import_btn.isHidden()
                    assert not window.convert_button.isHidden()
                    assert window.convert_button.isEnabled()
                    source = root / "source.mid"
                    midi = mido.MidiFile(ticks_per_beat=480)
                    midi_track = mido.MidiTrack()
                    midi.tracks.append(midi_track)
                    midi_track.append(mido.Message("note_on", note=60, velocity=90, time=0))
                    midi_track.append(mido.Message("note_off", note=60, velocity=0, time=480))
                    midi.save(source)
                    reference_audio = root / "reference.wav"
                    with wave.open(str(reference_audio), "wb") as audio:
                        audio.setnchannels(1)
                        audio.setsampwidth(2)
                        audio.setframerate(22050)
                        samples = [
                            int(10000 * math.sin(2 * math.pi * 440 * index / 22050))
                            for index in range(44100)
                        ]
                        audio.writeframes(struct.pack("<" + "h" * len(samples), *samples))
                    window.midi_path = str(source)
                    window.tracks = [
                        gui.TrackState(
                            1, [gui.Note(60, 90, 0.0, 250.0, 0)],
                            0, False, "lead", 0x0B,
                        )
                    ]
                    window.reference_audio.set_volume_percent(65)
                    assert window.reference_audio.set_audio_path(reference_audio)
                    deadline = time.monotonic() + 4.0
                    while window.reference_audio.waveform_loading and time.monotonic() < deadline:
                        QTest.qWait(20)
                        app.processEvents()
                    print("checkpoint:reference-loaded", flush=True)
                    window._play_preview()
                    QTest.qWait(220)
                    app.processEvents()
                    assert window.reference_audio.is_playing
                    playback_deadline = time.monotonic() + 2.0
                    while (
                        window.timeline.playhead_ms <= 50
                        and time.monotonic() < playback_deadline
                    ):
                        QTest.qWait(20)
                        app.processEvents()
                    assert window.timeline.playhead_ms > 50
                    window._pause_preview()
                    paused_at = window.timeline.playhead_ms
                    QTest.qWait(80)
                    app.processEvents()
                    assert not window.reference_audio.is_playing
                    assert abs(window.timeline.playhead_ms - paused_at) < 30
                    window._seek_preview(500.0)
                    assert abs(window.reference_audio.player.position() - 500) < 80
                    window._stop_preview(reset_playhead=True)
                    assert window.timeline.playhead_ms == 0.0
                    assert window._wait_for_autosave_idle()
                    print("checkpoint:preview-and-autosave", flush=True)
                    project_files = list(autosave_dir.glob("*/project.json"))
                    assert len(project_files) == 1
                    payload = json.loads(project_files[0].read_text(encoding="utf-8"))
                    project_index = json.loads(
                        project_files[0].with_name("project.index.json").read_text(encoding="utf-8")
                    )
                    assert payload["project_id"] == project_index["project_id"]
                    assert payload["path_policy"] == "project-relative-v1"
                    assert payload["original_midi_path"] == ""
                    assert payload["source_midi_path"] == "source.mid"
                    assert not Path(payload["source_midi_path"]).is_absolute()
                    assert (
                        project_files[0].parent / payload["source_midi_path"]
                    ).read_bytes() == source.read_bytes()
                    assert payload["reference_audio_path"] == ""
                    assert payload["reference_audio_attached"] is True
                    assert payload["reference_audio_volume"] == 65
                    assert payload["reference_layers"] == (
                        window.reference_layer_settings
                    )
                    serialized = project_files[0].read_text(encoding="utf-8")
                    assert str(root.resolve()) not in serialized
                    assert str(reference_audio.resolve()) not in serialized
                    autosave_log = project_files[0].with_name("autosave.log").read_text(
                        encoding="utf-8"
                    )
                    assert str(root.resolve()) not in autosave_log
                    source_copy = (
                        project_files[0].parent / payload["source_midi_path"]
                    ).resolve()
                    window._load_project(project_files[0])
                    assert window._wait_for_autosave_idle()
                    print("checkpoint:source-reloaded", flush=True)
                    assert Path(window.midi_path).resolve() == source_copy
                    assert window.reference_layer_settings == (
                        payload["reference_layers"]
                    )
                    assert window.reference_audio_path == ""
                    assert window.reference_audio_relink_required
                    assert "重新载入" in window.status_label.text()
                    sanitized = json.loads(
                        project_files[0].read_text(encoding="utf-8")
                    )
                    assert sanitized["source_midi_path"] == "source.mid"
                    assert sanitized["reference_audio_path"] == ""
                    assert sanitized["reference_audio_attached"] is True
                    window.reverb = 81
                    window.delay = 82
                    window.chorus = (83, 84, 85)
                    window._create_new_project("Blank Demo")
                    assert window._wait_for_autosave_idle()
                    print("checkpoint:blank-created", flush=True)
                    assert window.source_format == "project"
                    assert window.midi_path == ""
                    assert len(window.tracks) == 1
                    assert window.tracks[0].notes == []
                    assert window.reference_audio.volume_percent == 50
                    assert (window.reverb, window.delay, window.chorus) == (
                        0, 0, None
                    )
                    blank_project = next(autosave_dir.glob("Blank Demo_*/project.json"))
                    blank_payload = json.loads(blank_project.read_text(encoding="utf-8"))
                    assert blank_payload["source_format"] == "project"
                    assert blank_payload["original_midi_path"] == ""
                    assert blank_payload["source_midi_path"] == ""
                    assert blank_payload["reference_audio_path"] == ""
                    assert blank_payload["reference_audio_attached"] is False
                    window.tracks[0].notes = [gui.Note(64, 88, 125.0, 375.0, 0)]
                    window.reference_audio.set_volume_percent(35)
                    window._autosave_project("test blank notes", immediate=True)
                    assert window._wait_for_autosave_idle()
                    window._load_project(blank_project)
                    assert window._wait_for_autosave_idle()
                    print("checkpoint:blank-reloaded", flush=True)
                    assert window.source_format == "project"
                    assert window.tracks[0].notes == [gui.Note(64, 88, 125.0, 375.0, 0)]
                    assert window.reference_audio.volume_percent == 35
                    window.owner_id = 123
                    params = window._build_params()
                    assert params["midi_path"] == ""
                    assert params["direct_tracks"] is not window.tracks
                    assert params["direct_tracks"][0].notes == tuple(window.tracks[0].notes)
                    window.close()
                    assert window._wait_for_autosave_idle(timeout_ms=20_000)
                    window.close()
                    app.processEvents()
                    assert window.reference_audio.player.audioOutput() is None
                    print("checkpoint:window-closed", flush=True)
                    window.deleteLater()
                    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                    app.processEvents()
                    print("checkpoint:window-deleted", flush=True)
            app.quit()
            print("checkpoint:script-complete", flush=True)
            """
        )
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        try:
            completed = subprocess.run(
                [sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1], env=env,
                capture_output=True, text=True, timeout=60,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            self.fail(f"home workflow subprocess timed out\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_same_title_projects_remain_distinct_without_shared_identity(self) -> None:
        root = Path("C:/virtual")
        entries = [
            gui.HomeEntry("project", "  Demo Song  ", root / "old" / "project.json", "old", 10),
            gui.HomeEntry("midi", "demo song", root / "source.mid", "recent", 30),
            gui.HomeEntry("project", "Ｄｅｍｏ Song", root / "new" / "project.json", "new", 20),
            gui.HomeEntry("project", "Other", root / "other" / "project.json", "other", 15),
        ]

        merged = gui.merge_home_project_entries(entries)

        self.assertEqual(len(merged), 4)
        self.assertEqual({entry.path for entry in merged}, {entry.path for entry in entries})
        self.assertTrue(all(entry.version_count == 1 for entry in merged))

    def test_related_versions_remain_individually_openable(self) -> None:
        root = Path("C:/virtual")
        project_id = "4c792f3e-83e2-4fc6-901c-4d8e6a69eb2e"
        merged = gui.merge_home_project_entries([
            gui.HomeEntry(
                "project", "Song", root / "old" / "project.json", "old", 10,
                project_id=project_id,
            ),
            gui.HomeEntry(
                "project", "Song renamed", root / "new" / "project.json", "new", 20,
                project_id=project_id,
            ),
        ])
        self.assertEqual([entry.path for entry in merged], [
            root / "new" / "project.json",
            root / "old" / "project.json",
        ])
        self.assertEqual([entry.version_index for entry in merged], [2, 1])
        self.assertTrue(all(entry.version_count == 2 for entry in merged))
        self.assertTrue(all("版本" in entry.detail for entry in merged))

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
