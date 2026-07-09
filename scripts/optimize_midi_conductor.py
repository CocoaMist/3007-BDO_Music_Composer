#!/usr/bin/env python3
"""Apply conductor-style balancing and phrasing to an existing MIDI file."""

from __future__ import annotations

import argparse
from pathlib import Path

import mido


TRACK_PROFILES = {
    "A.PIANO 2": {"scale": 0.72, "floor": 44, "cap": 112, "pan": 56, "reverb": 28, "chorus": 10},
    "SYN BASS 2": {"scale": 0.94, "floor": 72, "cap": 108, "pan": 64, "reverb": 10, "chorus": 0},
    "BRIGHTNESS": {"scale": 0.58, "floor": 40, "cap": 92, "pan": 88, "reverb": 36, "chorus": 24},
    "MELODY": {"scale": 0.88, "floor": 82, "cap": 124, "pan": 62, "reverb": 34, "chorus": 12},
    "STRINGS": {"scale": 0.76, "floor": 50, "cap": 108, "pan": 76, "reverb": 42, "chorus": 22},
    "CRYSTAL": {"scale": 0.56, "floor": 46, "cap": 94, "pan": 96, "reverb": 48, "chorus": 30},
    "SYNBRASS 1": {"scale": 0.75, "floor": 70, "cap": 116, "pan": 44, "reverb": 30, "chorus": 14},
    "BOWEDGLASS": {"scale": 0.60, "floor": 34, "cap": 90, "pan": 98, "reverb": 52, "chorus": 32},
    "TUBULARBEL": {"scale": 0.72, "floor": 62, "cap": 104, "pan": 50, "reverb": 56, "chorus": 12},
    "DRUMS": {"scale": 0.88, "floor": 58, "cap": 118, "pan": 64, "reverb": 20, "chorus": 0},
    "DISTORTION": {"scale": 0.72, "floor": 48, "cap": 112, "pan": 34, "reverb": 24, "chorus": 8},
    "CLEAN GTR": {"scale": 0.68, "floor": 46, "cap": 104, "pan": 92, "reverb": 26, "chorus": 16},
    "TIMPANI": {"scale": 0.82, "floor": 48, "cap": 112, "pan": 64, "reverb": 36, "chorus": 0},
    "GTFRETNOIS": {"scale": 0.45, "floor": 32, "cap": 72, "pan": 30, "reverb": 12, "chorus": 0},
}


def clamp(value: float, low: int = 1, high: int = 127) -> int:
    return max(low, min(high, int(round(value))))


def track_name(track: mido.MidiTrack) -> str:
    for msg in track:
        if msg.type == "track_name":
            return msg.name
    return ""


def profile_for(name: str) -> dict[str, int | float]:
    return TRACK_PROFILES.get(name, {"scale": 0.72, "floor": 44, "cap": 108, "pan": 64, "reverb": 24, "chorus": 8})


def section_factor(tick: int, total_ticks: int) -> float:
    if total_ticks <= 0:
        return 1.0
    pos = tick / total_ticks
    points = [
        (0.00, 0.82),
        (0.10, 0.88),
        (0.22, 0.96),
        (0.34, 1.08),
        (0.48, 0.98),
        (0.62, 1.12),
        (0.78, 1.18),
        (0.92, 1.08),
        (1.00, 0.86),
    ]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= pos <= x1:
            ratio = (pos - x0) / (x1 - x0)
            return y0 + (y1 - y0) * ratio
    return points[-1][1]


def beat_factor(tick: int, ticks_per_beat: int) -> float:
    beat = (tick // ticks_per_beat) % 4
    if beat == 0:
        return 1.06
    if beat == 2:
        return 1.03
    return 0.97


def drum_velocity(note: int, velocity: int, factor: float, tick: int, ticks_per_beat: int) -> int:
    beat = (tick // ticks_per_beat) % 4
    if note in {35, 36}:  # kick
        factor *= 1.08 if beat in {0, 2} else 1.00
    elif note in {38, 40}:  # snare
        factor *= 1.12 if beat in {1, 3} else 1.02
    elif note in {42, 44, 46, 51, 59}:  # hats / ride
        factor *= 0.82
    elif note in {49, 57}:  # crashes
        factor *= 1.03
    return clamp(velocity * factor, 36, 120)


def add_channel_setup(messages: list[mido.Message], channel: int, prof: dict[str, int | float]) -> None:
    messages.extend(
        [
            mido.Message("control_change", channel=channel, control=7, value=100, time=0),
            mido.Message("control_change", channel=channel, control=10, value=int(prof["pan"]), time=0),
            mido.Message("control_change", channel=channel, control=91, value=int(prof["reverb"]), time=0),
            mido.Message("control_change", channel=channel, control=93, value=int(prof["chorus"]), time=0),
        ]
    )


def optimize_track(track: mido.MidiTrack, name: str, total_ticks: int, ticks_per_beat: int) -> mido.MidiTrack:
    prof = profile_for(name)
    out = mido.MidiTrack()
    abs_tick = 0
    configured_channels: set[int] = set()
    pending_setup: dict[int, list[mido.Message]] = {}

    for msg in track:
        abs_tick += msg.time
        new_msg = msg.copy()

        if msg.type in {"program_change", "note_on", "note_off", "control_change"} and hasattr(msg, "channel"):
            channel = msg.channel
            if channel not in configured_channels and channel not in pending_setup and msg.time > 0:
                pending_setup[channel] = []
                add_channel_setup(pending_setup[channel], channel, prof)
                configured_channels.add(channel)

        if msg.type == "note_on" and msg.velocity > 0:
            base = float(prof["scale"]) * section_factor(abs_tick, total_ticks) * beat_factor(abs_tick, ticks_per_beat)
            if name == "MELODY":
                if msg.note >= 64:
                    base *= 1.06
                if msg.velocity >= 120:
                    base *= 0.94
            elif name in {"CRYSTAL", "BRIGHTNESS", "BOWEDGLASS"}:
                base *= 0.92
            elif name in {"DISTORTION", "CLEAN GTR"}:
                base *= 0.98 if msg.note < 57 else 0.88

            if name == "DRUMS" or msg.channel == 9:
                new_msg.velocity = drum_velocity(msg.note, msg.velocity, base, abs_tick, ticks_per_beat)
            else:
                shaped = msg.velocity * base
                new_msg.velocity = clamp(max(int(prof["floor"]), shaped), int(prof["floor"]), int(prof["cap"]))

        elif msg.type == "control_change":
            if msg.control == 7:
                new_msg.value = min(msg.value, 104)
            elif msg.control == 11:
                new_msg.value = clamp(msg.value * section_factor(abs_tick, total_ticks), 48, 118)
            elif msg.control == 91:
                new_msg.value = max(msg.value, int(prof["reverb"]))
            elif msg.control == 93:
                new_msg.value = max(msg.value, int(prof["chorus"]))

        if pending_setup and msg.time > 0:
            first = True
            for channel, setup_messages in list(pending_setup.items()):
                for setup in setup_messages:
                    setup.time = msg.time if first else 0
                    out.append(setup)
                    first = False
                del pending_setup[channel]
            new_msg.time = 0

        out.append(new_msg)

    return out


def rebuild_tempo_track(track: mido.MidiTrack, total_ticks: int) -> mido.MidiTrack:
    existing_meta = [msg.copy(time=0) for msg in track if msg.is_meta and msg.type not in {"set_tempo", "end_of_track"}]
    events: list[tuple[int, mido.MetaMessage]] = []
    for msg in existing_meta:
        events.append((0, msg))

    tempo_points = [
        (0.00, 92),
        (0.06, 96),
        (0.28, 98),
        (0.36, 101),
        (0.52, 97),
        (0.63, 102),
        (0.79, 104),
        (0.94, 98),
        (0.985, 90),
    ]
    for pos, bpm in tempo_points:
        events.append((int(total_ticks * pos), mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0)))

    marker_points = [
        (0.00, "Conductor: restrained intro"),
        (0.34, "Conductor: chorus opens"),
        (0.62, "Conductor: lift"),
        (0.79, "Conductor: final push"),
        (0.94, "Conductor: coda relax"),
    ]
    for pos, label in marker_points:
        events.append((int(total_ticks * pos), mido.MetaMessage("marker", text=label, time=0)))

    events.sort(key=lambda item: item[0])
    out = mido.MidiTrack()
    previous = 0
    for tick, msg in events:
        msg.time = max(0, tick - previous)
        out.append(msg)
        previous = tick
    out.append(mido.MetaMessage("end_of_track", time=max(0, total_ticks - previous)))
    return out


def max_track_ticks(mid: mido.MidiFile) -> int:
    return max((sum(msg.time for msg in track) for track in mid.tracks), default=0)


def optimize(input_path: Path, output_path: Path) -> None:
    mid = mido.MidiFile(input_path)
    total_ticks = max_track_ticks(mid)
    out = mido.MidiFile(type=mid.type, ticks_per_beat=mid.ticks_per_beat, charset=mid.charset)

    for index, track in enumerate(mid.tracks):
        name = track_name(track)
        if index == 0:
            out.tracks.append(rebuild_tempo_track(track, total_ticks))
        else:
            out.tracks.append(optimize_track(track, name, total_ticks, mid.ticks_per_beat))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.save(output_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    optimize(args.input, args.output)


if __name__ == "__main__":
    main()
