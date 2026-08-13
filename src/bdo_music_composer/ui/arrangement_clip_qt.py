"""Main-window transaction host for arrangement clip gestures."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from bdo_music_composer.editor.arrangement_clip import (
    ClipEditError,
    ClipEditPlan,
    clip_edit_fingerprint,
    clip_editor_notes,
    clip_editor_scope,
    copy_clip,
    plan_clip_create,
    plan_clip_delete,
    plan_clip_edit,
    plan_clip_paste,
    plan_clip_split,
    plan_clip_note_edit,
    overlapping_clip_ids,
)
from bdo_music_composer.editor.editor_models import game_supported_pitches
from bdo_music_composer.editor.game_score_model import (
    reconcile_track_game_velocity_records,
)
from bdo_music_composer.editor.model_change import ModelChange
from bdo_music_composer.transcription.bdo_transcription_session import (
    TranscriptionEditorCommitReport,
)
from bdo_music_composer.ui.i18n import tr, trf


class ArrangementClipHostMixin:
    _arrangement_clip_clipboard = None

    def _commit_arrangement_clip_note_editor(
        self, request, track, draft_notes
    ) -> TranscriptionEditorCommitReport | None:
        """Publish one explicit Clip draft without touching sibling Clips."""

        if request.routes or request.new_track_specs:
            QMessageBox.warning(
                self,
                tr("无法应用音符编辑"),
                tr("片段编辑不能同时提交转录路由。"),
            )
            return None
        try:
            if (
                clip_edit_fingerprint(track, request.arrangement_clip_id)
                != request.arrangement_clip_fingerprint
            ):
                raise ClipEditError(
                    "clip_stale",
                    "clip changed after the note editor was opened",
                )
            if tuple(clip_editor_notes(
                track, request.arrangement_clip_id
            )) == tuple(draft_notes):
                return TranscriptionEditorCommitReport(
                    project_changed=False
                )
            plan = plan_clip_note_edit(
                track,
                clip_id=request.arrangement_clip_id,
                notes=draft_notes,
            )
            self._publish_clip_plan(
                plan,
                "edit arrangement clip notes",
                reconcile_velocity=True,
            )
        except (TypeError, ValueError) as exc:
            error_text = str(exc)
            if isinstance(exc, ClipEditError):
                error_text = {
                    "clip_stale": tr(
                        "目标片段已在外部发生变化。请关闭并重新打开编辑器后再试。"
                    ),
                    "note_out_of_scope": tr(
                        "草稿中有音符超出当前片段的时间范围。请将音符移回片段内。"
                    ),
                    "clip_missing": tr("目标片段已不存在。"),
                    "invalid_timing": tr("草稿包含无效的音符时间。"),
                }.get(exc.code, error_text)
            QMessageBox.warning(
                self,
                tr("无法应用音符编辑"),
                trf("片段编辑无法安全应用：{error}", error=error_text),
            )
            return None
        return TranscriptionEditorCommitReport(project_changed=True)

    @staticmethod
    def _clip_update_matches_track(update, track) -> bool:
        return (
            tuple(track.notes) == tuple(update.notes)
            and tuple(track.performance_controls)
            == tuple(update.performance_controls)
            and tuple(track.bdo_source_note_records)
            == tuple(update.source_note_records)
            and track.bdo_source_group_index == update.source_group_index
            and track.clip_start_ms == update.clip_start_ms
            and track.clip_end_ms == update.clip_end_ms
            and tuple(track.arrangement_clips)
            == tuple(update.arrangement_clips)
        )

    def _synchronize_open_clip_editors(
        self,
        plan: ClipEditPlan,
        *,
        source_editor=None,
    ) -> None:
        updated_ids = {int(update.track_id) for update in plan.updates}
        tracks_by_id = {int(track.track_id): track for track in self.tracks}
        for editor in tuple(getattr(self, "_note_editors", {}).values()):
            clip_id = str(
                getattr(editor, "arrangement_clip_id", "") or ""
            )
            track_id = int(getattr(editor.track, "track_id", -1))
            if not clip_id or track_id not in updated_ids:
                continue
            track = tracks_by_id.get(track_id)
            if track is None:
                continue
            try:
                scope = clip_editor_scope(track, clip_id)
                notes = (
                    None
                    if editor is source_editor
                    else clip_editor_notes(track, clip_id)
                )
                editor.synchronize_clip_scope(scope, notes)
            except ClipEditError as exc:
                # A delete or overlap-merge can remove the exact Clip an
                # editor owns.  Do not leave a writable orphan dialog behind.
                if exc.code == "clip_missing":
                    editor.close()
                continue
            except (AttributeError, TypeError, ValueError):
                continue

    def _publish_clip_plan(
        self,
        plan: ClipEditPlan,
        reason: str,
        *,
        push_snapshot: bool = True,
        source_editor=None,
        reconcile_velocity: bool = False,
    ) -> None:
        tracks_by_id = {int(track.track_id): track for track in self.tracks}
        if any(update.track_id not in tracks_by_id for update in plan.updates):
            raise ValueError("clip target track is no longer available")
        self._stop_preview(reset_playhead=False)
        if push_snapshot:
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
            if reconcile_velocity:
                reconcile_track_game_velocity_records(track, track.notes)
        selected = tracks_by_id[plan.selected_track_id]
        self._select_track(selected)
        self.timeline.set_selected_clip(selected, plan.selected_clip_id)
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
        self._synchronize_open_clip_editors(
            plan, source_editor=source_editor
        )
        if push_snapshot:
            updated_ids = {int(update.track_id) for update in plan.updates}
            for editor in tuple(
                getattr(self, "_note_editors", {}).values()
            ):
                if int(editor.track.track_id) in updated_ids:
                    editor._clip_live_snapshot_pushed = False
        self._autosave_project(reason, immediate=True)

    def _ensure_clip_editor_project_snapshot(self, editor) -> None:
        if bool(getattr(editor, "_clip_live_snapshot_pushed", False)):
            return
        self._push_project_snapshot()
        editor._clip_live_snapshot_pushed = True

    def _sync_arrangement_clip_editor(
        self, editor, draft_notes
    ) -> bool:
        """Publish one completed piano-roll transaction immediately."""

        if editor not in getattr(self, "_note_editors", {}).values():
            return False
        track_id = int(editor.track.track_id)
        track = next((
            value for value in self.tracks
            if int(value.track_id) == track_id
        ), None)
        clip_id = str(getattr(editor, "arrangement_clip_id", "") or "")
        if track is None or not clip_id:
            return False
        try:
            if (
                clip_edit_fingerprint(track, clip_id)
                != str(editor.arrangement_clip_fingerprint or "")
            ):
                editor.synchronize_clip_scope(
                    clip_editor_scope(track, clip_id),
                    clip_editor_notes(track, clip_id),
                )
                self.show_toast(
                    tr("片段已从混音台同步；请继续编辑。"),
                    kind="warning",
                )
                return False
            plan = plan_clip_note_edit(
                track, clip_id=clip_id, notes=tuple(draft_notes)
            )
            if self._clip_update_matches_track(plan.updates[0], track):
                editor.synchronize_clip_scope(
                    clip_editor_scope(track, clip_id)
                )
                return True
            self._ensure_clip_editor_project_snapshot(editor)
            self._publish_clip_plan(
                plan,
                "live arrangement clip note edit",
                push_snapshot=False,
                source_editor=editor,
                reconcile_velocity=True,
            )
            return True
        except (AttributeError, TypeError, ValueError) as exc:
            self.show_toast(
                trf("无法实时同步片段：{error}", error=exc),
                kind="error",
            )
            return False

    def _resize_arrangement_clip_from_editor(
        self, editor, mode: str, value: float
    ) -> bool:
        track = next((
            item for item in self.tracks
            if int(item.track_id) == int(editor.track.track_id)
        ), None)
        clip_id = str(getattr(editor, "arrangement_clip_id", "") or "")
        if track is None or not clip_id:
            return False
        try:
            if clip_edit_fingerprint(track, clip_id) != str(
                editor.arrangement_clip_fingerprint or ""
            ):
                raise ClipEditError(
                    "clip_stale", "clip changed before boundary edit"
                )
            scope = clip_editor_scope(track, clip_id)
            start = (
                float(value)
                if mode == "resize_start"
                else scope.timeline_start_ms
            )
            end = (
                float(value)
                if mode == "resize_end"
                else scope.timeline_end_ms
            )
            plan = plan_clip_edit(
                track,
                mode=str(mode),
                new_start_ms=start,
                new_end_ms=end,
                clip_id=clip_id,
            )
            self._ensure_clip_editor_project_snapshot(editor)
            self._publish_clip_plan(
                plan,
                "live arrangement clip boundary edit",
                push_snapshot=False,
            )
            return True
        except (AttributeError, TypeError, ValueError) as exc:
            try:
                editor.synchronize_clip_scope(
                    clip_editor_scope(track, clip_id),
                    clip_editor_notes(track, clip_id),
                )
            except (AttributeError, TypeError, ValueError):
                pass
            message = (
                tr("片段边界不能越过已有音符。")
                if isinstance(exc, ClipEditError)
                and exc.code == "clip_resize_over_notes"
                else str(exc)
            )
            self.show_toast(
                trf("无法调整片段边界：{error}", error=message),
                kind="error",
            )
            return False

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

    def _copy_timeline_clip(self, track, clip_id: str) -> None:
        try:
            self._arrangement_clip_clipboard = copy_clip(track, clip_id)
        except (TypeError, ValueError) as exc:
            self.show_toast(trf("无法复制片段：{error}", error=exc), kind="error")
            return
        self.show_toast(tr("片段已复制"), kind="success")

    def _delete_timeline_clip(self, track, clip_id: str) -> None:
        try:
            plan = plan_clip_delete(track, clip_id=clip_id)
            self._publish_clip_plan(plan, "delete arrangement clip")
        except (TypeError, ValueError) as exc:
            self.show_toast(
                trf("无法删除片段：{error}", error=exc), kind="error"
            )
            return
        self.show_toast(tr("片段已删除"), kind="success")

    def _paste_timeline_clip(self, track, start_ms: float) -> None:
        if self._arrangement_clip_clipboard is None:
            self.show_toast(tr("没有可粘贴的片段"))
            return
        try:
            plan = plan_clip_paste(
                track,
                self._arrangement_clip_clipboard,
                start_ms=start_ms,
            )
            self._publish_clip_plan(plan, "paste arrangement clip")
        except (TypeError, ValueError) as exc:
            self.show_toast(trf("无法粘贴片段：{error}", error=exc), kind="error")
            return
        self.show_toast(tr("片段已粘贴"), kind="success")

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
        if "_open_note_editor" in getattr(self, "__dict__", {}):
            self._open_note_editor(track)
        else:
            self._open_clip_note_editor(track, plan.selected_clip_id)


__all__ = ["ArrangementClipHostMixin"]
