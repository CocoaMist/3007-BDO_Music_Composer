"""Main-window transaction host for arrangement clip gestures."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from bdo_music_composer.editor.arrangement_clip import (
    ClipEditPlan,
    plan_clip_create,
    plan_clip_edit,
    plan_clip_split,
    overlapping_clip_ids,
)
from bdo_music_composer.editor.editor_models import game_supported_pitches
from bdo_music_composer.editor.model_change import ModelChange
from bdo_music_composer.ui.i18n import tr, trf


class ArrangementClipHostMixin:
    def _publish_clip_plan(self, plan: ClipEditPlan, reason: str) -> None:
        tracks_by_id = {int(track.track_id): track for track in self.tracks}
        if any(update.track_id not in tracks_by_id for update in plan.updates):
            raise ValueError("clip target track is no longer available")
        self._stop_preview(reset_playhead=False)
        self._push_project_snapshot()
        for update in plan.updates:
            track = tracks_by_id[update.track_id]
            track.notes = list(update.notes)
            track.performance_controls = list(update.performance_controls)
            track.bdo_source_note_records = update.source_note_records
            track.bdo_source_group_index = update.source_group_index
            track.duration_scale = 1.0
            track.clip_start_ms = update.clip_start_ms
            track.clip_end_ms = update.clip_end_ms
            track.arrangement_clips = list(update.arrangement_clips)
        selected = tracks_by_id[plan.selected_track_id]
        self._select_track(selected)
        self._apply_workspace_change(ModelChange.notes(
            *(update.track_id for update in plan.updates)
        ))
        self._schedule_timeline_validation_refresh()
        # Cross-track moves are permissive: publish the musical edit first,
        # then immediately expose destination mapping failures on the lane and
        # exact notes instead of rejecting the gesture.
        refresh_validation = getattr(self, "_refresh_timeline_validation", None)
        if callable(refresh_validation):
            refresh_validation()
        self._autosave_project(reason, immediate=True)

    def _commit_timeline_clip_edit(self, request) -> None:
        overlap_ids: tuple[str, ...] = ()
        if request.mode == "move":
            overlap_ids = overlapping_clip_ids(
                request.target_track,
                start_ms=request.new_start_ms,
                end_ms=request.new_end_ms,
                ignored_id=(
                    request.clip_id
                    if request.source_track is request.target_track
                    else ""
                ),
            )
        if overlap_ids:
            answer = QMessageBox.warning(
                self,
                tr("确认合并片段"),
                tr(
                    "目标位置与已有片段重叠。确认后会把两个片段合并；选择“否”将取消本次拖动，不会自动对齐或修改工程。"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            plan = plan_clip_edit(
                request.source_track,
                target=request.target_track,
                mode=request.mode,
                new_start_ms=request.new_start_ms,
                new_end_ms=request.new_end_ms,
                clip_id=request.clip_id,
                merge_overlaps=bool(overlap_ids),
            )
            self._publish_clip_plan(plan, "arrangement clip edit")
        except (TypeError, ValueError) as exc:
            self.show_toast(
                trf("无法编辑片段：{error}", error=exc), kind="error"
            )
            return
        target = request.target_track
        notice = self.timeline._track_validation_notice(target)
        if request.source_track is not target and notice.get("errors"):
            self.show_toast(
                tr("片段已移动；目标乐器存在音高或映射问题，已标红"),
                kind="error",
                duration_ms=4600,
            )
        else:
            self.show_toast(tr("片段编辑已应用"), kind="success")

    def _split_timeline_clip(self, request) -> None:
        try:
            plan = plan_clip_split(
                request.track,
                clip_id=request.clip_id,
                split_ms=request.split_ms,
            )
            self._publish_clip_plan(plan, "split arrangement clip")
        except (TypeError, ValueError) as exc:
            self.show_toast(
                trf("无法切分片段：{error}", error=exc), kind="error"
            )
            return
        self.show_toast(tr("片段已切分"), kind="success")

    def _create_timeline_clip(self, track, start_ms: float) -> None:
        pitches = game_supported_pitches(
            int(track.bdo_instrument_id),
            str(track.marnian_synth_mode),
        ) or frozenset(range(48, 85))
        pitch = min(pitches, key=lambda value: (abs(int(value) - 60), int(value)))
        beat_ms = 60_000.0 / max(1, int(self.bpm_override or self.bpm))
        try:
            plan = plan_clip_create(
                track,
                start_ms=start_ms,
                duration_ms=beat_ms,
                pitch=int(pitch),
                ntype=(
                    99
                    if bool(track.is_percussion)
                    or int(track.bdo_instrument_id) == 0x0D
                    else 0
                ),
            )
            self._publish_clip_plan(plan, "create arrangement clip")
        except (TypeError, ValueError) as exc:
            self.show_toast(
                trf("无法创建片段：{error}", error=exc), kind="error"
            )
            return
        self._open_note_editor(track)


__all__ = ["ArrangementClipHostMixin"]
