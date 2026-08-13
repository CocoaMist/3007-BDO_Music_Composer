"""Focused host behavior for non-modal note editors and timeline markers."""

from __future__ import annotations

import time

from PySide6.QtWidgets import QInputDialog

from bdo_music_composer.ui.i18n import tr
from bdo_music_composer.editor.timeline_markers import normalize_timeline_markers


class EditorWorkspaceHostMixin:
    def _reset_project_timeline_metadata(self) -> None:
        current = self.research_metadata if isinstance(self.research_metadata, dict) else {}
        self.research_metadata = {
            "profile_id": current.get("profile_id", ""),
            "ab_experiments": [],
            "timeline_markers": [],
        }

    def _activate_note_editor(self, dialog) -> None:
        if dialog not in self._note_editors.values():
            return
        self.active_transcription_editor = dialog
        self._refresh_transcription_workspace()

    def _synchronize_timeline_markers(self) -> None:
        markers = list(normalize_timeline_markers(
            self.research_metadata.get("timeline_markers", ())
        ))
        self.research_metadata["timeline_markers"] = markers
        self.timeline.set_timeline_markers(markers)
        for editor in tuple(self._note_editors.values()):
            editor.set_timeline_markers(markers)

    def _route_focused_editor_history(self, *, redo: bool) -> bool:
        editor = self.active_transcription_editor
        if editor is None or not editor.isVisible() or not editor.isActiveWindow():
            return False
        (editor.redo if redo else editor.undo)()
        return True

    def _project_history_is_safe(self) -> bool:
        dirty = next((
            editor for editor in self._note_editors.values()
            if editor.isVisible()
            and (
                editor.edited_notes() != editor.last_applied
                or editor.has_transcription_staging()
            )
        ), None)
        if dirty is None:
            return True
        dirty.raise_()
        dirty.activateWindow()
        self.show_toast(
            tr("音符编辑器仍有未应用修改；请先应用或关闭，再撤销工程。"),
            kind="warning",
        )
        return False

    def _claim_playback_focus(self, dialog) -> None:
        """Give the shared audio engine to exactly one editor or timeline."""

        for editor in tuple(self._note_editors.values()):
            if editor is not dialog and editor.draft_playback_state != "stopped":
                editor.stop_draft()
        if dialog is not None:
            self.active_transcription_editor = dialog
            self._stop_preview(reset_playhead=False)

    def _close_all_note_editors(self) -> None:
        for editor in tuple(self._note_editors.values()):
            editor.close()
        self._note_editors.clear()
        self.active_transcription_editor = None

    def _edit_timeline_marker(self, request: object) -> None:
        if not isinstance(request, dict):
            return
        action = str(request.get("action") or "")
        markers = list(normalize_timeline_markers(
            self.research_metadata.get("timeline_markers") or []
        ))
        marker_id = str(request.get("id") or "")
        if action == "delete":
            updated = [
                item for item in markers
                if str(item.get("id") or "") != marker_id
            ]
            if len(updated) == len(markers):
                return
            self._push_project_snapshot()
            markers = updated
        else:
            label, accepted = QInputDialog.getText(
                self, tr("时间轴标记"), tr("标记名称"),
                text=str(request.get("label") or ""),
            )
            label = label.strip()
            if not accepted or not label:
                return
            if action == "rename":
                target = next((
                    item for item in markers
                    if str(item.get("id") or "") == marker_id
                ), None)
                if target is None or str(target.get("label") or "") == label:
                    return
                self._push_project_snapshot()
                for item in markers:
                    if str(item.get("id") or "") == marker_id:
                        item["label"] = label
                        break
            else:
                self._push_project_snapshot()
                markers.append({
                    "id": f"marker-{time.time_ns()}", "label": label,
                    "time_ms": max(0.0, float(request.get("time_ms") or 0.0)),
                })
        markers = list(normalize_timeline_markers(markers))
        self.research_metadata["timeline_markers"] = markers
        self._synchronize_timeline_markers()
        self._autosave_project("timeline marker", immediate=True)


__all__ = ["EditorWorkspaceHostMixin"]
