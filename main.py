#!/usr/bin/env python3
"""黑色沙漠 MIDI 转换器入口。

不带参数运行会打开图形界面。带参数运行会使用命令行转换，例如：

    python main.py samples/test_chord.mid test_song
"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TOOL_DIR = ROOT / "tools" / "midi-to-bdo"


def main() -> None:
    if len(sys.argv) > 1:
        from scripts.bdo_convert import main as cli_main

        cli_main()
        return

    sys.path.insert(0, str(TOOL_DIR))
    from midi2bdo_gui import App

    App().mainloop()


if __name__ == "__main__":
    main()
