#!/usr/bin/env python3
"""Verify local private game scores without printing identity fields or paths."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bdo_codec import decode_score, encode_score, validate_score


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    failures = 0
    files = sorted(path for path in args.directory.iterdir() if path.is_file())
    for index, path in enumerate(files, start=1):
        try:
            source = path.read_bytes()
            document = decode_score(source)
            encoded = encode_score(document, mode="lossless")
            issues = validate_score(document)
            errors = sum(issue.severity == "error" for issue in issues)
            digest = hashlib.sha256(source).hexdigest()[:12]
            passed = source == encoded and not errors
            failures += not passed
            print(
                f"sample-{index:03d} sha256={digest} bytes={len(source)} "
                f"groups={len(document.groups)} notes={document.total_notes} "
                f"warnings={len(issues) - errors} result={'PASS' if passed else 'FAIL'}"
            )
        except Exception as exc:
            failures += 1
            print(f"sample-{index:03d} result=FAIL error={type(exc).__name__}: {exc}")
    print(f"checked={len(files)} failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
