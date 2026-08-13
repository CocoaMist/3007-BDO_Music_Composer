"""Main-window host for explicit same-game-route track merging."""

from __future__ import annotations

from PySide6.QtWidgets import QInputDialog, QMessageBox

from bdo_music_composer.editor.game_score_model import serialized_game_instrument_id
from bdo_music_composer.editor.model_change import ModelChange
from bdo_music_composer.editor.track_merge import TrackMergePlan, plan_track_merge
from bdo_music_composer.ui.i18n import tr, trf


class TrackMergeHostMixin:
    def _merge_same_instrument_track(self, source) -> None:
        candidates = [
            track for track in self.tracks
            if track is not source
            and serialized_game_instrument_id(track)
            == serialized_game_instrument_id(source)
        ]
        if not candidates:
            self.show_toast(tr("没有可合并的同游戏乐器轨道"), kind="warning")
            return
        labels = [
            trf(
                "{name} · {count} 个音符 · #{track_id}",
                name=track.display_name,
                count=len(track.notes),
                track_id=track.track_id,
            )
            for track in candidates
        ]
        selected, accepted = QInputDialog.getItem(
            self,
            tr("合并同乐器轨道"),
            trf("选择要并入“{name}”的轨道：", name=source.display_name),
            labels,
            0,
            False,
        )
        if not accepted:
            return
        try:
            plan = plan_track_merge(source, candidates[labels.index(selected)])
        except (TypeError, ValueError):
            QMessageBox.warning(
                self,
                tr("无法合并轨道"),
                tr(
                    "两条轨道必须使用相同游戏乐器、游戏音高映射、音量和全部混音参数。可先统一同乐器音量和 FX。"
                ),
            )
            return
        if not self._confirm_track_merge(plan):
            return
        self._commit_track_merge_plan(plan)

    def _confirm_track_merge(self, plan: TrackMergePlan) -> bool:
        report = plan.report
        if report.has_overlap:
            detail = trf(
                "检测到 {regions} 个重叠区域，共 {duration:.0f} ms；涉及 {pairs} 对音块，其中同音高 {same_pitch} 对、完全重复 {duplicates} 个。合并不会自动删除或降音量：重叠可能造成叠音、突出的起音和更高复音占用，合并后会在时间轴高亮这些区域供你调节。",
                regions=len(report.overlap_regions),
                duration=report.overlap_duration_ms,
                pairs=report.overlap_pair_count,
                same_pitch=report.same_pitch_pair_count,
                duplicates=report.exact_duplicate_count,
            )
        else:
            detail = tr("未检测到两条轨道之间的重叠音块。")
        split = (
            trf(
                "合并后共 {count} 个音符；游戏导出仍是 1 个乐器组，内部会拆为 {tracks} 条承载音符轨道（另有格式要求的空尾轨）。",
                count=report.merged_note_count,
                tracks=report.physical_note_track_count,
            )
            if report.physical_note_track_count > 1
            else trf(
                "合并后共 {count} 个音符，并导出为 1 个游戏乐器组。",
                count=report.merged_note_count,
            )
        )
        answer = QMessageBox.warning(
            self,
            tr("确认合并轨道"),
            f"{detail}\n\n{split}\n\n{tr('该操作可撤销。')}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _commit_track_merge_plan(self, plan: TrackMergePlan) -> None:
        if not any(int(track.track_id) == plan.source_track_id for track in self.tracks):
            raise ValueError("merge source is no longer available")
        if not any(int(track.track_id) == plan.absorbed_track_id for track in self.tracks):
            raise ValueError("merge target is no longer available")
        self._stop_preview(reset_playhead=False)
        self._push_project_snapshot()
        next_tracks = []
        for track in self.tracks:
            track_id = int(track.track_id)
            if track_id == plan.absorbed_track_id:
                continue
            next_tracks.append(
                plan.merged_track if track_id == plan.source_track_id else track
            )
        self.tracks = next_tracks
        self._apply_workspace_change(ModelChange.structure())
        self._select_track(plan.merged_track)
        self.timeline.set_merge_overlap_regions(
            plan.source_track_id, plan.report.overlap_regions
        )
        if plan.report.overlap_regions:
            first = plan.report.overlap_regions[0]
            self.timeline.set_time_range(first.start_ms, first.end_ms)
        self._schedule_timeline_validation_refresh()
        self._autosave_project("merge same game instrument tracks", immediate=True)
        self.show_toast(
            trf(
                "轨道已合并；{count} 个重叠区域已标记",
                count=len(plan.report.overlap_regions),
            ),
            kind="warning" if plan.report.has_overlap else "success",
        )


__all__ = ["TrackMergeHostMixin"]
