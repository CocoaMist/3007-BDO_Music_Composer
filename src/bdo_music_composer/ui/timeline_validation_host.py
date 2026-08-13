"""Timeline presentation of structured export-validation issues."""

from __future__ import annotations

from bdo_music_composer.export.bdo_validation import localized_validation_message
from bdo_music_composer.editor.arrangement_clip import project_track_notes
from bdo_music_composer.ui.i18n import tr, trf


class TimelineValidationHostMixin:
    """Map current validator issues to lane badges and exact note markers."""

    def _schedule_timeline_validation_refresh(self) -> None:
        if hasattr(self, "timeline_validation_timer"):
            self.timeline_validation_timer.start()

    def _refresh_timeline_validation(self) -> None:
        if not hasattr(self, "timeline"):
            return
        if not self.tracks:
            self.timeline.set_validation_notices({})
            self._timeline_validation_toast_signature = ()
            return
        issues = self._validation_issues()
        errors = [item for item in issues if item.severity == "error"]
        merges = [item for item in issues if item.code == "tracks.merge"]
        tracks_by_id = {int(track.track_id): track for track in self.tracks}
        track_notices: dict[int, dict[str, list]] = {}
        for issue in issues:
            if issue.severity != "error" and issue.code != "tracks.merge":
                continue
            track_ids = {
                int(track_id) for track_id in issue.related_track_ids
            }
            if issue.track_id is not None:
                track_ids.add(int(issue.track_id))
            if not track_ids:
                continue
            category = "errors" if issue.severity == "error" else "attentions"
            message = localized_validation_message(
                issue,
                tr,
                format_translate=trf,
            )
            for track_id in track_ids:
                notice = track_notices.setdefault(
                    track_id,
                    {"errors": [], "attentions": [], "invalid_note_keys": []},
                )
                if message not in notice[category]:
                    notice[category].append(message)
                if (
                    issue.severity == "error"
                    and issue.track_id is not None
                    and int(issue.track_id) == track_id
                    and issue.note_indices
                ):
                    track = tracks_by_id.get(track_id)
                    if track is None:
                        continue
                    projected_notes = project_track_notes(track)
                    for note_index in issue.note_indices:
                        index = int(note_index)
                        if not 0 <= index < len(projected_notes):
                            continue
                        key = self.timeline._validation_note_key(
                            projected_notes[index]
                        )
                        if key not in notice["invalid_note_keys"]:
                            notice["invalid_note_keys"].append(key)
        self.timeline.set_validation_notices({
            track_id: {
                "errors": tuple(notice["errors"]),
                "attentions": tuple(notice["attentions"]),
                "invalid_note_keys": tuple(notice["invalid_note_keys"]),
            }
            for track_id, notice in track_notices.items()
        })
        if errors:
            text = trf(
                "发现 {count} 个导出错误；对应轨道已标红，可点击轨道标记查看。",
                count=len(errors),
            )
            toast_kind = "error"
            toast_signature: tuple[object, ...] = (
                "error",
                tuple(
                    (
                        issue.code,
                        issue.track_id,
                        issue.related_track_ids,
                        issue.message,
                    )
                    for issue in errors
                ),
            )
        elif merges:
            attention_track_count = sum(
                bool(notice["attentions"])
                for notice in track_notices.values()
            )
            text = trf(
                "{count} 条轨道使用相同乐器；已标为琥珀色，导出时会合并。",
                count=attention_track_count,
            )
            toast_kind = "warning"
            toast_signature = (
                "warning",
                tuple(
                    (issue.code, issue.related_track_ids, issue.message)
                    for issue in merges
                ),
            )
        else:
            self._timeline_validation_toast_signature = ()
            return
        if toast_signature == self._timeline_validation_toast_signature:
            return
        self._timeline_validation_toast_signature = toast_signature
        self.show_toast(
            text,
            kind=toast_kind,
            duration_ms=4600 if toast_kind == "error" else 3600,
        )


__all__ = ["TimelineValidationHostMixin"]
