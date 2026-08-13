from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

import mido

from bdo_midi import Note
from bdo_music_composer.editor.editor_models import TrackState
from bdo_music_composer.editor.preview_midi_writer import (
    build_filtered_midi,
    build_filtered_midi_bytes,
)


ROOT = Path(__file__).resolve().parents[1]


def _track(
    track_id: int,
    *,
    notes: list[Note],
    gm_program: int,
    percussion: bool = False,
) -> TrackState:
    return TrackState(
        track_id=track_id,
        notes=notes,
        gm_program=gm_program,
        is_percussion=percussion,
        display_name=str(track_id),
        bdo_instrument_id=0x0D if percussion else 0x0B,
    )


def _absolute_messages(track: mido.MidiTrack) -> list[tuple[int, object]]:
    absolute_tick = 0
    messages: list[tuple[int, object]] = []
    for message in track:
        absolute_tick += int(message.time)
        messages.append((absolute_tick, message))
    return messages


class PreviewMidiWriterTests(unittest.TestCase):
    def test_duration_scale_and_same_tick_note_order_are_preserved(self) -> None:
        lead = _track(
            1,
            notes=[
                Note(60, 0, 0.0, 1000.0, 0),
                Note(62, 200, 500.0, 250.0, 0),
            ],
            gm_program=17,
        )
        lead.duration_scale = 0.5

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "scaled.mid"
            build_filtered_midi([lead], 120, 7, path)
            midi = mido.MidiFile(path)

        time_signature = next(
            message
            for message in midi.tracks[0]
            if message.type == "time_signature"
        )
        self.assertEqual(
            (time_signature.numerator, time_signature.denominator),
            (7, 4),
        )
        messages = _absolute_messages(midi.tracks[1])
        program = next(
            message for _tick, message in messages
            if message.type == "program_change"
        )
        self.assertEqual((program.channel, program.program), (0, 17))
        same_tick_notes = [
            (message.type, message.note, message.velocity)
            for tick, message in messages
            if tick == 480 and message.type in {"note_on", "note_off"}
        ]
        self.assertEqual(
            same_tick_notes,
            [("note_off", 60, 0), ("note_on", 62, 127)],
        )
        first_note_on = next(
            message for _tick, message in messages
            if message.type == "note_on" and message.note == 60
        )
        self.assertEqual(first_note_on.velocity, 1)

    def test_track_position_controls_program_and_percussion_channels(self) -> None:
        tracks = [
            _track(
                index,
                notes=[Note(48 if index == 1 else 60, 90, 0.0, 100.0, 0)],
                gm_program=20 + index,
                percussion=index == 1,
            )
            for index in range(11)
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "channels.mid"
            build_filtered_midi(tracks, 120, 4, path)
            midi = mido.MidiFile(path)

        for index, midi_track in enumerate(midi.tracks[1:]):
            messages = [
                message
                for _tick, message in _absolute_messages(midi_track)
                if not message.is_meta
            ]
            if index == 1:
                self.assertNotIn(
                    "program_change",
                    {message.type for message in messages},
                )
                self.assertEqual({message.channel for message in messages}, {9})
                continue
            program = next(
                message for message in messages
                if message.type == "program_change"
            )
            self.assertEqual(program.program, 20 + index)
            self.assertEqual(program.channel, min(index, 8))
            self.assertEqual(
                {
                    message.channel
                    for message in messages
                    if hasattr(message, "channel")
                },
                {min(index, 8)},
            )

    def test_performance_controls_and_lyrics_round_trip_directly(self) -> None:
        track = _track(
            1,
            notes=[Note(60, 90, 0.0, 600.0, 0)],
            gm_program=10,
        )
        track.performance_controls = [
            {"time": 0.0, "kind": "control_change", "control": 64, "value": 127},
            {"time": 100.0, "kind": "pitchwheel", "pitch": 1234},
            {"time": 200.0, "kind": "aftertouch", "value": 73},
            {"time": 300.0, "kind": "polytouch", "note": 60, "value": 55},
        ]
        lyrics = [
            {"time": 0.0, "kind": "lyrics", "text": "Hello"},
            {"time": 500.0, "kind": "marker", "text": "A"},
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "expressive.mid"
            build_filtered_midi([track], 120, 4, path, lyrics)
            midi = mido.MidiFile(path)

        self.assertEqual(
            [
                (message.type, message.text)
                for message in midi.tracks[0]
                if message.type in {"lyrics", "marker"}
            ],
            [("lyrics", "Hello"), ("marker", "A")],
        )
        self.assertEqual(
            {
                message.type
                for message in midi.tracks[1]
                if not message.is_meta
            },
            {
                "program_change",
                "control_change",
                "pitchwheel",
                "aftertouch",
                "polytouch",
                "note_on",
                "note_off",
            },
        )

    def test_main_gui_keeps_friendly_missing_mido_error(self) -> None:
        script = textwrap.dedent(
            """
            import builtins

            real_import = builtins.__import__

            def import_without_mido(name, *args, **kwargs):
                if name == "mido" or name.startswith("mido."):
                    raise ModuleNotFoundError("mido intentionally unavailable")
                return real_import(name, *args, **kwargs)

            builtins.__import__ = import_without_mido
            try:
                import bdo_music_composer.ui.main_window as pyside_bdo_gui
            except SystemExit as exc:
                assert "PySide6/mido is not installed." in str(exc), exc
            else:
                raise AssertionError("missing mido did not stop GUI import")
            """
        )
        env = dict(os.environ)
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_in_memory_projection_is_a_complete_standard_midi(self) -> None:
        payload = build_filtered_midi_bytes(
            [_track(
                1,
                notes=[Note(60, 90, 250.0, 500.0, 0)],
                gm_program=12,
            )],
            120,
            4,
            [{"time": 250.0, "kind": "lyrics", "text": "A"}],
        )

        midi = mido.MidiFile(file=BytesIO(payload))

        self.assertEqual(len(midi.tracks), 2)
        self.assertTrue(any(message.type == "lyrics" for message in midi.tracks[0]))
        self.assertTrue(any(message.type == "note_on" for message in midi.tracks[1]))

    def test_standard_projection_rejects_more_than_fifteen_programs(self) -> None:
        tracks = [
            _track(
                index,
                notes=[Note(60, 90, 0.0, 100.0, 0)],
                gm_program=index,
            )
            for index in range(16)
        ]
        with self.assertRaisesRegex(ValueError, "15 simultaneous"):
            build_filtered_midi_bytes(tracks, 120, 4)


if __name__ == "__main__":
    unittest.main()
