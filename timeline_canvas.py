"""Custom-painted, visible-range-indexed multitrack timeline canvas."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
import math
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QScrollBar, QWidget

from bdo_instrument_adaptation import instrument_editor_display_adaptations
from bdo_instrument_lane_art_qt import (
    InstrumentLaneArtwork,
    instrument_header_background_rect,
    paint_instrument_header_background,
)
from bdo_midi import BDO_NOTE_MAX, BDO_NOTE_MIN, _GM_TO_BDO_DRUM
from bdo_midi.instruments import (
    localized_bdo_instrument_name,
    localized_bdo_instrument_names,
)
from editor_models import (
    BDO_DRUM_MAX,
    BDO_DRUM_MIN,
    TrackState,
    game_supported_pitches,
    track_uses_canonical_drum_lanes,
)
from editor_ui_helpers import add_instrument_submenus, articulation_color
from i18n import tr, trf, trv
from pitch_transform import PitchTransformPlan
from project_paths import ASSETS_DIR


TIMELINE_BACKGROUND_IMAGE = ASSETS_DIR / "ui" / "timeline_background_v2.png"
TIMELINE_BACKGROUND_OPACITY = 0.24


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
    instrument_changed = Signal(object)
    selected = Signal(object)
    validation_requested = Signal(object)
    effects_requested = Signal(object)
    pitch_requested = Signal(object)
    midi_tools_requested = Signal(object)
    note_editor_requested = Signal(object)
    seek_requested = Signal(float)
    time_range_changed = Signal(object)
    playhead_changed = Signal(float)
    TRACK_NOTE_QUERY_BLOCK_SIZE = 128
    GRID_MIN_TICK_SPACING_PX = 56.0
    MEASURE_BANDING_MIN_WIDTH_PX = 72.0
    KEYBOARD_SHORTCUT_HINT = (
        "上下键选择轨道；M 静音；S 独奏；F 打开效果；"
        "Enter 编辑音符；左右键调整轨道音量（Shift 5）"
    )

    def __init__(self) -> None:
        super().__init__()
        self.tracks: list[TrackState] = []
        self.hit_regions: list[tuple[QRectF, str, object]] = []
        self.track_validation_notices: dict[
            int, dict[str, tuple[str, ...]]
        ] = {}
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
        self.selected_track: TrackState | None = None
        self.pitch_transform_plan = PitchTransformPlan()
        self.conversion_transpose = 0
        self.background_pixmap = QPixmap(str(TIMELINE_BACKGROUND_IMAGE)) if TIMELINE_BACKGROUND_IMAGE.is_file() else QPixmap()
        self._scaled_background = QPixmap()
        self._scaled_background_size = QSize()
        self._instrument_adaptations = instrument_editor_display_adaptations()
        self.instrument_lane_art = InstrumentLaneArtwork()
        self.track_scroll = QScrollBar(Qt.Vertical, self)
        # Entries keep the original first five fields for the pitch/range
        # helpers, followed by exact ends and a block-max segment tree used by
        # interval viewport queries.
        self._track_note_indexes: dict[int, tuple] = {}
        self._last_track_note_query_inspections = 0
        self._conversion_problem_cache: dict[tuple[object, ...], bool] = {}
        self._timeline_end_cache = 1.0
        self.track_scroll.setObjectName("TimelineScroll")
        self.track_scroll.valueChanged.connect(self.update)
        self.setObjectName("TimelineCanvas")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(tr("轨道时间轴"))
        self.setToolTip(tr(self.KEYBOARD_SHORTCUT_HINT))
        self.setStatusTip(tr(self.KEYBOARD_SHORTCUT_HINT))
        self._update_accessible_track_state()
        self.setMouseTracking(True)
        self.setMinimumHeight(380)

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
        self.update()
        return loaded

    def set_tracks(self, tracks: list[TrackState]) -> None:
        self.tracks = tracks
        if not any(track is self.selected_track for track in tracks):
            self.selected_track = None
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

    def set_validation_notices(
        self,
        notices: dict[int, dict[str, tuple[str, ...]]],
    ) -> None:
        """Apply export errors and non-blocking attention marks by track ID."""

        valid_track_ids = {int(track.track_id) for track in self.tracks}
        normalized: dict[int, dict[str, tuple[str, ...]]] = {}
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
            if errors or attentions:
                normalized[track_id] = {
                    "errors": errors,
                    "attentions": attentions,
                }
        if normalized == self.track_validation_notices:
            return
        self.track_validation_notices = normalized
        self._validation_hover_track_id = None
        self.setToolTip(tr(self.KEYBOARD_SHORTCUT_HINT))
        self._update_accessible_track_state()
        self.update()

    def _track_validation_notice(
        self,
        track: TrackState,
    ) -> dict[str, tuple[str, ...]]:
        return self.track_validation_notices.get(
            int(track.track_id),
            {"errors": (), "attentions": ()},
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
        self._rebuild_track_indexes()
        self.playhead_ms = min(self.playhead_ms, self._timeline_end_ms())
        self._clamp_view()
        self._update_track_scrollbar()
        self.update()

    def _timeline_row_count(self) -> int:
        return len(self.tracks) + (1 if self.reference_audio is not None else 0)

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

    def _rebuild_track_indexes(self) -> None:
        self._track_note_indexes = {}
        self._conversion_problem_cache.clear()
        timeline_end = 1.0
        for track in self.tracks:
            ordered = sorted(track.notes, key=lambda note: note.start)
            starts = [float(note.start) for note in ordered]
            scaled_durations = [
                float(note.dur) * track.duration_scale
                for note in ordered
            ]
            max_duration = max(scaled_durations, default=0.0)
            ends = [
                start + duration
                for start, duration in zip(starts, scaled_durations)
            ]
            block_size = self.TRACK_NOTE_QUERY_BLOCK_SIZE
            block_count = (len(ends) + block_size - 1) // block_size
            tree_base = 1 << max(0, (block_count - 1).bit_length())
            block_max_tree = [float("-inf")] * (tree_base * 2)
            for block_index in range(block_count):
                block_start = block_index * block_size
                block_stop = min(len(ends), block_start + block_size)
                block_max_tree[tree_base + block_index] = max(
                    ends[block_start:block_stop],
                    default=float("-inf"),
                )
            for node in range(tree_base - 1, 0, -1):
                block_max_tree[node] = max(
                    block_max_tree[node * 2],
                    block_max_tree[node * 2 + 1],
                )
            pitch_min = min((note.pitch for note in ordered), default=0)
            pitch_max = max((note.pitch for note in ordered), default=0)
            self._track_note_indexes[id(track)] = (
                starts,
                ordered,
                max_duration,
                pitch_min,
                pitch_max,
                ends,
                block_max_tree,
                tree_base,
            )
            timeline_end = max(
                timeline_end,
                max(ends, default=0.0),
            )
        if self.reference_audio is not None:
            timeline_end = max(timeline_end, self.reference_audio.project_end_ms)
        self._timeline_end_cache = timeline_end

    def _visible_track_notes(self, track: TrackState, start: float, end: float) -> list:
        ordered, lo, hi = self._visible_track_note_window(track, start, end)
        if lo == 0 and hi == len(ordered):
            return ordered
        return ordered[lo:hi]

    def _visible_track_note_window(
        self, track: TrackState, start: float, end: float,
    ) -> tuple[list, int, int]:
        self._last_track_note_query_inspections = 0
        index = self._track_note_indexes.get(id(track))
        if index is None:
            self._rebuild_track_indexes()
            index = self._track_note_indexes.get(
                id(track),
                ([], [], 0.0, 0, 0, [], [float("-inf"), float("-inf")], 1),
            )
        (
            starts,
            ordered,
            _max_duration,
            _pitch_min,
            _pitch_max,
            ends,
            block_max_tree,
            tree_base,
        ) = index
        hi = bisect_right(starts, end)
        if hi <= 0:
            return [], 0, 0

        block_size = self.TRACK_NOTE_QUERY_BLOCK_SIZE
        last_block = (hi - 1) // block_size
        matching_blocks: list[int] = []
        # Prefix-range + maximum-end pruning is a small segment-tree query:
        # future blocks are discarded by range and old blocks whose notes have
        # all ended are discarded without inspecting individual notes.
        stack = [(1, 0, tree_base)]
        while stack:
            node, node_start, node_stop = stack.pop()
            if node_start > last_block or block_max_tree[node] < start:
                continue
            if node_stop - node_start == 1:
                matching_blocks.append(node_start)
                continue
            midpoint = (node_start + node_stop) // 2
            stack.append((node * 2 + 1, midpoint, node_stop))
            stack.append((node * 2, node_start, midpoint))

        visible: list = []
        for block_index in matching_blocks:
            block_start = block_index * block_size
            block_stop = min(hi, block_start + block_size)
            self._last_track_note_query_inspections += block_stop - block_start
            for note_index in range(block_start, block_stop):
                if ends[note_index] >= start:
                    visible.append(ordered[note_index])
        return visible, 0, len(visible)

    def _track_pitch_bounds(self, track: TrackState) -> tuple[int, int]:
        index = self._track_note_indexes.get(id(track))
        if index is None:
            self._rebuild_track_indexes()
            index = self._track_note_indexes.get(id(track), ([], [], 0.0, 0, 0))
        return index[3], index[4]

    def set_selected_track(self, track: TrackState | None) -> None:
        self._select_track(track, emit=False)

    def _select_track(
        self,
        track: TrackState | None,
        *,
        emit: bool,
    ) -> None:
        self.selected_track = track
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

    def _note_has_conversion_problem(self, track: TrackState, pitch: int) -> bool:
        canonical_drum_lanes = track_uses_canonical_drum_lanes(track)
        effective_transpose = self.pitch_transform_plan.effective_semitones(
            track.track_id,
            is_drum=bool(track.is_percussion),
        )
        cache_key = (
            int(track.bdo_instrument_id),
            str(track.marnian_synth_mode),
            int(pitch),
            effective_transpose,
            canonical_drum_lanes,
        )
        cached = self._conversion_problem_cache.get(cache_key)
        if cached is not None:
            return cached
        if track.bdo_instrument_id == 0x0d:
            if canonical_drum_lanes:
                supported = game_supported_pitches(
                    track.bdo_instrument_id, track.marnian_synth_mode
                )
                result = not (
                    BDO_DRUM_MIN <= int(pitch) <= BDO_DRUM_MAX
                    and (supported is None or int(pitch) in supported)
                )
            else:
                mapped_pitch = _GM_TO_BDO_DRUM.get(pitch)
                if (
                    mapped_pitch is None
                    or mapped_pitch < BDO_DRUM_MIN
                    or mapped_pitch > BDO_DRUM_MAX
                ):
                    result = True
                else:
                    supported = game_supported_pitches(
                        track.bdo_instrument_id, track.marnian_synth_mode
                    )
                    result = (
                        supported is not None
                        and mapped_pitch not in supported
                    )
        else:
            converted_pitch = pitch + effective_transpose
            supported = game_supported_pitches(
                track.bdo_instrument_id, track.marnian_synth_mode
            )
            if supported is not None:
                result = converted_pitch not in supported
            else:
                result = converted_pitch < BDO_NOTE_MIN or converted_pitch > BDO_NOTE_MAX
        self._conversion_problem_cache[cache_key] = result
        return result

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
        new_zoom = max(1.0, min(8.0, value / 100.0))
        if math.isclose(new_zoom, self.zoom_factor):
            return
        old_duration = self._visible_duration_ms()
        center = self.view_start_ms + old_duration / 2
        self.zoom_factor = new_zoom
        self.view_start_ms = center - self._visible_duration_ms() / 2
        self._clamp_view()
        self.update()
        self.changed.emit()

    def set_pan_percent(self, value: int) -> None:
        max_start = max(0.0, self._timeline_end_ms() - self._visible_duration_ms())
        new_start = max_start * max(0, min(1000, value)) / 1000.0
        if math.isclose(new_start, self.view_start_ms, abs_tol=0.5):
            return
        self.view_start_ms = new_start
        self._clamp_view()
        self.update()
        self.changed.emit()

    def pan_percent(self) -> int:
        max_start = max(0.0, self._timeline_end_ms() - self._visible_duration_ms())
        if max_start <= 0:
            return 0
        return round(self.view_start_ms / max_start * 1000)

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
            # merge attention remains available in the tooltip/check dialog
            # but never splits an error lane into competing red/amber states.
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
                painter.fillRect(
                    QRectF(left, y, header_w, lane_h),
                    QColor(184, 128, 47, 24),
                )
                painter.fillRect(
                    QRectF(left, y, 5.0, lane_h),
                    QColor("#d1a24d"),
                )
            else:
                track_identity_color = QColor(
                    track.color if active else "#4a4743"
                )
                painter.fillRect(
                    QRectF(left, y, 3.0, lane_h),
                    track_identity_color,
                )

            validation_badges: list[tuple[str, str, QColor, float]] = []
            if validation_errors:
                validation_badges.append(
                    ("!", "error", QColor("#d9635d"), y + 7.0)
                )
            elif validation_attentions:
                validation_badges.append(
                    ("=", "attention", QColor("#d1a24d"), y + 7.0)
                )
            for marker, notice_kind, accent, badge_y in validation_badges:
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
                self.hit_regions.append(
                    (
                        badge_rect,
                        f"validation_{notice_kind}",
                        track,
                    )
                )

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
            volume_label = tr("音量")
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

            meter_level = self.track_levels.get(int(track.track_id), 0.0) if active else 0.0
            meter_rect = QRectF(left + header_w - 14, y + 8, 7, lane_h - 16)
            segment_count = 10
            segment_gap = 1.0
            segment_height = (meter_rect.height() - segment_gap * (segment_count - 1)) / segment_count
            lit_segments = min(segment_count, math.ceil(meter_level * segment_count))
            painter.setPen(Qt.NoPen)
            for segment in range(segment_count):
                segment_y = meter_rect.bottom() - (segment + 1) * segment_height - segment * segment_gap
                if segment < lit_segments:
                    color = "#d05c4f" if segment >= 9 else ("#caa24f" if segment >= 7 else "#83a543")
                else:
                    color = "#343438"
                painter.fillRect(QRectF(meter_rect.left(), segment_y, meter_rect.width(), segment_height), QColor(color))

            # No nested horizontal gutter: the colored note region shares the
            # grid's exact left/right edge, while retaining a little vertical
            # breathing room between adjacent lanes.
            region_rect = QRectF(grid_left, y + 9, grid_w, lane_h - 18)
            region_bg = QColor("#253022" if focused and active else "#242427")
            region_bg.setAlpha(152 if active else 116)
            painter.setBrush(region_bg)
            painter.setPen(QPen(QColor("#735b2d" if focused else "#3b3b3f"), 1))
            painter.drawRect(region_rect)

            if track.notes:
                pitch_min, pitch_max = self._track_pitch_bounds(track)
                pitch_span = max(1, pitch_max - pitch_min)
                painter.save()
                painter.setClipRect(region_rect)
                normal_rects: list[QRectF] = []
                articulation_markers: dict[str, list[QRectF]] = {}
                invalid_rects: list[QRectF] = []
                ordered, note_lo, note_hi = self._visible_track_note_window(
                    track, visible_start, visible_end,
                )
                for note_index in range(note_lo, min(note_hi, note_lo + 2600)):
                    note = ordered[note_index]
                    scaled_dur = note.dur * track.duration_scale
                    note_end = note.start + scaled_dur
                    if note_end < visible_start or note.start > visible_end:
                        continue
                    x = region_rect.left() + ((note.start - visible_start) / visible_duration) * region_rect.width()
                    w = max(2.5, (scaled_dur / visible_duration) * region_rect.width())
                    pitch_pos = (note.pitch - pitch_min) / pitch_span
                    note_y = region_rect.top() + 6 + (1.0 - pitch_pos) * (region_rect.height() - 14)
                    note_rect = QRectF(x, note_y, w, 5.0)
                    if self._note_has_conversion_problem(track, note.pitch):
                        invalid_rects.append(note_rect)
                    else:
                        normal_rects.append(note_rect)
                        ntype = int(getattr(note, "ntype", 0))
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
            inst_name = _ui_bdo_instrument_name(track.bdo_instrument_id)
            metadata = trf(
                "{instrument} · {count} 音符",
                instrument=inst_name,
                count=track.note_count,
            )
            metadata_font = painter.font()
            metadata_font.setPointSize(max(7, metadata_font.pointSize() - 1))
            painter.save()
            painter.setFont(metadata_font)
            metadata_left = left + 12.0
            metadata_right = volume_label_rect.left() - 6.0
            metadata_width = max(0.0, metadata_right - metadata_left)
            painter.drawText(
                QRectF(metadata_left, y + 39, metadata_width, 20),
                Qt.AlignLeft | Qt.AlignVCenter,
                painter.fontMetrics().elidedText(
                    metadata,
                    Qt.ElideRight,
                    max(0, int(metadata_width - 4.0)),
                ),
            )
            painter.restore()
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
                visible_end,
            )

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

        position = controller.project_position_ms
        if controller.audio_path and visible_start <= position <= visible_end:
            position_x = waveform_rect.left() + (
                (position - visible_start) / visible_duration
            ) * waveform_rect.width()
            painter.fillRect(
                QRectF(position_x, waveform_rect.top(), 1.5, waveform_rect.height()),
                QColor("#f4e3bd"),
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
            trf("轨道 · {count}", count=self._timeline_row_count()),
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

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        self._paint_canvas_background(painter)
        self.hit_regions = []

        area, header_w, ruler_h, lane_h = self._timeline_layout_metrics()
        if self._timeline_row_count() <= 0:
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
        left, top, grid_left, grid_top = self._paint_timeline_shell(
            painter, area, header_w, ruler_h, grid_w, grid_h
        )
        self.grid_rect = QRectF(grid_left, top, grid_w, grid_h + ruler_h)
        bars = self._paint_grid_ruler(
            painter, left, top, grid_left, grid_top, grid_w, grid_h, visible_start, visible_duration
        )
        play_x = self._paint_playhead(
            painter, top, grid_left, grid_top, grid_w, grid_h,
            visible_start, visible_duration, visible_end, grid_h
        )
        self._paint_track_rows(
            painter, left, grid_left, grid_top, header_w, grid_w, grid_h,
            lane_h, visible_start, visible_duration, visible_end
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
        self._paint_ruler_overlay(
            painter, area, left, top, grid_left, grid_top, grid_w, grid_h,
            ruler_h, bars, visible_start, visible_duration, play_x
        )
        if self.buffer_visible:
            buffer_y = grid_top - 3
            painter.fillRect(QRectF(grid_left, buffer_y, grid_w, 3), QColor("#30383a"))
            if self.buffer_progress > 0:
                painter.fillRect(
                    QRectF(grid_left, buffer_y, grid_w * self.buffer_progress, 3),
                    QColor("#55b8ad"),
                )

    def mousePressEvent(self, event) -> None:
        pos = event.position()
        self.setFocus(Qt.MouseFocusReason)
        if event.button() == Qt.RightButton:
            for rect, _action, track in reversed(self.hit_regions):
                if rect.contains(pos) and isinstance(track, TrackState):
                    self._select_track(track, emit=True)
                    self._show_instrument_menu(track, event.globalPosition().toPoint())
                    return
            super().mousePressEvent(event)
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
                if action == "lane":
                    continue
                self._select_track(track, emit=True)
                if action in {"validation_error", "validation_attention"}:
                    self.validation_requested.emit(
                        (track, action.removeprefix("validation_"))
                    )
                elif action == "track_volume":
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

    def _show_instrument_menu(self, track: TrackState, global_pos) -> None:
        menu = QMenu(self)
        edit_notes_action = menu.addAction(tr("编辑音符…"))
        pitch_action = menu.addAction(tr("轨道八度…"))
        pitch_action.setEnabled(
            not track.is_percussion and int(track.bdo_instrument_id) != 0x0D
        )
        menu.addSeparator()
        optimize_action = menu.addAction(tr("优化此轨道"))
        menu.addSeparator()
        current_id = track.bdo_instrument_id
        title = menu.addAction(tr("更换乐器"))
        title.setEnabled(False)
        menu.addSeparator()
        add_instrument_submenus(menu, current_id, _ui_bdo_instrument_names())
        selected = menu.exec(global_pos)
        if selected is None:
            return
        if selected is edit_notes_action:
            self.note_editor_requested.emit(track)
            return
        if selected is pitch_action:
            self.pitch_requested.emit(track)
            return
        if selected is optimize_action:
            self.midi_tools_requested.emit(track)
            return
        inst_id = selected.data()
        if inst_id is None or inst_id == track.bdo_instrument_id:
            return
        track.bdo_instrument_id = int(inst_id)
        self.changed.emit()
        self.instrument_changed.emit(track)
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            for rect, action, track in reversed(self.hit_regions):
                if track is self.reference_audio and rect.contains(event.position()):
                    if action in ("audio_lane", "audio_waveform"):
                        if not track.audio_path:
                            track.choose_audio(self)
                        return
                if (
                    isinstance(track, TrackState)
                    and action in ("lane", "select")
                    and rect.contains(event.position())
                ):
                    self.setFocus(Qt.MouseFocusReason)
                    self._select_track(track, emit=True)
                    self.note_editor_requested.emit(track)
                    return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        if self._volume_drag_track is not None:
            self._set_track_volume_from_position(
                self._volume_drag_track,
                self._volume_drag_rect,
                pos.x(),
            )
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
        if hover_on_badge:
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
        if self._volume_drag_track is not None:
            changed = (
                int(self._volume_drag_track.bdo_track_volume)
                != self._volume_drag_initial
            )
            self._volume_drag_track = None
            self._volume_drag_rect = QRectF()
            if changed:
                self.changed.emit()
                self.track_state_changed.emit()
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
            self.zoom_factor = max(1.0, min(8.0, self.zoom_factor * step))
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
                track.bdo_track_volume = value
                self._update_accessible_track_state()
                self.changed.emit()
                self.track_state_changed.emit()
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
