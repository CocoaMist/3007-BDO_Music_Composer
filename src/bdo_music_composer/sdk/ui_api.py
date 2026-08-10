"""Optional, lazy-loaded PySide6 integration helpers for SDK consumers.

Importing this module does not import PySide6.  Qt and the application UI are
loaded only when a helper is called, so command-line codec users stay Qt-free.
"""

from __future__ import annotations

from dataclasses import dataclass
import sys
from typing import Any, Sequence


@dataclass(frozen=True, slots=True)
class UiComponents:
    """Advanced UI classes with their original constructor contracts."""

    main_window: type
    timeline_canvas: type
    piano_roll_canvas: type
    note_editor_dialog: type


def create_application(
    argv: Sequence[str] | None = None,
    *,
    language: str = "auto",
) -> Any:
    """Create or configure the shared QApplication used by SDK widgets."""

    from PySide6.QtWidgets import QApplication

    from bdo_music_composer.app.application_metadata import (
        APP_NAME,
        APP_VERSION,
    )
    from bdo_music_composer.ui.i18n import install_localizer, localizer
    from bdo_music_composer.ui.theme.fluent_theme import configure_widget_style

    app = QApplication.instance()
    if app is not None and not isinstance(app, QApplication):
        raise RuntimeError(
            "a QCoreApplication already exists; reusable widgets require "
            "QApplication to be the process-level Qt application"
        )
    if app is None:
        app = QApplication(list(argv) if argv is not None else list(sys.argv))
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    configure_widget_style(app)
    current_localizer = localizer()
    if current_localizer is None:
        install_localizer(app, language)
    elif language != "auto" and current_localizer.language != language:
        current_localizer.set_language(language)
    return app


def load_ui_components() -> UiComponents:
    """Load reusable widgets without constructing the complete application."""

    from bdo_music_composer.ui.editor.midi_note_editor import MidiNoteEditorDialog
    from bdo_music_composer.ui.editor.piano_roll_canvas import PianoRollCanvas
    from bdo_music_composer.ui.editor.timeline_canvas import TimelineCanvas
    from bdo_music_composer.ui.main_window import MidiToBdoWindow

    return UiComponents(
        main_window=MidiToBdoWindow,
        timeline_canvas=TimelineCanvas,
        piano_roll_canvas=PianoRollCanvas,
        note_editor_dialog=MidiNoteEditorDialog,
    )


def create_timeline_canvas(
    tracks: Sequence[Any] = (),
    *,
    argv: Sequence[str] | None = None,
    language: str = "auto",
) -> Any:
    """Create the standalone multitrack timeline and optionally load tracks."""

    create_application(argv, language=language)
    from bdo_music_composer.ui.editor.timeline_canvas import TimelineCanvas

    canvas = TimelineCanvas()
    canvas.set_tracks(list(tracks))
    return canvas


def run_desktop_app() -> int:
    """Run the complete BDO Music Composer desktop application."""

    from bdo_music_composer.ui.main_window import main

    return int(main())


__all__ = [
    "UiComponents",
    "create_application",
    "create_timeline_canvas",
    "load_ui_components",
    "run_desktop_app",
]
