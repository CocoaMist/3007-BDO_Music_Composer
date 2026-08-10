"""Standard MIDI import for the editor's millisecond note model."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import mido

from .model import ChannelGroup, Note


DEFAULT_BPM = 120
DEFAULT_TIME_SIGNATURE = 4
FLATTENED_TEMPO_BPM = 200
_TEXT_EVENT_TYPES = frozenset({"lyrics", "text", "marker", "cue_marker"})


def _absolute_events(tracks: Sequence[mido.MidiTrack]) -> Iterator[tuple[int, Any]]:
    """Merge tracks without cloning messages, preserving file order at equal ticks."""
    timeline: list[tuple[int, int, Any]] = []
    order = 0
    for track in tracks:
        tick = 0
        for message in track:
            tick += message.time
            if message.type != "end_of_track":
                timeline.append((tick, order, message))
            order += 1
    timeline.sort(key=lambda event: (event[0], event[1]))
    for tick, _order, message in timeline:
        yield tick, message


def _read_header_events(mid: mido.MidiFile) -> tuple[list[tuple[int, int]], int]:
    tempos: list[tuple[int, int]] = []
    numerator = DEFAULT_TIME_SIGNATURE
    signature_found = False
    for track in mid.tracks:
        tick = 0
        for message in track:
            tick += message.time
            if message.type == "set_tempo":
                tempos.append((tick, int(message.tempo)))
            elif message.type == "time_signature":
                if int(message.denominator) != 4:
                    raise ValueError(
                        f"BDO v9 only supports a /4 meter; MIDI uses "
                        f"{message.numerator}/{message.denominator}"
                    )
                if not signature_found:
                    numerator = int(message.numerator)
                    signature_found = True

    tempos.sort(key=lambda item: item[0])
    default_tempo = int(mido.bpm2tempo(DEFAULT_BPM))
    if not tempos or tempos[0][0] > 0:
        tempos.insert(0, (0, default_tempo))

    normalized: list[tuple[int, int]] = []
    for tick, tempo in tempos:
        if tick < 0:
            raise ValueError("Invalid MIDI tempo map")
        if normalized and normalized[-1][0] == tick:
            normalized[-1] = (tick, tempo)
        else:
            normalized.append((tick, tempo))
    return normalized, numerator


def _control_event(message: Any, time_ms: float) -> dict[str, int | float | str] | None:
    common: dict[str, int | float | str] = {
        "time": round(time_ms, 3),
        "kind": str(message.type),
        "channel": int(message.channel),
    }
    if message.type == "control_change":
        common.update(control=int(message.control), value=int(message.value))
    elif message.type == "pitchwheel":
        common["pitch"] = int(message.pitch)
    elif message.type == "aftertouch":
        common["value"] = int(message.value)
    elif message.type == "polytouch":
        common.update(note=int(message.note), value=int(message.value))
    else:
        return None
    return common


def parse_midi(
    midi_path: str | Path,
    apply_sustain: bool = True,
    flatten_tempo: bool = False,
    include_controls: bool = False,
    include_lyrics: bool = False,
) -> tuple:
    """Parse a MIDI file into channel/program groups using real-time milliseconds.

    The variable-length return contract is retained for existing application
    callers: the first four values are BPM, meter numerator, channel groups,
    and normalized tempo-map size. Controls and text events are appended when
    their corresponding flags are enabled.
    """
    mid = mido.MidiFile(midi_path)
    if mid.type not in (0, 1):
        raise ValueError(f"MIDI type {mid.type} has asynchronous tracks and is not supported")
    tempo_map, numerator = _read_header_events(mid)
    bpm = (
        FLATTENED_TEMPO_BPM
        if flatten_tempo and len(tempo_map) > 1
        else round(mido.tempo2bpm(tempo_map[0][1]))
    )

    notes_by_group: dict[tuple[int, int, bool], list[Note]] = defaultdict(list)
    controls_by_group: dict[tuple[int, int, bool], list[dict]] = defaultdict(list)
    text_events: list[dict[str, float | str]] = []
    programs: dict[int, int] = defaultdict(int)
    pedal_down: dict[int, bool] = defaultdict(bool)
    active: dict[tuple[int, int], tuple[int, float, int]] = {}
    pedal_held: dict[tuple[int, int], tuple[int, float, int]] = {}

    def group_key(channel: int, program: int) -> tuple[int, int, bool]:
        percussion = channel == 9
        return channel, 0 if percussion else program, percussion

    def finish_note(
        channel: int,
        pitch: int,
        velocity: int,
        start_ms: float,
        end_ms: float,
        program: int,
    ) -> None:
        duration = end_ms - start_ms
        if duration > 0:
            notes_by_group[group_key(channel, program)].append(
                Note(pitch, velocity, start_ms, duration, 0)
            )

    current_tempo = tempo_map[0][1]
    previous_tick = 0
    elapsed_ms = 0.0
    ticks_per_beat = mid.ticks_per_beat

    for tick, message in _absolute_events(mid.tracks):
        tick_delta = tick - previous_tick
        if tick_delta:
            elapsed_ms += tick_delta * current_tempo / ticks_per_beat / 1000.0
            previous_tick = tick

        if message.type == "set_tempo":
            current_tempo = int(message.tempo)
            continue
        if message.type in _TEXT_EVENT_TYPES:
            text_events.append({
                "time": round(elapsed_ms, 3),
                "kind": str(message.type),
                "text": str(getattr(message, "text", "")),
            })
        if not hasattr(message, "channel"):
            continue

        channel = int(message.channel)
        if message.type == "program_change":
            programs[channel] = int(message.program)
            continue

        control = _control_event(message, elapsed_ms)
        if control is not None:
            controls_by_group[group_key(channel, programs[channel])].append(control)

        if message.type == "control_change":
            if message.control != 64 or not apply_sustain:
                continue
            pedal_down[channel] = message.value >= 64
            if pedal_down[channel]:
                continue
            for identity, held in tuple(pedal_held.items()):
                if identity[0] != channel:
                    continue
                velocity, start_ms, program = held
                finish_note(channel, identity[1], velocity, start_ms, elapsed_ms, program)
                del pedal_held[identity]
            continue

        identity = (channel, int(getattr(message, "note", -1)))
        if message.type == "note_on" and message.velocity > 0:
            if identity in pedal_held:
                velocity, start_ms, program = pedal_held.pop(identity)
                finish_note(channel, identity[1], velocity, start_ms, elapsed_ms, program)
            if identity in active:
                velocity, start_ms, program = active.pop(identity)
                finish_note(channel, identity[1], velocity, start_ms, elapsed_ms, program)
            active[identity] = (int(message.velocity), elapsed_ms, programs[channel])
        elif message.type == "note_off" or (
            message.type == "note_on" and message.velocity == 0
        ):
            if identity not in active:
                continue
            if apply_sustain and pedal_down[channel]:
                pedal_held[identity] = active.pop(identity)
            else:
                velocity, start_ms, program = active.pop(identity)
                finish_note(channel, identity[1], velocity, start_ms, elapsed_ms, program)

    for unfinished in (active, pedal_held):
        for (channel, pitch), (velocity, start_ms, program) in unfinished.items():
            notes_by_group[group_key(channel, program)].append(
                Note(pitch, velocity, start_ms, 100.0, 0)
            )

    groups: list[ChannelGroup] = []
    aligned_controls: list[list[dict]] = []
    for key in sorted(notes_by_group):
        group_notes = notes_by_group[key]
        if not group_notes:
            continue
        group_notes.sort(key=lambda note: note.start)
        _channel, program, percussion = key
        groups.append((group_notes, program, percussion))
        aligned_controls.append(controls_by_group.get(key, []))

    result: tuple = (bpm, numerator, groups, len(tempo_map))
    if include_controls:
        result += (aligned_controls,)
    if include_lyrics:
        result += (text_events,)
    return result


__all__ = [
    "DEFAULT_BPM", "DEFAULT_TIME_SIGNATURE", "FLATTENED_TEMPO_BPM",
    "parse_midi",
]
