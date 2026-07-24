#!/usr/bin/env python3
"""Build a strict BDO game-playback coverage matrix from saves and Wwise data."""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from bdo_sample_renderer import BDO_BANK_BY_ID, sample_map_supported_pitches, sample_map_supports_note  # noqa: E402
from inspect_bdo import parse_bdo  # noqa: E402
from bdo_midi import BDO_INSTRUMENT_NAMES  # noqa: E402
from pyside_bdo_gui import BDO_ARTICULATIONS, BDO_SAMPLE_MAP_PATH, game_pitch_range_label, game_supported_pitches  # noqa: E402


def note_name(pitch: int) -> str:
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    return f"{names[pitch % 12]}{pitch // 12 - 1}"


def compress_pitches(pitches: set[int]) -> str:
    if not pitches:
        return "-"
    ordered = sorted(pitches)
    ranges: list[tuple[int, int]] = []
    start = previous = ordered[0]
    for pitch in ordered[1:]:
        if pitch == previous + 1:
            previous = pitch
            continue
        ranges.append((start, previous))
        start = previous = pitch
    ranges.append((start, previous))
    return ", ".join(note_name(a) if a == b else f"{note_name(a)}-{note_name(b)}" for a, b in ranges)


def parse_scores(music_dir: Path) -> tuple[dict[int, list[dict]], list[str]]:
    notes: dict[int, list[dict]] = defaultdict(list)
    failures = []
    for path in sorted(music_dir.iterdir()):
        if not path.is_file():
            continue
        try:
            report = parse_bdo(path, sample_notes=1_000_000)
        except Exception as exc:
            failures.append(f"{path.name}: {exc}")
            continue
        for group in report["groups"]:
            for track in group["tracks"]:
                for note in track["sample_notes"]:
                    notes[track["instrument_id"]].append({**note, "file": path.name})
    return notes, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--music-dir",
        type=Path,
        default=Path.home() / "Documents" / "Black Desert" / "Music",
    )
    parser.add_argument("--map", type=Path, default=BDO_SAMPLE_MAP_PATH)
    parser.add_argument("--output", type=Path, default=ROOT / "out" / "bdo" / "game_playback_coverage.md")
    args = parser.parse_args()

    saved_notes, failures = parse_scores(args.music_dir)
    lines = [
        "# BDO 游戏播放覆盖矩阵",
        "",
        "标准：`可 1:1 离线播放` 必须同时具备已命名的游戏 BNK、精确键位/力度 zone、"
        "基础音符类型或已实现的奏法 DSP、以及已实现的轨道效果。",
        "",
        "| ID | 乐器 | 游戏有效音域 | Wwise 键位 | 存档音符 | ntype | 离线 1:1 |",
        "|---|---|---|---|---:|---|---|",
    ]
    blockers: list[str] = []

    for instrument_id, name in sorted(BDO_INSTRUMENT_NAMES.items()):
        game_keys = game_supported_pitches(instrument_id)
        source_keys = (
            sample_map_supported_pitches(args.map, instrument_id)
            if args.map.is_file() and instrument_id in BDO_BANK_BY_ID
            else frozenset()
        )
        notes = saved_notes.get(instrument_id, [])
        ntypes = sorted({int(note["ntype"]) for note in notes})
        unsupported = []
        for note in notes:
            pitch = int(note["pitch"])
            velocity = int(note["velocity_a"])
            if instrument_id == 0x0D:
                if pitch not in source_keys:
                    unsupported.append(note)
            elif instrument_id in BDO_BANK_BY_ID and not sample_map_supports_note(
                args.map, instrument_id, pitch, velocity
            ):
                unsupported.append(note)

        expected_fx = {ntype for ntype, _label in BDO_ARTICULATIONS.get(instrument_id, [])}
        unknown_fx = set(ntypes) - expected_fx if expected_fx else set()
        # ntype=0 is a basic melodic note and 99 is the game's percussion marker.
        unknown_fx -= {0, 99}
        unsupported_ntypes = {ntype for ntype in ntypes if ntype not in {0, 99}}

        status = "否"
        reasons = []
        if instrument_id not in BDO_BANK_BY_ID:
            reasons.append("未绑定已命名游戏 BNK")
        if unsupported:
            reasons.append(f"{len(unsupported)} 个存档音符没有对应 Wwise key/velocity")
        if unsupported_ntypes:
            reasons.append("奏法 DSP 未由离线渲染器实现")
        if unknown_fx:
            reasons.append(f"未知 ntype {sorted(unknown_fx)}")
        if not reasons and source_keys:
            status = "基础音符可"
        else:
            blockers.append(f"0x{instrument_id:02x} {name}: " + "；".join(reasons or ["缺少采样键位"]))

        source_label = compress_pitches(set(source_keys)) if source_keys else "未绑定"
        lines.append(
            f"| 0x{instrument_id:02x} | {name} | {game_pitch_range_label(instrument_id)} | "
            f"{source_label} | {len(notes)} | {ntypes or '-'} | {status} |"
        )

    lines.extend(["", "## 阻断项", ""])
    lines.extend(f"- {item}" for item in blockers)
    if not blockers:
        lines.append("- 无")
    lines.extend(["", "## 解析状态", ""])
    lines.append(f"- 已解析游戏曲谱：{args.music_dir}")
    lines.append(f"- 解析失败：{len(failures)}")
    lines.extend(f"- {failure}" for failure in failures)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"saved={args.output}")
    print(f"instruments={len(BDO_INSTRUMENT_NAMES)} blockers={len(blockers)} parse_failures={len(failures)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
