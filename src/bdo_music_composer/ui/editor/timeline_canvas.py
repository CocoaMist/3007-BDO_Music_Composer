"""Packaged, visible-range-indexed multitrack timeline canvas."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QScrollBar, QWidget

from bdo_music_composer.editor.bdo_instrument_adaptation import instrument_editor_display_adaptations
from bdo_music_composer.ui.editor.bdo_instrument_lane_art_qt import (
    InstrumentLaneArtwork,
    instrument_header_background_rect,
    paint_instrument_header_background,
)
from bdo_midi.instruments import (
    localized_bdo_instrument_name,
    localized_bdo_instrument_names,
)
from bdo_music_composer.editor.editor_models import TrackState, note_name
from .editor_ui_helpers import (
    add_instrument_submenus,
    articulation_color,
)
from .timeline_velocity_curve_qt import TimelineVelocityCurveOverlay
from bdo_music_composer.ui.i18n import tr, trf, trv
from bdo_music_composer.editor.interval_index import IntervalIndex
from bdo_music_composer.editor.arrangement_clip import (
    MIN_CLIP_DURATION_MS,
    clip_by_id,
    clip_projected_note_bounds,
    project_track_notes,
    track_clips,
)
from bdo_music_composer.editor.pitch_transform import (
    PitchTransformPlan,
    track_uses_percussion_pitch_semantics,
)
from bdo_music_composer.editor.track_group import move_group_block
from bdo_music_composer.editor.timeline_markers import normalize_timeline_markers
from bdo_music_composer.editor.arrangement_snap import (
    ArrangementSnapResult,
    ArrangementSnapIndex,
    ArrangementSnapTarget,
    build_snap_index,
    snap_clip_start,
)
from bdo_music_composer.core.project_paths import ASSETS_DIR


TIMELINE_BACKGROUND_IMAGE = ASSETS_DIR / "ui" / "timeline_background_v2.png"
TIMELINE_BACKGROUND_OPACITY = 0.24


@dataclass(frozen=True, slots=True)
class _TimelineNoteOverviewBin:
    start: float
    end: float
    pitch_min: int
    pitch_max: int
    pitch_mask: int
    articulation_type: int


@dataclass(frozen=True, slots=True)
class _TimelineNoteOverviewLevel:
    bucket_count: int
    bins: tuple[_TimelineNoteOverviewBin, ...]
    starts: tuple[float, ...]
    max_span: float


@dataclass(frozen=True, slots=True)
class _ArrangementGroupView:
    group_id: str
    first_row: int
    last_row: int
    members: tuple[TrackState, ...]
    instrument_id: int
    color: str

    @property
    def count(self) -> int:
        return len(self.members)


@dataclass(frozen=True, slots=True)
class _TimelineTrackNoteIndex:
    intervals: IntervalIndex[object]
    clips: IntervalIndex[object]
    pitch_min: int
    pitch_max: int
    overview_levels: tuple[_TimelineNoteOverviewLevel, ...]


@dataclass(frozen=True, slots=True)
class TimelineClipEditRequest:
    source_track: TrackState
    target_track: TrackState
    mode: str
    new_start_ms: float
    new_end_ms: float
    clip_id: str


@dataclass(frozen=True, slots=True)
class TimelineClipSplitRequest:
    track: TrackState
    clip_id: str
    split_ms: float


class ReferenceAudioView(Protocol):
    audio_path: Path | None
    display_name: str
    project_end_ms: float
    volume_percent: int
    waveform: object
    waveform_loading: bool
    waveform_starts: object
    changed: object
    timeline_changed: object

    def audio_to_project(self, position_ms: float) -> float: ...
    def project_to_audio(self, position_ms: float) -> float: ...
    def project_position_ms(self) -> float: ...
    def choose_audio(self, parent: QWidget) -> None: ...
    def set_audio_path(self, path: Path | None) -> None: ...
    def set_position(self, position_ms: float) -> None: ...
    def set_volume_percent(self, value: int) -> None: ...


def _ui_bdo_instrument_name(instrument_id: int) -> str:
    return localized_bdo_instrument_name(int(instrument_id), tr)


def _ui_bdo_instrument_names() -> dict[int, str]:
    return localized_bdo_instrument_names(tr)


class TimelineCanvas(QWidget):
    changed = Signal()
    track_state_changed = Signal()
    game_volume_committed = Signal(object, int, int)
    instrument_changed = Signal(object, int)
    mixer_unify_requested = Signal(object)
    merge_track_requested = Signal(object)
    create_track_requested = Signal(int)
    move_track_requested = Signal(object, int)
    delete_track_requested = Signal(object)
    clear_solo_requested = Signal()
    unmute_all_requested = Signal()
    selected = Signal(object)
    effects_requested = Signal(object)
    pitch_requested = Signal(object)
    midi_tools_requested = Signal(object)
    velocity_base_requested = Signal(object)
    note_editor_requested = Signal(object)
    clip_note_editor_requested = Signal(object, str)
    seek_requested = Signal(float)
    time_range_changed = Signal(object)
    playhead_changed = Signal(float)
    velocity_curve_committed = Signal(object, object)
    clip_edit_requested = Signal(object)
    clip_create_requested = Signal(object, float)
    clip_split_requested = Signal(object)
    clip_copy_requested = Signal(object, str)
    clip_paste_requested = Signal(object, float)
    clip_delete_requested = Signal(object, str)
    marker_edit_requested = Signal(object)
    group_control_requested = Signal(object, str)
    TRACK_NOTE_QUERY_BLOCK_SIZE = 128
    TRACK_CLIP_QUERY_BLOCK_SIZE = 64
    GRID_MIN_TICK_SPACING_PX = 56.0
    MEASURE_BANDING_MIN_WIDTH_PX = 72.0
    EDIT_TAIL_MEASURES = 8
    EDIT_TAIL_MIN_MS = 10_000.0
    NOTE_OVERVIEW_BUCKET_PX = 3.0
    NOTE_OVERVIEW_LEVELS = (256,)
    KEYBOARD_SHORTCUT_HINT = (
        "上下键选择轨道；M 静音；S 独奏；F 打开效果；"
        "Enter 编辑音符；左右键调整轨道音量（Shift 5）"
    )

    def __init__(self) -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.tracks: list[TrackState] = []
        self._arrangement_group_counts: dict[str, int] = {}
        self._arrangement_groups: dict[str, _ArrangementGroupView] = {}
        self._arrangement_group_by_row: dict[int, _ArrangementGroupView] = {}
        self._selected_arrangement_group_id = ""
        self.timeline_markers: list[dict[str, object]] = []
        self._timeline_marker_times: tuple[float, ...] = ()
        self._marker_label_regions: list[tuple[QRectF, dict[str, object]]] = []
        self._marker_delete_regions: list[tuple[QRectF, dict[str, object]]] = []
        self.hit_regions: list[tuple[QRectF, str, object]] = []
        self.track_validation_notices: dict[int, dict[str, tuple]] = {}
        self._validation_hover_track_id: int | None = None
        self.reference_audio: ReferenceAudioView | None = None
        self.zoom_factor = 1.0
        self.view_start_ms = 0.0
        self.playhead_ms = 0.0
        self.bpm = 120
        self.time_sig = 4
        self.beat_origin_ms = 0.0
        self.buffer_progress = 0.0
        self.buffer_visible = False
        self.track_levels: dict[int, float] = {}
        self.grid_rect = QRectF()
        self.dragging_timeline = False
        self.last_drag_x = 0.0
        self.range_start_ms: float | None = None
        self.range_end_ms: float | None = None
        self._range_drag_anchor_ms: float | None = None
        self._range_drag_mode = ""
        self._range_drag_moved = False
        self._volume_drag_track: TrackState | None = None
        self._volume_drag_rect = QRectF()
        self._volume_drag_initial = 70
        self._clip_drag_source: TrackState | None = None
        self._clip_drag_target: TrackState | None = None
        self._clip_drag_mode = ""
        self._clip_drag_press_ms = 0.0
        self._clip_drag_press_pos = QPointF()
        self._clip_drag_origin_press_ms = 0.0
        self._clip_drag_origin_start_ms = 0.0
        self._clip_drag_origin_end_ms = 0.0
        self._clip_drag_start_ms = 0.0
        self._clip_drag_end_ms = 0.0
        self._clip_drag_occupied_start_ms: float | None = None
        self._clip_drag_occupied_end_ms: float | None = None
        self._clip_drag_id = ""
        self._selected_clip_id = ""
        self._selected_clip_track_id: int | None = None
        self.snap_enabled = True
        self._clip_snap_targets = ArrangementSnapIndex((), ())
        self._clip_snap_result = ArrangementSnapResult(0.0)
        self.arrangement_tool = "select"
        self._merge_overlap_track_id: int | None = None
        self._merge_overlap_regions: tuple[object, ...] = ()
        self.selected_track: TrackState | None = None
        self.pitch_transform_plan = PitchTransformPlan()
        self.conversion_transpose = 0
        self.background_pixmap = QPixmap(str(TIMELINE_BACKGROUND_IMAGE)) if TIMELINE_BACKGROUND_IMAGE.is_file() else QPixmap()
        self._scaled_background = QPixmap()
        self._scaled_background_size = QSize()
        self._instrument_adaptations = instrument_editor_display_adaptations()
        self.instrument_lane_art = InstrumentLaneArtwork()
        self.track_scroll = QScrollBar(Qt.Vertical, self)
        self.velocity_curve_overlay = TimelineVelocityCurveOverlay(self)
        self.velocity_curve_overlay.commit_requested.connect(
            self.velocity_curve_committed.emit
        )
        self._track_note_indexes: dict[int, _TimelineTrackNoteIndex] = {}
        self._last_track_note_query_inspections = 0
        self._last_track_clip_query_inspections = 0
        self._conversion_problem_cache: dict[tuple[object, ...], bool] = {}
        self._conversion_problem_masks: dict[tuple[object, ...], int] = {}
        self._timeline_end_cache = 1.0
        # The multitrack page is mostly static while playback advances.  Keep
        # notes, headers, artwork, text, grid and waveform in one device-local
        # pixmap so a narrow playhead update does not re-run every visible
        # interval query and every text/layout operation at audio-frame rate.
        self._static_timeline_cache = QPixmap()
        self._static_timeline_cache_key: tuple[object, ...] | None = None
        self._static_timeline_hit_regions: list[tuple[QRectF, str, object]] = []
        self._viewport_motion_active = False
        self._viewport_motion_timer = QTimer(self)
        self._viewport_motion_timer.setSingleShot(True)
        self._viewport_motion_timer.setInterval(140)
        self._viewport_motion_timer.timeout.connect(
            self._finish_viewport_motion
        )
        self.track_scroll.setObjectName("TimelineScroll")
        self.track_scroll.valueChanged.connect(self._track_scroll_changed)
        self.setObjectName("TimelineCanvas")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(tr("轨道时间轴"))
        self.setToolTip(tr(self.KEYBOARD_SHORTCUT_HINT))
        self.setStatusTip(tr(self.KEYBOARD_SHORTCUT_HINT))
        self._update_accessible_track_state()
        self.setMouseTracking(True)
        self.setMinimumHeight(380)

    def set_arrangement_tool(self, tool: str) -> None:
        normalized = str(tool or "select")
        if normalized not in {"select", "razor"}:
            normalized = "select"
        self.arrangement_tool = normalized
        self.unsetCursor()
        self.update()

    def set_instrument_art_dir(self, directory: str | Path | None) -> int:
        """Preload optional user artwork; painting remains filesystem-free."""

        loaded = self.instrument_lane_art.reload(
            directory,
            {
                instrument_id: adaptation.visual_key
                for instrument_id, adaptation
                in self._instrument_adaptations.items()
            },
        )
        self._static_timeline_cache_key = None
        self.update()
        return loaded

    def set_tracks(self, tracks: list[TrackState]) -> None:
        self.tracks = tracks
        self._rebuild_arrangement_group_views()
        self.clear_merge_overlap_regions()
        self.velocity_curve_overlay.synchronize_tracks(tracks)
        selected_track_is_current = any(
            track is self.selected_track for track in tracks
        )
        if not selected_track_is_current:
            self.selected_track = None
            self._selected_clip_id = ""
            self._selected_clip_track_id = None
        elif self._selected_clip_id:
            selected_clip_track = next((
                track for track in tracks
                if int(track.track_id) == self._selected_clip_track_id
            ), None)
            try:
                if selected_clip_track is None:
                    raise ValueError("selected Clip track is unavailable")
                clip_by_id(selected_clip_track, self._selected_clip_id)
            except ValueError:
                self._selected_clip_id = ""
                self._selected_clip_track_id = None
        valid_track_ids = {int(track.track_id) for track in tracks}
        self.track_validation_notices = {
            track_id: notice
            for track_id, notice in self.track_validation_notices.items()
            if track_id in valid_track_ids
        }
        self.track_levels = {
            track_id: level for track_id, level in self.track_levels.items()
            if track_id in valid_track_ids
        }
        self._rebuild_track_indexes()
        self.playhead_ms = min(self.playhead_ms, self._timeline_end_ms())
        self._clamp_view()
        self.setMinimumHeight(380)
        self._update_track_scrollbar()
        self._update_accessible_track_state()
        self.update()

    def _rebuild_arrangement_group_views(self) -> None:
        rows_by_group: dict[str, list[int]] = {}
        members_by_group: dict[str, list[TrackState]] = {}
        for row, track in enumerate(self.tracks):
            group_id = str(track.arrangement_group_id or "")
            if group_id:
                rows_by_group.setdefault(group_id, []).append(row)
                members_by_group.setdefault(group_id, []).append(track)
        groups: dict[str, _ArrangementGroupView] = {}
        by_row: dict[int, _ArrangementGroupView] = {}
        for group_id, rows in rows_by_group.items():
            members = tuple(members_by_group[group_id])
            if len(members) < 2:
                continue
            view = _ArrangementGroupView(
                group_id, rows[0], rows[-1], members,
                int(members[0].bdo_instrument_id), str(members[0].color),
            )
            groups[group_id] = view
            for row in rows:
                by_row[row] = view
        self._arrangement_groups = groups
        self._arrangement_group_by_row = by_row
        self._arrangement_group_counts = {
            group_id: view.count for group_id, view in groups.items()
        }
        if self._selected_arrangement_group_id not in groups:
            self._selected_arrangement_group_id = ""

    def set_timeline_markers(self, markers: object) -> None:
        self.timeline_markers = list(normalize_timeline_markers(markers))
        self._timeline_marker_times = tuple(
            float(marker["time_ms"]) for marker in self.timeline_markers
        )
        self.update()

    def set_snap_enabled(self, enabled: bool) -> None:
        self.snap_enabled = bool(enabled)

    def _snap_drag_time(
        self,
        proposed_ms: float,
        duration_ms: float,
        modifiers: Qt.KeyboardModifier,
    ) -> float:
        """Snap one drag edge using a stable screen-space tolerance."""

        proposed_ms = max(0.0, float(proposed_ms))
        if not self.snap_enabled or modifiers & Qt.AltModifier:
            self._clip_snap_result = ArrangementSnapResult(proposed_ms)
            return proposed_ms
        tolerance = min(
            160.0,
            max(
                1.0,
                self._visible_duration_ms()
                * 12.0
                / max(1.0, self.grid_rect.width()),
            ),
        )
        beat_ms = 60_000.0 / max(1, self.bpm)
        self._clip_snap_result = snap_clip_start(
            proposed_ms,
            max(0.0, float(duration_ms)),
            self._clip_snap_targets,
            tolerance_ms=tolerance,
            grid_ms=beat_ms / 4.0,
            grid_origin_ms=self.beat_origin_ms,
        )
        return self._clip_snap_result.start_ms

    def _update_clip_drag_geometry(
        self,
        pos: QPointF,
        modifiers: Qt.KeyboardModifier,
    ) -> None:
        """Recompute a clip gesture from its pointer-down geometry."""

        current_ms = self._time_at_x(pos.x())
        delta = current_ms - self._clip_drag_origin_press_ms
        if self._clip_drag_mode == "move":
            duration = (
                self._clip_drag_origin_end_ms
                - self._clip_drag_origin_start_ms
            )
            start = self._snap_drag_time(
                self._clip_drag_origin_start_ms + delta,
                duration,
                modifiers,
            )
            target = self._track_at_position(pos)
            if target is not None:
                self._clip_drag_target = target
            self._clip_drag_start_ms = start
            self._clip_drag_end_ms = start + duration
        elif self._clip_drag_mode == "resize_start":
            start = self._snap_drag_time(
                self._clip_drag_origin_start_ms + delta,
                0.0,
                modifiers,
            )
            self._clip_drag_start_ms = min(
                self._clip_drag_origin_end_ms - MIN_CLIP_DURATION_MS,
                (
                    self._clip_drag_occupied_start_ms
                    if self._clip_drag_occupied_start_ms is not None
                    else math.inf
                ),
                start,
            )
            self._clip_drag_end_ms = self._clip_drag_origin_end_ms
        elif self._clip_drag_mode == "resize_end":
            end = self._snap_drag_time(
                self._clip_drag_origin_end_ms + delta,
                0.0,
                modifiers,
            )
            self._clip_drag_start_ms = self._clip_drag_origin_start_ms
            self._clip_drag_end_ms = max(
                self._clip_drag_origin_start_ms + MIN_CLIP_DURATION_MS,
                (
                    self._clip_drag_occupied_end_ms
                    if self._clip_drag_occupied_end_ms is not None
                    else -math.inf
                ),
                end,
            )

    def _build_clip_snap_targets(
        self, source: TrackState, clip_id: str
    ) -> ArrangementSnapIndex:
        targets: list[ArrangementSnapTarget] = []
        for track in self.tracks:
            for clip in track_clips(track):
                if track is source and clip.clip_id == clip_id:
                    continue
                label = str(getattr(track, "display_name", "") or "")
                targets.extend((
                    ArrangementSnapTarget(clip.start_ms, "clip", label),
                    ArrangementSnapTarget(clip.end_ms, "clip", label),
                ))
        targets.extend(
            ArrangementSnapTarget(
                float(marker["time_ms"]), "marker", str(marker["label"])
            )
            for marker in self.timeline_markers
        )
        return build_snap_index(targets)

    def set_merge_overlap_regions(self, track_id: int, regions: object) -> None:
        """Highlight the last merge's review areas until the model changes."""

        self._merge_overlap_track_id = int(track_id)
        self._merge_overlap_regions = tuple(regions)
        self.update()

    def clear_merge_overlap_regions(self) -> None:
        self._merge_overlap_track_id = None
        self._merge_overlap_regions = ()

    def update_tracks(self, track_ids: object) -> None:
        """Rebuild only changed track indexes after a non-structural commit."""

        requested = {int(track_id) for track_id in track_ids}
        if not requested:
            return
        tracks_by_id = {int(track.track_id): track for track in self.tracks}
        missing = requested - tracks_by_id.keys()
        if missing:
            raise ValueError(f"unknown timeline track IDs: {sorted(missing)}")
        self.velocity_curve_overlay.synchronize_tracks(self.tracks)
        for track_id in requested:
            track = tracks_by_id[track_id]
            self._track_note_indexes[id(track)] = self._build_track_index(track)
        self._conversion_problem_cache.clear()
        self._conversion_problem_masks.clear()
        self._refresh_timeline_end_cache()
        self.playhead_ms = min(self.playhead_ms, self._timeline_end_ms())
        self._clamp_view()
        self._update_track_scrollbar()
        self._static_timeline_cache_key = None
        self.update()

    def update_track_presentation(self, track_ids: object) -> None:
        """Refresh mute/solo/color state without rebuilding note indexes."""

        requested = {int(track_id) for track_id in track_ids}
        valid = {int(track.track_id) for track in self.tracks}
        if not requested or not requested <= valid:
            return
        self._static_timeline_cache_key = None
        self._update_accessible_track_state()
        self.update()

    def set_validation_notices(
        self,
        notices: dict[int, dict[str, tuple]],
    ) -> None:
        """Apply export errors and non-blocking attention marks by track ID."""

        valid_track_ids = {int(track.track_id) for track in self.tracks}
        normalized: dict[int, dict[str, tuple]] = {}
        for raw_track_id, raw_notice in notices.items():
            track_id = int(raw_track_id)
            if track_id not in valid_track_ids:
                continue
            errors = tuple(
                str(message).strip()
                for message in raw_notice.get("errors", ())
                if str(message).strip()
            )
            attentions = tuple(
                str(message).strip()
                for message in raw_notice.get("attentions", ())
                if str(message).strip()
            )
            invalid_note_keys = tuple(
                tuple(value)
                for value in raw_notice.get("invalid_note_keys", ())
                if isinstance(value, (tuple, list)) and len(value) == 5
            )
            if errors or attentions or invalid_note_keys:
                normalized[track_id] = {
                    "errors": errors,
                    "attentions": attentions,
                    "invalid_note_keys": invalid_note_keys,
                }
        if normalized == self.track_validation_notices:
            return
        self.track_validation_notices = normalized
        self._conversion_problem_cache.clear()
        self._conversion_problem_masks.clear()
        self._static_timeline_cache_key = None
        self._validation_hover_track_id = None
        self.setToolTip(tr(self.KEYBOARD_SHORTCUT_HINT))
        self._update_accessible_track_state()
        self.update()

    def _track_validation_notice(
        self,
        track: TrackState,
    ) -> dict[str, tuple]:
        return self.track_validation_notices.get(
            int(track.track_id),
            {"errors": (), "attentions": (), "invalid_note_keys": ()},
        )

    def _track_validation_tooltip(self, track: TrackState) -> str:
        notice = self._track_validation_notice(track)
        sections: list[str] = []
        errors = notice["errors"]
        attentions = notice["attentions"]
        if errors:
            sections.append(
                tr("导出错误") + "\n" + "\n".join(
                    f"• {message}" for message in errors
                )
            )
        if attentions:
            sections.append(
                tr("需要注意") + "\n" + "\n".join(
                    f"• {message}" for message in attentions
                )
            )
        return "\n\n".join(sections)

    def _track_attention_accent(self, row: int) -> QColor:
        """Use an arrangement Group's identity color for its merge notice."""

        group = self._arrangement_group_by_row.get(int(row))
        return QColor(group.color if group is not None else "#d1a24d")

    def set_reference_audio(self, controller: "ReferenceAudioView") -> None:
        if self.reference_audio is controller:
            return
        if self.reference_audio is not None:
            try:
                self.reference_audio.changed.disconnect(self.update)
                self.reference_audio.timeline_changed.disconnect(self._reference_audio_updated)
            except (RuntimeError, TypeError):
                pass
        self.reference_audio = controller
        controller.changed.connect(self.update)
        controller.timeline_changed.connect(self._reference_audio_updated)
        self._reference_audio_updated()

    def _reference_audio_updated(self) -> None:
        # Reference alignment and waveform updates do not mutate editor
        # notes. Rebuilding every interval/overview index here made loading
        # or moving a reference audio file scale with the whole score.
        self._refresh_timeline_end_cache()
        self.playhead_ms = min(self.playhead_ms, self._timeline_end_ms())
        self._clamp_view()
        self._update_track_scrollbar()
        self.update()

    def _timeline_row_count(self) -> int:
        return len(self.tracks) + (1 if self.reference_audio is not None else 0)

    def _musical_track_count(self) -> int:
        """Return authored tracks without presentation-only reference lanes."""

        return len(self.tracks)

    def set_track_levels(self, levels: dict[int, float]) -> None:
        normalized = {
            int(track_id): max(0.0, min(1.0, float(level)))
            for track_id, level in levels.items()
        }
        if normalized == self.track_levels:
            return
        self.track_levels = normalized
        area, header_w, ruler_h, _lane_h = self._timeline_layout_metrics()
        self.update(QRectF(
            area.left() + header_w - 18,
            area.top() + ruler_h,
            18,
            max(0.0, area.height() - ruler_h),
        ).toAlignedRect())

    def _build_track_index(
        self,
        track: TrackState,
    ) -> _TimelineTrackNoteIndex:
        notes = project_track_notes(track)
        intervals = IntervalIndex.build(
            notes,
            start_of=lambda note: float(note.start),
            duration_of=lambda note: float(note.dur),
            block_size=self.TRACK_NOTE_QUERY_BLOCK_SIZE,
        )
        clips = IntervalIndex.build(
            track_clips(track),
            start_of=lambda clip: float(clip.start_ms),
            duration_of=lambda clip: float(clip.end_ms - clip.start_ms),
            block_size=self.TRACK_CLIP_QUERY_BLOCK_SIZE,
        )
        return _TimelineTrackNoteIndex(
            intervals=intervals,
            clips=clips,
            pitch_min=min(
                (int(note.pitch) for note in intervals.items),
                default=0,
            ),
            pitch_max=max(
                (int(note.pitch) for note in intervals.items),
                default=0,
            ),
            # Dense overview bins are only needed for tracks that are actually
            # painted. Building them lazily avoids blocking the workspace when
            # a large project contains many offscreen tracks.
            overview_levels=(),
        )

    def _rebuild_track_indexes(self) -> None:
        self._track_note_indexes = {}
        self._conversion_problem_cache.clear()
        self._conversion_problem_masks.clear()
        for track in self.tracks:
            self._track_note_indexes[id(track)] = self._build_track_index(track)
        self._refresh_timeline_end_cache()

    def _refresh_timeline_end_cache(self) -> None:
        timeline_end = max(
            1.0,
            max(
                (
                    index.intervals.maximum_end
                    for index in self._track_note_indexes.values()
                ),
                default=1.0,
            ),
        )
        timeline_end = max(
            timeline_end,
            max(
                (index.clips.maximum_end for index in self._track_note_indexes.values()),
                default=1.0,
            ),
        )
        if self.reference_audio is not None:
            timeline_end = max(timeline_end, self.reference_audio.project_end_ms)
        # A note-only project still needs blank musical space at its right
        # edge. Otherwise the last note becomes a hard boundary and users
        # cannot pan right to author the next phrase. A loaded reference with
        # known duration remains the authoritative timeline boundary.
        reference_duration = (
            self.reference_audio.duration_ms
            if self.reference_audio is not None
            else 0.0
        )
        if reference_duration <= 0.0:
            measure_ms = 60_000.0 / max(1, self.bpm) * max(1, self.time_sig)
            timeline_end += max(
                self.EDIT_TAIL_MIN_MS,
                measure_ms * self.EDIT_TAIL_MEASURES,
            )
        self._timeline_end_cache = timeline_end

    def _build_note_overview_levels(
        self,
        intervals: IntervalIndex[object],
    ) -> tuple[_TimelineNoteOverviewLevel, ...]:
        """Precompute bounded visual summaries for dense timeline zooms."""

        timeline_end = max(1.0, float(intervals.maximum_end))
        levels: list[_TimelineNoteOverviewLevel] = []
        for bucket_count in self.NOTE_OVERVIEW_LEVELS:
            starts = [float("inf")] * bucket_count
            ends = [float("-inf")] * bucket_count
            pitch_mins = [128] * bucket_count
            pitch_maxes = [-1] * bucket_count
            pitch_masks = [0] * bucket_count
            articulation_types = [0] * bucket_count
            for note, effective_end in zip(intervals.items, intervals.ends):
                start = float(note.start)
                end = float(effective_end)
                bucket = max(
                    0,
                    min(
                        bucket_count - 1,
                        int(start / timeline_end * bucket_count),
                    ),
                )
                pitch = int(note.pitch)
                ntype = int(getattr(note, "ntype", 0))
                starts[bucket] = min(starts[bucket], start)
                ends[bucket] = max(ends[bucket], end)
                pitch_mins[bucket] = min(pitch_mins[bucket], pitch)
                pitch_maxes[bucket] = max(pitch_maxes[bucket], pitch)
                pitch_masks[bucket] |= 1 << max(0, pitch)
                if ntype != 0 and articulation_types[bucket] == 0:
                    articulation_types[bucket] = ntype
            overview_bins = tuple(
                _TimelineNoteOverviewBin(
                    start=starts[bucket],
                    end=ends[bucket],
                    pitch_min=pitch_mins[bucket],
                    pitch_max=pitch_maxes[bucket],
                    pitch_mask=pitch_masks[bucket],
                    articulation_type=articulation_types[bucket],
                )
                for bucket in range(bucket_count)
                if pitch_maxes[bucket] >= 0
            )
            levels.append(
                _TimelineNoteOverviewLevel(
                    bucket_count=bucket_count,
                    bins=overview_bins,
                    starts=tuple(value.start for value in overview_bins),
                    max_span=max(
                        (value.end - value.start for value in overview_bins),
                        default=0.0,
                    ),
                )
            )
        return tuple(levels)

    def _visible_note_overview_bins(
        self,
        track: TrackState,
        visible_start: float,
        visible_duration: float,
        region_width: float,
    ) -> tuple[_TimelineNoteOverviewBin, ...]:
        index = self._track_note_indexes.get(id(track))
        if index is None:
            return ()
        if not index.overview_levels:
            index = _TimelineTrackNoteIndex(
                intervals=index.intervals,
                clips=index.clips,
                pitch_min=index.pitch_min,
                pitch_max=index.pitch_max,
                overview_levels=self._build_note_overview_levels(
                    index.intervals
                ),
            )
            self._track_note_indexes[id(track)] = index
        track_duration = max(1.0, float(index.intervals.maximum_end))
        desired_bucket_count = (
            track_duration / max(1.0, visible_duration)
            * max(1.0, region_width)
            / self.NOTE_OVERVIEW_BUCKET_PX
        )
        level = min(
            index.overview_levels,
            key=lambda value: abs(value.bucket_count - desired_bucket_count),
        )
        visible_end = visible_start + visible_duration
        lower = bisect_left(
            level.starts,
            visible_start - level.max_span,
        )
        upper = bisect_right(level.starts, visible_end)
        return tuple(
            value
            for value in level.bins[lower:upper]
            if value.end >= visible_start
        )

    def _visible_track_notes(self, track: TrackState, start: float, end: float) -> list:
        ordered, lo, hi = self._visible_track_note_window(track, start, end)
        if lo == 0 and hi == len(ordered):
            return ordered
        return ordered[lo:hi]

    def _visible_track_clips(
        self, track: TrackState, start: float, end: float,
    ) -> tuple[object, ...]:
        self._last_track_clip_query_inspections = 0
        index = self._track_note_indexes.get(id(track))
        if index is None:
            self._rebuild_track_indexes()
            index = self._track_note_indexes.get(id(track))
        if index is None:
            return ()
        result = index.clips.query_closed(start, end)
        self._last_track_clip_query_inspections = result.inspected_count
        return result.items

    def _visible_track_note_window(
        self, track: TrackState, start: float, end: float,
    ) -> tuple[list, int, int]:
        self._last_track_note_query_inspections = 0
        index = self._track_note_indexes.get(id(track))
        if index is None:
            self._rebuild_track_indexes()
            index = self._track_note_indexes.get(id(track))
        if index is None:
            return [], 0, 0
        result = index.intervals.query_closed(start, end)
        self._last_track_note_query_inspections = result.inspected_count
        visible = list(result.items)
        return visible, 0, len(visible)

    def _track_pitch_bounds(self, track: TrackState) -> tuple[int, int]:
        index = self._track_note_indexes.get(id(track))
        if index is None:
            self._rebuild_track_indexes()
            index = self._track_note_indexes.get(id(track))
        if index is None:
            return 0, 0
        return index.pitch_min, index.pitch_max

    def set_selected_track(self, track: TrackState | None) -> None:
        self._select_track(track, emit=False)

    def set_selected_clip(
        self, track: TrackState | None, clip_id: str = ""
    ) -> None:
        """Select one Clip without opening its note editor."""

        self._select_track(track, emit=False)
        if track is None or not clip_id:
            self._selected_clip_id = ""
            self._selected_clip_track_id = None
            self.update()
            return
        try:
            clip_by_id(track, clip_id)
        except ValueError:
            self._selected_clip_id = ""
            self._selected_clip_track_id = None
            self.update()
            return
        self._selected_clip_id = str(clip_id)
        self._selected_clip_track_id = int(track.track_id)
        self.update()

    def _select_track(
        self,
        track: TrackState | None,
        *,
        emit: bool,
    ) -> None:
        if (
            track is None
            or str(track.arrangement_group_id or "")
            != self._selected_arrangement_group_id
        ):
            self._selected_arrangement_group_id = ""
        self.selected_track = track
        if (
            track is None
            or self._selected_clip_track_id != int(track.track_id)
        ):
            self._selected_clip_id = ""
            self._selected_clip_track_id = None
        self.velocity_curve_overlay.selected_track_changed(track)
        if emit and track is not None:
            self.selected.emit(track)
        self._ensure_selected_track_visible()
        self._update_accessible_track_state()
        self.update()

    def _selected_track_index(self) -> int | None:
        return next(
            (
                index
                for index, track in enumerate(self.tracks)
                if track is self.selected_track
            ),
            None,
        )

    def _ensure_selected_track_visible(self) -> None:
        index = self._selected_track_index()
        if index is None or not self.track_scroll.isVisible():
            return
        lane_height = self._lane_height()
        top = index * lane_height
        bottom = top + lane_height
        current = self.track_scroll.value()
        page = max(lane_height, self.track_scroll.pageStep())
        if top < current:
            self.track_scroll.setValue(top)
        elif bottom > current + page:
            self.track_scroll.setValue(bottom - page)

    def _update_accessible_track_state(self) -> None:
        track = self.selected_track
        if track is None:
            self.setAccessibleDescription(tr(self.KEYBOARD_SHORTCUT_HINT))
            return
        validation_description = self._track_validation_tooltip(track)
        self.setAccessibleDescription(
            trf(
                "当前轨道：{track}；音量 {volume}。{shortcuts}",
                track=str(track.display_name),
                volume=int(track.bdo_track_volume),
                shortcuts=trv(self.KEYBOARD_SHORTCUT_HINT),
            )
            + (
                "\n" + validation_description
                if validation_description
                else ""
            )
        )

    def set_conversion_transpose(self, semitones: int) -> None:
        self.set_pitch_transform_plan(
            self.pitch_transform_plan.with_global(semitones)
        )

    def set_pitch_transform_plan(self, plan: PitchTransformPlan) -> None:
        if plan == self.pitch_transform_plan:
            return
        self.pitch_transform_plan = plan
        self.conversion_transpose = plan.global_semitones
        self._conversion_problem_cache.clear()
        self._conversion_problem_masks.clear()
        self.update()

    def set_musical_grid(
        self,
        bpm: int,
        time_sig: int,
        beat_origin_ms: float,
    ) -> None:
        values = (
            max(1, int(bpm)),
            max(1, int(time_sig)),
            float(beat_origin_ms),
        )
        if values == (self.bpm, self.time_sig, self.beat_origin_ms):
            return
        self.bpm, self.time_sig, self.beat_origin_ms = values
        self._refresh_timeline_end_cache()
        self.playhead_ms = min(self.playhead_ms, self._timeline_end_ms())
        self._clamp_view()
        self._update_track_scrollbar()
        self.update()

    def _visible_musical_ticks(
        self,
        visible_start: float,
        visible_duration: float,
        grid_width: float,
    ) -> list[tuple[float, bool, str]]:
        beat_ms = 60000.0 / max(1, self.bpm)
        measure_ms = beat_ms * max(1, self.time_sig)
        beat_pixels = grid_width * beat_ms / max(1.0, visible_duration)
        factor = 1
        while beat_pixels * factor < self.GRID_MIN_TICK_SPACING_PX:
            factor *= 2
        step_ms = beat_ms * factor
        first = self.beat_origin_ms + math.floor(
            (visible_start - self.beat_origin_ms) / step_ms
        ) * step_ms
        end = visible_start + visible_duration
        ticks: list[tuple[float, bool, str]] = []
        value = first
        for _index in range(514):
            if value > end + step_ms:
                break
            measure_position = (
                (value - self.beat_origin_ms) / measure_ms
            )
            nearest_measure = round(measure_position)
            is_major = abs(measure_position - nearest_measure) < 1e-4
            label = (
                str(nearest_measure + 1)
                if is_major
                else ""
            )
            ticks.append((value, is_major, label))
            value += step_ms
        return ticks

    def _show_measure_banding(
        self,
        visible_duration: float,
        grid_width: float,
    ) -> bool:
        measure_ms = (
            60000.0 / max(1, self.bpm) * max(1, self.time_sig)
        )
        measure_width = grid_width * measure_ms / max(1.0, visible_duration)
        return measure_width >= self.MEASURE_BANDING_MIN_WIDTH_PX

    @staticmethod
    def _validation_note_key(note: object) -> tuple[object, ...]:
        return (
            int(getattr(note, "pitch")),
            int(getattr(note, "vel")),
            float(getattr(note, "start")),
            float(getattr(note, "dur")),
            int(getattr(note, "ntype")),
        )

    def _note_has_conversion_problem(
        self,
        track: TrackState,
        note: object,
    ) -> bool:
        invalid_keys = self._track_validation_notice(track).get(
            "invalid_note_keys",
            (),
        )
        if isinstance(note, int):
            return any(int(key[0]) == int(note) for key in invalid_keys)
        return self._validation_note_key(note) in invalid_keys

    def _conversion_problem_mask(self, track: TrackState) -> int:
        mask = 0
        for key in self._track_validation_notice(track).get(
            "invalid_note_keys",
            (),
        ):
            pitch = int(key[0])
            if 0 <= pitch < 128:
                mask |= 1 << pitch
        return mask

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_scaled_background()
        self._update_track_scrollbar()

    def _refresh_scaled_background(self) -> None:
        if self.background_pixmap.isNull() or self.size().isEmpty():
            self._scaled_background = QPixmap()
            self._scaled_background_size = QSize()
            return
        if self._scaled_background_size == self.size():
            return
        self._scaled_background = self.background_pixmap.scaled(
            self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation,
        )
        self._scaled_background_size = self.size()

    def _lane_height(self) -> int:
        return 68

    def _visible_track_row_range(self, grid_height: float) -> tuple[int, int]:
        lane_height = self._lane_height()
        scroll_y = self.track_scroll.value() if self.track_scroll.isVisible() else 0
        first_row = max(0, int(scroll_y // lane_height))
        last_row = min(
            len(self.tracks),
            int(math.ceil((scroll_y + grid_height) / lane_height)) + 1,
        )
        return first_row, last_row

    def _timeline_layout_metrics(self) -> tuple[QRectF, int, int, int]:
        # The workspace itself supplies separation from the fixed bars.  Keep
        # the painted track grid full-bleed inside it—no extra canvas gutter.
        area = QRectF(self.rect())
        # Keep the left column compact; pitch-range detail belongs in the
        # inspector/conversion check rather than competing with row controls.
        header_w = 296
        ruler_h = 34
        lane_h = self._lane_height()
        return area, header_w, ruler_h, lane_h

    def _reference_audio_lane_height(self) -> int:
        controller = self.reference_audio
        if controller is None:
            return 0
        if controller.audio_path or controller.waveform_loading:
            return self._lane_height()
        return 34

    def _update_track_scrollbar(self) -> None:
        if not hasattr(self, "track_scroll"):
            return
        area, _header_w, ruler_h, lane_h = self._timeline_layout_metrics()
        grid_top = area.top() + ruler_h
        grid_h = max(80, area.bottom() - grid_top)
        instrument_view_h = max(
            0,
            grid_h - self._reference_audio_lane_height(),
        )
        content_h = lane_h * len(self.tracks)
        max_scroll = max(0, content_h - instrument_view_h)
        scrollbar_width = 12
        self.track_scroll.setGeometry(
            int(area.right() - scrollbar_width),
            int(grid_top),
            scrollbar_width,
            int(instrument_view_h),
        )
        self.track_scroll.setRange(0, int(max_scroll))
        self.track_scroll.setPageStep(int(instrument_view_h))
        self.track_scroll.setSingleStep(lane_h)
        self.track_scroll.setVisible(max_scroll > 0)

    def set_playhead(self, ms: float, follow: bool = False) -> None:
        old_rect = self._playhead_update_rect(self.playhead_ms)
        old_view_start = self.view_start_ms
        old_playhead = self.playhead_ms
        self.playhead_ms = max(0.0, min(float(ms), self._timeline_end_ms()))
        if follow:
            visible_duration = self._visible_duration_ms()
            if self.playhead_ms < self.view_start_ms or self.playhead_ms > self.view_start_ms + visible_duration * 0.92:
                self.view_start_ms = self.playhead_ms - visible_duration * 0.18
                self._clamp_view()
        if self.view_start_ms != old_view_start:
            self.update()
            if not math.isclose(old_playhead, self.playhead_ms, abs_tol=0.25):
                self.playhead_changed.emit(self.playhead_ms)
            return
        new_rect = self._playhead_update_rect(self.playhead_ms)
        if old_rect is not None:
            self.update(old_rect)
        if new_rect is not None:
            self.update(new_rect)
        if not math.isclose(old_playhead, self.playhead_ms, abs_tol=0.25):
            self.playhead_changed.emit(self.playhead_ms)

    @property
    def time_range(self) -> tuple[float, float] | None:
        if self.range_start_ms is None or self.range_end_ms is None:
            return None
        return (
            min(self.range_start_ms, self.range_end_ms),
            max(self.range_start_ms, self.range_end_ms),
        )

    def set_time_range(
        self,
        start_ms: float | None,
        end_ms: float | None,
        *,
        notify: bool = False,
    ) -> None:
        if start_ms is None or end_ms is None:
            changed = self.time_range is not None
            self.range_start_ms = None
            self.range_end_ms = None
        else:
            start = max(0.0, min(float(start_ms), self._timeline_end_ms()))
            end = max(0.0, min(float(end_ms), self._timeline_end_ms()))
            changed = self.time_range != (min(start, end), max(start, end))
            self.range_start_ms = min(start, end)
            self.range_end_ms = max(start, end)
        if changed:
            self.update()
            if notify:
                self.time_range_changed.emit(self.time_range)

    def _playhead_update_rect(self, position_ms: float):
        visible_duration = self._visible_duration_ms()
        if not self.view_start_ms <= position_ms <= self.view_start_ms + visible_duration:
            return None
        area, header_w, _ruler_h, _lane_h = self._timeline_layout_metrics()
        scrollbar_w = 14 if self.track_scroll.isVisible() else 0
        grid_w = max(120.0, area.width() - header_w - scrollbar_w)
        x = area.left() + header_w + (
            (position_ms - self.view_start_ms) / visible_duration
        ) * grid_w
        return QRectF(x - 9.0, area.top(), 19.0, area.height()).toAlignedRect()

    def set_buffer_progress(self, progress: float, visible: bool = True) -> None:
        progress = max(0.0, min(1.0, float(progress)))
        if self.buffer_progress == progress and self.buffer_visible == bool(visible):
            return
        self.buffer_progress = progress
        self.buffer_visible = bool(visible)
        self.update()

    def set_zoom_percent(self, value: int) -> None:
        new_zoom = max(0.25, min(32.0, value / 100.0))
        if math.isclose(new_zoom, self.zoom_factor):
            return
        old_duration = self._visible_duration_ms()
        center = self.view_start_ms + old_duration / 2
        self.zoom_factor = new_zoom
        self.view_start_ms = center - self._visible_duration_ms() / 2
        self._clamp_view()
        self._begin_viewport_motion()
        self.update()
        self.changed.emit()

    def set_pan_percent(self, value: int) -> None:
        max_start = max(0.0, self._timeline_end_ms() - self._visible_duration_ms())
        new_start = max_start * max(0, min(1000, value)) / 1000.0
        if math.isclose(new_start, self.view_start_ms, abs_tol=0.5):
            return
        self.view_start_ms = new_start
        self._clamp_view()
        self._begin_viewport_motion()
        self.update()
        self.changed.emit()

    def pan_percent(self) -> int:
        max_start = max(0.0, self._timeline_end_ms() - self._visible_duration_ms())
        if max_start <= 0:
            return 0
        return round(self.view_start_ms / max_start * 1000)

    def _track_scroll_changed(self, _value: int) -> None:
        self._begin_viewport_motion()
        self.update()

    def _begin_viewport_motion(self) -> None:
        self._viewport_motion_active = True
        self._viewport_motion_timer.start()

    def _finish_viewport_motion(self) -> None:
        if not self._viewport_motion_active:
            return
        self._viewport_motion_active = False
        self.update()

    def _timeline_end_ms(self) -> float:
        return self._timeline_end_cache

    def _visible_duration_ms(self) -> float:
        return max(1.0, self._timeline_end_ms() / self.zoom_factor)

    def _clamp_view(self) -> None:
        max_start = max(0.0, self._timeline_end_ms() - self._visible_duration_ms())
        self.view_start_ms = max(0.0, min(self.view_start_ms, max_start))

    def _paint_canvas_background(self, painter: QPainter) -> None:
        painter.fillRect(self.rect(), QColor("#1c1c1e"))
        if self.background_pixmap.isNull():
            return
        self._refresh_scaled_background()
        target = QRectF(self.rect())
        x = (self.width() - self._scaled_background.width()) / 2
        y = (self.height() - self._scaled_background.height()) / 2
        painter.save()
        painter.setOpacity(TIMELINE_BACKGROUND_OPACITY)
        painter.drawPixmap(int(x), int(y), self._scaled_background)
        painter.restore()
        painter.fillRect(target, QColor(17, 17, 18, 112))

    def _paint_timeline_shell(
        self,
        painter: QPainter,
        area: QRectF,
        header_w: int,
        ruler_h: int,
        grid_w: float,
        grid_h: float,
    ) -> tuple[float, float, float, float]:
        left = area.left()
        top = area.top()
        grid_left = left + header_w
        grid_top = top + ruler_h
        painter.fillRect(QRectF(left, top, area.width(), ruler_h), QColor(44, 44, 48, 236))
        timeline_clip = QRectF(grid_left, grid_top, grid_w, grid_h)
        painter.fillRect(QRectF(left, grid_top, header_w, grid_h), QColor(36, 36, 39, 226))
        painter.fillRect(timeline_clip, QColor(28, 28, 30, 204))
        painter.setPen(QPen(QColor("#735b2d"), 1))
        painter.drawLine(grid_left, top, grid_left, area.bottom())
        painter.drawLine(left, grid_top, area.right(), grid_top)
        return left, top, grid_left, grid_top

    def _paint_grid_ruler(
        self,
        painter: QPainter,
        left: float,
        top: float,
        grid_left: float,
        grid_top: float,
        grid_w: float,
        grid_h: float,
        visible_start: float,
        visible_duration: float,
    ) -> int:
        measure_ms = (
            60000.0 / max(1, self.bpm) * max(1, self.time_sig)
        )
        first_measure = self.beat_origin_ms + math.floor(
            (visible_start - self.beat_origin_ms) / measure_ms
        ) * measure_ms
        measure = first_measure
        measure_index = math.floor(
            (measure - self.beat_origin_ms) / measure_ms
        )
        visible_end = visible_start + visible_duration
        if self._show_measure_banding(visible_duration, grid_w):
            while measure <= visible_end + measure_ms:
                next_measure = measure + measure_ms
                # One very light band every two measures gives orientation
                # without placing a dark stripe behind every bar.
                if measure_index % 2:
                    left_x = grid_left + (
                        (measure - visible_start) / visible_duration
                    ) * grid_w
                    right_x = grid_left + (
                        (next_measure - visible_start) / visible_duration
                    ) * grid_w
                    painter.fillRect(
                        QRectF(
                            left_x,
                            grid_top,
                            right_x - left_x,
                            grid_h,
                        ),
                        QColor(138, 112, 67, 10),
                    )
                measure = next_measure
                measure_index += 1
        ticks = self._visible_musical_ticks(
            visible_start,
            visible_duration,
            grid_w,
        )
        for value, is_major, label in ticks:
            x = grid_left + (
                (value - visible_start) / visible_duration
            ) * grid_w
            painter.setPen(
                QPen(
                    QColor(74, 62, 43, 176)
                    if is_major
                    else QColor(49, 49, 53, 132),
                    1,
                )
            )
            painter.drawLine(int(x), grid_top, int(x), grid_top + grid_h)
            if label:
                painter.setPen(QColor("#d3bea0" if is_major else "#7e705e"))
                painter.drawText(int(x + 6), top + 22, label)
        painter.setPen(QColor("#ffedd4"))
        painter.drawText(left + 10, top + 22, tr("轨道"))
        return len(ticks)

    def _paint_playhead(
        self,
        painter: QPainter,
        top: float,
        grid_left: float,
        grid_top: float,
        grid_w: float,
        grid_h: float,
        visible_start: float,
        visible_duration: float,
        visible_end: float,
        height: float,
    ) -> float | None:
        if visible_start <= self.playhead_ms <= visible_end:
            play_x = grid_left + ((self.playhead_ms - visible_start) / visible_duration) * grid_w
            painter.fillRect(QRectF(play_x, grid_top, 2, height), QColor("#f5a524"))
            marker = QPainterPath()
            marker.moveTo(play_x - 5, top + 1)
            marker.lineTo(play_x + 7, top + 1)
            marker.lineTo(play_x + 1, top + 9)
            marker.closeSubpath()
            painter.fillPath(marker, QColor("#f5a524"))
            return play_x
        return None

    def _paint_time_range(
        self,
        painter: QPainter,
        top: float,
        grid_left: float,
        grid_top: float,
        grid_w: float,
        grid_h: float,
        visible_start: float,
        visible_duration: float,
        visible_end: float,
    ) -> None:
        selected = self.time_range
        if selected is None:
            return
        start, end = selected
        if end < visible_start or start > visible_end:
            return
        left_ms = max(start, visible_start)
        right_ms = min(end, visible_end)
        left_x = grid_left + (
            (left_ms - visible_start) / visible_duration
        ) * grid_w
        right_x = grid_left + (
            (right_ms - visible_start) / visible_duration
        ) * grid_w
        painter.fillRect(
            QRectF(left_x, grid_top, max(1.0, right_x - left_x), grid_h),
            QColor(85, 196, 186, 22),
        )
        for value in (start, end):
            if visible_start <= value <= visible_end:
                x = grid_left + (
                    (value - visible_start) / visible_duration
                ) * grid_w
                painter.fillRect(
                    QRectF(x - 1.0, top, 2.0, grid_h + (grid_top - top)),
                    QColor("#55c4ba"),
                )

    def _paint_arrangement_group_marker(
        self, painter: QPainter, track: TrackState, row: int, left: float,
        grid_left: float, grid_w: float, y: float, lane_h: int,
        has_validation_notice: bool,
    ) -> None:
        group = self._arrangement_group_by_row.get(row)
        if group is None:
            return
        selected = group.group_id == self._selected_arrangement_group_id
        group_color = QColor(group.color)
        group_color.setAlpha(215 if selected else 132)
        tint = QColor(group.color)
        tint.setAlpha(22 if selected else 10)
        painter.fillRect(QRectF(left, y, grid_left - left, lane_h), tint)
        if row == group.first_row:
            painter.fillRect(
                QRectF(left, y, grid_left + grid_w - left, 2.0 if selected else 1.0),
                group_color,
            )
            control = QRectF(left + 8.0, y + 36.0, 132.0, 24.0)
            control_fill = QColor(group.color)
            control_fill.setAlpha(70 if selected else 38)
            painter.setBrush(control_fill)
            painter.setPen(QPen(group_color, 1))
            painter.drawRoundedRect(control, 5.0, 5.0)
            icon_left = control.left() + 7.0
            for offset, width in ((0.0, 12.0), (4.0, 9.0), (8.0, 6.0)):
                painter.fillRect(
                    QRectF(icon_left, control.top() + 6.0 + offset, width, 2.0),
                    QColor("#e8d7b6"),
                )
            group_font = painter.font()
            group_font.setPointSize(max(7, group_font.pointSize() - 1))
            group_font.setBold(True)
            painter.save()
            painter.setFont(group_font)
            painter.setPen(QColor("#e6ddd0"))
            painter.drawText(
                QRectF(control.left() + 23.0, control.top(), 63.0, control.height()),
                Qt.AlignLeft | Qt.AlignVCenter,
                trf("乐器组 ×{count}", count=group.count),
            )
            painter.restore()
            mute_rect = QRectF(control.right() - 43.0, control.top() + 2.0, 20.0, 20.0)
            solo_rect = QRectF(control.right() - 22.0, control.top() + 2.0, 20.0, 20.0)
            for label, action, rect, checked in (
                ("M", "group_mute", mute_rect, all(item.muted for item in group.members)),
                ("S", "group_solo", solo_rect, all(item.solo for item in group.members)),
            ):
                painter.fillRect(rect, QColor("#6b5228" if checked else "#272529"))
                painter.setPen(QColor("#f0d887" if checked else "#b4a486"))
                painter.drawText(rect, Qt.AlignCenter, label)
                self.hit_regions.append((rect, action, track))
            self.hit_regions.append((control.adjusted(0, 0, -44, 0), "group_select", track))
        if selected:
            painter.fillRect(QRectF(left, y, 3.0, lane_h), group_color)
        if row == group.last_row:
            painter.fillRect(
                QRectF(
                    left, y + lane_h - (2.0 if selected else 1.0),
                    grid_left + grid_w - left, 2.0 if selected else 1.0,
                ),
                group_color,
            )

    def _is_arrangement_group_start(self, row: int, track: TrackState) -> bool:
        group = self._arrangement_group_by_row.get(row)
        return group is not None and row == group.first_row

    def _paint_track_rows(
        self,
        painter: QPainter,
        left: float,
        grid_left: float,
        grid_top: float,
        header_w: int,
        grid_w: float,
        grid_h: float,
        lane_h: int,
        visible_start: float,
        visible_duration: float,
        visible_end: float,
        *,
        paint_meters: bool = True,
        paint_selected_velocity: bool = True,
        paint_reference_position: bool = True,
    ) -> None:
        any_solo = any(track.solo for track in self.tracks)
        scroll_y = self.track_scroll.value() if self.track_scroll.isVisible() else 0
        instrument_grid_h = max(
            0.0,
            grid_h - self._reference_audio_lane_height(),
        )
        first_row, last_row = self._visible_track_row_range(instrument_grid_h)
        painter.save()
        painter.setClipRect(QRectF(left, grid_top, header_w + grid_w, instrument_grid_h))
        for row in range(first_row, last_row):
            track = self.tracks[row]
            y = grid_top + row * lane_h - scroll_y
            group_start = self._is_arrangement_group_start(row, track)
            active = not track.muted and (not any_solo or track.solo)
            focused = track is self.selected_track
            validation_notice = self._track_validation_notice(track)
            validation_errors = validation_notice["errors"]
            validation_attentions = validation_notice["attentions"]
            has_validation_notice = bool(
                validation_errors or validation_attentions
            )
            lane_color = QColor(38, 38, 41, 188) if row % 2 else QColor(32, 32, 35, 184)
            if not active:
                lane_color = QColor(27, 27, 29, 204)
            if focused:
                lane_color = QColor(46, 50, 38, 214) if active else QColor(35, 36, 32, 212)
            painter.setBrush(lane_color)
            painter.setPen(Qt.NoPen)
            painter.drawRect(QRectF(grid_left, y, grid_w, lane_h))
            painter.fillRect(
                QRectF(left, y, header_w, lane_h),
                QColor(61, 67, 46, 226) if focused else (QColor(44, 44, 48, 220) if active else QColor(34, 34, 37, 222)),
            )
            if focused:
                painter.setPen(
                    QPen(
                        QColor("#d6b867" if self.hasFocus() else "#9b804a"),
                        2 if self.hasFocus() else 1,
                    )
                )
                painter.drawRect(QRectF(left + 0.5, y + 0.5, header_w + grid_w - 1, lane_h - 1))
            painter.setPen(QPen(QColor("#3b3b3f"), 1))
            painter.drawLine(left, y + lane_h - 1, grid_left + grid_w, y + lane_h - 1)

            self.hit_regions.append((QRectF(left, y, header_w + grid_w, lane_h), "lane", track))
            row_rect = QRectF(left, y, header_w, lane_h)
            self.hit_regions.append((row_rect, "select", track))

            adaptation = self._instrument_adaptations.get(
                int(track.bdo_instrument_id)
            )
            header_background_rect = instrument_header_background_rect(
                row_rect
            )
            if adaptation is not None and not header_background_rect.isEmpty():
                paint_instrument_header_background(
                    painter,
                    header_background_rect,
                    visual_key=adaptation.visual_key,
                    accent=QColor(track.color),
                    pixmap=self.instrument_lane_art.pixmap_for(
                        int(track.bdo_instrument_id)
                    ),
                    active=active,
                )

            # One lane has one visible severity. Export blockers always win;
            # details remain available in the lane tooltip.
            if validation_errors:
                painter.fillRect(
                    QRectF(left, y, header_w, lane_h),
                    QColor(164, 54, 48, 27),
                )
                painter.fillRect(
                    QRectF(left, y, 5.0, lane_h),
                    QColor("#d9635d"),
                )
            elif validation_attentions:
                attention_accent = self._track_attention_accent(row)
                attention_tint = QColor(attention_accent)
                attention_tint.setAlpha(24)
                painter.fillRect(
                    QRectF(left, y, header_w, lane_h),
                    attention_tint,
                )
                attention_accent.setAlpha(255)
                painter.fillRect(
                    QRectF(left, y, 5.0, lane_h),
                    attention_accent,
                )
            else:
                track_identity_color = QColor(
                    track.color if active else "#4a4743"
                )
                painter.fillRect(
                    QRectF(left, y, 3.0, lane_h),
                    track_identity_color,
                )
            validation_badges: list[tuple[str, QColor, float]] = []
            if validation_errors:
                validation_badges.append(
                    ("!", QColor("#d9635d"), y + 7.0)
                )
            elif validation_attentions:
                validation_badges.append(
                    ("=", self._track_attention_accent(row), y + 7.0)
                )
            for marker, accent, badge_y in validation_badges:
                badge_rect = QRectF(left + 8.0, badge_y, 18.0, 18.0)
                badge_fill = QColor(accent)
                badge_fill.setAlpha(42)
                painter.setBrush(badge_fill)
                painter.setPen(QPen(accent, 1))
                painter.drawRoundedRect(badge_rect, 4.0, 4.0)
                badge_font = painter.font()
                badge_font.setPointSize(max(7, badge_font.pointSize() - 1))
                badge_font.setBold(True)
                painter.save()
                painter.setFont(badge_font)
                painter.setPen(QColor("#fff1dc"))
                painter.drawText(badge_rect, Qt.AlignCenter, marker)
                painter.restore()

            controls = [
                ("M", "mute", 26),
                ("S", "solo", 26),
                ("FX", "fx", 28),
            ]
            control_gap = 4.0
            controls_width = sum(width for _label, _action, width in controls)
            controls_width += control_gap * max(0, len(controls) - 1)
            control_x = left + header_w - 20.0 - controls_width
            control_y = y + 8.0
            for label, action, width in controls:
                rect = QRectF(control_x, control_y, width, 24)
                checked = (action == "mute" and track.muted) or (action == "solo" and track.solo)
                painter.fillRect(rect, QColor("#5c4a28" if checked else "#242427"))
                painter.setPen(QPen(QColor("#caa24f" if checked else "#4b4b50"), 1))
                painter.drawRect(rect)
                painter.setPen(QColor("#ffedd4" if active else "#837a6f"))
                painter.drawText(rect, Qt.AlignCenter, label)
                self.hit_regions.append((rect, action, track))
                control_x += width + control_gap

            # This is the game's track-volume field, not the separate note-
            # velocity scale.  The official authoring UI clamps edits to
            # 0..100 (default 70), although imported score bytes may be above
            # 100.  Such raw values remain visible and untouched until the
            # user deliberately edits this slider.
            volume_rect = QRectF(left + header_w - 101, y + 42, 50, 16)
            volume_value_rect = QRectF(left + header_w - 48, y + 42, 26, 16)
            volume_label = tr("轨道音量")
            volume_label_width = self._volume_label_width(
                painter.fontMetrics(),
                volume_label,
            )
            volume_label_rect = QRectF(
                volume_rect.left() - volume_label_width - 4.0,
                y + 42,
                volume_label_width,
                16,
            )
            painter.setPen(QColor("#a78e6a" if active else "#665e54"))
            painter.drawText(volume_label_rect, Qt.AlignCenter, volume_label)
            painter.fillRect(volume_rect, QColor("#1c1c1e"))
            painter.setPen(QPen(QColor("#514a3e"), 1))
            painter.drawRect(volume_rect)
            raw_track_volume = int(track.bdo_track_volume)
            fill_width = max(
                0.0,
                (volume_rect.width() - 4.0)
                * max(0, min(100, raw_track_volume))
                / 100.0,
            )
            painter.fillRect(
                QRectF(
                    volume_rect.left() + 2.0,
                    volume_rect.top() + 5.0,
                    fill_width,
                    6.0,
                ),
                QColor("#83a543" if active else "#556042"),
            )
            handle_x = volume_rect.left() + 2.0 + fill_width
            painter.fillRect(
                QRectF(handle_x - 1.0, volume_rect.top() + 3.0, 2.0, 10.0),
                QColor("#d9c07a" if active else "#81735d"),
            )
            painter.setPen(
                QColor(
                    "#ef7772"
                    if not 0 <= raw_track_volume <= 100
                    else ("#ffedd4" if active else "#77716a")
                )
            )
            painter.drawText(
                volume_value_rect,
                Qt.AlignRight | Qt.AlignVCenter,
                str(raw_track_volume),
            )
            self.hit_regions.append((volume_rect, "track_volume", track))

            if paint_meters:
                self._paint_track_meter(
                    painter,
                    track,
                    left + header_w - 14,
                    y,
                    lane_h,
                    active,
                )

            # No nested horizontal gutter: the colored note region shares the
            # grid's exact left/right edge, while retaining a little vertical
            # breathing room between adjacent lanes.
            region_top = y + 9
            region_rect = QRectF(
                grid_left, region_top, grid_w,
                max(18.0, y + lane_h - 9.0 - region_top),
            )
            self._paint_track_region_background(
                painter, region_rect, focused=focused, active=active,
                has_error=bool(validation_errors),
            )

            self._paint_track_clip(
                painter,
                track,
                region_rect,
                visible_start,
                visible_duration,
                active=active,
                focused=focused,
                has_error=bool(validation_errors),
            )

            if track.notes:
                pitch_min, pitch_max = self._track_pitch_bounds(track)
                pitch_span = max(1, pitch_max - pitch_min)
                painter.save()
                painter.setClipRect(region_rect)
                ordered, note_lo, note_hi = self._visible_track_note_window(
                    track, visible_start, visible_end,
                )
                (
                    normal_rects,
                    articulation_markers,
                    invalid_rects,
                ) = self._timeline_note_rect_batches(
                    track,
                    region_rect,
                    visible_start,
                    visible_duration,
                    pitch_min,
                    pitch_span,
                    ordered,
                    note_lo,
                    note_hi,
                )
                painter.setPen(Qt.NoPen)
                if normal_rects:
                    note_fill = QColor(track.color if active else "#566149")
                    note_fill.setAlpha(232 if active else 112)
                    painter.setBrush(note_fill)
                    painter.drawRects(normal_rects)
                for color, markers in articulation_markers.items():
                    painter.setBrush(QColor(color))
                    painter.drawRects(markers)
                if invalid_rects:
                    painter.setBrush(QColor("#d94a4a"))
                    painter.setPen(QPen(QColor("#ffb1a8"), 1))
                    painter.drawRects(invalid_rects)
                painter.restore()

            if not self._viewport_motion_active:
                self.velocity_curve_overlay.paint_velocity_trace(
                    painter,
                    track,
                    region_rect,
                    visible_start,
                    visible_duration,
                    active,
                )
            if focused and paint_selected_velocity:
                self.velocity_curve_overlay.paint_selected_track(
                    painter,
                    track,
                    region_rect,
                    visible_start,
                    visible_duration,
                    self.time_range,
                )

            title_left = left + (34.0 if has_validation_notice else 12.0)
            title_right = left + header_w - 114.0
            title_width = max(0.0, title_right - title_left)
            painter.setPen(QColor("#ffedd4" if active else "#8a847d"))
            painter.drawText(
                QRectF(title_left, y + 8, title_width, 24),
                Qt.AlignLeft | Qt.AlignVCenter,
                painter.fontMetrics().elidedText(
                    track.display_name,
                    Qt.ElideRight,
                    max(0, int(title_width - 6.0)),
                ),
            )
            painter.setPen(QColor("#b8a487" if active else "#69645f"))
            metadata = trf(
                "{count} 音符 · {pitch_range}",
                count=(
                    len(index.intervals.items)
                    if (index := self._track_note_indexes.get(id(track)))
                    is not None else 0
                ),
                pitch_range=(
                    f"{note_name(index.pitch_min)} - {note_name(index.pitch_max)}"
                    if index is not None and index.intervals.items else "-"
                ),
            )
            metadata_font = painter.font()
            metadata_font.setPointSize(max(7, metadata_font.pointSize() - 1))
            painter.save()
            painter.setFont(metadata_font)
            metadata_left = left + 12.0
            metadata_right = volume_label_rect.left() - 6.0
            metadata_width = max(0.0, metadata_right - metadata_left)
            if not group_start:
                painter.drawText(
                    QRectF(metadata_left, y + 39, metadata_width, 20),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    painter.fontMetrics().elidedText(
                        metadata, Qt.ElideRight,
                        max(0, int(metadata_width - 4.0)),
                    ),
                )
            painter.restore()
            self._paint_arrangement_group_marker(
                painter, track, row, left, grid_left, grid_w, y, lane_h,
                has_validation_notice,
            )
        painter.restore()
        if self.reference_audio is not None:
            self._paint_reference_audio_row(
                painter,
                left,
                grid_left,
                grid_top,
                header_w,
                grid_w,
                grid_h,
                lane_h,
                visible_start,
                visible_duration,
                visible_end, paint_position=paint_reference_position,
            )
    @staticmethod
    def _paint_track_region_background(
        painter: QPainter, region_rect: QRectF, *, focused: bool,
        active: bool, has_error: bool,
    ) -> None:
        background = QColor(
            "#391719" if has_error
            else ("#253022" if focused and active else "#242427")
        )
        background.setAlpha(184 if has_error else (152 if active else 116))
        painter.setBrush(background)
        painter.setPen(QPen(
            QColor(
                "#d94a4a" if has_error
                else ("#735b2d" if focused else "#3b3b3f")
            ),
            2 if has_error else 1,
        ))
        painter.drawRect(region_rect)

    def _paint_track_clip(
        self,
        painter: QPainter,
        track: TrackState,
        region_rect: QRectF,
        visible_start: float,
        visible_duration: float,
        *,
        active: bool,
        focused: bool,
        has_error: bool = False,
    ) -> None:
        for clip in self._visible_track_clips(
            track, visible_start, visible_start + visible_duration
        ):
            selected = (
                self._selected_clip_id == clip.clip_id
                and self._selected_clip_track_id == int(track.track_id)
            )
            clip_x = region_rect.left() + (
                (clip.start_ms - visible_start) / visible_duration
            ) * region_rect.width()
            clip_width = max(
                8.0,
                (clip.end_ms - clip.start_ms)
                / visible_duration * region_rect.width(),
            )
            clip_rect = QRectF(
                clip_x,
                region_rect.top() + 2.0,
                clip_width,
                region_rect.height() - 4.0,
            ).intersected(region_rect)
            if clip_rect.isEmpty():
                continue
            clip_color = QColor("#8f2429" if has_error else track.color)
            clip_color.setAlpha(
                112 if has_error else (96 if selected else (54 if active else 30))
            )
            painter.fillRect(clip_rect, clip_color)
            painter.setPen(QPen(
                QColor(
                    "#ff554f"
                    if has_error
                    else (
                        "#ffd766"
                        if selected
                        else ("#a88e50" if focused else track.color)
                    )
                ),
                3 if selected else (2 if has_error else 1),
            ))
            painter.drawRoundedRect(clip_rect, 4.0, 4.0)
            if selected and clip_rect.width() > 8.0 and clip_rect.height() > 8.0:
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor("#fff1ad"), 1))
                painter.drawRoundedRect(
                    clip_rect.adjusted(3.0, 3.0, -3.0, -3.0),
                    2.5,
                    2.5,
                )
            self.hit_regions.append((
                clip_rect, f"clip_body|{clip.clip_id}", track
            ))
            handle_width = min(7.0, clip_rect.width() / 2.0)
            if selected and self.arrangement_tool == "select":
                for handle_x in (
                    clip_rect.left() + 2.0,
                    clip_rect.right() - 5.0,
                ):
                    painter.fillRect(QRectF(
                        handle_x,
                        clip_rect.center().y() - 8.0,
                        3.0,
                        16.0,
                    ), QColor("#f0d887"))
            self.hit_regions.append((QRectF(
                clip_rect.left(), clip_rect.top(),
                handle_width, clip_rect.height(),
            ), f"clip_start|{clip.clip_id}", track))
            self.hit_regions.append((QRectF(
                clip_rect.right() - handle_width, clip_rect.top(),
                handle_width, clip_rect.height(),
            ), f"clip_end|{clip.clip_id}", track))

    def _timeline_note_rect_batches(
        self,
        track: TrackState,
        region: QRectF,
        visible_start: float,
        visible_duration: float,
        pitch_min: int,
        pitch_span: int,
        ordered: list[object],
        note_lo: int,
        note_hi: int,
    ) -> tuple[list[QRectF], dict[str, list[QRectF]], list[QRectF]]:
        """Project visible notes with a pixel-bounded overview LOD.

        Once several notes compete for each horizontal pixel, individual
        2.5-DIP rectangles are no longer distinguishable.  Collapse those
        onsets into three-pixel pitch-envelope buckets instead of spending a
        full paint pass on thousands of overdrawn blocks.  Conversion errors
        and articulation colors remain visible in the collapsed view.
        """

        normal_rects: list[QRectF] = []
        articulation_markers: dict[str, list[QRectF]] = {}
        invalid_rects: list[QRectF] = []
        note_count = max(0, note_hi - note_lo)
        detail_limit = max(320, int(region.width() / 2.0))
        use_overview = note_count > detail_limit
        if use_overview:
            conversion_problem_mask = self._conversion_problem_mask(track)
            clips = self._visible_track_clips(
                track,
                visible_start,
                visible_start + visible_duration,
            )
            overview_bins = self._visible_note_overview_bins(
                track,
                visible_start,
                visible_duration,
                region.width(),
            )
            if self._viewport_motion_active and len(overview_bins) > 1:
                overview_bins = tuple(
                    _TimelineNoteOverviewBin(
                        start=min(value.start for value in pair),
                        end=max(value.end for value in pair),
                        pitch_min=min(value.pitch_min for value in pair),
                        pitch_max=max(value.pitch_max for value in pair),
                        pitch_mask=pair[0].pitch_mask
                        | (pair[1].pitch_mask if len(pair) > 1 else 0),
                        articulation_type=pair[0].articulation_type
                        or (
                            pair[1].articulation_type
                            if len(pair) > 1
                            else 0
                        ),
                    )
                    for index in range(0, len(overview_bins), 2)
                    for pair in (overview_bins[index:index + 2],)
                )
            for summary in overview_bins:
                high_position = (summary.pitch_max - pitch_min) / pitch_span
                low_position = (summary.pitch_min - pitch_min) / pitch_span
                top = (
                    region.top()
                    + 6
                    + (1.0 - high_position) * (region.height() - 14)
                )
                bottom = (
                    region.top()
                    + 6
                    + (1.0 - low_position) * (region.height() - 14)
                    + 5.0
                )
                for clip in clips:
                    summary_start = max(float(summary.start), clip.start_ms)
                    summary_end = min(float(summary.end), clip.end_ms)
                    if summary_end <= summary_start:
                        continue
                    x = region.left() + (
                        (summary_start - visible_start) / visible_duration
                    ) * region.width()
                    width = max(
                        2.5,
                        (summary_end - summary_start)
                        / visible_duration
                        * region.width(),
                    )
                    rect = QRectF(x, top, width, max(5.0, bottom - top))
                    if summary.pitch_mask & conversion_problem_mask:
                        invalid_rects.append(rect)
                        continue
                    normal_rects.append(rect)
                    if summary.articulation_type != 0:
                        marker_color = articulation_color(summary.articulation_type)
                        articulation_markers.setdefault(marker_color, []).append(
                            QRectF(
                                rect.left(),
                                rect.top(),
                                min(2.0, rect.width()),
                                rect.height(),
                            )
                        )
            return normal_rects, articulation_markers, invalid_rects

        for note_index in range(note_lo, note_hi):
            note = ordered[note_index]
            note_start = float(note.start)
            note_end = note_start + float(note.dur)
            if note_end <= note_start or note_end < visible_start or note_start > visible_start + visible_duration:
                continue
            x = region.left() + (
                (note_start - visible_start) / visible_duration
            ) * region.width()
            width = max(
                2.5,
                ((note_end - note_start) / visible_duration) * region.width(),
            )
            pitch_pos = (int(note.pitch) - pitch_min) / pitch_span
            note_y = (
                region.top()
                + 6
                + (1.0 - pitch_pos) * (region.height() - 14)
            )
            has_problem = self._note_has_conversion_problem(track, note)
            ntype = int(getattr(note, "ntype", 0))

            note_rect = QRectF(x, note_y, width, 5.0)
            if note_rect.width() <= 0.0:
                continue
            if has_problem:
                invalid_rects.append(note_rect)
            else:
                normal_rects.append(note_rect)
                if ntype != 0:
                    marker = QRectF(
                        note_rect.left(),
                        note_rect.top(),
                        min(2.0, note_rect.width()),
                        note_rect.height(),
                    )
                    articulation_markers.setdefault(
                        articulation_color(ntype), []
                    ).append(marker)
        return normal_rects, articulation_markers, invalid_rects

    @staticmethod
    def _volume_label_width(font_metrics, label: str) -> float:
        """Reserve the rendered locale width instead of the Chinese width."""

        return float(
            max(
                25,
                font_metrics.horizontalAdvance(str(label)) + 8,
            )
        )

    @staticmethod
    def _track_volume_from_position(rect: QRectF, x: float) -> int:
        if rect.width() <= 0:
            return 0
        ratio = max(0.0, min(1.0, (float(x) - rect.left()) / rect.width()))
        return max(0, min(100, round(ratio * 100.0)))

    def _set_track_volume_from_position(
        self,
        track: TrackState,
        rect: QRectF,
        x: float,
    ) -> bool:
        value = self._track_volume_from_position(rect, x)
        if int(track.bdo_track_volume) == value:
            return False
        track.bdo_track_volume = value
        if track is self.selected_track:
            self._update_accessible_track_state()
        self.update(rect.adjusted(-4.0, -3.0, 32.0, 3.0).toAlignedRect())
        return True

    def _paint_reference_audio_row(
        self,
        painter: QPainter,
        left: float,
        grid_left: float,
        grid_top: float,
        header_w: int,
        grid_w: float,
        grid_h: float,
        lane_h: int,
        visible_start: float,
        visible_duration: float,
        visible_end: float,
        *,
        paint_position: bool = True,
    ) -> None:
        controller = self.reference_audio
        if controller is None:
            return
        reference_h = self._reference_audio_lane_height()
        compact = reference_h < lane_h
        y = grid_top + grid_h - reference_h
        accent = QColor("#d39a42")
        lane_rect = QRectF(left, y, header_w + grid_w, reference_h)
        header_rect = QRectF(left, y, header_w, reference_h)
        waveform_rect = QRectF(
            grid_left, y + 5, grid_w, max(12, reference_h - 10)
        )

        painter.fillRect(QRectF(grid_left, y, grid_w, reference_h), QColor(29, 28, 27, 186))
        painter.fillRect(header_rect, QColor(37, 35, 32, 218))
        painter.fillRect(QRectF(left, y, 5, reference_h), accent)
        painter.setPen(QPen(QColor("#2e2e2e"), 1))
        painter.drawLine(left, y + reference_h - 1, grid_left + grid_w, y + reference_h - 1)
        self.hit_regions.append((lane_rect, "audio_lane", controller))

        button_specs = (
            ((tr("卸载"), "audio_unload", 44),)
            if controller.audio_path
            else ((tr("载入"), "audio_load", 44),)
        )
        gap = 4.0
        buttons_width = sum(width for _label, _action, width in button_specs)
        buttons_width += gap * max(0, len(button_specs) - 1)
        button_x = left + header_w - 13.0 - buttons_width
        button_y = y + (6.0 if compact else 5.0)
        for label, action, width in button_specs:
            rect = QRectF(button_x, button_y, width, 22)
            painter.fillRect(rect, QColor("#2b2b2b"))
            painter.setPen(QPen(QColor("#55504a"), 1))
            painter.drawRect(rect)
            painter.setPen(QColor("#f3f1ea"))
            painter.drawText(rect, Qt.AlignCenter, label)
            self.hit_regions.append((rect, action, controller))
            button_x += width + gap

        volume_specs = (
            ("−", "audio_volume_down", 24),
            (f"{controller.volume_percent}%", "audio_volume", 42),
            ("+", "audio_volume_up", 24),
        )
        volume_width = sum(width for _label, _action, width in volume_specs)
        volume_width += gap * max(0, len(volume_specs) - 1)
        volume_x = (
            left + header_w - 13.0 - buttons_width - 8.0 - volume_width
            if compact
            else left + header_w - 13.0 - volume_width
        )
        for label, action, width in volume_specs:
            rect = QRectF(volume_x, y + (8.0 if compact else 32.0), width, 18)
            painter.fillRect(rect, QColor("#292826"))
            painter.setPen(QPen(QColor("#55504a"), 1))
            painter.drawRect(rect)
            painter.setPen(QColor("#d7c6a5" if action == "audio_volume" else "#f3f1ea"))
            painter.drawText(rect, Qt.AlignCenter, label)
            self.hit_regions.append((rect, action, controller))
            volume_x += width + gap

        text_width = max(
            40.0,
            header_w
            - buttons_width
            - (volume_width + 46.0 if compact else 38.0),
        )
        painter.setPen(QColor("#f3f1ea"))
        painter.drawText(
            QRectF(left + 12, y + 5, text_width, 22),
            Qt.AlignLeft | Qt.AlignVCenter,
            tr("参考音频"),
        )
        if not compact:
            metadata = tr("正在分析波形…") if controller.waveform_loading else controller.display_name
            painter.setPen(QColor("#aaa39b"))
            metadata_width = max(40.0, header_w - volume_width - 38.0)
            painter.drawText(
                QRectF(left + 12, y + 31, metadata_width, 20),
                Qt.AlignLeft | Qt.AlignVCenter,
                painter.fontMetrics().elidedText(metadata, Qt.ElideMiddle, int(metadata_width)),
            )

        waveform_bg = QColor("#d39a42")
        waveform_bg.setAlpha(24 if controller.audio_path else 12)
        painter.fillRect(waveform_rect, waveform_bg)
        painter.setPen(QPen(QColor("#775d35"), 1))
        painter.drawRect(waveform_rect)
        self.hit_regions.append((waveform_rect, "audio_waveform", controller))

        if controller.waveform:
            audio_visible_start = controller.project_to_audio(visible_start)
            audio_visible_end = controller.project_to_audio(visible_end)
            first = max(
                0,
                bisect_left(controller.waveform_starts, audio_visible_start) - 1,
            )
            last = bisect_right(controller.waveform_starts, audio_visible_end)
            center_y = waveform_rect.center().y()
            max_half_height = max(1.0, waveform_rect.height() / 2.0 - 3.0)
            bars: list[QRectF] = []
            for bucket_start, bucket_end, peak in controller.waveform[first:last]:
                project_start = controller.audio_to_project(bucket_start)
                project_end = controller.audio_to_project(bucket_end)
                x = waveform_rect.left() + (
                    (project_start - visible_start) / visible_duration
                ) * waveform_rect.width()
                width = max(
                    1.0,
                    ((project_end - project_start) / visible_duration)
                    * waveform_rect.width(),
                )
                half_height = max(1.0, min(1.0, peak) * max_half_height)
                bars.append(QRectF(x, center_y - half_height, width, half_height * 2.0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#d7a34c"))
            if bars:
                painter.drawRects(bars)
        else:
            painter.setPen(QColor("#817665"))
            placeholder = tr("正在分析波形…") if controller.waveform_loading else tr("载入 MP3/WAV 后显示波形")
            painter.drawText(waveform_rect, Qt.AlignCenter, placeholder)

        if paint_position:
            self._paint_reference_audio_position(
                painter,
                waveform_rect,
                visible_start,
                visible_duration,
                visible_end,
            )

    def _paint_ruler_overlay(
        self,
        painter: QPainter,
        area: QRectF,
        left: float,
        top: float,
        grid_left: float,
        grid_top: float,
        grid_w: float,
        grid_h: float,
        ruler_h: int,
        bars: int,
        visible_start: float,
        visible_duration: float,
        play_x: float | None,
    ) -> None:
        painter.fillRect(QRectF(left, top, area.width(), ruler_h), QColor(32, 32, 32, 224))
        painter.setPen(QColor("#a8a29e"))
        painter.drawText(
            left + 10,
            top + 22,
            trf("轨道 · {count}", count=self._musical_track_count()),
        )
        for value, is_major, label in self._visible_musical_ticks(
            visible_start,
            visible_duration,
            grid_w,
        ):
            x = grid_left + (
                (value - visible_start) / visible_duration
            ) * grid_w
            painter.setPen(QPen(QColor("#3a3a3a" if is_major else "#292929"), 1))
            painter.drawLine(int(x), top + 8, int(x), grid_top)
            if label:
                painter.setPen(QColor("#8e8982" if is_major else "#5f5a54"))
                painter.drawText(int(x + 6), top + 22, label)
        if play_x is not None:
            painter.fillRect(QRectF(play_x, top, 2, ruler_h), QColor("#f5a524"))
            marker = QPainterPath()
            marker.moveTo(play_x - 5, top + 1)
            marker.lineTo(play_x + 7, top + 1)
            marker.lineTo(play_x + 1, top + 9)
            marker.closeSubpath()
            painter.fillPath(marker, QColor("#f5a524"))
        painter.setPen(QPen(QColor("#343434"), 1))
        painter.drawLine(grid_left, top, grid_left, grid_top + grid_h)
        painter.drawLine(left, grid_top, grid_left + grid_w, grid_top)

    def _paint_track_meter(
        self,
        painter: QPainter,
        track: TrackState,
        meter_left: float,
        row_y: float,
        lane_h: int,
        active: bool,
    ) -> None:
        meter_level = (
            self.track_levels.get(int(track.track_id), 0.0) if active else 0.0
        )
        meter_rect = QRectF(meter_left, row_y + 8, 7, lane_h - 16)
        segment_count = 10
        segment_gap = 1.0
        segment_height = (
            meter_rect.height() - segment_gap * (segment_count - 1)
        ) / segment_count
        lit_segments = min(
            segment_count,
            math.ceil(meter_level * segment_count),
        )
        painter.setPen(Qt.NoPen)
        for segment in range(segment_count):
            segment_y = (
                meter_rect.bottom()
                - (segment + 1) * segment_height
                - segment * segment_gap
            )
            if segment < lit_segments:
                color = (
                    "#d05c4f"
                    if segment >= 9
                    else "#caa24f"
                    if segment >= 7
                    else "#83a543"
                )
            else:
                color = "#343438"
            painter.fillRect(
                QRectF(
                    meter_rect.left(),
                    segment_y,
                    meter_rect.width(),
                    segment_height,
                ),
                QColor(color),
            )

    def _paint_reference_audio_position(
        self,
        painter: QPainter,
        waveform_rect: QRectF,
        visible_start: float,
        visible_duration: float,
        visible_end: float,
    ) -> None:
        controller = self.reference_audio
        if controller is None or not controller.audio_path:
            return
        position = float(controller.project_position_ms)
        if not visible_start <= position <= visible_end:
            return
        position_x = waveform_rect.left() + (
            (position - visible_start) / visible_duration
        ) * waveform_rect.width()
        painter.fillRect(
            QRectF(
                position_x,
                waveform_rect.top(),
                1.5,
                waveform_rect.height(),
            ),
            QColor("#f4e3bd"),
        )

    def _static_timeline_key(
        self,
        *,
        grid_h: float,
        visible_start: float,
        visible_duration: float,
    ) -> tuple[object, ...]:
        instrument_grid_h = max(
            0.0,
            grid_h - self._reference_audio_lane_height(),
        )
        first_row, last_row = self._visible_track_row_range(instrument_grid_h)
        visible_tracks: list[tuple[object, ...]] = []
        for track in self.tracks[first_row:last_row]:
            index = self._track_note_indexes.get(id(track))
            notice = self._track_validation_notice(track)
            visible_tracks.append(
                (
                    id(track),
                    id(index.intervals) if index is not None else 0,
                    int(track.track_id),
                    str(track.display_name),
                    int(track.bdo_instrument_id),
                    bool(track.muted),
                    bool(track.solo),
                    float(track.duration_scale),
                    str(track.marnian_synth_mode),
                    str(track.color),
                    int(track.bdo_track_volume),
                    str(track.arrangement_group_id),
                    id(index.clips) if index is not None else 0,
                    tuple(notice["errors"]),
                    tuple(notice["attentions"]),
                    _ui_bdo_instrument_name(track.bdo_instrument_id),
                )
            )
        controller = self.reference_audio
        waveform = getattr(controller, "waveform", ()) if controller else ()
        reference_key = (
            id(controller),
            str(getattr(controller, "audio_path", "") or ""),
            str(getattr(controller, "display_name", "") or ""),
            int(getattr(controller, "volume_percent", 0) or 0),
            bool(getattr(controller, "waveform_loading", False)),
            id(waveform),
            len(waveform) if waveform is not None else 0,
            round(float(getattr(controller, "project_end_ms", 0.0) or 0.0), 3),
        )
        return (
            self.width(),
            self.height(),
            round(float(self.devicePixelRatioF()), 3),
            round(float(visible_start), 3),
            round(float(visible_duration), 3),
            round(float(grid_h), 3),
            int(self.track_scroll.value()),
            bool(self._viewport_motion_active),
            bool(self.track_scroll.isVisible()),
            int(self.bpm),
            int(self.time_sig),
            round(float(self.beat_origin_ms), 3),
            id(self.selected_track),
            self._selected_clip_track_id,
            self._selected_clip_id,
            self._selected_arrangement_group_id,
            bool(self.hasFocus()),
            self.arrangement_tool,
            self.pitch_transform_plan,
            tuple(visible_tracks),
            reference_key,
            tr("轨道"),
            tr("轨道音量"),
            tr("乐器组 ×{count}"),
        )

    def _render_static_timeline(
        self,
        *,
        area: QRectF,
        header_w: int,
        ruler_h: int,
        lane_h: int,
        grid_w: float,
        grid_h: float,
        visible_start: float,
        visible_duration: float,
        visible_end: float,
    ) -> None:
        ratio = max(1.0, float(self.devicePixelRatioF()))
        pixel_size = QSize(
            max(1, round(self.width() * ratio)),
            max(1, round(self.height() * ratio)),
        )
        cache = QPixmap(pixel_size)
        cache.setDevicePixelRatio(ratio)
        cache.fill(Qt.transparent)
        painter = QPainter(cache)
        try:
            self.hit_regions = []
            self._paint_canvas_background(painter)
            left, top, grid_left, grid_top = self._paint_timeline_shell(
                painter,
                area,
                header_w,
                ruler_h,
                grid_w,
                grid_h,
            )
            self.grid_rect = QRectF(
                grid_left,
                top,
                grid_w,
                grid_h + ruler_h,
            )
            bars = self._paint_grid_ruler(
                painter,
                left,
                top,
                grid_left,
                grid_top,
                grid_w,
                grid_h,
                visible_start,
                visible_duration,
            )
            self._paint_track_rows(
                painter,
                left,
                grid_left,
                grid_top,
                header_w,
                grid_w,
                grid_h,
                lane_h,
                visible_start,
                visible_duration,
                visible_end,
                paint_meters=False,
                paint_selected_velocity=False,
                paint_reference_position=False,
            )
            self._paint_ruler_overlay(
                painter,
                area,
                left,
                top,
                grid_left,
                grid_top,
                grid_w,
                grid_h,
                ruler_h,
                bars,
                visible_start,
                visible_duration,
                None,
            )
        finally:
            painter.end()
        self._static_timeline_cache = cache
        self._static_timeline_hit_regions = list(self.hit_regions)

    def _paint_dynamic_track_overlays(
        self,
        painter: QPainter,
        *,
        left: float,
        grid_left: float,
        grid_top: float,
        header_w: int,
        grid_w: float,
        grid_h: float,
        lane_h: int,
        visible_start: float,
        visible_duration: float,
        visible_end: float,
    ) -> None:
        any_solo = any(track.solo for track in self.tracks)
        scroll_y = self.track_scroll.value() if self.track_scroll.isVisible() else 0
        instrument_grid_h = max(
            0.0,
            grid_h - self._reference_audio_lane_height(),
        )
        first_row, last_row = self._visible_track_row_range(instrument_grid_h)
        painter.save()
        painter.setClipRect(
            QRectF(left, grid_top, header_w + grid_w, instrument_grid_h)
        )
        for row in range(first_row, last_row):
            track = self.tracks[row]
            y = grid_top + row * lane_h - scroll_y
            active = not track.muted and (not any_solo or track.solo)
            self._paint_track_meter(
                painter,
                track,
                left + header_w - 14,
                y,
                lane_h,
                active,
            )
            if track is self.selected_track:
                region_rect = QRectF(
                    grid_left,
                    y + 9,
                    grid_w,
                    lane_h - 18,
                )
                self._paint_merge_overlap_regions(
                    painter,
                    track,
                    region_rect,
                    visible_start,
                    visible_duration,
                )
                self.velocity_curve_overlay.paint_selected_track(
                    painter,
                    track,
                    region_rect,
                    visible_start,
                    visible_duration,
                    self.time_range,
                )
        painter.restore()
        controller = self.reference_audio
        if controller is not None:
            reference_h = self._reference_audio_lane_height()
            y = grid_top + grid_h - reference_h
            waveform_rect = QRectF(
                grid_left,
                y + 5,
                grid_w,
                max(12, reference_h - 10),
            )
            self._paint_reference_audio_position(
                painter,
                waveform_rect,
                visible_start,
                visible_duration,
                visible_end,
            )

    def _paint_merge_overlap_regions(
        self,
        painter: QPainter,
        track: TrackState,
        region_rect: QRectF,
        visible_start: float,
        visible_duration: float,
    ) -> None:
        if int(track.track_id) != self._merge_overlap_track_id:
            return
        visible_end = visible_start + visible_duration
        for region in self._merge_overlap_regions:
            start = max(visible_start, float(region.start_ms))
            end = min(visible_end, float(region.end_ms))
            if end <= start:
                continue
            x = region_rect.left() + (
                (start - visible_start) / visible_duration
            ) * region_rect.width()
            width = max(2.0, (end - start) / visible_duration * region_rect.width())
            rect = QRectF(x, region_rect.top(), width, region_rect.height())
            painter.fillRect(rect, QColor(220, 113, 62, 76))
            painter.setPen(QPen(QColor("#f0a067"), 1, Qt.DashLine))
            painter.drawRect(rect)
    def _paint_clip_drag_preview(
        self,
        painter: QPainter,
        *,
        grid_left: float,
        grid_top: float,
        grid_w: float,
        lane_h: int,
        visible_start: float,
        visible_duration: float,
    ) -> None:
        target = self._clip_drag_target
        if self._clip_drag_source is None or target is None:
            return
        try:
            row = self.tracks.index(target)
        except ValueError:
            return
        scroll_y = self.track_scroll.value() if self.track_scroll.isVisible() else 0
        x = grid_left + (
            (self._clip_drag_start_ms - visible_start) / visible_duration
        ) * grid_w
        width = max(
            8.0,
            (self._clip_drag_end_ms - self._clip_drag_start_ms)
            / visible_duration * grid_w,
        )
        rect = QRectF(
            x,
            grid_top + row * lane_h - scroll_y + 11.0,
            width,
            lane_h - 22.0,
        )
        painter.save()
        painter.setBrush(QColor(214, 184, 103, 66))
        painter.setPen(QPen(QColor("#f0d887"), 2, Qt.DashLine))
        painter.drawRoundedRect(rect, 4.0, 4.0)
        snap = self._clip_snap_result
        if snap.target_ms is not None:
            guide_x = grid_left + (
                (snap.target_ms - visible_start) / visible_duration
            ) * grid_w
            painter.setPen(QPen(QColor("#f3ba4f"), 1, Qt.DashLine))
            painter.drawLine(guide_x, grid_top, guide_x, self.grid_rect.bottom())
            kind = {
                "marker": tr("时间轴标记"),
                "clip": tr("片段边界"),
                "grid": tr("网格"),
            }.get(snap.kind, "")
            guide_label = f"{kind} · {snap.label}" if snap.label else kind
            if guide_label:
                label_w = min(180.0, painter.fontMetrics().horizontalAdvance(guide_label) + 14.0)
                label_rect = QRectF(
                    max(grid_left + 3.0, min(guide_x + 4.0, grid_left + grid_w - label_w - 3.0)),
                    grid_top + 3.0,
                    label_w,
                    20.0,
                )
                painter.fillRect(label_rect, QColor(42, 35, 21, 238))
                painter.setPen(QColor("#f3d38b"))
                painter.drawText(label_rect.adjusted(6, 0, -4, 0), Qt.AlignVCenter, guide_label)
        painter.restore()

    def _time_at_x(self, x: float) -> float:
        rel = max(
            0.0,
            min(
                1.0,
                (float(x) - self.grid_rect.left())
                / max(1.0, self.grid_rect.width()),
            ),
        )
        return self.view_start_ms + rel * self._visible_duration_ms()

    def _track_at_position(self, position) -> TrackState | None:
        for rect, action, item in reversed(self.hit_regions):
            if (
                action == "lane"
                and isinstance(item, TrackState)
                and rect.contains(position)
            ):
                return item
        return None

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        area, header_w, ruler_h, lane_h = self._timeline_layout_metrics()
        if self._timeline_row_count() <= 0:
            self._paint_canvas_background(painter)
            painter.setPen(QColor("#8d8780"))
            painter.drawText(
                area,
                Qt.AlignCenter,
                tr("导入 MIDI 后显示轨道与音符时间轴"),
            )
            return

        visible_start = self.view_start_ms
        visible_duration = self._visible_duration_ms()
        visible_end = visible_start + visible_duration
        scrollbar_w = 14 if self.track_scroll.isVisible() else 0
        grid_w = max(120, area.width() - header_w - scrollbar_w)
        grid_h = max(80, area.bottom() - (area.top() + ruler_h))
        left = area.left()
        top = area.top()
        grid_left = left + header_w
        grid_top = top + ruler_h
        cache_key = self._static_timeline_key(
            grid_h=grid_h,
            visible_start=visible_start,
            visible_duration=visible_duration,
        )
        if (
            cache_key != self._static_timeline_cache_key
            or self._static_timeline_cache.isNull()
        ):
            self._render_static_timeline(
                area=area,
                header_w=header_w,
                ruler_h=ruler_h,
                lane_h=lane_h,
                grid_w=grid_w,
                grid_h=grid_h,
                visible_start=visible_start,
                visible_duration=visible_duration,
                visible_end=visible_end,
            )
            self._static_timeline_cache_key = cache_key
        painter.drawPixmap(0, 0, self._static_timeline_cache)
        self.hit_regions = list(self._static_timeline_hit_regions)
        self.velocity_curve_overlay.begin_frame()
        self._paint_dynamic_track_overlays(
            painter,
            left=left,
            grid_left=grid_left,
            grid_top=grid_top,
            header_w=header_w,
            grid_w=grid_w,
            grid_h=grid_h,
            lane_h=lane_h,
            visible_start=visible_start,
            visible_duration=visible_duration,
            visible_end=visible_end,
        )
        self._paint_clip_drag_preview(
            painter,
            grid_left=grid_left,
            grid_top=grid_top,
            grid_w=grid_w,
            lane_h=lane_h,
            visible_start=visible_start,
            visible_duration=visible_duration,
        )
        self._paint_playhead(
            painter, top, grid_left, grid_top, grid_w, grid_h,
            visible_start, visible_duration, visible_end, grid_h
        )
        self._paint_time_range(
            painter,
            top,
            grid_left,
            grid_top,
            grid_w,
            grid_h,
            visible_start,
            visible_duration,
            visible_end,
        )
        self._paint_timeline_markers(
            painter, top, grid_left, grid_top, grid_w, grid_h,
            visible_start, visible_duration, visible_end,
        )
        if self.buffer_visible:
            buffer_y = grid_top - 3
            painter.fillRect(QRectF(grid_left, buffer_y, grid_w, 3), QColor("#30383a"))
            if self.buffer_progress > 0:
                painter.fillRect(
                    QRectF(grid_left, buffer_y, grid_w * self.buffer_progress, 3),
                    QColor("#55b8ad"),
                )

    def _paint_timeline_markers(
        self, painter: QPainter, top: float, grid_left: float, grid_top: float,
        grid_w: float, grid_h: float, visible_start: float,
        visible_duration: float, visible_end: float,
    ) -> None:
        self._marker_label_regions.clear()
        self._marker_delete_regions.clear()
        first = bisect_left(self._timeline_marker_times, visible_start)
        last = bisect_right(self._timeline_marker_times, visible_end)
        for marker in self.timeline_markers[first:last]:
            time_ms = float(marker["time_ms"])
            if not visible_start <= time_ms <= visible_end:
                continue
            x = grid_left + ((time_ms - visible_start) / visible_duration) * grid_w
            painter.fillRect(QRectF(x, grid_top, 1.0, grid_h), QColor(229, 174, 69, 150))
            label = str(marker["label"])
            width = min(184.0, max(64.0, painter.fontMetrics().horizontalAdvance(label) + 30.0))
            label_x = max(grid_left + 3.0, min(x + 3.0, grid_left + grid_w - width - 3.0))
            pill = QRectF(label_x, top + 3.0, width, 20.0)
            painter.setBrush(QColor(48, 40, 25, 246))
            painter.setPen(QPen(QColor("#d9a53f"), 1))
            painter.drawRoundedRect(pill, 4.0, 4.0)
            painter.setPen(QColor("#f1d9a3"))
            painter.drawText(pill.adjusted(7.0, 0.0, -22.0, 0.0), Qt.AlignVCenter, label)
            delete_rect = QRectF(pill.right() - 21.0, pill.top(), 21.0, pill.height())
            painter.setPen(QColor("#caa967"))
            painter.drawText(delete_rect, Qt.AlignCenter, "×")
            self._marker_label_regions.append((pill, marker))
            self._marker_delete_regions.append((delete_rect, marker))

    def _marker_near_x(self, x: float) -> dict[str, object] | None:
        if self.grid_rect.width() <= 0:
            return None
        tolerance = self._visible_duration_ms() * 8.0 / self.grid_rect.width()
        target = self._time_at_x(x)
        position = bisect_left(self._timeline_marker_times, target)
        candidates = (
            self.timeline_markers[index]
            for index in (position - 1, position)
            if 0 <= index < len(self.timeline_markers)
        )
        nearest = min(
            candidates,
            key=lambda marker: abs(float(marker["time_ms"]) - target),
            default=None,
        )
        if nearest is None or abs(float(nearest["time_ms"]) - target) > tolerance:
            return None
        return nearest

    def _show_marker_menu(self, global_pos, local_x: float) -> None:
        menu = QMenu(self)
        marker = self._marker_near_x(local_x)
        add_action = menu.addAction(tr("添加时间轴标记…"))
        rename_action = delete_action = None
        if marker is not None:
            rename_action = menu.addAction(tr("重命名时间轴标记…"))
            delete_action = menu.addAction(tr("删除时间轴标记"))
        selected = menu.exec(global_pos)
        if selected is add_action:
            self.marker_edit_requested.emit({"action": "add", "time_ms": self._time_at_x(local_x)})
        elif rename_action is not None and selected is rename_action:
            self.marker_edit_requested.emit({"action": "rename", **marker})
        elif delete_action is not None and selected is delete_action:
            self.marker_edit_requested.emit({"action": "delete", **marker})

    def _build_clip_context_menu(self) -> tuple[QMenu, dict[str, QAction]]:
        """Build the Clip menu separately so every destructive entry is testable."""

        menu = QMenu(self)
        actions = {
            "copy": menu.addAction(tr("复制片段")),
            "paste": menu.addAction(tr("在播放头粘贴片段")),
        }
        menu.addSeparator()
        actions["delete"] = menu.addAction(tr("删除片段"))
        return menu, actions

    def mousePressEvent(self, event) -> None:
        pos = event.position()
        self.setFocus(Qt.MouseFocusReason)
        if self.velocity_curve_overlay.mouse_press(pos, event.button()):
            return
        if event.button() == Qt.LeftButton:
            for rect, marker in reversed(self._marker_delete_regions):
                if rect.contains(pos):
                    self.marker_edit_requested.emit({"action": "delete", **marker})
                    event.accept()
                    return
        if event.button() == Qt.RightButton:
            area, header_w, ruler_h, _lane_h = self._timeline_layout_metrics()
            ruler_rect = QRectF(area.left() + header_w, area.top(), max(0.0, area.width() - header_w), ruler_h)
            if ruler_rect.contains(pos):
                self._show_marker_menu(event.globalPosition().toPoint(), pos.x())
                return
            for rect, action, track in reversed(self.hit_regions):
                if rect.contains(pos) and isinstance(track, TrackState):
                    if action.startswith("group_"):
                        self._select_arrangement_group(track)
                        self._show_arrangement_group_menu(
                            track, event.globalPosition().toPoint()
                        )
                        return
                    action_kind, _separator, clip_id = action.partition("|")
                    if action_kind in {"clip_body", "clip_start", "clip_end"}:
                        self._select_track(track, emit=True)
                        self.set_selected_clip(track, clip_id)
                        menu, actions = self._build_clip_context_menu()
                        selected = menu.exec(event.globalPosition().toPoint())
                        if selected is actions["copy"]:
                            self.clip_copy_requested.emit(track, clip_id)
                        elif selected is actions["paste"]:
                            self.clip_paste_requested.emit(track, self.playhead_ms)
                        elif selected is actions["delete"]:
                            self.clip_delete_requested.emit(track, clip_id)
                        return
                    self._select_track(track, emit=True)
                    self._show_instrument_menu(
                        track,
                        event.globalPosition().toPoint(),
                        create_clip_at_ms=(
                            self._time_at_x(pos.x())
                            if pos.x() >= self.grid_rect.left()
                            else None
                        ),
                    )
                    return
            # The reference-audio lane is a separate transport layer, not a
            # musical track. Its header must not offer track creation.
            if any(
                rect.contains(pos) and track is self.reference_audio
                for rect, _action, track in self.hit_regions
            ):
                return
            self._show_create_track_menu(event.globalPosition().toPoint())
            return
        for rect, action, track in reversed(self.hit_regions):
            if rect.contains(pos):
                if track is self.reference_audio:
                    if action == "audio_load":
                        track.choose_audio(self)
                    elif action == "audio_unload":
                        track.set_audio_path(None)
                    elif action == "audio_volume_down":
                        track.set_volume_percent(track.volume_percent - 5)
                    elif action == "audio_volume_up":
                        track.set_volume_percent(track.volume_percent + 5)
                    elif action == "audio_volume":
                        return
                    elif action in ("audio_waveform", "audio_lane"):
                        if action == "audio_lane":
                            return
                        rel = max(
                            0.0,
                            min(1.0, (pos.x() - rect.left()) / max(1.0, rect.width())),
                        )
                        target = self.view_start_ms + rel * self._visible_duration_ms()
                        track.set_position(target)
                        self.set_playhead(target)
                        self.seek_requested.emit(self.playhead_ms)
                    self.update()
                    return
                if not isinstance(track, TrackState):
                    continue
                if action == "group_select":
                    self._select_arrangement_group(track)
                    return
                if action in {"group_mute", "group_solo"}:
                    self._select_arrangement_group(track)
                    self.group_control_requested.emit(
                        str(track.arrangement_group_id),
                        action.removeprefix("group_"),
                    )
                    return
                action_kind, _separator, clip_id = action.partition("|")
                if action_kind in {"clip_body", "clip_start", "clip_end"}:
                    try:
                        clip = clip_by_id(track, clip_id)
                    except ValueError:
                        return
                    self._select_track(track, emit=True)
                    self.set_selected_clip(track, clip.clip_id)
                    if self.arrangement_tool == "razor":
                        self.clip_split_requested.emit(TimelineClipSplitRequest(
                            track, clip.clip_id, self._time_at_x(pos.x())
                        ))
                        return
                    self._clip_drag_source = track
                    self._clip_drag_target = track
                    self._clip_drag_id = clip.clip_id
                    self._clip_drag_mode = {
                        "clip_body": "move",
                        "clip_start": "resize_start",
                        "clip_end": "resize_end",
                    }[action_kind]
                    self._clip_drag_press_ms = self._time_at_x(pos.x())
                    self._clip_drag_press_pos = QPointF(pos)
                    self._clip_drag_start_ms = clip.start_ms
                    self._clip_drag_end_ms = clip.end_ms
                    self._clip_drag_origin_press_ms = self._clip_drag_press_ms
                    self._clip_drag_origin_start_ms = clip.start_ms
                    self._clip_drag_origin_end_ms = clip.end_ms
                    occupied = clip_projected_note_bounds(
                        track, clip.clip_id
                    )
                    self._clip_drag_occupied_start_ms = (
                        occupied.start_ms if occupied is not None else None
                    )
                    self._clip_drag_occupied_end_ms = (
                        occupied.end_ms if occupied is not None else None
                    )
                    self._clip_snap_targets = self._build_clip_snap_targets(
                        track, clip.clip_id
                    )
                    self._clip_snap_result = ArrangementSnapResult(
                        clip.start_ms
                    )
                    self.setCursor(
                        Qt.ClosedHandCursor
                        if action_kind == "clip_body"
                        else Qt.SizeHorCursor
                    )
                    return
                if action == "lane":
                    self._select_track(track, emit=True)
                    self.set_selected_clip(track)
                    continue
                self._select_track(track, emit=True)
                if action == "track_volume":
                    self._volume_drag_track = track
                    self._volume_drag_rect = QRectF(rect)
                    self._volume_drag_initial = int(track.bdo_track_volume)
                    self._set_track_volume_from_position(track, rect, pos.x())
                elif action == "mute":
                    track.muted = not track.muted
                    self._update_accessible_track_state()
                    self.changed.emit()
                    self.track_state_changed.emit()
                elif action == "solo":
                    track.solo = not track.solo
                    self._update_accessible_track_state()
                    self.changed.emit()
                    self.track_state_changed.emit()
                elif action == "fx":
                    self.effects_requested.emit(track)
                self.update()
                return
        area, header_w, ruler_h, _lane_h = self._timeline_layout_metrics()
        ruler_rect = QRectF(
            area.left() + header_w,
            area.top(),
            max(0.0, area.width() - header_w),
            ruler_h,
        )
        if event.button() == Qt.LeftButton and ruler_rect.contains(pos):
            rel = max(
                0.0,
                min(
                    1.0,
                    (pos.x() - ruler_rect.left())
                    / max(1.0, ruler_rect.width()),
                ),
            )
            target = self.view_start_ms + rel * self._visible_duration_ms()
            selected = self.time_range
            handle_tolerance = self._visible_duration_ms() * 7.0 / max(
                1.0,
                ruler_rect.width(),
            )
            if selected and abs(target - selected[0]) <= handle_tolerance:
                self._range_drag_mode = "start"
                self._range_drag_anchor_ms = selected[1]
            elif selected and abs(target - selected[1]) <= handle_tolerance:
                self._range_drag_mode = "end"
                self._range_drag_anchor_ms = selected[0]
            else:
                self._range_drag_mode = "new"
                self._range_drag_anchor_ms = target
                self.set_time_range(target, target)
            self._range_drag_moved = False
            self.set_playhead(target)
            return
        if self.grid_rect.contains(pos):
            rel = max(0.0, min(1.0, (pos.x() - self.grid_rect.left()) / max(1.0, self.grid_rect.width())))
            target = self.view_start_ms + rel * self._visible_duration_ms()
            self.set_playhead(target)
            self.seek_requested.emit(self.playhead_ms)
            return
        if event.button() == Qt.LeftButton:
            self.dragging_timeline = True
            self.last_drag_x = pos.x()
            return
        super().mousePressEvent(event)

    def _select_arrangement_group(self, track: TrackState) -> None:
        group_id = str(track.arrangement_group_id or "")
        if group_id not in self._arrangement_groups:
            return
        self._selected_arrangement_group_id = group_id
        self._select_track(track, emit=True)

    def _show_arrangement_group_menu(
        self, track: TrackState, global_pos
    ) -> None:
        group_id = str(track.arrangement_group_id or "")
        group = self._arrangement_groups.get(group_id)
        if group is None:
            return
        menu = QMenu(self)
        title = menu.addAction(trf(
            "乐器组 · {instrument} · {count} 轨",
            instrument=_ui_bdo_instrument_name(group.instrument_id),
            count=group.count,
        ))
        title.setEnabled(False)
        menu.addSeparator()
        mute_action = menu.addAction(
            tr("取消整组静音")
            if all(item.muted for item in group.members)
            else tr("整组静音")
        )
        solo_action = menu.addAction(
            tr("取消整组独奏")
            if all(item.solo for item in group.members)
            else tr("整组独奏")
        )
        selected = menu.exec(global_pos)
        if selected is mute_action:
            self.group_control_requested.emit(group_id, "mute")
        elif selected is solo_action:
            self.group_control_requested.emit(group_id, "solo")

    def _show_instrument_menu(
        self,
        track: TrackState,
        global_pos,
        *,
        create_clip_at_ms: float | None = None,
    ) -> None:
        menu, actions = self._build_track_context_menu(
            track, create_clip_at_ms=create_clip_at_ms
        )
        selected = menu.exec(global_pos)
        if selected is None:
            return
        if selected is actions.get("create_clip"):
            self.clip_create_requested.emit(
                track, max(0.0, float(create_clip_at_ms))
            )
            return
        if selected is actions["edit_notes"]:
            self.note_editor_requested.emit(track)
            return
        if selected is actions["create_track"]:
            self._show_create_track_menu(global_pos)
            return
        if selected is actions["pitch"]:
            self.pitch_requested.emit(track)
            return
        if selected is actions["effects"]:
            self.effects_requested.emit(track)
            return
        if selected in {actions["move_up"], actions["move_down"]}:
            return
        if selected is actions["optimize"]:
            self.midi_tools_requested.emit(track)
            return
        if selected is actions["merge"]:
            self.merge_track_requested.emit(track)
            return
        if selected is actions["unify_mixer"]:
            self.mixer_unify_requested.emit(track)
            return
        if selected is actions["delete"]:
            self.delete_track_requested.emit(track)
            return
        if selected is actions["clear_solo"]:
            self.clear_solo_requested.emit()
            return
        if selected is actions["unmute_all"]:
            self.unmute_all_requested.emit()
            return
        inst_id = selected.data()
        if inst_id is None or inst_id == track.bdo_instrument_id:
            return
        previous_instrument_id = int(track.bdo_instrument_id)
        track.bdo_instrument_id = int(inst_id)
        self.instrument_changed.emit(track, previous_instrument_id)
        self.update()

    def _build_track_context_menu(
        self,
        track: TrackState,
        *,
        create_clip_at_ms: float | None = None,
    ) -> tuple[QMenu, dict[str, QAction]]:
        menu = QMenu(self)

        # Instrument selection and note editing are the two most frequent
        # lane operations, so they remain immediately reachable.
        create_clip_action = None
        if create_clip_at_ms is not None:
            create_clip_action = menu.addAction(tr("在此处创建片段"))
            create_clip_action.setData(float(create_clip_at_ms))
            menu.addSeparator()
        instrument_menu = menu.addMenu(tr("更换游戏乐器"))
        menu._instrument_menu = instrument_menu
        add_instrument_submenus(
            instrument_menu,
            track.bdo_instrument_id,
            _ui_bdo_instrument_names(),
        )
        instrument_menu.addSeparator()
        unify_mixer_action = instrument_menu.addAction(
            tr("以此轨统一同乐器音量和 FX")
        )
        edit_notes_action = menu.addAction(tr("编辑音符…"))

        menu.addSeparator()
        sound_menu = menu.addMenu(tr("音高与力度"))
        menu._sound_menu = sound_menu
        effects_action = sound_menu.addAction(tr("轨道 FX"))
        pitch_action = sound_menu.addAction(tr("轨道移调…"))
        pitch_action.setEnabled(
            not track_uses_percussion_pitch_semantics(track)
        )
        velocity_action = self._add_velocity_base_action(sound_menu, track)
        optimize_action = menu.addAction(tr("优化此轨道"))

        menu.addSeparator()
        track_menu = menu.addMenu(tr("轨道管理"))
        menu._track_menu = track_menu
        create_track_action = track_menu.addAction(tr("新建轨道"))
        merge_action = track_menu.addAction(tr("合并同乐器轨道…"))
        move_up_action, move_down_action = self._add_track_move_actions(
            track_menu,
            track,
        )
        track_menu.addSeparator()
        delete_action = track_menu.addAction(tr("删除轨道"))

        monitor_menu = menu.addMenu(tr("监听状态"))
        menu._monitor_menu = monitor_menu
        clear_solo_action = monitor_menu.addAction(tr("清除 Solo"))
        unmute_all_action = monitor_menu.addAction(tr("取消静音"))
        actions = {
            "edit_notes": edit_notes_action,
            "effects": effects_action,
            "pitch": pitch_action,
            "velocity": velocity_action,
            "optimize": optimize_action,
            "create_track": create_track_action,
            "merge": merge_action,
            "move_up": move_up_action,
            "move_down": move_down_action,
            "delete": delete_action,
            "unify_mixer": unify_mixer_action,
            "clear_solo": clear_solo_action,
            "unmute_all": unmute_all_action,
        }
        if create_clip_action is not None:
            actions["create_clip"] = create_clip_action
        return menu, actions

    def _add_velocity_base_action(
        self,
        menu: QMenu,
        track: TrackState,
    ) -> QAction:
        action = menu.addAction(tr("轨道力度基数…"))
        action.triggered.connect(
            lambda _checked=False: self.velocity_base_requested.emit(track)
        )
        return action

    def _add_track_move_actions(
        self,
        menu: QMenu,
        track: TrackState,
    ) -> tuple[QAction, QAction]:
        move_up_action = menu.addAction(tr("上移轨道"))
        move_down_action = menu.addAction(tr("下移轨道"))
        current = tuple(self.tracks)
        move_up_action.setEnabled(move_group_block(self.tracks, track, -1) != current)
        move_down_action.setEnabled(move_group_block(self.tracks, track, 1) != current)
        move_up_action.triggered.connect(
            lambda _checked=False: self.move_track_requested.emit(track, -1)
        )
        move_down_action.triggered.connect(
            lambda _checked=False: self.move_track_requested.emit(track, 1)
        )
        return move_up_action, move_down_action

    def _show_create_track_menu(self, global_pos) -> None:
        """Choose an instrument for a new musical lane from blank canvas space."""

        menu = QMenu(self)
        title = menu.addAction(tr("选择新轨道的 BDO 乐器"))
        title.setEnabled(False)
        menu.addSeparator()
        add_instrument_submenus(menu, -1, _ui_bdo_instrument_names())
        selected = menu.exec(global_pos)
        if selected is not None and selected.data() is not None:
            self.create_track_requested.emit(int(selected.data()))

    def mouseDoubleClickEvent(self, event) -> None:
        if self.velocity_curve_overlay.active:
            return
        if event.button() == Qt.LeftButton:
            for rect, marker in reversed(self._marker_label_regions):
                if rect.contains(event.position()):
                    self.marker_edit_requested.emit({"action": "rename", **marker})
                    return
            area, header_w, ruler_h, _lane_h = self._timeline_layout_metrics()
            ruler_rect = QRectF(area.left() + header_w, area.top(), max(0.0, area.width() - header_w), ruler_h)
            if ruler_rect.contains(event.position()):
                self.marker_edit_requested.emit({"action": "add", "time_ms": self._time_at_x(event.position().x())})
                return
            for rect, action, track in reversed(self.hit_regions):
                if track is self.reference_audio and rect.contains(event.position()):
                    if action in ("audio_lane", "audio_waveform"):
                        if not track.audio_path:
                            track.choose_audio(self)
                        return
                if (
                    isinstance(track, TrackState)
                    and (
                        action in ("lane", "select")
                        or action.startswith(("clip_body|", "clip_start|", "clip_end|"))
                    )
                    and rect.contains(event.position())
                ):
                    self.setFocus(Qt.MouseFocusReason)
                    self._select_track(track, emit=True)
                    clip_id = (
                        action.split("|", 1)[1]
                        if action.startswith(("clip_body|", "clip_start|", "clip_end|"))
                        else ""
                    )
                    if clip_id:
                        self.set_selected_clip(track, clip_id)
                        self.clip_note_editor_requested.emit(track, clip_id)
                    elif not track.notes and event.position().x() >= self.grid_rect.left():
                        self.clip_create_requested.emit(
                            track, self._time_at_x(event.position().x())
                        )
                    else:
                        self.note_editor_requested.emit(track)
                    return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        if self.velocity_curve_overlay.mouse_move(pos):
            return
        if self._volume_drag_track is not None:
            self._set_track_volume_from_position(
                self._volume_drag_track,
                self._volume_drag_rect,
                pos.x(),
            )
            return
        if self._clip_drag_source is not None:
            self._update_clip_drag_geometry(pos, event.modifiers())
            self.update()
            return
        if self._range_drag_anchor_ms is not None:
            area, header_w, _ruler_h, _lane_h = self._timeline_layout_metrics()
            grid_width = max(1.0, area.width() - header_w)
            rel = max(
                0.0,
                min(1.0, (pos.x() - (area.left() + header_w)) / grid_width),
            )
            target = self.view_start_ms + rel * self._visible_duration_ms()
            self._range_drag_moved = (
                self._range_drag_moved
                or abs(target - self._range_drag_anchor_ms)
                > self._visible_duration_ms() * 3.0 / grid_width
            )
            self.set_time_range(self._range_drag_anchor_ms, target)
            return
        if self.dragging_timeline:
            dx = pos.x() - self.last_drag_x
            self.last_drag_x = pos.x()
            if self.width() > 0:
                self.view_start_ms -= dx / max(1, self.width()) * self._visible_duration_ms()
                self._clamp_view()
                self.update()
                self.changed.emit()
            return
        hover_track: TrackState | None = None
        hover_on_badge = False
        for rect, action, item in reversed(self.hit_regions):
            if (
                action in {"validation_error", "validation_attention"}
                and isinstance(item, TrackState)
                and rect.contains(pos)
            ):
                hover_track = item
                hover_on_badge = True
                break
        if hover_track is None:
            for rect, action, item in reversed(self.hit_regions):
                if (
                    action == "lane"
                    and isinstance(item, TrackState)
                    and rect.contains(pos)
                    and self._track_validation_tooltip(item)
                ):
                    hover_track = item
                    break
        hover_track_id = (
            int(hover_track.track_id) if hover_track is not None else None
        )
        if hover_track_id != self._validation_hover_track_id:
            self._validation_hover_track_id = hover_track_id
            self.setToolTip(
                self._track_validation_tooltip(hover_track)
                if hover_track is not None
                else tr(self.KEYBOARD_SHORTCUT_HINT)
            )
        group_hover = next((
            item for rect, action, item in reversed(self.hit_regions)
            if action.startswith("group_")
            and isinstance(item, TrackState)
            and rect.contains(pos)
        ), None)
        if group_hover is not None:
            self.setToolTip(trf(
                "乐器组 · {instrument} · {count} 轨；点击组名选择整组，M/S 控制整组",
                instrument=_ui_bdo_instrument_name(group_hover.bdo_instrument_id),
                count=self._arrangement_group_counts.get(
                    group_hover.arrangement_group_id, 0
                ),
            ))
        clip_hover = next((
            action
            for rect, action, _item in reversed(self.hit_regions)
            if rect.contains(pos) and action.startswith("clip_")
        ), "")
        clip_hover_kind = clip_hover.partition("|")[0]
        if self.arrangement_tool == "razor" and clip_hover_kind.startswith("clip_"):
            self.setCursor(Qt.CrossCursor)
        elif clip_hover_kind in {"clip_start", "clip_end"}:
            self.setCursor(Qt.SizeHorCursor)
        elif clip_hover_kind == "clip_body":
            self.setCursor(Qt.OpenHandCursor)
        elif hover_on_badge or group_hover is not None:
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._validation_hover_track_id = None
        self.setToolTip(tr(self.KEYBOARD_SHORTCUT_HINT))
        self.unsetCursor()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self.velocity_curve_overlay.mouse_release(event.button()):
            return
        if self._volume_drag_track is not None:
            track = self._volume_drag_track
            previous_volume = int(self._volume_drag_initial)
            next_volume = int(track.bdo_track_volume)
            changed = (
                next_volume != previous_volume
            )
            self._volume_drag_track = None
            self._volume_drag_rect = QRectF()
            if changed:
                self.game_volume_committed.emit(
                    track,
                    previous_volume,
                    next_volume,
                )
            return
        if self._clip_drag_source is not None:
            # Some platforms deliver the final pointer coordinate only with
            # mouse release, so apply snapping once more before committing.
            pointer_moved = (
                event.position() - self._clip_drag_press_pos
            ).manhattanLength() >= QApplication.startDragDistance()
            if pointer_moved:
                self._update_clip_drag_geometry(
                    event.position(), event.modifiers()
                )
            source = self._clip_drag_source
            target = self._clip_drag_target or source
            request = TimelineClipEditRequest(
                source,
                target,
                self._clip_drag_mode,
                self._clip_drag_start_ms,
                self._clip_drag_end_ms,
                self._clip_drag_id,
            )
            self._clip_drag_source = None
            self._clip_drag_target = None
            self._clip_drag_mode = ""
            self._clip_drag_id = ""
            self._clip_drag_occupied_start_ms = None
            self._clip_drag_occupied_end_ms = None
            self._clip_drag_press_pos = QPointF()
            self._clip_snap_targets = ArrangementSnapIndex((), ())
            self._clip_snap_result = ArrangementSnapResult(0.0)
            self.unsetCursor()
            changed = (
                pointer_moved
                and (
                    target is not source
                or not math.isclose(
                    request.new_start_ms,
                    self._clip_drag_origin_start_ms,
                    abs_tol=1e-6,
                )
                or not math.isclose(
                    request.new_end_ms,
                    self._clip_drag_origin_end_ms,
                    abs_tol=1e-6,
                )
                )
            )
            if changed:
                self.clip_edit_requested.emit(request)
            self.update()
            return
        if self._range_drag_anchor_ms is not None:
            if not self._range_drag_moved:
                target = self._range_drag_anchor_ms
                self.set_time_range(None, None)
                self.set_playhead(target)
                self.seek_requested.emit(self.playhead_ms)
            else:
                self.time_range_changed.emit(self.time_range)
            self._range_drag_anchor_ms = None
            self._range_drag_mode = ""
            self._range_drag_moved = False
            return
        self.dragging_timeline = False
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        angle = event.angleDelta()
        delta = angle.x() or angle.y()
        if not delta:
            super().wheelEvent(event)
            return
        if event.modifiers() & Qt.ControlModifier:
            step = 1.12 if delta > 0 else 1 / 1.12
            center = self.view_start_ms + self._visible_duration_ms() / 2
            self.zoom_factor = max(0.25, min(32.0, self.zoom_factor * step))
            self.view_start_ms = center - self._visible_duration_ms() / 2
        elif angle.x() or (event.modifiers() & Qt.ShiftModifier):
            self.view_start_ms += (delta / 120.0) * self._visible_duration_ms() * 0.12
        else:
            if self.track_scroll.isVisible():
                self.track_scroll.setValue(self.track_scroll.value() - int(delta / 120.0 * self._lane_height()))
            else:
                self.view_start_ms += (delta / 120.0) * self._visible_duration_ms() * 0.12
        self._clamp_view()
        self.update()
        self.changed.emit()

    def keyPressEvent(self, event) -> None:
        if self.velocity_curve_overlay.key_press(event):
            return
        key = event.key()
        modifiers = event.modifiers()
        navigation_keys = {
            Qt.Key_Up,
            Qt.Key_Down,
            Qt.Key_Home,
            Qt.Key_End,
        }
        if key in navigation_keys and not (
            modifiers & (Qt.ControlModifier | Qt.AltModifier)
        ):
            if not self.tracks:
                event.accept()
                return
            current = self._selected_track_index()
            if key == Qt.Key_Home:
                target_index = 0
            elif key == Qt.Key_End:
                target_index = len(self.tracks) - 1
            elif current is None:
                target_index = 0
            else:
                step = -1 if key == Qt.Key_Up else 1
                target_index = max(
                    0,
                    min(len(self.tracks) - 1, current + step),
                )
            self._select_track(self.tracks[target_index], emit=True)
            event.accept()
            return

        track_index = self._selected_track_index()
        track = self.tracks[track_index] if track_index is not None else None
        if track is None:
            super().keyPressEvent(event)
            return
        if modifiers & Qt.ControlModifier and key == Qt.Key_C and self._selected_clip_id:
            self.clip_copy_requested.emit(track, self._selected_clip_id)
            event.accept()
            return
        if modifiers & Qt.ControlModifier and key == Qt.Key_V:
            self.clip_paste_requested.emit(track, self.playhead_ms)
            event.accept()
            return
        if (
            key in (Qt.Key_Delete, Qt.Key_Backspace)
            and modifiers == Qt.NoModifier
            and self._selected_clip_id
            and self._selected_clip_track_id == int(track.track_id)
        ):
            self.clip_delete_requested.emit(
                track, self._selected_clip_id
            )
            event.accept()
            return
        plain_shortcut = not (
            modifiers & (Qt.ControlModifier | Qt.AltModifier)
        )
        if plain_shortcut and key == Qt.Key_M:
            track.muted = not track.muted
            self._update_accessible_track_state()
            self.changed.emit()
            self.track_state_changed.emit()
            self.update()
            event.accept()
            return
        if plain_shortcut and key == Qt.Key_S:
            track.solo = not track.solo
            self._update_accessible_track_state()
            self.changed.emit()
            self.track_state_changed.emit()
            self.update()
            event.accept()
            return
        if plain_shortcut and key == Qt.Key_F:
            self.effects_requested.emit(track)
            event.accept()
            return
        if plain_shortcut and key in (Qt.Key_Return, Qt.Key_Enter):
            self.note_editor_requested.emit(track)
            event.accept()
            return
        volume_direction = (
            1
            if key in (Qt.Key_Right, Qt.Key_Plus, Qt.Key_Equal)
            else -1
            if key in (Qt.Key_Left, Qt.Key_Minus)
            else 0
        )
        if plain_shortcut and volume_direction:
            step = 5 if modifiers & Qt.ShiftModifier else 1
            value = max(
                0,
                min(
                    100,
                    int(track.bdo_track_volume)
                    + volume_direction * step,
                ),
            )
            if value != int(track.bdo_track_volume):
                previous_volume = int(track.bdo_track_volume)
                track.bdo_track_volume = value
                self._update_accessible_track_state()
                self.game_volume_committed.emit(
                    track,
                    previous_volume,
                    value,
                )
                self.update()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event) -> None:
        self._update_accessible_track_state()
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        self.update()
        super().focusOutEvent(event)
