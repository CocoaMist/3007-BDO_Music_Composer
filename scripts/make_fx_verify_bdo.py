#!/usr/bin/env python3
"""Generate a BDO score that exercises known instrument FX/note types."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL_DIR = ROOT / "tools" / "midi-to-bdo"
sys.path.insert(0, str(TOOL_DIR))

from midi2bdo import BDO_INSTRUMENT_NAMES, Note, build_bdo_binary, encrypt_bdo, extract_owner_id  # noqa: E402


BPM = 120
NOTE_MS = 500.0
GAP_MS = 40.0
GROUP_GAP_MS = 1000.0

ARTICULATIONS: dict[int, list[tuple[int, str]]] = {
    0x0A: [(0, "延音"), (3, "向上滑动"), (12, "滑弦下降"), (13, "弱音"), (14, "泛音"), (15, "三连音")],
    0x0B: [(0, "延音"), (1, "标签"), (2, "剪切"), (3, "向上滑动"), (4, "颤音小调"), (15, "三连音")],
    0x0E: [(0, "延音"), (3, "向上滑动"), (12, "滑弦下降"), (13, "弱音"), (14, "泛音"), (16, "滑音"), (22, "拍弦"), (23, "滑音上升"), (24, "X-音符")],
    0x0F: [(0, "延音"), (3, "向上滑动"), (12, "滑弦下降"), (13, "弱音"), (14, "泛音"), (23, "滑音上升")],
    0x10: [(0, "延音"), (9, "大调和弦"), (10, "和弦小调"), (16, "滑音")],
    0x11: [(0, "延音"), (11, "延音踏板")],
    0x12: [(0, "延音"), (1, "标签"), (2, "剪切"), (3, "向上滑动"), (4, "颤音小调"), (5, "颤音大调"), (6, "颤音"), (7, "颤音 2"), (8, "大调颤音")],
    0x14: [(0, "延音"), (1, "标签"), (2, "剪切"), (3, "向上滑动"), (4, "颤音小调"), (5, "颤音大调"), (6, "颤音"), (7, "颤音 2"), (8, "颤音小调 2"), (17, "颤音 3"), (18, "大调颤音"), (19, "颤音 4"), (20, "维持滤波器"), (21, "滤波铜管")],
    0x18: [(0, "延音"), (1, "标签"), (2, "剪切"), (3, "向上滑动"), (4, "颤音小调"), (5, "颤音大调"), (6, "颤音"), (7, "颤音 2"), (8, "颤音小调 2"), (17, "颤音 3"), (18, "大调颤音"), (19, "颤音 4")],
    0x1C: [(0, "延音"), (1, "基本")],
    0x20: [(0, "延音"), (1, "基本")],
    0x24: [(0, "延音"), (6, "颤音"), (13, "弱音"), (14, "泛音"), (25, "FX(C2-G2)")],
    0x25: [(0, "延音"), (6, "颤音"), (13, "弱音"), (14, "泛音"), (25, "FX(C2-G2)")],
    0x26: [(0, "延音"), (6, "颤音"), (13, "弱音"), (14, "泛音"), (25, "FX(C2-G2)")],
    0x27: [(0, "延音"), (4, "颤音小调"), (7, "颤音小调 2"), (8, "大调颤音"), (15, "三连音"), (26, "SusPiano"), (27, "SusMezzoForte"), (28, "SusForte")],
    0x28: [(0, "延音"), (3, "向上滑动"), (4, "颤音小调"), (12, "滑弦下降"), (26, "SusPiano"), (27, "SusMezzoForte"), (28, "SusForte")],
}

PITCHES = {
    0x0A: 79,
    0x0B: 79,
    0x0E: 47,
    0x0F: 62,
    0x10: 60,
    0x11: 81,
    0x12: 59,
    0x14: 78,
    0x18: 74,
    0x1C: 71,
    0x20: 70,
    0x24: 45,
    0x25: 43,
    0x26: 33,
    0x27: 77,
    0x28: 76,
}

PERCUSSION_NOTES = {
    0x04: (77, "新手手鼓"),
    0x05: (71, "新手钹"),
    0x0D: (58, "架子鼓套装"),
    0x13: (75, "手碟"),
}


def default_game_music_dir() -> Path:
    return Path.home() / "Documents" / "Black Desert" / "Music"


def find_owner_file(game_dir: Path) -> Path | None:
    candidates = [p for p in game_dir.iterdir() if p.is_file() and p.stat().st_size <= 600]
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            owner_id, _name = extract_owner_id(path)
            if owner_id:
                return path
        except Exception:
            continue
    return None


def build_groups(include_percussion: bool) -> tuple[list[tuple[int, list[list[Note]]]], list[str]]:
    groups: list[tuple[int, list[list[Note]]]] = []
    manifest: list[str] = []
    start = 0.0

    for inst_id, items in ARTICULATIONS.items():
        pitch = PITCHES[inst_id]
        notes: list[Note] = []
        manifest.append(f"0x{inst_id:02x} {BDO_INSTRUMENT_NAMES[inst_id]}")
        for index, (ntype, label) in enumerate(items):
            note_start = start + index * (NOTE_MS + GAP_MS)
            notes.append(Note(pitch, 100, note_start, NOTE_MS, ntype))
            manifest.append(f"  {index:02d}: pitch={pitch} type={ntype} {label}")
        groups.append((inst_id, [notes]))
        start += max(1, len(items)) * (NOTE_MS + GAP_MS) + GROUP_GAP_MS

    if include_percussion:
        for inst_id, (pitch, label) in PERCUSSION_NOTES.items():
            groups.append((inst_id, [[Note(pitch, 100, start, NOTE_MS, 99)]]))
            manifest.append(f"0x{inst_id:02x} {BDO_INSTRUMENT_NAMES[inst_id]}")
            manifest.append(f"  00: pitch={pitch} type=99 {label}")
            start += NOTE_MS + GROUP_GAP_MS

    return groups, manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="BDO_FX_Verify", help="output BDO score name")
    parser.add_argument("--outdir", default=str(ROOT / "out" / "bdo"), help="output directory")
    parser.add_argument("--install", action="store_true", help="copy to the Black Desert Music directory")
    parser.add_argument("--game-dir", default=str(default_game_music_dir()), help="Black Desert Music directory")
    parser.add_argument("--owner-file", help="existing BDO file used to copy Owner ID and character name")
    parser.add_argument("--name", default="FXVerify", help="character name if no owner file is used")
    parser.add_argument("--no-percussion", action="store_true", help="skip percussion sample groups")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    out_dir = Path(args.outdir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / args.output

    owner_id = 0
    char_name = args.name
    owner_file = Path(args.owner_file) if args.owner_file else None
    if owner_file is None and args.install:
        owner_file = find_owner_file(Path(args.game_dir))
    if owner_file:
        owner_id, owner_name = extract_owner_id(owner_file)
        char_name = owner_name or char_name

    groups, manifest = build_groups(include_percussion=not args.no_percussion)
    bdo_data = encrypt_bdo(build_bdo_binary(BPM, 4, groups, char_name=char_name, owner_id=owner_id))
    out_path.write_bytes(bdo_data)
    manifest_path = out_path.with_suffix(".txt")
    manifest_path.write_text("\n".join(manifest) + "\n", encoding="utf-8")

    print(f"saved={out_path}")
    print(f"manifest={manifest_path}")
    print(f"bytes={len(bdo_data)} instruments={len(groups)} owner=0x{owner_id:08x} name={char_name}")

    if args.install:
        game_dir = Path(args.game_dir)
        game_dir.mkdir(parents=True, exist_ok=True)
        installed = game_dir / out_path.name
        shutil.copy2(out_path, installed)
        print(f"installed={installed}")


if __name__ == "__main__":
    main()
