#!/usr/bin/env python3
"""Build a path-free BDO preview-route coverage matrix from local evidence."""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from bdo_music_composer.audio.bdo_instrument_samples import (  # noqa: E402
    bank_for_instrument,
    preview_has_native_articulation,
    preview_route_ntype,
    row_routes_ntype,
)
from bdo_music_composer.audio.bdo_sample_renderer import (  # noqa: E402
    BdoSampleMap,
    sample_map_supported_pitches,
    sample_map_supports_note,
)
from inspect_bdo import parse_bdo  # noqa: E402
from bdo_midi import BDO_INSTRUMENT_NAMES  # noqa: E402
from bdo_music_composer.ui.main_window import (  # noqa: E402
    BDO_ARTICULATIONS,
    BDO_SAMPLE_MAP_PATH,
    decode_marnian_instrument,
    game_pitch_range_label,
)


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


def parse_scores(
    music_dir: Path,
) -> tuple[dict[int, list[dict]], int, Counter[str]]:
    """Read scores into numeric aggregates without retaining private identity."""

    notes: dict[int, list[dict]] = defaultdict(list)
    failure_types: Counter[str] = Counter()
    parsed_count = 0
    for path in sorted(music_dir.iterdir()):
        if not path.is_file():
            continue
        try:
            report = parse_bdo(path, sample_notes=1_000_000)
        except Exception as exc:  # One private/corrupt score must not hide others.
            failure_types[type(exc).__name__] += 1
            continue
        parsed_count += 1
        for group in report["groups"]:
            for track in group["tracks"]:
                instrument_id, synth_mode = decode_marnian_instrument(
                    int(track["instrument_id"])
                )
                for note in track["sample_notes"]:
                    notes[instrument_id].append({
                        "pitch": int(note["pitch"]),
                        "ntype": int(note["ntype"]),
                        "velocity_a": int(note["velocity_a"]),
                        "synth_mode": synth_mode,
                    })
    return notes, parsed_count, failure_types


def _route_coverage(
    sample_map: BdoSampleMap,
    map_path: Path,
    instrument_id: int,
    note: dict,
) -> tuple[str, int]:
    """Return preview coverage using the production Event/zone selector."""

    pitch = int(note["pitch"])
    velocity = int(note["velocity_a"])
    ntype = int(note["ntype"])
    synth_mode = str(note.get("synth_mode", "basic"))
    if not sample_map_supports_note(
        map_path,
        instrument_id,
        pitch,
        velocity,
        ntype,
        synth_mode,
    ):
        return "missing", preview_route_ntype(instrument_id, ntype)

    row = sample_map.choose(
        instrument_id,
        pitch,
        velocity,
        ntype,
        synth_mode,
    )
    route_ntype = preview_route_ntype(instrument_id, ntype)
    if row is None:
        return "missing", route_ntype
    if preview_has_native_articulation(instrument_id, row, route_ntype):
        return "native", route_ntype
    # This includes a shared approximate articulation fallback and Marnian's
    # native sample layer whose unrecovered modulators remain approximate.
    if row_routes_ntype(row, route_ntype):
        return "native_layer_approximate", route_ntype
    return "approximate", route_ntype


def _format_failure_types(failure_types: Counter[str]) -> str:
    if not failure_types:
        return "- 无"
    return "\n".join(
        f"- {name}: {count}"
        for name, count in sorted(failure_types.items())
    )


def build_report(
    *,
    map_path: Path,
    saved_notes: dict[int, list[dict]],
    parsed_count: int,
    failure_types: Counter[str],
) -> tuple[str, int]:
    """Return the anonymous Markdown report and number of hard mismatches."""

    sample_map = BdoSampleMap(map_path)
    lines = [
        "# BDO 游戏试听路由覆盖矩阵",
        "",
        "本报告只区分本地预览所用的原生 Event 路由、共享近似处理与缺少路由；"
        "它不代表游戏内 A/B 验证，也不声称复现全部 Wwise DSP。",
        "",
        "| ID | 乐器 | 游戏有效音域 | Wwise 键位 | 存档音符 | ntype | 试听路由 |",
        "|---|---|---|---|---:|---|---|",
    ]
    blockers: list[str] = []
    approximations: list[str] = []
    route_cache: dict[tuple[int, int, int, int, str], tuple[str, int]] = {}

    for instrument_id, name in sorted(BDO_INSTRUMENT_NAMES.items()):
        notes = saved_notes.get(instrument_id, [])
        modes = sorted({str(note.get("synth_mode", "basic")) for note in notes}) or ["basic"]
        source_keys: set[int] = set()
        if bank_for_instrument(instrument_id) is not None:
            for synth_mode in modes:
                source_keys.update(
                    sample_map_supported_pitches(
                        map_path,
                        instrument_id,
                        synth_mode,
                    )
                )

        ntypes = sorted({int(note["ntype"]) for note in notes})
        route_counts: Counter[str] = Counter()
        missing_route_types: Counter[int] = Counter()
        for note in notes:
            cache_key = (
                instrument_id,
                int(note["pitch"]),
                int(note["velocity_a"]),
                int(note["ntype"]),
                str(note.get("synth_mode", "basic")),
            )
            coverage = route_cache.get(cache_key)
            if coverage is None:
                coverage = _route_coverage(
                    sample_map,
                    map_path,
                    instrument_id,
                    note,
                )
                route_cache[cache_key] = coverage
            route_kind, route_ntype = coverage
            route_counts[route_kind] += 1
            if route_kind == "missing":
                missing_route_types[route_ntype] += 1

        declared_ntypes = {
            int(ntype)
            for ntype, _label in BDO_ARTICULATIONS.get(instrument_id, [])
        }
        unknown_ntypes = set(ntypes) - declared_ntypes - {0, 99}

        reasons: list[str] = []
        if bank_for_instrument(instrument_id) is None:
            reasons.append("未绑定试听 BNK")
        elif not source_keys:
            reasons.append("映射没有可用 Wwise zone")
        if route_counts["missing"]:
            reasons.append(
                f"缺少 {route_counts['missing']} 个 Event/key/velocity 路由"
                f"（type {sorted(missing_route_types)}）"
            )
        if unknown_ntypes:
            reasons.append(f"编辑器未声明 ntype {sorted(unknown_ntypes)}")
        if reasons:
            blockers.append(f"0x{instrument_id:02x} {name}: " + "；".join(reasons))

        approximate_count = (
            route_counts["approximate"]
            + route_counts["native_layer_approximate"]
        )
        if approximate_count:
            approximations.append(
                f"0x{instrument_id:02x} {name}: {approximate_count} 个音符使用共享近似处理"
            )

        if route_counts["missing"]:
            status = f"缺少 {route_counts['missing']}"
        elif approximate_count:
            status = f"原生 {route_counts['native']} / 近似 {approximate_count}"
        elif notes:
            status = f"原生 Event {route_counts['native']}"
        elif source_keys:
            status = "已映射（无存档样本）"
        else:
            status = "无可用 zone"

        source_label = compress_pitches(source_keys) if source_keys else "未绑定"
        lines.append(
            f"| 0x{instrument_id:02x} | {name} | {game_pitch_range_label(instrument_id)} | "
            f"{source_label} | {len(notes)} | {ntypes or '-'} | {status} |"
        )

    unknown_instruments = sorted(set(saved_notes) - set(BDO_INSTRUMENT_NAMES))
    for instrument_id in unknown_instruments:
        blockers.append(
            f"0x{instrument_id:02x}: {len(saved_notes[instrument_id])} 个音符使用未知乐器 ID"
        )

    lines.extend(["", "## 缺失或不一致", ""])
    lines.extend(f"- {item}" for item in blockers)
    if not blockers:
        lines.append("- 无")
    lines.extend(["", "## 近似试听（需游戏内 A/B）", ""])
    lines.extend(f"- {item}" for item in approximations)
    if not approximations:
        lines.append("- 无")
    lines.extend([
        "",
        "## 匿名解析状态",
        "",
        f"- 成功解析：{parsed_count}",
        f"- 解析失败：{sum(failure_types.values())}",
        _format_failure_types(failure_types),
    ])
    return "\n".join(lines) + "\n", len(blockers)


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

    if not args.music_dir.is_dir():
        print("error: music input directory is unavailable", file=sys.stderr)
        return 2
    if not args.map.is_file():
        print("error: sample map is unavailable", file=sys.stderr)
        return 2

    try:
        saved_notes, parsed_count, failure_types = parse_scores(args.music_dir)
        report, blocker_count = build_report(
            map_path=args.map,
            saved_notes=saved_notes,
            parsed_count=parsed_count,
            failure_types=failure_types,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    except (OSError, ValueError, TypeError, KeyError):
        # Inputs may contain private paths and score metadata. Keep CLI failures
        # actionable without echoing exception text or a traceback.
        print("error: playback coverage input could not be parsed", file=sys.stderr)
        return 2

    failure_count = sum(failure_types.values())
    print("saved_report=yes")
    print(
        f"instruments={len(BDO_INSTRUMENT_NAMES)} "
        f"blockers={blocker_count} parse_failures={failure_count}"
    )
    return 1 if failure_count or blocker_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
