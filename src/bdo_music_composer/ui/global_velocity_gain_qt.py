"""Global and per-track velocity-base controls for the main workspace."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSlider,
    QSpinBox,
)

from bdo_midi import Note
from bdo_music_composer.editor.editor_models import TrackState
from bdo_music_composer.editor.game_score_model import (
    bound_game_velocity_b_values,
    transform_game_velocity_records,
)
from bdo_music_composer.editor.global_velocity_gain import base_velocity_map
from bdo_music_composer.editor.model_change import ModelChange
from bdo_music_composer.ui.dialogs.track_settings_dialogs import (
    TrackVelocityBaseDialog,
)
from bdo_music_composer.ui.i18n import tr


class GlobalVelocityGainHostMixin:
    """Own the velocity-base widgets and their undoable model transactions."""

    def _build_global_velocity_gain_control(self) -> QFrame:
        group = QFrame()
        group.setObjectName("ToolbarGlobalGainGroup")
        layout = QHBoxLayout(group)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(7)

        self.toolbar_global_gain_group = group
        self.toolbar_global_gain_label = QLabel(tr("全局力度基数"))
        self.toolbar_global_gain_label.setObjectName("ToolbarGlobalGainTitle")
        self.toolbar_global_gain = QSlider(Qt.Horizontal)
        self.toolbar_global_gain.setObjectName("ToolbarGlobalGainSlider")
        self.toolbar_global_gain.setRange(-127, 127)
        self.toolbar_global_gain.setFixedWidth(220)
        self.toolbar_global_gain.setEnabled(False)
        self.toolbar_global_gain.setToolTip(
            tr(
                "自由设置整首曲谱的力度基数；勾选均化后，先加基数，再把整组力度统一按比例映射到 0–127。"
            )
        )
        self.toolbar_global_gain.setAccessibleName(tr("全局力度基数"))
        self.toolbar_global_gain_value = QSpinBox()
        self.toolbar_global_gain_value.setObjectName("ToolbarGlobalGainValue")
        self.toolbar_global_gain_value.setRange(-127, 127)
        self.toolbar_global_gain_value.setValue(0)
        self.toolbar_global_gain_value.setButtonSymbols(QSpinBox.NoButtons)
        self.toolbar_global_gain_value.setKeyboardTracking(False)
        self.toolbar_global_gain_value.setAlignment(Qt.AlignCenter)
        self.toolbar_global_gain_value.setFixedWidth(52)
        self.toolbar_global_gain_equalize = QCheckBox(tr("均化"))
        self.toolbar_global_gain_equalize.setObjectName(
            "ToolbarGlobalGainEqualize"
        )
        self.toolbar_global_gain_equalize.setToolTip(
            tr("按整首曲谱的原始力度关系统一缩放，使调整后的力度落在 0–127。")
        )
        self._toolbar_global_gain_initial_value = 0
        self._toolbar_global_gain_reference = 0
        self._toolbar_global_gain_track_signature: tuple[object, ...] = ()
        self._toolbar_global_gain_origin_notes: list[
            tuple[TrackState, list[Note], tuple[tuple, ...]]
        ] | None = None
        self._toolbar_global_gain_initial_notes: list[
            tuple[TrackState, list[Note], tuple[tuple, ...]]
        ] | None = None
        self.toolbar_global_gain.sliderPressed.connect(
            self._begin_toolbar_global_gain_drag
        )
        self.toolbar_global_gain.valueChanged.connect(
            self._preview_toolbar_global_gain
        )
        self.toolbar_global_gain.sliderReleased.connect(
            self._commit_toolbar_global_gain
        )
        self.toolbar_global_gain_value.editingFinished.connect(
            self._commit_toolbar_global_gain_input
        )
        self.toolbar_global_gain_equalize.toggled.connect(
            self._on_toolbar_global_gain_equalize_toggled
        )
        layout.addWidget(self.toolbar_global_gain_label)
        layout.addWidget(self.toolbar_global_gain)
        layout.addWidget(self.toolbar_global_gain_value)
        layout.addWidget(self.toolbar_global_gain_equalize)
        return group

    def _sync_toolbar_global_gain(self, track: TrackState | None = None) -> None:
        del track
        if not hasattr(self, "toolbar_global_gain"):
            return
        has_notes = any(item.notes for item in self.tracks)
        signature = self._toolbar_global_gain_model_signature()
        if signature != self._toolbar_global_gain_track_signature:
            self._toolbar_global_gain_track_signature = signature
            self._toolbar_global_gain_reference = 0
            self._toolbar_global_gain_origin_notes = [
                (item, list(item.notes), tuple(item.bdo_source_note_records))
                for item in self.tracks
            ]
        self.toolbar_global_gain.blockSignals(True)
        self.toolbar_global_gain_value.blockSignals(True)
        self.toolbar_global_gain.setEnabled(has_notes)
        self.toolbar_global_gain_value.setEnabled(has_notes)
        self.toolbar_global_gain_equalize.setEnabled(has_notes)
        reference = self._toolbar_global_gain_reference if has_notes else 0
        self.toolbar_global_gain.setRange(-127, 127)
        self.toolbar_global_gain_value.setRange(-127, 127)
        self.toolbar_global_gain.setValue(reference)
        self.toolbar_global_gain_value.setValue(reference)
        self.toolbar_global_gain.blockSignals(False)
        self.toolbar_global_gain_value.blockSignals(False)

    def _toolbar_global_gain_model_signature(self) -> tuple[object, ...]:
        return tuple(
            (id(item), tuple(item.notes), tuple(item.bdo_source_note_records))
            for item in self.tracks
        )

    def _begin_toolbar_global_gain_drag(self) -> None:
        if not self.toolbar_global_gain.isEnabled() or not self.tracks:
            return
        if self._toolbar_global_gain_initial_notes is not None:
            return
        self._toolbar_global_gain_initial_value = int(
            self.toolbar_global_gain.value()
        )
        self._toolbar_global_gain_initial_notes = [
            (track, list(track.notes), tuple(track.bdo_source_note_records))
            for track in self.tracks
        ]

    def _preview_toolbar_global_gain(self, value: int) -> None:
        baseline = self._toolbar_global_gain_initial_notes
        if baseline is None:
            if not self.toolbar_global_gain.isEnabled() or not self.tracks:
                return
            # A groove click changes value before sliderPressed fires.
            self._toolbar_global_gain_initial_value = int(
                self._toolbar_global_gain_reference
            )
            self._toolbar_global_gain_initial_notes = [
                (track, list(track.notes), tuple(track.bdo_source_note_records))
                for track in self.tracks
            ]
            baseline = self._toolbar_global_gain_initial_notes
        source = self._toolbar_global_gain_origin_notes or baseline
        baseline_velocities = [
            int(item)
            for _track, initial_notes, initial_records in source
            for item in (
                *(note.vel for note in initial_notes),
                *bound_game_velocity_b_values(initial_notes, initial_records),
            )
        ]
        velocity_map = base_velocity_map(
            baseline_velocities,
            int(value),
            0,
            equalize=self.toolbar_global_gain_equalize.isChecked(),
        )
        for track, initial_notes, initial_records in source:
            next_notes = [
                note._replace(vel=velocity_map[int(note.vel)])
                for note in initial_notes
            ]
            track.bdo_source_note_records = transform_game_velocity_records(
                initial_notes,
                initial_records,
                next_notes,
                lambda velocity: velocity_map[int(velocity)],
            )
            track.notes = next_notes
        self.toolbar_global_gain_value.blockSignals(True)
        self.toolbar_global_gain_value.setValue(int(value))
        self.toolbar_global_gain_value.blockSignals(False)
        self.timeline.update()

    def _on_toolbar_global_gain_equalize_toggled(self, _checked: bool) -> None:
        if not self.toolbar_global_gain.isEnabled():
            return
        self._begin_toolbar_global_gain_drag()
        self._preview_toolbar_global_gain(self.toolbar_global_gain.value())
        self._commit_toolbar_global_gain()

    def _commit_toolbar_global_gain_input(self) -> None:
        if not self.toolbar_global_gain_value.isEnabled():
            return
        selected = int(self.toolbar_global_gain_value.value())
        if selected == int(self.toolbar_global_gain.value()):
            return
        self._begin_toolbar_global_gain_drag()
        self.toolbar_global_gain.blockSignals(True)
        self.toolbar_global_gain.setValue(selected)
        self.toolbar_global_gain.blockSignals(False)
        self._preview_toolbar_global_gain(selected)
        self._commit_toolbar_global_gain()

    def _commit_toolbar_global_gain(self) -> None:
        baseline = self._toolbar_global_gain_initial_notes
        self._toolbar_global_gain_initial_notes = None
        if baseline is None:
            self._sync_toolbar_global_gain()
            return
        selected_base = int(self.toolbar_global_gain.value())
        final_notes = [
            (track, list(track.notes), tuple(track.bdo_source_note_records))
            for track, _initial_notes, _initial_records in baseline
        ]
        has_changes = any(
            notes != initial_notes or records != initial_records
            for (
                (_track, notes, records),
                (_initial_track, initial_notes, initial_records),
            ) in zip(final_notes, baseline)
        )
        if not has_changes:
            self._sync_toolbar_global_gain()
            return
        for track, initial_notes, initial_records in baseline:
            track.notes = initial_notes
            track.bdo_source_note_records = initial_records
        self._push_project_snapshot()
        changed_track_ids: list[int] = []
        for track, notes, records in final_notes:
            if notes != track.notes or records != track.bdo_source_note_records:
                track.notes = notes
                track.bdo_source_note_records = records
                changed_track_ids.append(int(track.track_id))
        self._toolbar_global_gain_reference = selected_base
        self._toolbar_global_gain_track_signature = (
            self._toolbar_global_gain_model_signature()
        )
        self._schedule_timeline_validation_refresh()
        if changed_track_ids:
            self._restart_preview_after_timeline_change(
                ModelChange.notes(*changed_track_ids)
            )
        self._autosave_project("global note base gain")
        self._sync_toolbar_global_gain()

    def _show_track_velocity_base_dialog(self, track: TrackState) -> None:
        if track not in self.tracks or not track.notes:
            return
        self.selected_track = track
        dialog = TrackVelocityBaseDialog(self, track)
        if dialog.exec() != QDialog.Accepted:
            return
        base = dialog.selected_velocity_base()
        if base == 0:
            return
        initial_notes = list(track.notes)
        initial_records = tuple(track.bdo_source_note_records)
        velocities = [int(note.vel) for note in initial_notes]
        velocities.extend(
            bound_game_velocity_b_values(initial_notes, initial_records)
        )
        velocity_map = base_velocity_map(
            velocities,
            base,
            0,
            equalize=dialog.equalize_enabled(),
        )
        next_notes = [
            note._replace(vel=velocity_map[int(note.vel)])
            for note in initial_notes
        ]
        next_records = transform_game_velocity_records(
            initial_notes,
            initial_records,
            next_notes,
            lambda velocity: velocity_map[int(velocity)],
        )
        if next_notes == initial_notes and next_records == initial_records:
            return
        self._push_project_snapshot()
        track.notes = next_notes
        track.bdo_source_note_records = next_records
        self._schedule_timeline_validation_refresh()
        self._restart_preview_after_timeline_change(
            ModelChange.notes(int(track.track_id))
        )
        self._autosave_project("track velocity base", immediate=True)
        self._select_track(track)


__all__ = ["GlobalVelocityGainHostMixin"]
