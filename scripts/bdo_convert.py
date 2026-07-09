import argparse
import os
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL_DIR = ROOT / "tools" / "midi-to-bdo"
sys.path.insert(0, str(TOOL_DIR))

from midi2bdo import extract_owner_id, midi_to_bdo  # noqa: E402


def default_game_music_dir() -> Path:
    documents = Path.home() / "Documents"
    return documents / "Black Desert" / "music"


def convert(args: argparse.Namespace) -> Path:
    midi_path = Path(args.input).resolve()
    out_dir = Path(args.outdir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    out_name = args.output or midi_path.stem
    out_path = out_dir / out_name

    owner_id = 0
    char_name = args.name
    if args.owner_file:
        owner_id, owner_name = extract_owner_id(args.owner_file)
        if args.use_owner_name:
            char_name = owner_name
        print(f"Owner ID=0x{owner_id:08x} 角色名={owner_name}")

    bdo_data, summary = midi_to_bdo(
        str(midi_path),
        bpm_override=args.bpm,
        char_name=char_name,
        vel_range=args.vel,
        vel_floor=args.vel_floor,
        vel_step=args.vel_step,
        vel_layered=args.vel_layered,
        transpose=args.transpose,
        apply_sustain=not args.no_sustain,
        flatten_tempo=args.flatten_tempo,
        owner_id=owner_id,
        reverb=args.reverb,
        delay=args.delay,
        chorus=tuple(args.chorus) if args.chorus else None,
    )

    out_path.write_bytes(bdo_data)
    print_summary(out_path, bdo_data, summary)

    if args.install:
        game_dir = Path(args.game_dir).resolve() if args.game_dir else default_game_music_dir()
        game_dir.mkdir(parents=True, exist_ok=True)
        installed_path = game_dir / out_path.name
        shutil.copy2(out_path, installed_path)
        print(f"已安装到游戏曲谱目录={installed_path}")

    return out_path


def print_summary(out_path: Path, bdo_data: bytes, summary: dict) -> None:
    print(f"已保存={out_path}")
    print(f"字节数={len(bdo_data)}")
    print(f"BPM={summary['bpm']} 节拍={summary['time_sig']}/4")
    print(
        f"乐器数={summary['instruments']} "
        f"轨道数={summary['tracks']} 音符数={summary['total_notes']}"
    )
    if summary.get("notes_dropped"):
        print(f"已丢弃音符数={summary['notes_dropped']}")
    for idx, track in enumerate(summary["track_details"]):
        if not track["notes"]:
            continue
        print(
            f"轨道[{idx}] 乐器={track['instrument']} 音符={track['notes']} "
            f"音域={track['pitch_min']}-{track['pitch_max']} "
            f"时长毫秒={track['duration_ms']:.0f}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="将 MIDI 转换为黑色沙漠演奏系统曲谱文件。")
    parser.add_argument("input", help="输入 .mid/.midi 文件")
    parser.add_argument("output", nargs="?", help="输出曲谱文件名，不带扩展名")
    parser.add_argument("--outdir", default=str(ROOT / "out" / "bdo"), help="输出目录")
    parser.add_argument("--install", action="store_true", help="复制结果到游戏曲谱目录")
    parser.add_argument("--game-dir", help="指定黑色沙漠曲谱目录")
    parser.add_argument("--name", default="MIDI", help="写入曲谱的角色名")
    parser.add_argument("--owner-file", help="游戏内保存的单音符曲谱，用于读取 Owner ID")
    parser.add_argument("--use-owner-name", action="store_true", help="使用 Owner 文件里的角色名")
    parser.add_argument("--bpm", type=int, help="指定 BPM")
    parser.add_argument("--transpose", type=int, default=0, help="移调半音数")
    parser.add_argument("--vel", nargs=2, type=int, metavar=("MIN", "MAX"))
    parser.add_argument("--vel-floor", type=int)
    parser.add_argument("--vel-step", nargs=2, type=int, metavar=("BASE", "STEP"))
    parser.add_argument("--vel-layered", action="store_true")
    parser.add_argument("--no-sustain", action="store_true")
    parser.add_argument("--flatten-tempo", action="store_true")
    parser.add_argument("--reverb", type=int, default=0)
    parser.add_argument("--delay", type=int, default=0)
    parser.add_argument("--chorus", nargs=3, type=int, metavar=("FB", "DEPTH", "FREQ"))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    convert(args)


if __name__ == "__main__":
    main()
