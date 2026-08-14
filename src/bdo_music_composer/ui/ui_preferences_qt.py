"""Qt bindings for validated, application-local interface preferences."""

from __future__ import annotations

from collections.abc import Callable
import os
from typing import Any, MutableMapping

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QApplication

from bdo_music_composer.app.ui_preferences import (
    normalize_ui_preferences,
    store_ui_preferences,
    ui_preferences,
)


class _PreferenceBinding(QObject):
    def __init__(
        self,
        owner: QObject,
        config: MutableMapping[str, Any],
        persist: Callable[[], None],
        owned_sections: tuple[str, ...],
    ) -> None:
        super().__init__(owner)
        self.owner = owner
        self.config = config
        self._enabled = bool(
            QApplication.platformName().lower() != "offscreen"
            or os.environ.get("BDO_TEST_UI_PREFERENCES") == "1"
        )
        self.preferences = (
            ui_preferences(config)
            if self._enabled
            else normalize_ui_preferences(None)
        )
        self._persist = persist
        self._owned_sections = owned_sections
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(250)
        self._save_timer.timeout.connect(self.flush)

    def schedule(self, *_args: object) -> None:
        if not self._enabled:
            return
        self.capture()
        self._save_timer.start()

    def flush(self) -> None:
        if not self._enabled:
            return
        self.capture()
        merged = ui_preferences(self.config)
        for section in self._owned_sections:
            merged[section] = self.preferences[section]
        self.preferences = store_ui_preferences(self.config, merged)
        self._persist()

    def capture(self) -> None:
        raise NotImplementedError


class WorkspaceUiPreferenceBinding(_PreferenceBinding):
    """Restore and persist main workspace controls and window geometry."""

    def __init__(self, window, config, persist: Callable[[], None]) -> None:
        super().__init__(window, config, persist, ("workspace",))
        values = self.preferences["workspace"]
        window.resize(values["window_width"], values["window_height"])
        window.timeline_zoom.setValue(values["timeline_zoom_percent"])
        window.timeline_pan.setValue(values["timeline_pan_percent"])
        window.timeline_loop_box.setChecked(values["timeline_loop_enabled"])
        window.reference_audio.set_volume_percent(
            values["reference_volume_percent"], notify=False
        )
        window.timeline.set_layout_metrics(
            header_width=values["timeline_header_width"],
            lane_height=values["timeline_lane_height"],
            reference_lane_height=values["reference_lane_height"],
        )
        if values["window_maximized"]:
            QTimer.singleShot(0, window.showMaximized)
        window.timeline_zoom.valueChanged.connect(self.schedule)
        window.timeline_pan.valueChanged.connect(self.schedule)
        window.timeline_loop_box.toggled.connect(self.schedule)
        window.reference_audio.volume_changed.connect(self.schedule)
        window.timeline.layout_preferences_changed.connect(self.schedule)
        window.installEventFilter(self)

    @property
    def timeline_zoom_percent(self) -> int:
        return int(self.preferences["workspace"]["timeline_zoom_percent"])

    @property
    def timeline_pan_percent(self) -> int:
        return int(self.preferences["workspace"]["timeline_pan_percent"])

    @property
    def reference_volume_percent(self) -> int:
        return int(self.preferences["workspace"]["reference_volume_percent"])

    def capture(self) -> None:
        window = self.owner
        values = self.preferences["workspace"]
        if not window.isMaximized():
            values["window_width"] = window.width()
            values["window_height"] = window.height()
        values["window_maximized"] = window.isMaximized()
        values["timeline_zoom_percent"] = window.timeline_zoom.value()
        values["timeline_pan_percent"] = window.timeline_pan.value()
        values["timeline_loop_enabled"] = window.timeline_loop_box.isChecked()
        values["reference_volume_percent"] = window.reference_audio.volume_percent
        values.update({
            "timeline_header_width": window.timeline.header_width,
            "timeline_lane_height": window.timeline.lane_height,
            "reference_lane_height": window.timeline.reference_lane_height,
        })

    def reset_timeline_position(self, *, fit: bool = False) -> None:
        window = self.owner
        zoom = 100 if fit else self.timeline_zoom_percent
        pan = 0 if fit else self.timeline_pan_percent
        window.timeline.set_zoom_percent(zoom)
        window.timeline.set_pan_percent(pan)
        window.timeline.set_playhead(0.0, follow=True)
        for control, value in (
            (window.timeline_zoom, zoom),
            (window.timeline_pan, pan),
        ):
            blocked = control.blockSignals(True)
            control.setValue(value)
            control.blockSignals(blocked)
        window.timeline_pan.setEnabled(zoom > 100)
        window.timeline.update()
        if fit:
            self.schedule()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.owner and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.WindowStateChange,
        }:
            self.schedule()
        elif watched is self.owner and event.type() == QEvent.Type.Close:
            self.flush()
        return False


class EditorUiPreferenceBinding(_PreferenceBinding):
    """Restore and persist reusable piano-roll interaction preferences."""

    def __init__(self, editor, config, persist: Callable[[], None]) -> None:
        super().__init__(editor, config, persist, ("editor", "transcription"))
        self._restore(editor)
        for signal in (
            editor.editor_zoom.valueChanged,
            editor.quantize_combo.currentIndexChanged,
            editor.snap_box.toggled,
            editor.note_preview_box.toggled,
            editor.draw_mode_button.toggled,
            editor.loop_box.toggled,
            editor.velocity_toggle.toggled,
            editor.velocity_radius_combo.currentIndexChanged,
            editor.velocity_scope_combo.currentIndexChanged,
            editor.transcription_panel.confidence_changed,
            editor.transcription_panel.show_rejected_changed,
            editor.transcription_panel.show_suppressed_changed,
            editor.transcription_panel.rhythm_projection_enabled_changed,
            editor.transcription_panel.rhythm_profile_changed,
        ):
            signal.connect(self.schedule)
        for button in (
            editor.note_mode_button,
            editor.articulation_mode_button,
            editor.grid_mode_button,
            editor.velocity_point_button,
            editor.velocity_brush_button,
        ):
            button.clicked.connect(self.schedule)
        editor.editor_splitter.splitterMoved.connect(self.schedule)
        editor.installEventFilter(self)
        editor.canvas.installEventFilter(self)
        editor.velocity_lane.installEventFilter(self)

    def _restore(self, editor) -> None:
        values = self.preferences["editor"]
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        width = values["window_width"]
        height = values["window_height"]
        if available is not None:
            width = min(width, available.width() - 32)
            height = min(height, available.height() - 32)
        editor.resize(max(editor.minimumWidth(), width), max(editor.minimumHeight(), height))
        editor.editor_zoom.setValue(values["horizontal_zoom"])
        editor.canvas.ROW_H = float(values["note_row_height"])
        quantize_index = editor.quantize_combo.findData(values["quantize_divisor"])
        editor.quantize_combo.setCurrentIndex(max(0, quantize_index))
        editor.snap_box.setChecked(values["snap_enabled"])
        editor.note_preview_box.setChecked(values["note_preview_enabled"])
        editor.draw_mode_button.setChecked(values["draw_mode_enabled"])
        editor._set_top_inspector_mode(values["inspector_mode"])
        editor.loop_box.setChecked(values["loop_enabled"])
        editor.velocity_toggle.setChecked(values["velocity_visible"])
        editor.set_velocity_panel_height(values["velocity_panel_height"])
        editor._set_velocity_mode(values["velocity_mode"])
        radius_index = editor.velocity_radius_combo.findData(values["velocity_radius_beats"])
        editor.velocity_radius_combo.setCurrentIndex(max(0, radius_index))
        scope_index = editor.velocity_scope_combo.findData(values["velocity_scope"])
        editor.velocity_scope_combo.setCurrentIndex(max(0, scope_index))
        transcription = self.preferences["transcription"]
        panel = editor.transcription_panel
        panel.set_confidence_floor(transcription["confidence_percent"] / 100.0)
        panel.show_rejected_checkbox.setChecked(transcription["show_rejected"])
        panel.show_suppressed_checkbox.setChecked(transcription["show_suppressed"])
        panel.rhythm_projection_checkbox.setChecked(
            transcription["rhythm_projection_enabled"]
        )
        rhythm_index = panel.rhythm_profile_combo.findData(transcription["rhythm_profile"])
        panel.rhythm_profile_combo.setCurrentIndex(max(0, rhythm_index))
        editor.transcription_rhythm_projection_enabled = bool(
            transcription["rhythm_projection_enabled"]
        )

    def capture(self) -> None:
        editor = self.owner
        values = self.preferences["editor"]
        values.update({
            "window_width": editor.width(),
            "window_height": editor.height(),
            "horizontal_zoom": editor.editor_zoom.value(),
            "note_row_height": round(float(editor.canvas.ROW_H), 3),
            "quantize_divisor": int(editor.quantize_combo.currentData() or 1),
            "snap_enabled": editor.snap_box.isChecked(),
            "note_preview_enabled": editor.note_preview_box.isChecked(),
            "draw_mode_enabled": editor.draw_mode_button.isChecked(),
            "inspector_mode": self._inspector_mode(editor),
            "loop_enabled": editor.loop_box.isChecked(),
            "velocity_visible": editor.velocity_toggle.isChecked(),
            "velocity_panel_height": editor.velocity_panel_height(),
            "velocity_mode": editor.velocity_lane.edit_mode,
            "velocity_radius_beats": editor.velocity_lane.influence_beats,
            "velocity_scope": editor.velocity_lane.scope_mode,
        })
        panel = editor.transcription_panel
        self.preferences["transcription"].update({
            "confidence_percent": round(panel.confidence_floor * 100),
            "show_rejected": panel.show_rejected_checkbox.isChecked(),
            "show_suppressed": panel.show_suppressed_checkbox.isChecked(),
            "rhythm_projection_enabled": panel.rhythm_projection_checkbox.isChecked(),
            "rhythm_profile": panel.rhythm_alignment_profile,
        })

    @staticmethod
    def _inspector_mode(editor) -> str:
        if editor.articulation_mode_button.isChecked():
            return "articulation"
        return "grid" if editor.grid_mode_button.isChecked() else "note"

    def eventFilter(self, watched, event) -> bool:
        if watched is self.owner and event.type() == QEvent.Type.Resize:
            self.schedule()
        elif watched in {self.owner.canvas, self.owner.velocity_lane} and event.type() == QEvent.Type.Wheel:
            QTimer.singleShot(0, self.schedule)
        elif watched is self.owner and event.type() == QEvent.Type.Close:
            self.flush()
        return False


__all__ = ["EditorUiPreferenceBinding", "WorkspaceUiPreferenceBinding"]
