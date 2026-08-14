"""Report candidate-dead functions and methods in the app package.

Read-only by default: a def is reported when its name has no textual reference
anywhere in the repository beyond its own definition(s). Qt framework callbacks
and dunder methods are excluded. Results require manual review because textual
scanning cannot prove that a framework callback or public compatibility surface
is unused.

Run:
  python tools/find_dead_code.py
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOT = ROOT / "src" / "bdo_music_composer"
WORD = re.compile(r"\b\w+\b")

FRAMEWORK = frozenset({
    "paintEvent", "mousePressEvent", "mouseReleaseEvent", "mouseMoveEvent",
    "mouseDoubleClickEvent", "wheelEvent", "keyPressEvent", "keyReleaseEvent",
    "resizeEvent", "leaveEvent", "enterEvent", "focusInEvent", "focusOutEvent",
    "closeEvent", "showEvent", "hideEvent", "contextMenuEvent", "timerEvent",
    "event", "eventFilter", "dragEnterEvent", "dragMoveEvent", "dropEvent",
    "dragLeaveEvent", "sizeHint", "minimumSizeHint", "heightForWidth",
    "paintEngine",
})


def _collect_text(root: Path) -> dict[Path, str]:
    return {
        p: p.read_text(encoding="utf-8-sig")
        for p in root.rglob("*.py")
        if ".venv" not in str(p)
        and "site-packages" not in str(p)
        and "__pycache__" not in str(p)
    }


def _dead_defs() -> list[tuple[Path, int, int, str]]:
    """Return (path, start_line, end_line, name) for candidate-dead defs."""

    texts = _collect_text(ROOT)
    word_total: Counter[str] = Counter()
    def_count: Counter[str] = Counter()
    for text in texts.values():
        word_total.update(WORD.findall(text))
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                def_count[node.name] += 1

    found: list[tuple[Path, int, int, str]] = []
    targets = [p for p in SCAN_ROOT.rglob("*.py") if "__pycache__" not in str(p)]
    for path in sorted(targets):
        text = texts.get(path)
        if text is None:
            continue
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            name = node.name
            if name in FRAMEWORK or (name.startswith("__") and name.endswith("__")):
                continue
            if word_total[name] - def_count[name] <= 0:
                start = node.lineno
                for dec in node.decorator_list:
                    start = min(start, dec.lineno)
                found.append((path, start, node.end_lineno or node.lineno, name))
    return found


def main() -> int:
    found = _dead_defs()
    for path, start, _end, name in found:
        print(f"{path.relative_to(ROOT).as_posix()}:{start}  {name}")
    print(f"--- total candidates: {len(found)} ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
