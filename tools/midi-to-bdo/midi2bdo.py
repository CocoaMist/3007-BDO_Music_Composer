#!/usr/bin/env python3
"""Convert MIDI files to Black Desert Online music composer format (v9)."""

import argparse
from bisect import bisect_right
from collections import defaultdict, namedtuple
import struct
import os
import sys
import warnings
import mido
import _ice

Note = namedtuple('Note', ['pitch', 'vel', 'start', 'dur', 'ntype'])
BDO_VERSION = 9
HEADER_SIZE = 0x150  # Fixed header size before track data
NAME_FIELD_SIZE = 62  # Each character name field in bytes (31 UTF-16LE chars)
NOTE_SIZE = 20
TRACK_PREFIX_STRUCT = struct.Struct('<HH8sH')
NOTE_STRUCT = struct.Struct('<BBBBdd')
MAX_NOTES_PER_TRACK = 730
MAX_NOTES_PER_INSTRUMENT = (0x4E << 7) + 0x10
DEFAULT_BPM = 120
DEFAULT_TIME_SIG = 4
BDO_BPM_MIN = 1
BDO_BPM_MAX = 200
BDO_VELOCITY_MIN = 0
BDO_VELOCITY_MAX = 127
# Track settings: 8 bytes per track
# [0] inst_reverb  (per-instrument)  [1] eff_reverb     (global)
# [2] inst_delay   (per-instrument)  [3] eff_delay      (global)
# [4] inst_chorus  (per-instrument)  [5] chorus_feedback (global)
# [6] chorus_lfo_depth (global)      [7] chorus_lfo_freq (global)
TRACK_SETTINGS = bytes(8)  # all zeros = dry/no effector
DEFAULT_VOLUME = 0x46  # 70 — BDO's default track volume

BDO_INSTRUMENTS = {
    # Beginner
    'beginner_guitar':    0x00,
    'beginner_flute':     0x01,
    'beginner_recorder':  0x02,
    'hand_drum':          0x04,
    'cymbals':            0x05,
    'beginner_harp':      0x06,
    'beginner_piano':     0x07,
    'beginner_violin':    0x08,
    # Florchestra
    'guitar':             0x0a,
    'flute':              0x0b,
    'drum_set':           0x0d,
    'marnibass':          0x0e,
    'contrabass':         0x0f,
    'harp':               0x10,
    'piano':              0x11,
    'violin':             0x12,
    'handpan':            0x13,
    # Marnian
    'marnian_wavy':       0x14,
    'marnian_illusion':   0x18,
    'marnian_secret':     0x1c,
    'marnian_sandwich':   0x20,
    # Electric Guitar
    'eguitar_silver':     0x24,
    'eguitar_highway':    0x25,
    'eguitar_hexe':       0x26,
    # Florchestra (continued)
    'clarinet':           0x27,
    'horn':               0x28,
}

DEFAULT_INSTRUMENT = BDO_INSTRUMENTS['piano']

BDO_INSTRUMENT_NAMES = {
    0x00: '新手专用：吉他',
    0x01: '新手专用：长笛',
    0x02: '新手专用：笛子',
    0x04: '新手专用：手鼓',
    0x05: '新手专用：钹',
    0x06: '新手专用：竖琴',
    0x07: '新手专用：钢琴',
    0x08: '新手专用：小提琴',
    0x0a: '弗罗凯特拉：原声吉他',
    0x0b: '弗罗凯特拉：长笛',
    0x0d: '弗罗凯特拉：架子鼓套装',
    0x0e: '玛勒尼斯：贝斯',
    0x0f: '弗罗凯特拉：肯特拉贝斯',
    0x10: '弗罗凯特拉：竖琴',
    0x11: '弗罗凯特拉：钢琴',
    0x12: '弗罗凯特拉：小提琴',
    0x13: '弗罗凯特拉：手碟',
    0x14: '玛勒尼斯：玛勒尼恩 - 波纹行星',
    0x18: '玛勒尼斯：玛勒尼恩 - 幻象树',
    0x1c: '玛勒尼斯：玛勒尼恩 - 秘密笔记',
    0x20: '玛勒尼斯：玛勒尼恩 - 三明治',
    0x24: '玛勒尼斯：电吉他 - 银色水波',
    0x25: '玛勒尼斯：电吉他 - 高速路',
    0x26: '玛勒尼斯：电吉他 - 赫赛德兰',
    0x27: '弗罗凯特拉：竖笛',
    0x28: '弗罗凯特拉：圆号',
}

# Standard General MIDI program names (0–127)
_GM_PROGRAM_NAMES = [
    # 0–7: Piano
    '原声大钢琴', '明亮原声钢琴', '电钢琴',
    '酒吧钢琴', '电钢琴 1', '电钢琴 2', '羽管键琴', '击弦古钢琴',
    # 8–15: Chromatic Percussion
    '钢片琴', '钟琴', '音乐盒', '颤音琴',
    '马林巴', '木琴', '管钟', '扬琴',
    # 16–23: Organ
    '拉杆风琴', '打击风琴', '摇滚风琴', '教堂风琴',
    '簧风琴', '手风琴', '口琴', '探戈手风琴',
    # 24–31: Guitar
    '原声吉他（尼龙弦）', '原声吉他（钢弦）', '电吉他（爵士）',
    '电吉他（清音）', '电吉他（闷音）', '过载吉他',
    '失真吉他', '吉他泛音',
    # 32–39: Bass
    '原声贝斯', '电贝斯（指弹）', '电贝斯（拨片）',
    '无品贝斯', '击弦贝斯 1', '击弦贝斯 2', '合成贝斯 1', '合成贝斯 2',
    # 40–47: Strings
    '小提琴', '中提琴', '大提琴', '低音提琴',
    '颤音弦乐', '拨奏弦乐', '管弦竖琴', '定音鼓',
    # 48–55: Ensemble
    '弦乐合奏 1', '弦乐合奏 2', '合成弦乐 1', '合成弦乐 2',
    '人声合唱 Aah', '人声 Ooh', '合成合唱', '管弦乐打击',
    # 56–63: Brass
    '小号', '长号', '大号', '弱音小号',
    '法国号', '铜管组', '合成铜管 1', '合成铜管 2',
    # 64–71: Reed
    '高音萨克斯', '中音萨克斯', '次中音萨克斯', '上低音萨克斯',
    '双簧管', '英国管', '巴松管', '单簧管',
    # 72–79: Pipe
    '短笛', '长笛', '竖笛', '排箫',
    '瓶笛', '尺八', '口哨', '陶笛',
    # 80–87: Synth Lead
    '合成主音 1（方波）', '合成主音 2（锯齿波）', '合成主音 3（汽笛）', '合成主音 4（吹管）',
    '合成主音 5（锐音）', '合成主音 6（人声）', '合成主音 7（五度）', '合成主音 8（贝斯+主音）',
    # 88–95: Synth Pad
    '合成音色 1（新时代）', '合成音色 2（温暖）', '合成音色 3（复合）', '合成音色 4（合唱）',
    '合成音色 5（弓弦）', '合成音色 6（金属）', '合成音色 7（光环）', '合成音色 8（扫频）',
    # 96–103: Synth Effects
    '音效 1（雨）', '音效 2（配乐）', '音效 3（水晶）', '音效 4（氛围）',
    '音效 5（明亮）', '音效 6（精灵）', '音效 7（回声）', '音效 8（科幻）',
    # 104–111: Ethnic
    '西塔琴', '班卓琴', '三味线', '古筝', '卡林巴', '风笛', '民谣小提琴', '唢呐',
    # 112–119: Percussive
    '铃铛', '阿哥哥铃', '钢鼓', '木鱼',
    '太鼓', '旋律鼓', '合成鼓', '反向钹',
    # 120–127: Sound Effects
    '吉他品噪', '呼吸声', '海浪声', '鸟鸣',
    '电话铃', '直升机', '掌声', '枪声',
]


def gm_program_name(program):
    """Return the human-readable GM instrument name for a program number (0–127)."""
    if 0 <= program < len(_GM_PROGRAM_NAMES):
        return _GM_PROGRAM_NAMES[program]
    return f'Program {program}'


# BDO drum note type (melodic notes use 0, drums use 99)
DRUM_NOTE_TYPE = 99
DRUM_NOTE_MAX_DURATION_MS = 80.0
DRUM_ROLL_PITCHES = {63, 64}

# GM MIDI percussion note → BDO drum pitch (range 48–64)
_GM_TO_BDO_DRUM = {
    35: 48,  # Acoustic Bass Drum → Kck
    36: 48,  # Bass Drum 1 → Kck
    37: 49,  # Side Stick → SnrSide
    38: 50,  # Acoustic Snare → SnrHit
    39: 50,  # Hand Clap → SnrHit
    40: 50,  # Electric Snare → SnrHit
    41: 53,  # Low Floor Tom → Tom1
    42: 54,  # Closed Hi-Hat → HihatC
    43: 55,  # High Floor Tom → Tom2
    44: 56,  # Pedal Hi-Hat → HatPdl
    45: 57,  # Low Tom → Tom3
    46: 58,  # Open Hi-Hat → HihatO
    47: 59,  # Low-Mid Tom → Tom4
    48: 60,  # Hi-Mid Tom → Tom5
    49: 61,  # Crash Cymbal 1 → CymCrsh
    50: 60,  # High Tom → Tom5
    51: 62,  # Ride Cymbal 1 → CymRide
    52: 61,  # Chinese Cymbal → CymCrsh
    53: 62,  # Ride Bell → CymRide
    54: 61,  # Tambourine → CymCrsh
    55: 61,  # Splash Cymbal → CymCrsh
    56: 51,  # Cowbell → RimShot
    57: 61,  # Crash Cymbal 2 → CymCrsh
    58: 51,  # Vibraslap → RimShot
    59: 62,  # Ride Cymbal 2 → CymRide
    60: 63,  # High Bongo → SnrRollS fallback
    61: 64,  # Low Bongo → SnrRollL fallback
}


def map_drum_notes(notes):
    """Convert MIDI percussion notes to BDO drum format.

    Maps GM percussion pitches to BDO drum pitches (48–64) and sets
    the note type to DRUM_NOTE_TYPE (99).
    """
    mapped = []
    for n in notes:
        bdo_pitch = _GM_TO_BDO_DRUM.get(n.pitch, 48)  # default to kick
        dur = n.dur if bdo_pitch in DRUM_ROLL_PITCHES else min(n.dur, DRUM_NOTE_MAX_DURATION_MS)
        mapped.append(Note(bdo_pitch, n.vel, n.start, max(1.0, dur), DRUM_NOTE_TYPE))
    return mapped


def normalize_drum_note_timing(notes):
    """Remove duplicate one-shot drum hits and prevent same-pitch overlaps."""
    if not notes:
        return notes

    dedup = {}
    for n in notes:
        key = (n.pitch, round(n.start, 3), n.ntype)
        existing = dedup.get(key)
        if existing is None or n.vel > existing.vel:
            dedup[key] = n

    by_pitch = defaultdict(list)
    passthrough = []
    for n in dedup.values():
        if n.ntype == DRUM_NOTE_TYPE and n.pitch not in DRUM_ROLL_PITCHES:
            by_pitch[n.pitch].append(n)
        else:
            passthrough.append(n)

    normalized = list(passthrough)
    for pitch_notes in by_pitch.values():
        ordered = sorted(pitch_notes, key=lambda n: (n.start, n.dur))
        for idx, n in enumerate(ordered):
            dur = min(n.dur, DRUM_NOTE_MAX_DURATION_MS)
            if idx + 1 < len(ordered):
                next_start = ordered[idx + 1].start
                if n.start + dur >= next_start:
                    dur = max(1.0, next_start - n.start - 1.0)
            normalized.append(n._replace(dur=max(1.0, dur)))
    normalized.sort(key=lambda n: (n.start, n.pitch, n.ntype))
    return normalized


# GM program number → BDO instrument name
_GM_RANGES = [
    (24,  'piano'),           # 0–23: pianos, chromatic perc, organs
    (32,  'guitar'),          # 24–31: guitar
    (40,  'contrabass'),      # 32–39: bass
    (42,  'violin'),          # 40–41: violin, viola
    (44,  'contrabass'),      # 42–43: cello, contrabass
    (47,  'harp'),            # 44–46: pizz strings, harp
    (48,  'drum_set'),        # 47: timpani
    (56,  'violin'),          # 48–55: string ensembles, choir
    (64,  'horn'),            # 56–63: brass
    (72,  'clarinet'),        # 64–71: sax, reed woodwinds
    (80,  'flute'),           # 72–79: flute family
    (88,  'flute'),           # 80–87: lead synths — conservative melodic fallback
    (96,  'violin'),          # 88–95: pad synths — sustained ensemble fallback
    (104, 'piano'),           # 96–103: synth effects — avoid crystal-like Marnian guesses
    (112, 'handpan'),         # 104–111: ethnic
    (120, 'hand_drum'),       # 112–119: percussive
    (128, 'piano'),           # 120–127: sound FX — fallback
]


def gm_to_bdo_instrument(program, is_percussion=False):
    """Map a GM program number (0–127) to a BDO instrument ID."""
    if is_percussion:
        return BDO_INSTRUMENTS['drum_set']
    if program in (24, 25):
        return BDO_INSTRUMENTS['guitar']
    if program in (26, 27, 28):
        return BDO_INSTRUMENTS['eguitar_silver']
    if program == 29:
        return BDO_INSTRUMENTS['eguitar_highway']
    if program in (30, 31):
        return BDO_INSTRUMENTS['eguitar_hexe']
    if program == 32:
        return BDO_INSTRUMENTS['contrabass']
    if 33 <= program <= 39:
        return BDO_INSTRUMENTS['marnibass']
    if program == 46:
        return BDO_INSTRUMENTS['harp']
    if program == 47:
        return BDO_INSTRUMENTS['drum_set']
    if 80 <= program <= 87:
        return BDO_INSTRUMENTS['flute']
    if 88 <= program <= 95:
        return BDO_INSTRUMENTS['violin']
    if 96 <= program <= 103:
        return BDO_INSTRUMENTS['piano']
    for upper, name in _GM_RANGES:
        if program < upper:
            return BDO_INSTRUMENTS[name]
    return DEFAULT_INSTRUMENT


def _clamp_int(value, low, high, name):
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer") from None
    if value < low or value > high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


def _clamp_velocity(value, name="velocity"):
    return _clamp_int(value, BDO_VELOCITY_MIN, BDO_VELOCITY_MAX, name)

# Broadest range verified from game-saved instrument range scores. Individual
# instruments have narrower ranges and are validated by the GUI capability map.
BDO_NOTE_MIN = 12   # C0
BDO_NOTE_MAX = 119  # B8


def _parse_midi_legacy(midi_path, apply_sustain=True, flatten_tempo=False):
    """Parse a MIDI file and extract notes grouped by channel.

    Notes are grouped by MIDI channel so that each channel's instrument
    (program change) can be mapped to a BDO instrument.

    Args:
        midi_path: Path to the MIDI file.
        apply_sustain: Whether to extend notes held by sustain pedal (CC64).
        flatten_tempo: If True and the MIDI has multiple tempos, set the BPM
            header to 200 (BDO's max).  Note positions are still computed with
            variable tempo (real-time ms), so playback preserves rubato.  The
            high BPM minimizes quantization error from BDO's 1/64 grid.

    Returns:
        (bpm, time_sig_num, channel_groups, tempo_changes) where
        channel_groups is a list of (notes, gm_program, is_percussion)
        per channel that has notes, and tempo_changes is the number of
        tempo change events found.
    """
    mid = mido.MidiFile(midi_path)

    # Build tempo metadata and capture the first time signature in one pass.
    tempo_map = []  # [(tick, tempo_us)]
    time_sig_num = DEFAULT_TIME_SIG
    found_time_sig = False
    for track in mid.tracks:
        abs_tick = 0
        for msg in track:
            abs_tick += msg.time
            if msg.type == 'set_tempo':
                tempo_map.append((abs_tick, msg.tempo))
            elif not found_time_sig and msg.type == 'time_signature':
                time_sig_num = msg.numerator
                found_time_sig = True
    tempo_map.sort(key=lambda x: x[0])
    if not tempo_map:
        tempo_map = [(0, mido.bpm2tempo(DEFAULT_BPM))]
    elif tempo_map[0][0] > 0:
        tempo_map.insert(0, (0, mido.bpm2tempo(DEFAULT_BPM)))
    elif tempo_map[0][0] < 0:
        raise ValueError("Invalid MIDI tempo map")

    # Keep the last tempo event at each tick and precompute cumulative time.
    normalized_tempo_map = []
    for tick, tempo in tempo_map:
        if normalized_tempo_map and normalized_tempo_map[-1][0] == tick:
            normalized_tempo_map[-1] = (tick, tempo)
        else:
            normalized_tempo_map.append((tick, tempo))
    tempo_map = normalized_tempo_map

    tempo_ticks = [tick for tick, _ in tempo_map]
    tempo_values = [tempo for _, tempo in tempo_map]
    tempo_ms = [0.0] * len(tempo_map)
    for i in range(1, len(tempo_map)):
        prev_tick = tempo_ticks[i - 1]
        tick = tempo_ticks[i]
        tempo_ms[i] = (
            tempo_ms[i - 1]
            + mido.tick2second(tick - prev_tick, mid.ticks_per_beat, tempo_values[i - 1]) * 1000
        )

    # Extract time signature
    time_sig_num = DEFAULT_TIME_SIG
    for track in mid.tracks:
        for msg in track:
            if msg.type == 'time_signature':
                time_sig_num = msg.numerator
                break
        else:
            continue
        break

    if flatten_tempo and len(tempo_map) > 1:
        bpm = 200  # max BDO allows — minimizes 1/64 grid quantization error
    else:
        bpm = round(mido.tempo2bpm(tempo_map[0][1]))

    def ticks_to_ms(ticks):
        """Convert absolute ticks to milliseconds using the tempo map."""
        idx = bisect_right(tempo_ticks, ticks) - 1
        if idx < 0:
            idx = 0
        return (
            tempo_ms[idx]
            + mido.tick2second(ticks - tempo_ticks[idx], mid.ticks_per_beat, tempo_values[idx]) * 1000
        )

    def append_note(grouped_notes, ch, program, pitch, vel, start_tick, end_tick):
        start_ms = ticks_to_ms(start_tick)
        dur_ms = ticks_to_ms(end_tick) - start_ms
        if dur_ms <= 0:
            return
        group_key = (ch, 0 if ch == 9 else program, ch == 9)
        grouped_notes[group_key].append(Note(pitch, vel, start_ms, dur_ms, 0))

    # Collect notes per MIDI channel across all tracks
    # Note tuple: (pitch, vel, start_ms, dur_ms, note_type)
    # note_type: 0 = normal
    channel_notes = defaultdict(list)  # {(channel, program, is_percussion): [Note]}
    current_program = defaultdict(int)
    active = {}     # {(channel, pitch): (velocity, start_tick, program)}
    sustain = {}    # {channel: bool}
    sustained = {}  # {(channel, pitch): (velocity, start_tick, program)}
    abs_tick = 0

    for msg in mido.merge_tracks(mid.tracks):
        abs_tick += msg.time
        if not hasattr(msg, 'channel'):
            continue
        ch = msg.channel

        if msg.type == 'program_change':
            current_program[ch] = msg.program

        elif msg.type == 'note_on' and msg.velocity > 0:
            key = (ch, msg.note)
            # End any sustained version of this note
            if key in sustained:
                vel, start_tick, program = sustained.pop(key)
                append_note(channel_notes, ch, program, msg.note, vel, start_tick, abs_tick)
            if key in active:
                vel, start_tick, program = active.pop(key)
                append_note(channel_notes, ch, program, msg.note, vel, start_tick, abs_tick)
            active[key] = (msg.velocity, abs_tick, current_program[ch])

        elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
            key = (ch, msg.note)
            if key in active:
                if sustain.get(ch, False):
                    sustained[key] = active.pop(key)
                else:
                    vel, start_tick, program = active.pop(key)
                    append_note(channel_notes, ch, program, msg.note, vel, start_tick, abs_tick)

        elif msg.type == 'control_change' and msg.control == 64 and apply_sustain:
            if msg.value >= 64:
                sustain[ch] = True
            else:
                sustain[ch] = False
                # Release all sustained notes on this channel
                to_release = [(k, v) for k, v in sustained.items() if k[0] == ch]
                for key, (vel, start_tick, program) in to_release:
                    append_note(channel_notes, key[0], program, key[1], vel, start_tick, abs_tick)
                    del sustained[key]

    # End any still-active or sustained notes from this MIDI stream.
    for store in (active, sustained):
        for (ch, pitch), (vel, start_tick, program) in store.items():
            group_key = (ch, 0 if ch == 9 else program, ch == 9)
            channel_notes[group_key].append(Note(pitch, vel, ticks_to_ms(start_tick), 100.0, 0))

    # Build channel_groups: (notes, gm_program, is_percussion)
    channel_groups = []
    for ch, program, is_perc in sorted(channel_notes):
        notes = channel_notes[(ch, program, is_perc)]
        if not notes:
            continue
        notes.sort(key=lambda n: n.start)
        channel_groups.append((notes, program, is_perc))

    return bpm, time_sig_num, channel_groups, len(tempo_map)


def _iter_merged_events_no_copy(tracks):
    """Yield (absolute_tick, msg) across tracks without copying mido messages."""
    events = []
    sequence = 0
    for track in tracks:
        abs_tick = 0
        for msg in track:
            abs_tick += msg.time
            if msg.type == 'end_of_track':
                continue
            events.append((abs_tick, sequence, msg))
            sequence += 1
    events.sort(key=lambda item: (item[0], item[1]))
    for abs_tick, _sequence, msg in events:
        yield abs_tick, msg


def _parse_midi_fast(midi_path, apply_sustain=True, flatten_tempo=False):
    """Parse MIDI notes using incremental time conversion over the merged event stream."""
    mid = mido.MidiFile(midi_path)

    tempo_map = []
    time_sig_num = DEFAULT_TIME_SIG
    found_time_sig = False
    for track in mid.tracks:
        abs_tick = 0
        for msg in track:
            abs_tick += msg.time
            if msg.type == 'set_tempo':
                tempo_map.append((abs_tick, msg.tempo))
            elif not found_time_sig and msg.type == 'time_signature':
                time_sig_num = msg.numerator
                found_time_sig = True

    tempo_map.sort(key=lambda item: item[0])
    if not tempo_map:
        tempo_map = [(0, mido.bpm2tempo(DEFAULT_BPM))]
    elif tempo_map[0][0] > 0:
        tempo_map.insert(0, (0, mido.bpm2tempo(DEFAULT_BPM)))
    elif tempo_map[0][0] < 0:
        raise ValueError("Invalid MIDI tempo map")

    normalized_tempo_map = []
    for tick, tempo in tempo_map:
        if normalized_tempo_map and normalized_tempo_map[-1][0] == tick:
            normalized_tempo_map[-1] = (tick, tempo)
        else:
            normalized_tempo_map.append((tick, tempo))
    tempo_map = normalized_tempo_map

    if flatten_tempo and len(tempo_map) > 1:
        bpm = 200
    else:
        bpm = round(mido.tempo2bpm(tempo_map[0][1]))

    ticks_per_beat = mid.ticks_per_beat
    current_tempo = tempo_map[0][1]
    abs_ms = 0.0

    def delta_ticks_to_ms(delta_ticks, tempo):
        return delta_ticks * tempo / ticks_per_beat / 1000

    def append_note(grouped_notes, ch, program, pitch, vel, start_ms, end_ms):
        dur_ms = end_ms - start_ms
        if dur_ms <= 0:
            return
        group_key = (ch, 0 if ch == 9 else program, ch == 9)
        grouped_notes[group_key].append(Note(pitch, vel, start_ms, dur_ms, 0))

    channel_notes = defaultdict(list)
    current_program = defaultdict(int)
    active = {}
    sustain = {}
    sustained = {}
    last_tick = 0

    for abs_tick, msg in _iter_merged_events_no_copy(mid.tracks):
        delta_ticks = abs_tick - last_tick
        if delta_ticks:
            abs_ms += delta_ticks_to_ms(delta_ticks, current_tempo)
            last_tick = abs_tick
        if msg.type == 'set_tempo':
            current_tempo = msg.tempo
            continue
        if not hasattr(msg, 'channel'):
            continue

        ch = msg.channel
        if msg.type == 'program_change':
            current_program[ch] = msg.program
        elif msg.type == 'note_on' and msg.velocity > 0:
            key = (ch, msg.note)
            if key in sustained:
                vel, start_ms, program = sustained.pop(key)
                append_note(channel_notes, ch, program, msg.note, vel, start_ms, abs_ms)
            if key in active:
                vel, start_ms, program = active.pop(key)
                append_note(channel_notes, ch, program, msg.note, vel, start_ms, abs_ms)
            active[key] = (msg.velocity, abs_ms, current_program[ch])
        elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
            key = (ch, msg.note)
            if key in active:
                if sustain.get(ch, False):
                    sustained[key] = active.pop(key)
                else:
                    vel, start_ms, program = active.pop(key)
                    append_note(channel_notes, ch, program, msg.note, vel, start_ms, abs_ms)
        elif msg.type == 'control_change' and msg.control == 64 and apply_sustain:
            if msg.value >= 64:
                sustain[ch] = True
            else:
                sustain[ch] = False
                to_release = [(k, v) for k, v in sustained.items() if k[0] == ch]
                for key, (vel, start_ms, program) in to_release:
                    append_note(channel_notes, key[0], program, key[1], vel, start_ms, abs_ms)
                    del sustained[key]

    for store in (active, sustained):
        for (ch, pitch), (vel, start_ms, program) in store.items():
            group_key = (ch, 0 if ch == 9 else program, ch == 9)
            channel_notes[group_key].append(Note(pitch, vel, start_ms, 100.0, 0))

    channel_groups = []
    for ch, program, is_perc in sorted(channel_notes):
        notes = channel_notes[(ch, program, is_perc)]
        if notes:
            notes.sort(key=lambda n: n.start)
            channel_groups.append((notes, program, is_perc))

    return bpm, time_sig_num, channel_groups, len(tempo_map)


parse_midi = _parse_midi_fast


def clamp_notes(notes):
    """Clamp note pitches to BDO's supported range."""
    clamped = []
    for n in notes:
        p = n.pitch
        if p < BDO_NOTE_MIN:
            p = p + 12 * ((BDO_NOTE_MIN - p + 11) // 12)
        elif p > BDO_NOTE_MAX:
            p = p - 12 * ((p - BDO_NOTE_MAX + 11) // 12)
        p = max(BDO_NOTE_MIN, min(BDO_NOTE_MAX, p))
        clamped.append(n._replace(pitch=p))
    return clamped


def split_notes(notes, max_per_track=MAX_NOTES_PER_TRACK):
    """Split a note list into chunks that fit BDO's per-track limit."""
    if len(notes) <= max_per_track:
        return [notes]
    chunks = []
    for i in range(0, len(notes), max_per_track):
        chunks.append(notes[i:i + max_per_track])
    return chunks


def encode_name(name, size=NAME_FIELD_SIZE):
    """Encode a character name as UTF-16LE, padded/truncated to size bytes."""
    max_chars = size // 2
    encoded = name[:max_chars].encode('utf-16-le')
    return encoded.ljust(size, b'\x00')[:size]


def build_bdo_binary(bpm, time_sig_num, instrument_groups, char_name='MIDI',
                     owner_id=0, track_settings=None):
    """Build the plaintext BDO binary (everything after the 4-byte version).

    Args:
        bpm: Tempo in BPM
        time_sig_num: Time signature numerator
        instrument_groups: List of (inst_id, [track_note_lists]) tuples.
            Each group is one BDO instrument with its tracks (already split
            at 730).  An empty trailing track is appended automatically.
        char_name: Character name to embed
        owner_id: Account/family ID for edit permissions
        track_settings: 8 bytes for track settings (pan, effector, etc.).
            If None, uses TRACK_SETTINGS (all zeros).

    Returns:
        bytes: The plaintext payload (to be encrypted)
    """
    settings = track_settings if track_settings is not None else TRACK_SETTINGS
    num_instruments = len(instrument_groups)

    # Build comma-separated instrument tag (ASCII decimal IDs)
    inst_tag = ','.join(str(inst_id) for inst_id, _ in instrument_groups).encode('ascii')

    buf = bytearray()

    # Owner ID (4 bytes) — controls who can edit in-game
    buf.extend(struct.pack('<I', owner_id))
    # Zeros (4 bytes)
    buf.extend(b'\x00' * 4)
    # Character names (62 bytes each, BPM follows immediately after)
    buf.extend(encode_name(char_name))
    buf.extend(encode_name(char_name))
    # BPM (uint16 LE)
    buf.extend(struct.pack('<H', bpm))
    # Time signature numerator (uint16 LE)
    buf.extend(struct.pack('<H', time_sig_num))
    # Instrument tag (variable length, zero-padded into the padding area)
    buf.extend(inst_tag)
    # Zero padding to HEADER_SIZE (0x150)
    padding_needed = HEADER_SIZE - len(buf)
    buf.extend(b'\x00' * padding_needed)

    def _write_track(buf, inst_id, notes):
        """Write a single track: data_size + marker + settings + note_count + notes."""
        note_count = len(notes)
        track_marker = inst_id | (DEFAULT_VOLUME << 8)
        data_size = 2 + 8 + 2 + note_count * NOTE_SIZE
        buf.extend(TRACK_PREFIX_STRUCT.pack(data_size, track_marker, settings, note_count))
        for n in notes:
            buf.extend(NOTE_STRUCT.pack(
                n.pitch & 0x7F,
                n.ntype & 0xFF,
                n.vel & 0x7F,
                n.vel & 0x7F,
                n.start,
                n.dur,
            ))

    # Write instrument groups
    for g, (inst_id, tracks) in enumerate(instrument_groups):
        # Each group's track count: first group's count is in the file header,
        # subsequent groups prefix their own count
        group_track_count = len(tracks) + 1  # +1 for empty trailing track

        if g == 0:
            # File header: 0x00 byte + num_instruments(u16) + first_group_tracks(u16)
            buf.append(0x00)
            buf.extend(struct.pack('<H', num_instruments))
            buf.extend(struct.pack('<H', group_track_count))
        else:
            # Subsequent groups: just the track count
            buf.extend(struct.pack('<H', group_track_count))

        # Data tracks
        for track_notes in tracks:
            _write_track(buf, inst_id, track_notes)

        # Empty trailing track (required by BDO)
        _write_track(buf, inst_id, [])

    # Pad to 8-byte alignment (ICE cipher block size)
    remainder = len(buf) % 8
    if remainder:
        buf.extend(b'\x00' * (8 - remainder))

    return bytes(buf)


def encrypt_bdo(plaintext):
    """Encrypt the plaintext payload with ICE and prepend the version header."""
    return struct.pack('<I', BDO_VERSION) + _ice.encrypt(plaintext)


def extract_owner_id(bdo_path):
    """Extract the owner ID and character name from an existing BDO file.

    Only works on single-note files (< 512 bytes payload). This prevents
    misuse for decrypting full compositions.

    Returns:
        (owner_id, char_name) where owner_id is an int and char_name is a str.

    Raises:
        ValueError: If the file is too large (not a single-note file).
    """
    with open(bdo_path, 'rb') as f:
        data = f.read()
    if len(data) < 4:
        raise ValueError("File too small to be a BDO music file")
    version = struct.unpack_from('<I', data, 0)[0]
    if version != BDO_VERSION:
        raise ValueError(f"Unsupported BDO music file version: {version}")
    # decrypt_owner_header enforces a 512-byte payload size limit
    plaintext = _ice.decrypt_owner_header(data[4:])
    if len(plaintext) < 8 + NAME_FIELD_SIZE:
        raise ValueError("BDO music file header is incomplete")

    owner_id = struct.unpack_from('<I', plaintext, 0)[0]
    char_name = plaintext[8:8 + NAME_FIELD_SIZE].decode('utf-16-le', errors='replace').rstrip('\x00')
    return owner_id, char_name


def rescale_velocity(notes, vel_min=0, vel_max=127):
    """Rescale note velocities to fit within [vel_min, vel_max]. Skips sustain pedal notes."""
    vel_min = _clamp_velocity(vel_min, "vel_min")
    vel_max = _clamp_velocity(vel_max, "vel_max")
    if vel_min > vel_max:
        raise ValueError("vel_min cannot be greater than vel_max")
    if not notes:
        return notes
    normal = [n for n in notes if n.ntype == 0]
    if not normal:
        return notes
    src_min = min(n.vel for n in normal)
    src_max = max(n.vel for n in normal)
    if src_min == src_max:
        flat_vel = (vel_min + vel_max) // 2
        return [n._replace(vel=flat_vel) if n.ntype == 0 else n for n in notes]
    result = []
    for n in notes:
        if n.ntype == 0:
            scaled = vel_min + (n.vel - src_min) / (src_max - src_min) * (vel_max - vel_min)
            result.append(n._replace(vel=round(scaled)))
        else:
            result.append(n)
    return result


def floor_velocity(notes, floor=100):
    """Proportionally scale velocities so the quietest note becomes floor, clamped to 127."""
    floor = _clamp_velocity(floor, "vel_floor")
    if not notes:
        return notes
    normal = [n for n in notes if n.ntype == 0]
    if not normal:
        return notes
    src_min = min(n.vel for n in normal)
    if src_min == 0 or src_min >= floor:
        return notes
    ratio = floor / src_min
    return [n._replace(vel=min(round(n.vel * ratio), 127)) if n.ntype == 0 else n
            for n in notes]


def stepped_velocity(notes, base=99, step=5):
    """Map each unique velocity level to stepped values: base, base+step, base+2*step, ..., 127."""
    base = _clamp_velocity(base, "vel_step base")
    step = _clamp_int(step, 0, BDO_VELOCITY_MAX, "vel_step step")
    if not notes:
        return notes
    normal_vels = sorted(set(n.vel for n in notes if n.ntype == 0))
    if not normal_vels:
        return notes
    vel_map = {}
    for i, v in enumerate(normal_vels):
        vel_map[v] = min(base + i * step, 127)
    # Ensure the loudest is always 127
    vel_map[normal_vels[-1]] = 127
    return [n._replace(vel=vel_map.get(n.vel, n.vel)) if n.ntype == 0 else n
            for n in notes]


# Layer-aware velocity levels based on analysis of well-made BDO compositions.
# Good composers use discrete steps that avoid harsh sample-switch boundaries.
BDO_VEL_LEVELS = [80, 90, 100, 121]


def layered_velocity(notes, levels=None, scale=1.0):
    """Map velocities to BDO-optimized discrete levels.

    Distributes unique MIDI velocity values evenly across the given levels,
    preserving relative dynamics while avoiding harsh sample-switch boundaries.

    Args:
        notes: List of Note tuples.
        levels: List of velocity levels to map to.
        scale: Volume scale factor (0.1–2.0). Controls which subset of levels
            is used: <1.0 limits to quieter levels, >1.0 biases toward louder.
            At 1.0 the full range is used.
    """
    if not notes:
        return notes
    if levels is None:
        levels = BDO_VEL_LEVELS
    # Apply scale by multiplying levels directly, allowing sub-80 velocities
    if scale != 1.0:
        levels = sorted(set(max(1, min(127, round(l * scale))) for l in levels))

    normal_vels = sorted(set(n.vel for n in notes if n.ntype == 0))
    if not normal_vels:
        return notes
    if len(normal_vels) == 1:
        vel_map = {normal_vels[0]: levels[len(levels) // 2]}
    else:
        vel_map = {}
        for i, v in enumerate(normal_vels):
            # Map position in the velocity range to position in levels
            idx = round(i / (len(normal_vels) - 1) * (len(levels) - 1))
            vel_map[v] = levels[idx]
    return [n._replace(vel=vel_map.get(n.vel, n.vel)) if n.ntype == 0 else n
            for n in notes]


def transpose_notes(notes, semitones):
    """Shift all note pitches by the given number of semitones."""
    return [n._replace(pitch=n.pitch + semitones) for n in notes]


def make_track_settings(reverb=0, delay=0, chorus=None):
    """Build the 8-byte track settings from effector parameters.

    Args:
        reverb: Reverb level 0-127 (global effector only)
        delay: Delay level 0-127 (global effector only)
        chorus: None or tuple (feedback, lfo_depth, lfo_freq) each 0-127

    Returns:
        bytes: 8-byte track settings (per-instrument sends left at 0)
    """
    s = bytearray(8)
    # Per-instrument sends (bytes 0, 2, 4) left at 0 — set manually in editor
    s[1] = _clamp_int(reverb, 0, BDO_VELOCITY_MAX, "reverb")    # eff reverb
    s[3] = _clamp_int(delay, 0, BDO_VELOCITY_MAX, "delay")     # eff delay
    if chorus:
        fb, depth, freq = chorus
        s[5] = _clamp_int(fb, 0, BDO_VELOCITY_MAX, "chorus feedback")
        s[6] = _clamp_int(depth, 0, BDO_VELOCITY_MAX, "chorus depth")
        s[7] = _clamp_int(freq, 0, BDO_VELOCITY_MAX, "chorus frequency")
    return bytes(s)


def channel_groups_to_bdo(bpm, time_sig_num, channel_groups, bpm_override=None,
                          char_name='MIDI', vel_range=None, vel_floor=None,
                          vel_step=None, vel_layered=False, transpose=0,
                          owner_id=0, instrument_map=None, reverb=0,
                          delay=0, chorus=None, vel_scales=None,
                          articulation_map=None, preserve_note_types=False):
    """Convert parsed MIDI channel groups to BDO format.

    Args:
        instrument_map: Optional dict {(gm_program, is_percussion): bdo_instrument_id}.
            When provided, overrides automatic GM→BDO mapping.  Groups that
            resolve to the same BDO instrument have their notes merged.
        reverb: Reverb level 0-127
        delay: Delay level 0-127
        chorus: None or tuple (feedback, lfo_depth, lfo_freq) each 0-127
        vel_scales: Optional dict {channel_index: float} where float is a
            velocity scale factor (1.0 = unchanged, 0.5 = half, 2.0 = double).
            Applied after global velocity processing, before merging.
        articulation_map: Optional dict {channel_index: note_type}.  Applies a
            BDO note type/articulation to all melodic notes in that channel
            group after velocity processing.

    Returns:
        (bdo_data, summary) where summary is a dict with keys:
            bpm, time_sig, tracks, total_notes, track_details
        track_details is a list of dicts with: notes, pitch_min, pitch_max, duration_ms
    """
    if bpm_override is not None:
        bpm = _clamp_int(bpm_override, BDO_BPM_MIN, BDO_BPM_MAX, "bpm")
    else:
        bpm = _clamp_int(bpm, BDO_BPM_MIN, BDO_BPM_MAX, "bpm")

    # Process each channel group and merge by assigned BDO instrument
    merged = defaultdict(list)
    for ch_idx, (notes, gm_program, is_perc) in enumerate(channel_groups):
        if instrument_map is not None:
            inst = instrument_map.get(
                ch_idx,
                instrument_map.get(
                    (gm_program, is_perc),
                    gm_to_bdo_instrument(gm_program, is_perc),
                ),
            )
        else:
            inst = gm_to_bdo_instrument(gm_program, is_perc)

        if is_perc or inst == BDO_INSTRUMENTS['drum_set']:
            # Percussion and any track explicitly routed to the drum set must
            # use BDO drum pitches + type 99.  Melodic type 0 notes inside
            # instrument 0x0d are accepted by the file parser but can break
            # in-game playback.
            notes = map_drum_notes(notes)
        else:
            # Melodic: transpose and clamp to BDO range.
            if transpose:
                notes = transpose_notes(notes, transpose)
            notes = clamp_notes(notes)

        preserved_ntypes = [n.ntype for n in notes] if preserve_note_types else None
        if preserved_ntypes is not None:
            notes = [n._replace(ntype=0) for n in notes]

        if vel_range:
            if len(vel_range) != 2:
                raise ValueError("vel_range requires two values")
            notes = rescale_velocity(notes, vel_range[0], vel_range[1])
        if vel_floor:
            notes = floor_velocity(notes, vel_floor)
        if vel_step:
            notes = stepped_velocity(notes, vel_step[0], vel_step[1])
        if vel_layered:
            ch_scale = vel_scales.get(ch_idx, 1.0) if vel_scales else 1.0
            notes = layered_velocity(notes, scale=ch_scale)
        elif vel_scales and ch_idx in vel_scales:
            # Non-layered modes: apply raw scaling
            scale = vel_scales[ch_idx]
            notes = [n._replace(vel=_clamp_velocity(round(n.vel * scale)))
                     for n in notes]
        if not is_perc and articulation_map and ch_idx in articulation_map:
            ntype = _clamp_int(articulation_map[ch_idx], 0, 255, "articulation")
            notes = [n._replace(ntype=ntype) for n in notes]
        elif preserved_ntypes is not None:
            notes = [n._replace(ntype=ntype) for n, ntype in zip(notes, preserved_ntypes)]
        merged[inst].extend(notes)

    if BDO_INSTRUMENTS['drum_set'] in merged:
        merged[BDO_INSTRUMENTS['drum_set']] = normalize_drum_note_timing(
            merged[BDO_INSTRUMENTS['drum_set']]
        )

    # Enforce per-instrument note limit (BDO's in-game limit)
    notes_dropped = 0
    for inst in merged:
        if len(merged[inst]) > MAX_NOTES_PER_INSTRUMENT:
            merged[inst].sort(key=lambda n: n.start)
            dropped = len(merged[inst]) - MAX_NOTES_PER_INSTRUMENT
            merged[inst] = merged[inst][:MAX_NOTES_PER_INSTRUMENT]
            notes_dropped += dropped
            inst_name = BDO_INSTRUMENT_NAMES.get(inst, f'0x{inst:02x}')
            warnings.warn(f"{inst_name}: {dropped} notes dropped "
                          f"(10k per-instrument limit)")

    # Build instrument groups: [(inst_id, [track_note_lists]), ...]
    instrument_groups = []
    for inst, notes in merged.items():
        notes.sort(key=lambda n: n.start)
        chunks = split_notes(notes)
        instrument_groups.append((inst, chunks))

    if not instrument_groups:
        instrument_groups = [(DEFAULT_INSTRUMENT, [[]])]

    # Build summary
    track_details = []
    total_notes = 0
    total_tracks = 0
    for inst, chunks in instrument_groups:
        inst_name = BDO_INSTRUMENT_NAMES.get(inst, f'0x{inst:02x}')
        for chunk in chunks:
            total_tracks += 1
            total_notes += len(chunk)
            if chunk:
                track_details.append({
                    'notes': len(chunk),
                    'pitch_min': min(n.pitch for n in chunk),
                    'pitch_max': max(n.pitch for n in chunk),
                    'duration_ms': max(n.start + n.dur for n in chunk),
                    'instrument': inst_name,
                })
            else:
                track_details.append({'notes': 0, 'pitch_min': 0, 'pitch_max': 0,
                                      'duration_ms': 0, 'instrument': inst_name})
        total_tracks += 1  # empty trailing track per group

    summary = {
        'bpm': bpm,
        'time_sig': time_sig_num,
        'tracks': total_tracks,
        'total_notes': total_notes,
        'instruments': len(instrument_groups),
        'track_details': track_details,
        'notes_dropped': notes_dropped,
    }

    track_settings = make_track_settings(reverb, delay, chorus)
    plaintext = build_bdo_binary(bpm, time_sig_num, instrument_groups, char_name,
                                 owner_id=owner_id, track_settings=track_settings)
    return encrypt_bdo(plaintext), summary


def midi_to_bdo(midi_path, bpm_override=None, char_name='MIDI', vel_range=None,
                vel_floor=None, vel_step=None, vel_layered=False, transpose=0,
                apply_sustain=True, flatten_tempo=False, owner_id=0,
                instrument_map=None, reverb=0, delay=0, chorus=None,
                vel_scales=None, articulation_map=None):
    """Convert a MIDI file to BDO format."""
    bpm, time_sig_num, channel_groups, _tempo_changes = parse_midi(
        midi_path, apply_sustain=apply_sustain, flatten_tempo=flatten_tempo)
    return channel_groups_to_bdo(
        bpm,
        time_sig_num,
        channel_groups,
        bpm_override=bpm_override,
        char_name=char_name,
        vel_range=vel_range,
        vel_floor=vel_floor,
        vel_step=vel_step,
        vel_layered=vel_layered,
        transpose=transpose,
        owner_id=owner_id,
        instrument_map=instrument_map,
        reverb=reverb,
        delay=delay,
        chorus=chorus,
        vel_scales=vel_scales,
        articulation_map=articulation_map,
    )


def main():
    parser = argparse.ArgumentParser(
        description='Convert MIDI files to BDO music composer format')
    parser.add_argument('input', help='Input MIDI file')
    parser.add_argument('output', nargs='?',
                        help='Output filename (no extension, default: input basename)')
    parser.add_argument('--bpm', type=int, help='Override BPM from MIDI')
    parser.add_argument('--name', default='MIDI',
                        help='Character name to embed (default: MIDI)')
    parser.add_argument('--outdir', default=None,
                        help='Output directory (default: ./converted/)')
    parser.add_argument('--vel', nargs=2, type=int, metavar=('MIN', 'MAX'),
                        help='Rescale velocities to MIN-MAX range (e.g. --vel 80 127)')
    parser.add_argument('--transpose', type=int, default=0,
                        help='Transpose by N semitones (e.g. -12 = down one octave)')
    parser.add_argument('--vel-floor', type=int, metavar='N',
                        help='Proportionally scale velocities so quietest becomes N')
    parser.add_argument('--vel-step', nargs=2, type=int, metavar=('BASE', 'STEP'),
                        help='Stepped velocity: BASE for quietest, +STEP per level, max 127')
    parser.add_argument('--vel-layered', action='store_true',
                        help='Map velocities to BDO layered velocity levels')
    parser.add_argument('--no-sustain', action='store_true',
                        help='Ignore sustain pedal (use raw note durations)')
    parser.add_argument('--flatten-tempo', action='store_true',
                        help='Set BPM to 200 (BDO max) for multi-tempo MIDIs — minimizes grid quantization')
    parser.add_argument('--owner-file', metavar='BDO_FILE',
                        help='Extract owner ID from an existing BDO file (needed to edit in-game)')
    parser.add_argument('--reverb', type=int, default=0, metavar='N',
                        help='Reverb level 0-127')
    parser.add_argument('--delay', type=int, default=0, metavar='N',
                        help='Delay level 0-127')
    parser.add_argument('--chorus', nargs=3, type=int, metavar=('FB', 'DEPTH', 'FREQ'),
                        help='Chorus: feedback, LFO depth, LFO frequency (each 0-127)')

    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"Error: {args.input} not found", file=sys.stderr)
        sys.exit(1)

    # Determine output path
    if args.output:
        out_name = args.output
    else:
        out_name = os.path.splitext(os.path.basename(args.input))[0]

    out_dir = args.outdir or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'converted')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, out_name)

    owner_id = 0
    if args.owner_file:
        owner_id, owner_name = extract_owner_id(args.owner_file)
        print(f"Owner ID: 0x{owner_id:08x} (from \"{owner_name}\")")

    print(f"Converting: {args.input}")
    bdo_data, summary = midi_to_bdo(args.input, bpm_override=args.bpm, char_name=args.name,
                                     vel_range=args.vel, vel_floor=args.vel_floor,
                                     vel_step=args.vel_step, vel_layered=args.vel_layered,
                                     transpose=args.transpose,
                                     apply_sustain=not args.no_sustain,
                                     flatten_tempo=args.flatten_tempo,
                                     owner_id=owner_id,
                                     reverb=args.reverb, delay=args.delay,
                                     chorus=tuple(args.chorus) if args.chorus else None)

    print(f"BPM: {summary['bpm']}, Time sig: {summary['time_sig']}/4")
    print(f"Tracks: {summary['tracks']}, Total notes: {summary['total_notes']}")
    if summary.get('notes_dropped', 0):
        print(f"  WARNING: {summary['notes_dropped']} notes dropped (10k per-instrument limit)")
    for i, td in enumerate(summary['track_details']):
        if td['notes']:
            print(f"  Track {i}: {td['notes']} notes, "
                  f"range: {td['pitch_min']}-{td['pitch_max']}, "
                  f"duration: {td['duration_ms']:.0f}ms, "
                  f"instrument: {td['instrument']}")
        else:
            print(f"  Track {i}: empty ({td['instrument']})")

    with open(out_path, 'wb') as f:
        f.write(bdo_data)
    print(f"Saved: {out_path} ({len(bdo_data)} bytes)")


if __name__ == '__main__':
    main()
