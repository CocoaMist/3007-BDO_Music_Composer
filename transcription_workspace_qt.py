"""Compatibility imports for the embedded transcription editor controls.

The former main-window transcription workspace and its second piano-roll
canvas were removed.  New code should import these lightweight, stateless
widgets from :mod:`transcription_editor_qt` directly.
"""

from transcription_editor_qt import (
    TranscriptionEditorPanel,
    TranscriptionWaveformLane,
)

__all__ = ["TranscriptionEditorPanel", "TranscriptionWaveformLane"]
