"""Canonical Qt-free MIDI writer for editor preview and round trips."""

from __future__ import annotations

from pathlib import Path

import mido

from .editor_models import TrackState


_TICKS_PER_BEAT = 480
_TEXT_EVENT_KINDS = frozenset({"lyrics", "text", "marker", "cue_marker"})


def _milliseconds_to_ticks(ms: float, *, tempo: int) -> int:
    return max(0, round(mido.second2tick(
        ms / 1000.0,
        _TICKS_PER_BEAT,
        tempo,
    )))


def _build_meta_track(
    bpm: int,
    time_sig: int,
    lyric_events: list[dict] | None,
) -> tuple[object, int]:
    tempo = mido.bpm2tempo(max(1, min(240, bpm or 120)))
    numerator = max(1, min(32, int(time_sig or 4)))
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
    meta.append(mido.MetaMessage(
        "time_signature",
        numerator=numerator,
        denominator=4,
        time=0,
    ))
    timed_text_events: list[tuple[int, object]] = []
    for event in lyric_events or []:
        kind = str(event.get("kind", "lyrics"))
        if kind not in _TEXT_EVENT_KINDS:
            continue
        try:
            tick = _milliseconds_to_ticks(
                float(event.get("time", 0.0)),
                tempo=tempo,
            )
            message = mido.MetaMessage(
                kind,
                text=str(event.get("text", "")),
                time=0,
            )
        except (TypeError, ValueError):
            continue
        timed_text_events.append((tick, message))
    last_meta_tick = 0
    for tick, message in sorted(timed_text_events, key=lambda item: item[0]):
        message.time = max(0, tick - last_meta_tick)
        meta.append(message)
        last_meta_tick = tick
    meta.append(mido.MetaMessage("end_of_track", time=0))
    return meta, tempo


def _control_message(control: dict, channel: int) -> object | None:
    kind = str(control.get("kind", "control_change"))
    if kind == "control_change":
        return mido.Message(
            "control_change",
            channel=channel,
            control=max(0, min(127, int(control["control"]))),
            value=max(0, min(127, int(control["value"]))),
        )
    if kind == "pitchwheel":
        return mido.Message(
            "pitchwheel",
            channel=channel,
            pitch=max(-8192, min(8191, int(control["pitch"]))),
        )
    if kind == "aftertouch":
        return mido.Message(
            "aftertouch",
            channel=channel,
            value=max(0, min(127, int(control["value"]))),
        )
    if kind == "polytouch":
        return mido.Message(
            "polytouch",
            channel=channel,
            note=max(0, min(127, int(control["note"]))),
            value=max(0, min(127, int(control["value"]))),
        )
    return None


def _track_events(
    track_state: TrackState,
    channel: int,
    *,
    tempo: int,
) -> list[tuple[int, int, object]]:
    events: list[tuple[int, int, object]] = []
    if not track_state.is_percussion:
        events.append((0, 0, mido.Message(
            "program_change",
            channel=channel,
            program=track_state.gm_program,
        )))
    for control in track_state.performance_controls:
        try:
            tick = _milliseconds_to_ticks(
                float(control.get("time", 0.0)),
                tempo=tempo,
            )
            message = _control_message(control, channel)
        except (KeyError, TypeError, ValueError):
            continue
        if message is not None:
            events.append((tick, 1, message))
    for note in track_state.notes:
        start = _milliseconds_to_ticks(note.start, tempo=tempo)
        end = _milliseconds_to_ticks(
            note.start + max(1.0, note.dur * track_state.duration_scale),
            tempo=tempo,
        )
        velocity = max(1, min(127, round(note.vel)))
        events.append((start, 1, mido.Message(
            "note_on",
            channel=channel,
            note=note.pitch,
            velocity=velocity,
        )))
        events.append((end, 0, mido.Message(
            "note_off",
            channel=channel,
            note=note.pitch,
            velocity=0,
        )))
    return events


def _midi_track(events: list[tuple[int, int, object]]) -> object:
    events.sort(key=lambda item: (item[0], item[1]))
    midi_track = mido.MidiTrack()
    last_tick = 0
    for tick, _order, message in events:
        message.time = max(0, tick - last_tick)
        midi_track.append(message)
        last_tick = tick
    midi_track.append(mido.MetaMessage("end_of_track", time=0))
    return midi_track


def build_filtered_midi(
    tracks: list[TrackState],
    bpm: int,
    time_sig: int,
    out_path: Path,
    lyric_events: list[dict] | None = None,
) -> None:
    """Write a deterministic /4 MIDI projection of current editor tracks."""

    mid = mido.MidiFile(ticks_per_beat=_TICKS_PER_BEAT)
    meta_track, tempo = _build_meta_track(bpm, time_sig, lyric_events)
    mid.tracks.append(meta_track)
    for out_index, track_state in enumerate(tracks):
        channel = 9 if track_state.is_percussion else min(out_index, 8)
        mid.tracks.append(_midi_track(_track_events(
            track_state,
            channel,
            tempo=tempo,
        )))
    mid.save(out_path)


__all__ = ["build_filtered_midi"]
