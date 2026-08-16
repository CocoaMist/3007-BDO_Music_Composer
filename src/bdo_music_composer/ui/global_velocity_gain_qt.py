"""Global and per-track velocity-base controls for the main workspace."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSlider,
    QSpinBox,
)

from bdo_music_composer.editor.editor_models import TrackState
from bdo_music_composer.editor.arrangement_clip import clip_by_id, track_clips
from bdo_music_composer.editor.model_change import ModelChange
from bdo_music_composer.editor.velocity_percentage import (
    MAX_VELOCITY_PERCENT,
    MIN_VELOCITY_PERCENT,
    NEUTRAL_VELOCITY_PERCENT,
    apply_clip_velocity_base,
    apply_clip_velocity_percent,
    apply_global_velocity_adjustment,
    apply_track_velocity_percent,
    selection_velocity_percent,
    track_velocity_percent,
)
from bdo_music_composer.ui.dialogs.track_settings_dialogs import (
    ClipVelocityBaseDialog,
)
from bdo_music_composer.ui.i18n import tr, trf


class GlobalVelocityGainHostMixin:
    """Own the velocity-base widgets and their undoable model transactions."""

    def _build_global_velocity_gain_control(self) -> QFrame:
        group = QFrame()
        group.setObjectName("ToolbarGlobalGainGroup")
        layout = QHBoxLayout(group)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(7)

        self.toolbar_global_gain_group = group
        self.toolbar_global_gain_label = QLabel(tr("全轨道分贝调整"))
        self.toolbar_global_gain_label.setObjectName("ToolbarGlobalGainTitle")
        self.toolbar_global_gain_mode = QComboBox()
        self.toolbar_global_gain_mode.setObjectName("ToolbarGlobalGainMode")
        self.toolbar_global_gain_mode.addItem(tr("抬高/降低"), "offset")
        self.toolbar_global_gain_mode.addItem(tr("百分比"), "percent")
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
        self._toolbar_global_gain_origin_states: list[
            tuple[TrackState, tuple[object, ...]]
        ] | None = None
        self._toolbar_global_gain_initial_states: list[
            tuple[TrackState, tuple[object, ...]]
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
        self.toolbar_global_gain_mode.currentIndexChanged.connect(
            self._on_toolbar_global_gain_mode_changed
        )
        layout.addWidget(self.toolbar_global_gain_label)
        layout.addWidget(self.toolbar_global_gain_mode)
        layout.addWidget(self.toolbar_global_gain)
        layout.addWidget(self.toolbar_global_gain_value)
        layout.addWidget(self.toolbar_global_gain_equalize)
        return group

    def _build_selection_velocity_percent_control(self) -> QFrame:
        group = QFrame()
        group.setObjectName("ToolbarSelectionVelocityGroup")
        group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout = QHBoxLayout(group)
        layout.setContentsMargins(6, 1, 4, 1)
        layout.setSpacing(4)
        self.toolbar_velocity_title = QLabel(tr("力度（分贝）"))
        self.toolbar_velocity_title.setObjectName(
            "ToolbarSelectionVelocityTitle"
        )
        self.toolbar_velocity_title.setFixedWidth(70)
        self.toolbar_velocity_scope = QLabel(tr("请选择轨道或Clip"))
        self.toolbar_velocity_scope.setObjectName(
            "ToolbarSelectionVelocityScope"
        )
        self.toolbar_velocity_scope.setMinimumWidth(64)
        self.toolbar_velocity_scope.setMaximumWidth(180)
        self.toolbar_velocity_scope.setSizePolicy(
            QSizePolicy.Preferred, QSizePolicy.Preferred
        )
        self.toolbar_velocity_percent = QSlider(Qt.Horizontal)
        self.toolbar_velocity_percent.setObjectName(
            "ToolbarSelectionVelocityPercent"
        )
        self.toolbar_velocity_percent.setRange(
            MIN_VELOCITY_PERCENT, MAX_VELOCITY_PERCENT
        )
        self.toolbar_velocity_percent.setValue(NEUTRAL_VELOCITY_PERCENT)
        self.toolbar_velocity_percent.setMinimumWidth(90)
        self.toolbar_velocity_percent.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed
        )
        self.toolbar_velocity_percent.setEnabled(False)
        self.toolbar_velocity_percent.setToolTip(tr(
            "将所选轨道或Clip的分贝比例烘焙到每个音块；100%可按工程记录恢复。"
        ))
        self.toolbar_velocity_percent_value = QSpinBox()
        self.toolbar_velocity_percent_value.setObjectName(
            "ToolbarSelectionVelocityPercentValue"
        )
        self.toolbar_velocity_percent_value.setRange(
            MIN_VELOCITY_PERCENT, MAX_VELOCITY_PERCENT
        )
        self.toolbar_velocity_percent_value.setSuffix("%")
        self.toolbar_velocity_percent_value.setValue(
            NEUTRAL_VELOCITY_PERCENT
        )
        self.toolbar_velocity_percent_value.setButtonSymbols(QSpinBox.NoButtons)
        self.toolbar_velocity_percent_value.setAlignment(Qt.AlignCenter)
        self.toolbar_velocity_percent_value.setFixedWidth(62)
        self.toolbar_velocity_percent_value.setKeyboardTracking(False)
        self.toolbar_velocity_percent_value.setEnabled(False)
        self._selection_velocity_drag_origin = None
        self.toolbar_velocity_percent.sliderPressed.connect(
            self._begin_selection_velocity_percent
        )
        self.toolbar_velocity_percent.valueChanged.connect(
            self._preview_selection_velocity_percent
        )
        self.toolbar_velocity_percent.sliderReleased.connect(
            self._commit_selection_velocity_percent
        )
        self.toolbar_velocity_percent_value.editingFinished.connect(
            self._commit_selection_velocity_percent_input
        )
        layout.addWidget(self.toolbar_velocity_title)
        layout.addWidget(self.toolbar_velocity_scope)
        layout.addWidget(self.toolbar_velocity_percent, 1)
        layout.addWidget(self.toolbar_velocity_percent_value)
        return group

    def _selection_velocity_items(self) -> tuple[tuple[TrackState, str], ...]:
        if not hasattr(self, "timeline"):
            return ()
        if self.timeline.selection_scope == "clip":
            return self.timeline.selected_clip_items()
        if self.timeline.selection_scope == "track":
            tracks = self.timeline.selected_track_items()
            return tuple(
                (track, str(clip.clip_id))
                for track in tracks
                for clip in track_clips(track)
            )
        return ()

    @staticmethod
    def _velocity_track_state(track: TrackState) -> tuple[object, ...]:
        return (
            list(track.notes),
            tuple(track.bdo_source_note_records),
            list(track.arrangement_clips),
            int(track.loose_velocity_percent),
            tuple(track.loose_velocity_baseline_a),
            tuple(track.loose_velocity_baseline_b),
        )

    @staticmethod
    def _restore_velocity_track_state(
        track: TrackState, state: tuple[object, ...]
    ) -> None:
        (
            notes, records, clips, loose_percent, loose_a, loose_b,
        ) = state
        # Notes, records and ArrangementClipState are immutable values. Copy
        # only their mutable outer containers so slider previews remain cheap
        # even for large projects without sharing TrackState-owned lists.
        track.notes = list(notes)
        track.bdo_source_note_records = tuple(records)
        track.arrangement_clips = list(clips)
        track.loose_velocity_percent = int(loose_percent)
        track.loose_velocity_baseline_a = tuple(loose_a)
        track.loose_velocity_baseline_b = tuple(loose_b)

    def _sync_selection_velocity_percent(self, _descriptor=None) -> None:
        if not hasattr(self, "toolbar_velocity_percent"):
            return
        items = self._selection_velocity_items()
        scope = self.timeline.selection_scope if hasattr(self, "timeline") else "none"
        if scope == "clip" and items:
            primary_clip = clip_by_id(items[0][0], items[0][1])
            primary_name = str(primary_clip.display_name or items[0][1])
            label = (
                trf("作用域：Clip · {name}", name=primary_name)
                if len(items) == 1
                else trf("作用域：已选择 {count} 个Clip", count=len(items))
            )
        elif scope == "track" and items:
            tracks = self.timeline.selected_track_items()
            label = (
                trf("作用域：轨道 · {name}", name=tracks[0].display_name)
                if len(tracks) == 1
                else trf("作用域：已选择 {count} 条轨道", count=len(tracks))
            )
        else:
            label = tr("请选择轨道或Clip")
        if scope == "track" and items:
            track_values = {
                track_velocity_percent(track)
                for track in self.timeline.selected_track_items()
            }
            value = (
                next(iter(track_values))
                if len(track_values) == 1 and None not in track_values
                else None
            )
        else:
            value = selection_velocity_percent(items) if items else None
        enabled = bool(items)
        self.toolbar_velocity_scope.setText(label)
        self.toolbar_velocity_scope.setToolTip(label)
        self.toolbar_velocity_percent.blockSignals(True)
        self.toolbar_velocity_percent_value.blockSignals(True)
        self.toolbar_velocity_percent.setEnabled(enabled)
        self.toolbar_velocity_percent_value.setEnabled(enabled)
        self.toolbar_velocity_percent.setValue(
            NEUTRAL_VELOCITY_PERCENT if value is None else value
        )
        self.toolbar_velocity_percent_value.setSpecialValueText(
            tr("混合") if enabled and value is None else ""
        )
        self.toolbar_velocity_percent_value.setValue(
            MIN_VELOCITY_PERCENT if enabled and value is None
            else NEUTRAL_VELOCITY_PERCENT if value is None else value
        )
        self.toolbar_velocity_percent.blockSignals(False)
        self.toolbar_velocity_percent_value.blockSignals(False)

    def _begin_selection_velocity_percent(self) -> None:
        items = self._selection_velocity_items()
        tracks_by_id = {
            int(track.track_id): track for track, _clip_id in items
        }
        tracks = tuple(tracks_by_id.values())
        if not tracks:
            return
        self._selection_velocity_drag_origin = {
            int(track.track_id): (track, self._velocity_track_state(track))
            for track in tracks
        }

    def _apply_selection_velocity_percent(self, value: int) -> list[int]:
        if self.timeline.selection_scope == "track":
            return [
                int(track.track_id)
                for track in self.timeline.selected_track_items()
                if apply_track_velocity_percent(track, int(value))
            ]
        grouped: dict[int, tuple[TrackState, list[str]]] = {}
        for track, clip_id in self._selection_velocity_items():
            grouped.setdefault(int(track.track_id), (track, []))[1].append(clip_id)
        changed: list[int] = []
        for track, clip_ids in grouped.values():
            if apply_clip_velocity_percent(track, tuple(clip_ids), int(value)):
                changed.append(int(track.track_id))
        return changed

    def _preview_selection_velocity_percent(self, value: int) -> None:
        if self._selection_velocity_drag_origin is None:
            self._begin_selection_velocity_percent()
        origin = self._selection_velocity_drag_origin
        if not origin:
            return
        for track, state in origin.values():
            self._restore_velocity_track_state(track, state)
        self._apply_selection_velocity_percent(value)
        self.toolbar_velocity_percent_value.blockSignals(True)
        self.toolbar_velocity_percent_value.setSpecialValueText("")
        self.toolbar_velocity_percent_value.setValue(int(value))
        self.toolbar_velocity_percent_value.blockSignals(False)
        self.timeline.update()

    def _commit_selection_velocity_percent_input(self) -> None:
        if not self.toolbar_velocity_percent_value.isEnabled():
            return
        value = int(self.toolbar_velocity_percent_value.value())
        self._begin_selection_velocity_percent()
        self.toolbar_velocity_percent.blockSignals(True)
        self.toolbar_velocity_percent.setValue(value)
        self.toolbar_velocity_percent.blockSignals(False)
        self._preview_selection_velocity_percent(value)
        self._commit_selection_velocity_percent()

    def _commit_selection_velocity_percent(self) -> None:
        origin = self._selection_velocity_drag_origin
        self._selection_velocity_drag_origin = None
        if not origin:
            self._sync_selection_velocity_percent()
            return
        final = {
            track_id: (track, self._velocity_track_state(track))
            for track_id, (track, _state) in origin.items()
        }
        if all(final[key][1] == origin[key][1] for key in origin):
            self._sync_selection_velocity_percent()
            return
        for track, state in origin.values():
            self._restore_velocity_track_state(track, state)
        self._push_project_snapshot()
        for track, state in final.values():
            self._restore_velocity_track_state(track, state)
        changed_ids = tuple(final)
        self._schedule_timeline_validation_refresh()
        self._restart_preview_after_timeline_change(ModelChange.notes(*changed_ids))
        self._autosave_project("selection velocity percent")
        self._sync_toolbar_global_gain()
        self._sync_selection_velocity_percent()

    def _sync_toolbar_global_gain(self, track: TrackState | None = None) -> None:
        del track
        if not hasattr(self, "toolbar_global_gain"):
            return
        has_notes = any(item.notes for item in self.tracks)
        signature = self._toolbar_global_gain_model_signature()
        if signature != self._toolbar_global_gain_track_signature:
            self._toolbar_global_gain_track_signature = signature
            self._toolbar_global_gain_reference = (
                100
                if self.toolbar_global_gain_mode.currentData() == "percent"
                else 0
            )
            self._toolbar_global_gain_origin_states = [
                (item, self._velocity_track_state(item)) for item in self.tracks
            ]
        self.toolbar_global_gain.blockSignals(True)
        self.toolbar_global_gain_value.blockSignals(True)
        self.toolbar_global_gain.setEnabled(has_notes)
        self.toolbar_global_gain_value.setEnabled(has_notes)
        self.toolbar_global_gain_equalize.setEnabled(has_notes)
        percent_mode = self.toolbar_global_gain_mode.currentData() == "percent"
        neutral = 100 if percent_mode else 0
        reference = self._toolbar_global_gain_reference if has_notes else neutral
        minimum, maximum = ((10, 200) if percent_mode else (-127, 127))
        self.toolbar_global_gain.setRange(minimum, maximum)
        self.toolbar_global_gain_value.setRange(minimum, maximum)
        self.toolbar_global_gain_value.setSuffix("%" if percent_mode else "")
        self.toolbar_global_gain_equalize.setEnabled(has_notes and not percent_mode)
        self.toolbar_global_gain.setValue(reference)
        self.toolbar_global_gain_value.setValue(reference)
        self.toolbar_global_gain.blockSignals(False)
        self.toolbar_global_gain_value.blockSignals(False)

    def _on_toolbar_global_gain_mode_changed(self, _index: int) -> None:
        if not hasattr(self, "toolbar_global_gain"):
            return
        percent_mode = self.toolbar_global_gain_mode.currentData() == "percent"
        self._toolbar_global_gain_reference = 100 if percent_mode else 0
        self._toolbar_global_gain_track_signature = (
            self._toolbar_global_gain_model_signature()
        )
        self._toolbar_global_gain_origin_states = [
            (item, self._velocity_track_state(item)) for item in self.tracks
        ]
        self._toolbar_global_gain_initial_states = None
        self._sync_toolbar_global_gain()

    def _toolbar_global_gain_model_signature(self) -> tuple[object, ...]:
        return tuple(
            (
                id(item),
                tuple(item.notes),
                tuple(item.bdo_source_note_records),
                tuple(item.arrangement_clips),
                int(item.loose_velocity_percent),
                tuple(item.loose_velocity_baseline_a),
                tuple(item.loose_velocity_baseline_b),
            )
            for item in self.tracks
        )

    def _begin_toolbar_global_gain_drag(self) -> None:
        if not self.toolbar_global_gain.isEnabled() or not self.tracks:
            return
        if self._toolbar_global_gain_initial_states is not None:
            return
        self._toolbar_global_gain_initial_value = int(
            self.toolbar_global_gain.value()
        )
        self._toolbar_global_gain_initial_states = [
            (track, self._velocity_track_state(track)) for track in self.tracks
        ]

    def _preview_toolbar_global_gain(self, value: int) -> None:
        baseline = self._toolbar_global_gain_initial_states
        if baseline is None:
            if not self.toolbar_global_gain.isEnabled() or not self.tracks:
                return
            # A groove click changes value before sliderPressed fires.
            self._toolbar_global_gain_initial_value = int(
                self._toolbar_global_gain_reference
            )
            self._toolbar_global_gain_initial_states = [
                (track, self._velocity_track_state(track))
                for track in self.tracks
            ]
            baseline = self._toolbar_global_gain_initial_states
        source = self._toolbar_global_gain_origin_states or baseline
        for track, state in source:
            self._restore_velocity_track_state(track, state)
        apply_global_velocity_adjustment(
            tuple(track for track, _state in source),
            int(value),
            percent_mode=(
                self.toolbar_global_gain_mode.currentData() == "percent"
            ),
            equalize=self.toolbar_global_gain_equalize.isChecked(),
        )
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
        baseline = self._toolbar_global_gain_initial_states
        self._toolbar_global_gain_initial_states = None
        if baseline is None:
            self._sync_toolbar_global_gain()
            return
        selected_base = int(self.toolbar_global_gain.value())
        final_states = [
            (track, self._velocity_track_state(track))
            for track, _initial_state in baseline
        ]
        has_changes = any(
            final_state != initial_state
            for ((_track, final_state), (_initial_track, initial_state))
            in zip(final_states, baseline)
        )
        if not has_changes:
            self._sync_toolbar_global_gain()
            return
        for track, initial_state in baseline:
            self._restore_velocity_track_state(track, initial_state)
        self._push_project_snapshot()
        changed_track_ids: list[int] = []
        for track, final_state in final_states:
            if final_state != self._velocity_track_state(track):
                self._restore_velocity_track_state(track, final_state)
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

    def _show_clip_velocity_base_dialog(self, selections) -> None:
        items = tuple(
            (track, str(clip_id))
            for track, clip_id in tuple(selections or ())
            if track in self.tracks
        )
        if not items:
            return
        primary = clip_by_id(items[0][0], items[0][1])
        dialog = ClipVelocityBaseDialog(
            self,
            str(primary.display_name or primary.clip_id),
            len(items),
        )
        if dialog.exec() != QDialog.Accepted:
            return
        base = dialog.selected_velocity_base()
        if base == 0:
            return
        grouped: dict[int, tuple[TrackState, list[str]]] = {}
        for track, clip_id in items:
            grouped.setdefault(int(track.track_id), (track, []))[1].append(clip_id)
        origin = {
            track_id: (track, self._velocity_track_state(track))
            for track_id, (track, _clip_ids) in grouped.items()
        }
        changed_ids = [
            track_id
            for track_id, (track, clip_ids) in grouped.items()
            if apply_clip_velocity_base(
                track,
                tuple(clip_ids),
                base,
                equalize=dialog.equalize_enabled(),
            )
        ]
        if not changed_ids:
            return
        final = {
            track_id: (track, self._velocity_track_state(track))
            for track_id, (track, _state) in origin.items()
        }
        for track, state in origin.values():
            self._restore_velocity_track_state(track, state)
        self._push_project_snapshot()
        for track, state in final.values():
            self._restore_velocity_track_state(track, state)
        self._schedule_timeline_validation_refresh()
        self._restart_preview_after_timeline_change(
            ModelChange.notes(*changed_ids)
        )
        self._autosave_project("clip velocity base", immediate=True)
        self.timeline.set_selected_clip_keys(
            {(int(track.track_id), clip_id) for track, clip_id in items},
            primary_key=(int(items[0][0].track_id), items[0][1]),
        )
        self._sync_toolbar_global_gain()
        self._sync_selection_velocity_percent()


__all__ = ["GlobalVelocityGainHostMixin"]
