#!/usr/bin/env python3
"""Audit Python real-time sample selection against actual Black Desert saves.

This is a resource/serialization compatibility check, not a claim of acoustic
identity.  A cell becomes acoustically verified only after a game-capture A/B
comparison is recorded in the validation matrix.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "tools" / "midi-to-bdo")]

from bdo_realtime_audio import (  # noqa: E402
    BANK_BY_ID,
    MARNIAN_SYNTH_WAVEFORM_BY_ID,
    resolve_bdo_pitch,
    select_wwise_zone,
)
from inspect_bdo import parse_bdo  # noqa: E402
from midi2bdo import BDO_INSTRUMENT_NAMES  # noqa: E402
from pyside_bdo_gui import BDO_ARTICULATIONS, BDO_EDITOR_PITCH_RANGES  # noqa: E402
from project_paths import WWISE_MIDI_MAP_PATH  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--music-dir", type=Path, default=Path.home() / "Documents" / "Black Desert" / "Music")
    parser.add_argument(
        "--pattern", default="list*",
        help="Only audit trusted hand-authored baseline files (default: list*)",
    )
    parser.add_argument("--map", type=Path, default=WWISE_MIDI_MAP_PATH)
    parser.add_argument("--output", type=Path, default=ROOT / "out" / "bdo" / "python_realtime_game_match.md")
    parser.add_argument("--details", type=Path, default=ROOT / "out" / "bdo" / "game_wwise_coverage.json")
    args = parser.parse_args()
    mapping = json.loads(args.map.read_text(encoding="utf-8"))
    banks = mapping.get("banks", {})
    stats: dict[int, Counter] = defaultdict(Counter)
    ntypes: dict[int, set[int]] = defaultdict(set)
    missing_zones: Counter[tuple[int, int, int, int]] = Counter()
    unknown_instrument_ids: Counter[int] = Counter()
    unknown_ntypes: Counter[tuple[int, int]] = Counter()
    baseline_pitches: dict[int, list[int]] = defaultdict(list)
    failures: list[str] = []
    files = sorted(path for path in args.music_dir.glob(args.pattern) if path.is_file())
    for path in files:
        try:
            report = parse_bdo(path, sample_notes=1_000_000)
        except Exception as exc:
            failures.append(f"{path.name}: {exc}")
            continue
        for group in report["groups"]:
            for track in group["tracks"]:
                instrument_id = int(track["instrument_id"])
                if instrument_id not in BDO_INSTRUMENT_NAMES:
                    unknown_instrument_ids[instrument_id] += int(track["note_count"])
                for note in track["sample_notes"]:
                    pitch = int(note["pitch"])
                    velocity = int(note["velocity_a"])
                    ntype = int(note["ntype"])
                    if float(note["start_ms"]) == 0.0 and ntype in (0, 99):
                        baseline_pitches[instrument_id].append(pitch)
                    stats[instrument_id]["notes"] += 1
                    ntypes[instrument_id].add(ntype)
                    selected = select_wwise_zone(banks, instrument_id, pitch, velocity, ntype)
                    if selected:
                        stats[instrument_id]["zone_match"] += 1
                    else:
                        stats[instrument_id]["zone_miss"] += 1
                        missing_zones[(instrument_id, pitch, velocity, ntype)] += 1
                    supported_ntypes = {0, 99} | {value for value, _label in BDO_ARTICULATIONS.get(instrument_id, [])}
                    if ntype not in supported_ntypes:
                        unknown_ntypes[(instrument_id, ntype)] += 1
                    if ntype in (0, 99):
                        stats[instrument_id]["base_type"] += 1
                    else:
                        stats[instrument_id]["dsp_pending"] += 1
                    if instrument_id == 0x0D:
                        resolved = resolve_bdo_pitch(instrument_id, pitch, ntype)
                        if ntype == 99 and 48 <= pitch <= 64:
                            stats[instrument_id]["canonical_drum"] += 1
                        elif ntype != 99:
                            stats[instrument_id]["drum_marker_risk"] += 1
                        if not 48 <= resolved <= 64:
                            stats[instrument_id]["drum_key_risk"] += 1
    expected_ids = set(BDO_INSTRUMENT_NAMES)
    missing_instrument_ids = sorted(expected_ids - set(stats))
    missing_expected_ntypes = [
        {
            "instrument_id": f"0x{instrument_id:02x}",
            "ntypes": sorted({value for value, _label in definitions} - ntypes.get(instrument_id, set())),
        }
        for instrument_id, definitions in sorted(BDO_ARTICULATIONS.items())
        if {value for value, _label in definitions} - ntypes.get(instrument_id, set())
    ]
    range_mismatches = []
    for instrument_id, expected_range in sorted(BDO_EDITOR_PITCH_RANGES.items()):
        pitches = baseline_pitches.get(instrument_id, [])
        if not pitches:
            range_mismatches.append({
                "instrument_id": f"0x{instrument_id:02x}", "reason": "no baseline min/max notes",
            })
            continue
        observed = (min(pitches), max(pitches))
        expected = (min(expected_range), max(expected_range))
        if observed != expected:
            range_mismatches.append({
                "instrument_id": f"0x{instrument_id:02x}",
                "observed": list(observed), "expected": list(expected),
            })

    lines = [
        "# Python 实时引擎与游戏存档匹配检查",
        "",
        "此检查验证当前 Python 模块对游戏存档的乐器、键位、力度区和 ntype 序列化选择是否有对应采样。它不验证 Wwise DSP/环境效果的听感；后者仍须游戏内录音 A/B。",
        "",
        "| ID | 乐器 | 存档音符 | Wwise zone 匹配 | zone 缺失 | 基础 ntype | DSP 待验证 | 结论 |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for instrument_id in sorted(BDO_INSTRUMENT_NAMES):
        row = stats[instrument_id]
        if instrument_id in MARNIAN_SYNTH_WAVEFORM_BY_ID:
            verdict = "暂定 synth/basic 路由；待游戏 A/B 验证"
        elif instrument_id not in BANK_BY_ID:
            verdict = "未绑定命名 BNK"
        elif row["zone_miss"]:
            verdict = "存在无对应键位/力度"
        elif row["dsp_pending"]:
            verdict = "基础采样匹配；DSP 待验证"
        else:
            verdict = "基础样本与序列化匹配"
        lines.append(
            f"| 0x{instrument_id:02x} | {BDO_INSTRUMENT_NAMES[instrument_id]} | {row['notes']} | "
            f"{row['zone_match']} | {row['zone_miss']} | {row['base_type']} | {row['dsp_pending']} | {verdict} |"
        )
    drum = stats[0x0D]
    lines.extend([
        "",
        "## 架子鼓",
        "",
        f"- canonical 48–64 / ntype 99：{drum['canonical_drum']} 个存档音符。",
        f"- ntype 非 99 的架子鼓存档音符：{drum['drum_marker_risk']}；这些可能是游戏内无声或非标准数据。",
        f"- 解析后仍不在 48–64 的键：{drum['drum_key_risk']}。",
        "",
        "## 解析状态",
        "",
        f"- 游戏存档文件：{len(files)}；解析失败：{len(failures)}。",
        *[f"- {failure}" for failure in failures],
    ])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    detail_payload = {
        "format": 1,
        "music_files": len(files),
        "file_pattern": args.pattern,
        "parse_failures": failures,
        "marnian_mode_checked": "basic",
        "marnian_routing": {
            f"0x{key:02x}": {
                "waveform": value,
                "modes": {
                    mode: {
                        "bank": f"midi_instrument_synth_{value}_{mode}",
                        "wav_present": any(
                            row.get("wav_exists")
                            for row in banks.get(f"midi_instrument_synth_{value}_{mode}", [])
                        ),
                    }
                    for mode in ("basic", "stereo", "super", "superoct")
                },
            }
            for key, value in MARNIAN_SYNTH_WAVEFORM_BY_ID.items()
        },
        "unknown_instrument_ids": {f"0x{key:02x}": value for key, value in sorted(unknown_instrument_ids.items())},
        "unknown_ntypes": [
            {"instrument_id": f"0x{instrument_id:02x}", "ntype": ntype, "notes": count}
            for (instrument_id, ntype), count in sorted(unknown_ntypes.items())
        ],
        "missing_instrument_ids": [f"0x{value:02x}" for value in missing_instrument_ids],
        "missing_expected_ntypes": missing_expected_ntypes,
        "range_mismatches": range_mismatches,
        "missing_zone_combinations": [
            {"instrument_id": f"0x{instrument_id:02x}", "pitch": pitch, "velocity": velocity, "ntype": ntype, "notes": count}
            for (instrument_id, pitch, velocity, ntype), count in sorted(missing_zones.items())
        ],
    }
    args.details.parent.mkdir(parents=True, exist_ok=True)
    args.details.write_text(json.dumps(detail_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"saved={args.output} details={args.details} instruments={len(stats)} "
        f"failures={len(failures)} missing_zones={sum(missing_zones.values())} "
        f"unknown_ids={len(unknown_instrument_ids)} unknown_ntypes={len(unknown_ntypes)} "
        f"missing_ids={len(missing_instrument_ids)} missing_ntypes={len(missing_expected_ntypes)} "
        f"range_mismatches={len(range_mismatches)}"
    )
    problems = (
        failures or missing_zones or unknown_instrument_ids or unknown_ntypes
        or missing_instrument_ids or missing_expected_ntypes or range_mismatches
    )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
