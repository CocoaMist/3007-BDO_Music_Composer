"""Optional MuScriptor CLI adapter for generic reference-instrument labels.

The application neither bundles nor downloads MuScriptor.  When a user has
installed the command separately, this adapter runs it off the GUI thread and
reads only its standard-MIDI output.  The labels remain display-only hints.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Callable

import mido

from bdo_music_composer.transcription.reference_timbre import (
    ReferenceInstrumentEvent,
)


CancelCallback = Callable[[], bool]
MUSCRIPTOR_BACKEND_ID = "muscriptor-small"


class MuScriptorBackendError(RuntimeError):
    pass


class MuScriptorCancelled(MuScriptorBackendError):
    pass


def resolve_muscriptor_executable(configured: str = "") -> str:
    """Return an explicit or PATH-resolved executable without installing it."""

    value = str(configured or "").strip()
    if value:
        path = Path(value).expanduser()
        if path.is_file():
            return str(path.resolve())
        resolved = shutil.which(value)
        return str(resolved or "")
    return str(shutil.which("muscriptor") or "")


def muscriptor_backend_status(configured: str = "") -> tuple[bool, str]:
    executable = resolve_muscriptor_executable(configured)
    if executable:
        return True, executable
    return False, "not-installed"


def transcribe_muscriptor_events(
    audio_path: str | Path,
    *,
    executable: str = "",
    timeout_seconds: float = 900.0,
    cancelled: CancelCallback | None = None,
) -> tuple[ReferenceInstrumentEvent, ...]:
    """Run the small model and parse its program-labelled MIDI result."""

    source = Path(audio_path)
    if not source.is_file():
        raise MuScriptorBackendError("reference audio is unavailable")
    command = resolve_muscriptor_executable(executable)
    if not command:
        raise MuScriptorBackendError("muscriptor is not installed")
    timeout = float(timeout_seconds)
    if timeout <= 0.0:
        raise ValueError("timeout_seconds must be positive")
    if cancelled is not None and cancelled():
        raise MuScriptorCancelled("instrument labelling cancelled")
    with tempfile.TemporaryDirectory(prefix="bdo-muscriptor-") as temp_dir:
        output_path = Path(temp_dir) / "labels.mid"
        args = [
            command,
            "transcribe",
            "--model",
            "small",
            str(source),
            "-o",
            str(output_path),
        ]
        creation_flags = (
            subprocess.CREATE_NO_WINDOW
            if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0
        )
        try:
            process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
        except OSError as exc:
            raise MuScriptorBackendError("could not start muscriptor") from exc
        started = time.monotonic()
        try:
            while process.poll() is None:
                if cancelled is not None and cancelled():
                    process.terminate()
                    try:
                        process.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    raise MuScriptorCancelled("instrument labelling cancelled")
                if time.monotonic() - started > timeout:
                    process.terminate()
                    try:
                        process.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    raise MuScriptorBackendError("muscriptor timed out")
                time.sleep(0.05)
            process.wait(timeout=2.0)
        finally:
            if process.poll() is None:
                process.kill()
        if process.returncode != 0 or not output_path.is_file():
            raise MuScriptorBackendError("muscriptor did not produce MIDI")
        return parse_instrument_midi(output_path, cancelled=cancelled)


def parse_instrument_midi(
    midi_path: str | Path,
    *,
    cancelled: CancelCallback | None = None,
) -> tuple[ReferenceInstrumentEvent, ...]:
    """Convert a standard MIDI file into generic family-labelled notes."""

    try:
        midi = mido.MidiFile(str(midi_path))
    except (OSError, EOFError, ValueError) as exc:
        raise MuScriptorBackendError("instrument MIDI is invalid") from exc
    tempo = 500_000
    elapsed_seconds = 0.0
    programs = {channel: 0 for channel in range(16)}
    active: dict[tuple[int, int], list[tuple[float, str]]] = {}
    events: list[ReferenceInstrumentEvent] = []
    for message in mido.merge_tracks(midi.tracks):
        if cancelled is not None and cancelled():
            raise MuScriptorCancelled("instrument labelling cancelled")
        elapsed_seconds += mido.tick2second(
            int(message.time), midi.ticks_per_beat, tempo
        )
        if message.type == "set_tempo":
            tempo = int(message.tempo)
            continue
        channel = int(getattr(message, "channel", 0))
        if message.type == "program_change":
            programs[channel] = int(message.program)
            continue
        is_on = message.type == "note_on" and int(message.velocity) > 0
        is_off = message.type == "note_off" or (
            message.type == "note_on" and int(message.velocity) == 0
        )
        if not is_on and not is_off:
            continue
        key = (channel, int(message.note))
        if is_on:
            family = (
                "percussion"
                if channel == 9
                else gm_program_family(programs.get(channel, 0))
            )
            active.setdefault(key, []).append((elapsed_seconds, family))
            continue
        starts = active.get(key)
        if not starts:
            continue
        start_seconds, family = starts.pop(0)
        if not starts:
            active.pop(key, None)
        duration_ms = (elapsed_seconds - start_seconds) * 1000.0
        if duration_ms > 1.0:
            events.append(
                ReferenceInstrumentEvent(
                    key[1],
                    start_seconds * 1000.0,
                    duration_ms,
                    family,
                )
            )
    return tuple(
        sorted(
            events,
            key=lambda event: (event.start_ms, event.pitch, event.family),
        )
    )


def gm_program_family(program: int) -> str:
    """Map a zero-based GM program to one deliberately broad family."""

    value = max(0, min(127, int(program)))
    return (
        "piano",
        "chromatic_percussion",
        "organ",
        "guitar",
        "bass",
        "strings",
        "ensemble",
        "brass",
        "reed",
        "pipe",
        "synth_lead",
        "synth_pad",
        "synth_effect",
        "ethnic",
        "percussive",
        "sound_effect",
    )[value // 8]


__all__ = [
    "MUSCRIPTOR_BACKEND_ID",
    "MuScriptorBackendError",
    "MuScriptorCancelled",
    "gm_program_family",
    "muscriptor_backend_status",
    "parse_instrument_midi",
    "resolve_muscriptor_executable",
    "transcribe_muscriptor_events",
]
