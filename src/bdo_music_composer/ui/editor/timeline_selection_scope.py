"""Track/Clip focus-scope helpers for the timeline canvas."""

from __future__ import annotations

from PySide6.QtCore import Qt


def selection_descriptor(canvas) -> dict[str, object]:
    return {
        "scope": canvas.selection_scope,
        "active_track": canvas.selected_track,
        "tracks": canvas.selected_track_items(),
        "clips": canvas.selected_clip_items(),
    }


def select_pointer_track(canvas, track, modifiers: Qt.KeyboardModifiers) -> None:
    track_id = int(track.track_id)
    if not modifiers & (Qt.ControlModifier | Qt.ShiftModifier):
        canvas._select_track(track, emit=True)
        return
    selected = set(canvas._selected_track_ids)
    if modifiers & Qt.ControlModifier and track_id in selected:
        selected.remove(track_id)
    else:
        selected.add(track_id)
    canvas._clear_clip_selection()
    canvas._focus_scope = "track"
    canvas._selected_track_ids = selected or {track_id}
    canvas.selected_track = track
    canvas.velocity_curve_overlay.selected_track_changed(track)
    canvas.selected.emit(track)
    canvas._ensure_selected_track_visible()
    canvas._update_accessible_track_state()
    canvas.update()
    canvas._emit_selection_scope()


__all__ = ["select_pointer_track", "selection_descriptor"]
