#!/usr/bin/env python3
"""BDO Music Composer application entry point.

Run without arguments to open the PySide6 desktop editor. Arguments retain
the command-line conversion entry point, for example::

    python main.py samples/test_chord.mid test_song
"""

import sys


def main() -> None:
    if len(sys.argv) > 1:
        from scripts.bdo_convert import main as cli_main

        cli_main()
        return

    from pyside_bdo_gui import main as gui_main

    raise SystemExit(gui_main())


if __name__ == "__main__":
    main()
