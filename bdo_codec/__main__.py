"""Command-line interface for the BDO v9 score codec."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from . import (
    compare_score_documents, decode_score, document_from_dict, document_to_dict,
    encode_score, read_score, validate_score,
)


def _write_json(path: Path | None, payload: object) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    if path is None:
        print(text)
    else:
        path.write_text(text + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bdo_codec", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="inspect a score with private fields redacted")
    inspect_parser.add_argument("input", type=Path)
    inspect_parser.add_argument("--include-private", action="store_true")

    decode_parser = subparsers.add_parser("decode", help="write reversible JSON (contains private fields)")
    decode_parser.add_argument("input", type=Path)
    decode_parser.add_argument("output", type=Path)

    encode_parser = subparsers.add_parser("encode", help="encode reversible JSON as a canonical v9 score")
    encode_parser.add_argument("input", type=Path)
    encode_parser.add_argument("output", type=Path)

    validate_parser = subparsers.add_parser("validate", help="validate a v9 score")
    validate_parser.add_argument("input", type=Path)

    roundtrip_parser = subparsers.add_parser("roundtrip", help="decode and encode a v9 score")
    roundtrip_parser.add_argument("input", type=Path)
    roundtrip_parser.add_argument("output", type=Path, nargs="?")
    roundtrip_parser.add_argument("--verify-bytes", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            _write_json(None, document_to_dict(read_score(args.input), include_private=args.include_private))
        elif args.command == "decode":
            document = read_score(args.input)
            _write_json(args.output, document_to_dict(document, include_private=True))
            print("Warning: reversible JSON contains Owner ID and character names.", file=sys.stderr)
        elif args.command == "encode":
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            args.output.write_bytes(encode_score(document_from_dict(payload), mode="canonical"))
        elif args.command == "validate":
            issues = validate_score(read_score(args.input))
            _write_json(None, [asdict(issue) for issue in issues])
            return 1 if any(issue.severity == "error" for issue in issues) else 0
        elif args.command == "roundtrip":
            source = args.input.read_bytes()
            encoded = encode_score(decode_score(source), mode="lossless")
            if args.output is not None:
                args.output.write_bytes(encoded)
            if args.verify_bytes and encoded != source:
                print("roundtrip byte comparison failed", file=sys.stderr)
                return 1
            print("roundtrip byte comparison passed" if encoded == source else "roundtrip completed")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
