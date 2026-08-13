"""Packaged piano-roll and velocity-lane canvases for the track editor."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Iterable
import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QMenu, QWidget

from bdo_midi import Note
from bdo_music_composer.ui.transcription.bdo_spectrogram_qt import SpectrogramTileController
from bdo_music_composer.audio.reference_audio_format import ReferenceAudioFormatError
from bdo_music_composer.transcription.bdo_transcription import TranscriptionCandidate
from bdo_music_composer.ui.transcription.bdo_transcription_evidence_qt import (
    ContourColorSpan,
    EvidenceTileController,
)
from bdo_music_composer.transcription.bdo_transcription_melody_lines import (
    BASS_ROLE as MELODY_LINE_BASS_ROLE,
    CHORD_SPAN_KIND as MELODY_LINE_CHORD_SPAN_KIND,
    CONFIDENCE_BUCKETS as MELODY_LINE_CONFIDENCE_BUCKETS,
    CONNECTOR_KIND as MELODY_LINE_CONNECTOR_KIND,
    CONTOUR_KIND as MELODY_LINE_CONTOUR_KIND,
    GUIDE_ROLES as MELODY_LINE_GUIDE_ROLES,
    HARMONY_ROLE as MELODY_LINE_HARMONY_ROLE,
    PRIMARY_ROLE as MELODY_LINE_PRIMARY_ROLE,
    MelodyLineSegment,
    build_melody_line_segments,
    melody_line_confidence_bucket,
    melody_line_kind_visible,
    melody_line_lod,
    melody_line_width,
)
from bdo_music_composer.transcription.bdo_transcription_policy import CANDIDATE_NOTE_POLICY
from bdo_music_composer.editor.editor_models import GhostNoteProjection, note_name
from bdo_music_composer.editor.timeline_markers import normalize_timeline_markers
from .editor_ui_helpers import (
    TRACK_COLORS,
    articulation_color,
)
from .editor_shortcuts import resolve_editor_key_command
from bdo_music_composer.ui.i18n import tr, trf, trv
from bdo_music_composer.ui.transcription.transcription_editor_qt import voice_role_label, voice_role_source_label
from bdo_music_composer.editor.velocity_curve import (
    velocity_neighbor_weight,
    velocity_time_points,
)


class PianoRollCanvas(QWidget):
    """Compact, dependency-free piano roll used by the per-track note editor."""

    selection_changed = Signal()
    notes_changed = Signal()
    hover_changed = Signal(float, int)
    ruler_seek_requested = Signal(float)
    candidate_selection_changed = Signal(object)
    time_range_changed = Signal(object)
    chord_segment_clicked = Signal(str)
    voice_group_split_requested = Signal(str, float)
    voice_group_merge_requested = Signal(str, str)
    voice_group_color_requested = Signal(str, str)
    voice_group_role_requested = Signal(str, str)
    marker_edit_requested = Signal(object)
    PIANO_KEY_W = 86
    NAMED_PERCUSSION_KEY_W = 138
    KEY_W = PIANO_KEY_W
    BLACK_KEY_X = 8
    BLACK_KEY_W = 48
    TIME_RULER_H = 31
    CHORD_H = 26
    RULER_H = TIME_RULER_H + CHORD_H
    ROW_H = 24
    MIN_ROW_H = 10.0
    MAX_ROW_H = 72.0
    MIN_PX_PER_BEAT = 8.0
    MAX_PX_PER_BEAT = 1600.0
    NOTE_RESIZE_VISUAL_MIN_WIDTH = 12.0
    NOTE_VELOCITY_MIN_WIDTH = 16.0
    NOTE_VELOCITY_SIDE_INSET = 5.0
    NOTE_VELOCITY_BOTTOM_INSET = 2.0
    NOTE_VELOCITY_BAR_HEIGHT = 4.0
    NOTE_TEXT_MIN_HEIGHT = 13.0
    NOTE_VELOCITY_MIN_HEIGHT = 15.0
    NOTE_RESIZE_HANDLE_MIN_HEIGHT = 15.0
    NOTE_TECHNIQUE_BADGE_MIN_HEIGHT = 18.0
    PIANO_FULL_LABEL_MIN_ROW_HEIGHT = 15.0
    MIN_PITCH = 0
    MAX_PITCH = 127
    CANDIDATE_QUERY_BLOCK_SIZE = 128
    MAX_CANDIDATE_CONTINUITY_GAP_MS = 80.0
    MAX_MELODY_LINE_SOURCE_CANDIDATES = 2048
    _MELODY_LINE_FEATURES_PER_BLOCK = 5

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.editor = editor
        self.KEY_W = (
            self.NAMED_PERCUSSION_KEY_W
            if getattr(self.editor, "uses_named_percussion_keys", False)
            else self.PIANO_KEY_W
        )
        self.notes: list = []
        self.timeline_markers: list[dict[str, object]] = []
        self._timeline_marker_times: tuple[float, ...] = ()
        self._marker_label_regions: list[tuple[QRectF, dict[str, object]]] = []
        self._marker_delete_regions: list[tuple[QRectF, dict[str, object]]] = []
        self.ghost_notes: list = []
        self._ghost_opacity = 0.24
        self.transcription_candidates: list[TranscriptionCandidate] = []
        self.transcription_candidates_visible = False
        self._transcription_candidate_layer_visible = True
        self._transcription_candidate_opacity = 0.52
        self._transcription_candidate_ids: list[str] = []
        self._transcription_candidate_id_to_index: dict[str, int] = {}
        self._folded_candidate_primary: dict[str, str] = {}
        self._fold_alternative_counts: dict[str, int] = {}
        self._fold_alternative_rank: dict[str, int] = {}
        self._selected_candidate_ids: set[str] = set()
        self._rejected_candidate_ids: set[str] = set()
        self._pending_candidate_ids: set[str] = set()
        self._applied_candidate_ids: set[str] = set()
        self._invalid_candidate_ids: set[str] = set()
        self._duplicate_candidate_ids: set[str] = set()
        self._staged_candidate_ids: set[str] = set()
        self._fragment_candidate_ids: set[str] = set()
        self._continuity_candidate_ids: set[str] = set()
        self._suppressed_candidate_ids: set[str] = set()
        self._confidence_floor = 0.30
        self._show_rejected_only = False
        self._audio_offset_ms = 0.0
        self._candidate_visual_revision = 0
        self._contour_clip_cache_key: tuple[object, ...] | None = None
        self._contour_clip_cache = QPainterPath()
        self._contour_clip_build_count = 0
        self._evidence_descriptor = None
        self._show_contour_evidence = False
        self._contour_denoise_profile = "standard"
        # Clean review is the default.  Dense posterior layers remain
        # available as explicit diagnostic evidence instead of competing with
        # editable semantic note blocks.
        self._show_frame_evidence = False
        self._show_onset_evidence = False
        self._evidence = EvidenceTileController(self)
        self._evidence.tile_ready.connect(self._evidence_tile_ready)
        self._show_spectrogram = False
        self._reference_background_opacity = 0.45
        self._contour_opacity = 0.82
        self._spectrogram_audio_path = ""
        self._spectrogram = SpectrogramTileController(self)
        self._spectrogram.tile_ready.connect(self._evidence_tile_ready)
        self._show_melody_lines = False
        self._melody_line_roles_visible = frozenset(
            {MELODY_LINE_PRIMARY_ROLE}
        )
        self._melody_line_segments: tuple[MelodyLineSegment, ...] = ()
        self._melody_line_starts: list[float] = []
        self._melody_line_ends: list[float] = []
        self._melody_line_block_max_ends: list[float] = []
        self._melody_line_projection_key: tuple[object, ...] | None = None
        self._last_melody_line_query_inspections = 0
        self._candidate_group_colors: dict[str, str] = {}
        self._candidate_group_ids: dict[str, str] = {}
        self._candidate_group_confidences: dict[str, float] = {}
        self._candidate_group_class_confidences: dict[str, float] = {}
        self._candidate_group_emphases: dict[str, float] = {}
        self._candidate_guided_instrument_labels: dict[str, str] = {}
        self._candidate_source_timings: dict[str, tuple[float, float]] = {}
        self._candidate_source_timing_object: object | None = None
        self._candidate_time_warps: dict[
            str,
            tuple[float, float, float, float],
        ] = {}
        self._contour_color_spans: tuple[ContourColorSpan, ...] = ()
        self._contour_color_revision = 0
        self._melody_guidance: object | None = None
        self._contour_default_emphasis = 1.0
        self._candidate_continuity_pairs: tuple[tuple[int, int], ...] = ()
        self._candidate_continuity_starts: tuple[float, ...] = ()
        self._candidate_chord_roles: dict[str, str] = {}
        self._voice_groups: tuple[object, ...] = ()
        self._assist_candidate_source_object: object | None = None
        self._assist_group_color_key: tuple[tuple[str, str], ...] = ()
        self._harmony_analysis: object | None = None
        self._harmony_segment_starts: list[float] = []
        self._max_harmony_segment_duration = 0.0
        self._hovered_candidate_id = ""
        self._candidate_marquee_origin: QPointF | None = None
        self._candidate_marquee_additive = False
        self._candidate_press_selected: set[str] = set()
        self._candidate_press_hit_ids: set[str] = set()
        self._ruler_range_anchor: float | None = None
        self._ruler_range_endpoint = ""
        self._ruler_range_moved = False
        self._drag_time_range: tuple[float, float] | None = None
        self.selected: set[int] = set()
        self.hovered_note_index: int | None = None
        self.scale_pitch_classes: frozenset[int] | None = None
        self.scale_root_pitch_class: int | None = None
        self.anchor_index: int | None = None
        self.px_per_beat = 92.0
        # Instance-owned so Alt+wheel can resize pitch lanes without changing
        # the default shared by other editor instances.
        self.ROW_H = float(type(self).ROW_H)
        self.scroll_ms = 0.0
        self.pitch_top = 84
        # Pitch rows are integer-addressed, while precision touchpads often
        # send sub-row deltas. Retain the fractional movement so a sequence of
        # small gestures remains responsive without making the paint/hit-test
        # coordinate model fractional.
        self._touchpad_pitch_remainder_rows = 0.0
        self.drag_mode = ""
        self.press_pos = QPointF()
        self.press_notes: list = []
        self.press_selected: set[int] = set()
        self.marquee = QRectF()
        self.creation_preview = None
        self.creation_anchor_ms = 0.0
        self.creation_anchor_pitch = 60
        self.edit_cursor_ms = 0.0
        self.ctrl_press_index: int | None = None
        self.clone_base_notes: list = []
        self.piano_key_dragging = False
        self.piano_pressed_pitch: int | None = None
        self.piano_hover_pitch: int | None = None
        self.playhead_ms = 0.0
        self.preload_progress = 0.0
        self.preload_state = "idle"
        self.dragging_playhead = False
        self._note_order: list[int] = []
        self._note_starts: list[float] = []
        self._note_ends: list[float] = []
        self._note_block_max_ends: list[float] = []
        self._max_note_duration = 0.0
        self._note_end_ms = 0.0
        self.content_end_ms = 0.0
        self._note_index_revision = 0
        self._visible_note_cache_key: tuple | None = None
        self._visible_note_cache: list[int] = []
        self._ghost_starts: list[float] = []
        self._ghost_ends: list[float] = []
        self._ghost_block_max_ends: list[float] = []
        self._ghost_max_duration = 0.0
        self._candidate_starts: list[float] = []
        self._candidate_ends: list[float] = []
        self._candidate_block_max_ends: list[float] = []
        self._last_candidate_query_inspections = 0
        self._candidate_end_audio_ms = 0.0
        self._candidate_id_set: frozenset[str] = frozenset()
        self._candidate_source_object: tuple[object, ...] | None = None
        self._review_projection_key: tuple | None = None
        self._background_cache_key: tuple | None = None
        self._background_cache = QPixmap()
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(480, 300)

    @property
    def beat_ms(self) -> float:
        return 60000.0 / max(1, self.editor.bpm)

    @property
    def px_per_ms(self) -> float:
        return self.px_per_beat / self.beat_ms

    @property
    def transcription_time_range(self) -> tuple[float, float] | None:
        if not self.editor.transcription_mode_enabled:
            return None
        if self._ruler_range_anchor is not None and self._drag_time_range is not None:
            return self._drag_time_range
        session = getattr(self.editor.parent(), "transcription_session", None)
        state = getattr(session, "state", None)
        return getattr(state, "region", None)

    def set_notes(self, notes: list, preserve_selection: bool = False) -> None:
        self.notes = list(notes)
        self.rebuild_note_index()
        if not preserve_selection:
            self.selected.clear()
        else:
            self.selected = {i for i in self.selected if i < len(self.notes)}
        self.update()

    def set_ghost_notes(self, notes: list) -> None:
        projected = [
            note
            if isinstance(note, GhostNoteProjection)
            else GhostNoteProjection(note)
            for note in notes
        ]
        self.ghost_notes = sorted(
            projected,
            key=lambda note: (
                float(note.start),
                int(note.pitch),
                int(note.track_id),
            ),
        )
        self._ghost_starts = [float(note.start) for note in self.ghost_notes]
        self._ghost_ends = [
            float(note.start) + float(note.dur)
            for note in self.ghost_notes
        ]
        block_size = self.CANDIDATE_QUERY_BLOCK_SIZE
        self._ghost_block_max_ends = [
            max(self._ghost_ends[start : start + block_size])
            for start in range(0, len(self._ghost_ends), block_size)
        ]
        self._ghost_max_duration = max((float(note.dur) for note in self.ghost_notes), default=0.0)
        self.update()

    def set_scale_highlight(
        self,
        pitch_classes: frozenset[int] | None,
        root_pitch_class: int | None = None,
    ) -> None:
        self.scale_pitch_classes = (
            None
            if pitch_classes is None
            else frozenset(int(value) % 12 for value in pitch_classes)
        )
        self.scale_root_pitch_class = (
            None if root_pitch_class is None else int(root_pitch_class) % 12
        )
        self.invalidate_roll_background()
        self.update()

    def set_ghost_opacity(self, opacity: float) -> None:
        try:
            normalized = max(0.0, min(1.0, float(opacity)))
        except (TypeError, ValueError, OverflowError):
            normalized = 0.24
        if not math.isfinite(normalized):
            normalized = 0.24
        if math.isclose(normalized, self._ghost_opacity, abs_tol=0.001):
            return
        self._ghost_opacity = normalized
        self.update()

    def _editable_note_base_color(self) -> QColor:
        color = QColor(
            str(
                getattr(
                    getattr(self.editor, "track", None),
                    "color",
                    "",
                )
            )
        )
        return color if color.isValid() else QColor("#718c3d")

    @staticmethod
    def _bounded_note_color(color: QColor, *, maximum_value: int) -> QColor:
        bounded = QColor(color)
        hue, saturation, value, alpha = bounded.getHsv()
        bounded.setHsv(
            max(0, hue),
            min(168, max(0, saturation)),
            min(maximum_value, max(72, value)),
            alpha,
        )
        return bounded

    @staticmethod
    def _blend_note_colors(base: QColor, accent: QColor, weight: float) -> QColor:
        amount = max(0.0, min(1.0, float(weight)))
        return QColor(
            round(base.red() * (1.0 - amount) + accent.red() * amount),
            round(base.green() * (1.0 - amount) + accent.green() * amount),
            round(base.blue() * (1.0 - amount) + accent.blue() * amount),
            base.alpha(),
        )

    def _technique_accent_color(self, ntype: int) -> QColor:
        return self._bounded_note_color(
            QColor(articulation_color(ntype)),
            maximum_value=174,
        )

    def _note_fill_color(
        self,
        note,
        *,
        track_color: QColor | None = None,
    ) -> QColor:
        velocity = max(0, min(127, int(note.vel)))
        resolved_track_color = (
            QColor(track_color)
            if track_color is not None
            else self._editable_note_base_color()
        )
        # The game editor presents notes as restrained metal/stone slabs. Keep
        # track identity in the outline and add only a small amount to the
        # neutral body so technique and velocity remain independent channels.
        base = self._blend_note_colors(
            QColor("#76777a"),
            resolved_track_color,
            0.13,
        )
        hue, saturation, value, _alpha = base.getHsv()
        # Body luminance is only a secondary velocity cue.  The explicit rail
        # below carries the readable 0..127 value without pretending it is dB.
        value_scale = 0.86 + (velocity / 127.0) * 0.12
        base.setHsv(
            max(0, hue),
            min(72, max(0, saturation)),
            max(78, min(158, round(value * value_scale))),
            234,
        )
        ntype = int(getattr(note, "ntype", 0))
        if ntype != int(self.editor.default_articulation_ntype):
            base = self._blend_note_colors(
                base,
                self._technique_accent_color(ntype),
                0.18,
            )
            base = self._bounded_note_color(base, maximum_value=158)
            base.setAlpha(234)
        return base

    @staticmethod
    def _note_text_color(fill: QColor) -> QColor:
        luminance = (
            fill.red() * 299
            + fill.green() * 587
            + fill.blue() * 114
        ) / 1000.0
        return QColor("#241f19" if luminance >= 139 else "#e8dfd2")

    @staticmethod
    def _group_palette_color(group_id: str) -> str:
        if not group_id:
            return "#5baaa4"
        checksum = sum(
            (index + 1) * ord(character)
            for index, character in enumerate(str(group_id))
        )
        return TRACK_COLORS[checksum % len(TRACK_COLORS)]

    @staticmethod
    def _chord_intervals(quality: str) -> tuple[int, ...]:
        return {
            "major": (0, 4, 7),
            "minor": (0, 3, 7),
            "dim": (0, 3, 6),
            "diminished": (0, 3, 6),
            "sus2": (0, 2, 7),
            "sus4": (0, 5, 7),
            "maj7": (0, 4, 7, 11),
            "major7": (0, 4, 7, 11),
            "7": (0, 4, 7, 10),
            "dominant7": (0, 4, 7, 10),
            "min7": (0, 3, 7, 10),
            "minor7": (0, 3, 7, 10),
            "half_diminished7": (0, 3, 6, 10),
            "half-diminished7": (0, 3, 6, 10),
        }.get(str(quality), ())

    def set_transcription_assist_projection(
        self,
        *,
        voice_groups=(),
        harmony_analysis=None,
        group_colors: dict[str, str] | None = None,
        melody_guidance=None,
    ) -> None:
        """Project Qt-free harmony/group sidecars into visible block styling."""

        groups = tuple(voice_groups or ())
        explicit_colors = dict(group_colors or {})
        color_key = tuple(
            sorted(
                (str(group_id), str(color))
                for group_id, color in explicit_colors.items()
            )
        )
        if (
            groups is self._voice_groups
            and harmony_analysis is self._harmony_analysis
            and self._candidate_source_object
            is self._assist_candidate_source_object
            and color_key == self._assist_group_color_key
            and melody_guidance == self._melody_guidance
        ):
            return
        candidate_groups: dict[str, str] = {}
        candidate_colors: dict[str, str] = {}
        candidate_group_confidences: dict[str, float] = {}
        candidate_group_class_confidences: dict[str, float] = {}
        for group in groups:
            group_id = str(getattr(group, "group_id", "") or "")
            color = str(
                explicit_colors.get(group_id)
                or getattr(group, "color", "")
                or self._group_palette_color(group_id)
            )
            group_confidence = float(getattr(group, "confidence", 0.0))
            candidate_confidence_lookup = dict(
                getattr(group, "candidate_confidences", ()) or ()
            )
            for candidate_id in getattr(group, "candidate_ids", ()) or ():
                normalized = str(candidate_id)
                candidate_groups[normalized] = group_id
                candidate_colors[normalized] = color
                candidate_group_confidences[normalized] = float(
                    candidate_confidence_lookup.get(
                        normalized,
                        group_confidence,
                    )
                )
                candidate_group_class_confidences[normalized] = group_confidence
        # Voice analysis intentionally receives only the primary of a folded
        # same-pitch hypothesis cluster.  Its alternatives remain reviewable
        # and inherit the primary block's phrase colour without becoming
        # artificial voices or additional timbre evidence.
        for alternative_id, primary_id in self._folded_candidate_primary.items():
            if primary_id in candidate_groups:
                candidate_groups.setdefault(
                    alternative_id,
                    candidate_groups[primary_id],
                )
                candidate_colors.setdefault(
                    alternative_id,
                    candidate_colors[primary_id],
                )
                candidate_group_confidences.setdefault(
                    alternative_id,
                    candidate_group_confidences.get(primary_id, 0.0),
                )
                candidate_group_class_confidences.setdefault(
                    alternative_id,
                    candidate_group_class_confidences.get(primary_id, 0.0),
                )

        group_emphasis = getattr(
            melody_guidance,
            "group_emphasis",
            lambda _group_id: 1.0,
        )
        highest_priority = getattr(
            melody_guidance,
            "is_highest_priority_group",
            lambda _group_id: False,
        )
        guided_label = str(
            getattr(melody_guidance, "target_instrument_label", "") or ""
        )
        candidate_group_emphases = {
            candidate_id: max(
                0.35,
                min(1.35, float(group_emphasis(group_id))),
            )
            for candidate_id, group_id in candidate_groups.items()
        }
        candidate_guided_labels = {
            candidate_id: guided_label
            for candidate_id, group_id in candidate_groups.items()
            if guided_label and highest_priority(group_id)
        }

        chord_roles: dict[str, str] = {}
        segments = tuple(
            sorted(
                (
                    getattr(harmony_analysis, "chord_segments", ())
                    or getattr(harmony_analysis, "segments", ())
                    or ()
                ),
                key=lambda item: (
                    float(getattr(item, "start_audio_ms", 0.0)),
                    float(getattr(item, "end_audio_ms", 0.0)),
                    str(getattr(item, "segment_id", "")),
                ),
            )
        )
        if segments:
            segment_starts = [
                float(getattr(item, "start_audio_ms", 0.0))
                for item in segments
            ]
            for candidate_id, candidate in zip(
                self._transcription_candidate_ids,
                self.transcription_candidates,
            ):
                midpoint = (
                    float(candidate.start_ms)
                    + float(candidate.duration_ms) * 0.5
                )
                segment_index = bisect_right(segment_starts, midpoint) - 1
                segment = (
                    segments[segment_index]
                    if segment_index >= 0
                    and midpoint
                    < float(
                        getattr(
                            segments[segment_index],
                            "end_audio_ms",
                            0.0,
                        )
                    )
                    else None
                )
                root = getattr(segment, "root_pc", None)
                if segment is None or root is None:
                    continue
                intervals = self._chord_intervals(
                    str(getattr(segment, "quality", ""))
                )
                relative = (int(candidate.pitch) - int(root)) % 12
                role_names = ("root", "third", "fifth", "seventh")
                for index, interval in enumerate(intervals):
                    if relative == interval:
                        chord_roles[candidate_id] = role_names[
                            min(index, len(role_names) - 1)
                        ]
                        break

        projection = (
            groups,
            harmony_analysis,
            melody_guidance,
            candidate_groups,
            candidate_colors,
            candidate_group_confidences,
            candidate_group_class_confidences,
            candidate_group_emphases,
            candidate_guided_labels,
            chord_roles,
        )
        current = (
            self._voice_groups,
            self._harmony_analysis,
            self._melody_guidance,
            self._candidate_group_ids,
            self._candidate_group_colors,
            self._candidate_group_confidences,
            self._candidate_group_class_confidences,
            self._candidate_group_emphases,
            self._candidate_guided_instrument_labels,
            self._candidate_chord_roles,
        )
        if projection == current:
            return
        (
            self._voice_groups,
            self._harmony_analysis,
            self._melody_guidance,
            self._candidate_group_ids,
            self._candidate_group_colors,
            self._candidate_group_confidences,
            self._candidate_group_class_confidences,
            self._candidate_group_emphases,
            self._candidate_guided_instrument_labels,
            self._candidate_chord_roles,
        ) = projection
        self._contour_default_emphasis = float(
            getattr(melody_guidance, "default_emphasis", 1.0)
        )
        self._harmony_segment_starts = [
            float(getattr(segment, "start_audio_ms", 0.0))
            for segment in segments
        ]
        self._max_harmony_segment_duration = max(
            (
                float(getattr(segment, "end_audio_ms", 0.0))
                - float(getattr(segment, "start_audio_ms", 0.0))
                for segment in segments
            ),
            default=0.0,
        )
        self._assist_candidate_source_object = self._candidate_source_object
        self._assist_group_color_key = color_key
        self._rebuild_candidate_continuity_projection()
        self._rebuild_contour_color_projection()
        self._rebuild_melody_line_projection()
        self.update()

    def _rebuild_candidate_continuity_projection(self) -> None:
        """Index evidence-backed false-split bridges outside paint paths."""

        by_pitch: dict[int, list[int]] = defaultdict(list)
        for index, (candidate_id, candidate) in enumerate(
            zip(
                self._transcription_candidate_ids,
                self.transcription_candidates,
            )
        ):
            if candidate_id in self._continuity_candidate_ids:
                by_pitch[int(candidate.pitch)].append(index)
        pairs: list[tuple[int, int]] = []
        for pitch_indices in by_pitch.values():
            for left_index, right_index in zip(
                pitch_indices,
                pitch_indices[1:],
            ):
                left = self.transcription_candidates[left_index]
                right = self.transcription_candidates[right_index]
                gap_ms = float(right.start_ms) - (
                    float(left.start_ms) + float(left.duration_ms)
                )
                if not 0.0 < gap_ms <= self.MAX_CANDIDATE_CONTINUITY_GAP_MS:
                    continue
                left_id = self._transcription_candidate_ids[left_index]
                right_id = self._transcription_candidate_ids[right_index]
                left_group = self._candidate_group_ids.get(left_id, "")
                right_group = self._candidate_group_ids.get(right_id, "")
                if left_group and right_group and left_group != right_group:
                    continue
                pairs.append((left_index, right_index))
        pairs.sort(
            key=lambda pair: (
                float(self.transcription_candidates[pair[0]].start_ms)
                + float(self.transcription_candidates[pair[0]].duration_ms),
                int(self.transcription_candidates[pair[0]].pitch),
                pair,
            )
        )
        projection = tuple(pairs)
        if projection == self._candidate_continuity_pairs:
            return
        self._candidate_continuity_pairs = projection
        self._candidate_continuity_starts = tuple(
            float(self.transcription_candidates[left_index].start_ms)
            + float(self.transcription_candidates[left_index].duration_ms)
            for left_index, _right_index in projection
        )
        self._candidate_visual_revision += 1
        self._contour_clip_cache_key = None

    def _visible_candidate_continuity_rects(
        self,
        project_left_ms: float,
        project_right_ms: float,
    ) -> tuple[tuple[str, QRectF], ...]:
        if not self._candidate_continuity_pairs:
            return ()
        audio_left = float(project_left_ms) - self._audio_offset_ms
        audio_right = float(project_right_ms) - self._audio_offset_ms
        first = bisect_left(
            self._candidate_continuity_starts,
            audio_left - self.MAX_CANDIDATE_CONTINUITY_GAP_MS,
        )
        last = bisect_right(self._candidate_continuity_starts, audio_right)
        bridges: list[tuple[str, QRectF]] = []
        blocked_ids = (
            self._rejected_candidate_ids
            | self._suppressed_candidate_ids
            | self._invalid_candidate_ids
        )
        for left_index, right_index in self._candidate_continuity_pairs[
            first:last
        ]:
            left_id = self._transcription_candidate_ids[left_index]
            right_id = self._transcription_candidate_ids[right_index]
            if left_id in blocked_ids or right_id in blocked_ids:
                continue
            left_rect = self.candidate_rect(
                self.transcription_candidates[left_index]
            )
            right_rect = self.candidate_rect(
                self.transcription_candidates[right_index]
            )
            if right_rect.left() <= left_rect.right():
                continue
            color = self._candidate_group_colors.get(
                left_id,
                self._candidate_group_colors.get(right_id, "#5baaa4"),
            )
            bridges.append(
                (
                    color,
                    QRectF(
                        left_rect.right(),
                        max(left_rect.top(), right_rect.top()),
                        right_rect.left() - left_rect.right(),
                        min(left_rect.height(), right_rect.height()),
                    ),
                )
            )
        return tuple(bridges)

    def _rebuild_contour_color_projection(self) -> None:
        """Build candidate-owned colour spans outside the paint path."""

        guidance = self._melody_guidance
        group_emphasis = getattr(
            guidance,
            "group_emphasis",
            lambda _group_id: 1.0,
        )
        highest_priority = getattr(
            guidance,
            "is_highest_priority_group",
            lambda _group_id: False,
        )
        target_instrument_id = getattr(
            guidance,
            "target_instrument_id",
            None,
        )
        target_instrument_label = str(
            getattr(guidance, "target_instrument_label", "") or ""
        )
        focused_color = self._editable_note_base_color().name()

        def source_timing(candidate_id: str, candidate) -> tuple[float, float]:
            return self._candidate_source_timings.get(
                candidate_id,
                (
                    float(candidate.start_ms),
                    float(candidate.duration_ms),
                ),
            )

        def span_for(
            candidate_id: str,
            candidate,
            start_ms: float,
            end_ms: float,
        ) -> ContourColorSpan:
            group_id = self._candidate_group_ids.get(candidate_id, "")
            focused = bool(highest_priority(group_id))
            return ContourColorSpan(
                start_ms,
                end_ms,
                float(candidate.pitch) - 1.75,
                float(candidate.pitch) + 1.75,
                (
                    focused_color
                    if focused
                    else self._candidate_group_colors[candidate_id]
                ),
                float(group_emphasis(group_id)),
                max(
                    0.0,
                    min(
                        1.0,
                        self._candidate_group_class_confidences.get(
                            candidate_id,
                            0.0,
                        ),
                    ),
                ),
                max(
                    0.0,
                    min(
                        1.0,
                        self._candidate_group_confidences.get(
                            candidate_id,
                            0.0,
                        ),
                    ),
                ),
                focused=focused,
                target_instrument_id=(
                    target_instrument_id if focused else None
                ),
                target_instrument_label=(
                    target_instrument_label if focused else ""
                ),
            )

        spans: list[ContourColorSpan] = []
        for candidate_id, candidate in zip(
            self._transcription_candidate_ids,
            self.transcription_candidates,
        ):
            if candidate_id not in self._candidate_group_colors:
                continue
            source_start, source_duration = source_timing(
                candidate_id,
                candidate,
            )
            spans.append(
                span_for(
                    candidate_id,
                    candidate,
                    source_start,
                    source_start + source_duration,
                )
            )
        for left_index, right_index in self._candidate_continuity_pairs:
            left_id = self._transcription_candidate_ids[left_index]
            right_id = self._transcription_candidate_ids[right_index]
            left_color = self._candidate_group_colors.get(left_id, "")
            if not left_color or left_color != self._candidate_group_colors.get(
                right_id,
                "",
            ):
                continue
            left = self.transcription_candidates[left_index]
            right = self.transcription_candidates[right_index]
            left_start, left_duration = source_timing(left_id, left)
            right_start, _right_duration = source_timing(right_id, right)
            if right_start <= left_start + left_duration:
                continue
            bridge = span_for(
                left_id,
                left,
                left_start + left_duration,
                right_start,
            )
            spans.append(
                ContourColorSpan(
                    bridge.start_ms,
                    bridge.end_ms,
                    bridge.pitch_min,
                    bridge.pitch_max,
                    bridge.color,
                    bridge.emphasis,
                    min(
                        self._candidate_group_class_confidences.get(
                            left_id,
                            0.0,
                        ),
                        self._candidate_group_class_confidences.get(
                            right_id,
                            0.0,
                        ),
                    ),
                    min(
                        self._candidate_group_confidences.get(left_id, 0.0),
                        self._candidate_group_confidences.get(right_id, 0.0),
                    ),
                    focused=bridge.focused,
                    target_instrument_id=bridge.target_instrument_id,
                    target_instrument_label=bridge.target_instrument_label,
                )
            )
        spans_value = tuple(spans)
        if spans_value == self._contour_color_spans:
            return
        self._contour_color_spans = spans_value
        self._contour_color_revision += 1

    def _rebuild_melody_line_projection(self) -> None:
        """Rebuild advisory paths outside ``paintEvent`` and audio callbacks."""

        candidate_values, candidate_ids = (
            self._bounded_melody_line_source()
        )
        try:
            group_revision: object = hash(self._voice_groups)
        except TypeError:
            group_revision = tuple(
                (
                    str(getattr(group, "group_id", "")),
                    tuple(getattr(group, "candidate_ids", ()) or ()),
                    str(getattr(group, "role", "")),
                    float(getattr(group, "confidence", 0.0)),
                )
                for group in self._voice_groups
            )
        projection_key = (
            len(candidate_values),
            hash(candidate_values),
            hash(candidate_ids),
            group_revision,
            id(self._harmony_analysis),
            round(self.beat_ms, 6),
        )
        if projection_key == self._melody_line_projection_key:
            return
        segments = build_melody_line_segments(
            candidate_values,
            candidate_ids,
            voice_groups=self._voice_groups,
            harmony_analysis=self._harmony_analysis,
            beat_ms=self.beat_ms,
        )
        self._melody_line_projection_key = projection_key
        self._melody_line_segments = segments
        self._melody_line_starts = [
            segment.start_audio_ms for segment in segments
        ]
        self._melody_line_ends = [
            segment.end_audio_ms for segment in segments
        ]
        block_size = self.CANDIDATE_QUERY_BLOCK_SIZE
        self._melody_line_block_max_ends = [
            max(self._melody_line_ends[start : start + block_size])
            for start in range(0, len(self._melody_line_ends), block_size)
        ]

    def _bounded_melody_line_source(
        self,
    ) -> tuple[
        tuple[TranscriptionCandidate, ...],
        tuple[str, ...],
    ]:
        """Return a deterministic, time-spanning guide-only projection.

        Each time block retains both temporal edges, its lowest and highest
        pitch, and its strongest-confidence candidate.  The full sorted
        candidate arrays remain untouched and continue to back visible-range
        painting, review state, hit testing and routing.
        """

        candidates = self.transcription_candidates
        candidate_ids = self._transcription_candidate_ids
        count = len(candidates)
        limit = self.MAX_MELODY_LINE_SOURCE_CANDIDATES
        if count <= limit:
            return tuple(candidates), tuple(candidate_ids)

        block_count = max(
            1,
            limit // self._MELODY_LINE_FEATURES_PER_BLOCK,
        )
        block_size = max(1, math.ceil(count / block_count))
        selected_indices: list[int] = []
        for start in range(0, count, block_size):
            stop = min(count, start + block_size)
            low_index = start
            high_index = start
            confidence_index = start
            low_pitch = int(candidates[start].pitch)
            high_pitch = low_pitch
            confidence_key = (
                float(candidates[start].confidence),
                float(candidates[start].duration_ms),
                -float(candidates[start].start_ms),
                candidate_ids[start],
            )
            for index in range(start + 1, stop):
                candidate = candidates[index]
                pitch = int(candidate.pitch)
                if pitch < low_pitch:
                    low_pitch = pitch
                    low_index = index
                if pitch > high_pitch:
                    high_pitch = pitch
                    high_index = index
                current_confidence_key = (
                    float(candidate.confidence),
                    float(candidate.duration_ms),
                    -float(candidate.start_ms),
                    candidate_ids[index],
                )
                if current_confidence_key > confidence_key:
                    confidence_key = current_confidence_key
                    confidence_index = index
            selected_indices.extend(
                sorted(
                    {
                        start,
                        stop - 1,
                        low_index,
                        high_index,
                        confidence_index,
                    }
                )
            )

        return (
            tuple(candidates[index] for index in selected_indices),
            tuple(candidate_ids[index] for index in selected_indices),
        )

    def set_transcription_candidates(
        self,
        candidates: list[TranscriptionCandidate] | tuple[TranscriptionCandidate, ...],
        *,
        visible: bool = True,
        candidate_id_resolver=None,
    ) -> None:
        parent = self.editor.parent()
        session = getattr(parent, "transcription_session", None)
        pairs = [
            (
                (
                    str(candidate_id_resolver(candidate))
                    if callable(candidate_id_resolver)
                    else (
                        session.candidate_id(candidate)
                        if session is not None
                        else str(
                            getattr(candidate, "candidate_id", "") or ""
                        )
                    )
                ),
                candidate,
            )
            for candidate in candidates
        ]
        pairs.sort(
            key=lambda pair: (
                float(pair[1].start_ms),
                int(pair[1].pitch),
                float(pair[1].duration_ms),
                pair[0],
            )
        )
        self._transcription_candidate_ids = [pair[0] for pair in pairs]
        self.transcription_candidates = [pair[1] for pair in pairs]
        self._transcription_candidate_id_to_index = {
            candidate_id: index
            for index, candidate_id in enumerate(
                self._transcription_candidate_ids
            )
        }
        by_pitch: dict[
            int, list[tuple[str, TranscriptionCandidate]]
        ] = defaultdict(list)
        for candidate_id, candidate in pairs:
            by_pitch[int(candidate.pitch)].append(
                (candidate_id, candidate)
            )
        folded_primary: dict[str, str] = {}
        alternative_counts: dict[str, int] = {}
        alternative_rank: dict[str, int] = {}
        for pitch_pairs in by_pitch.values():
            clusters: list[
                list[tuple[str, TranscriptionCandidate]]
            ] = []
            cluster_start = 0.0
            cluster_end = 0.0
            cluster_max_duration = 0.0
            for candidate_id, candidate in pitch_pairs:
                candidate_start = float(candidate.start_ms)
                candidate_duration = float(candidate.duration_ms)
                candidate_end = candidate_start + candidate_duration
                if not clusters:
                    clusters.append([(candidate_id, candidate)])
                    cluster_start = candidate_start
                    cluster_end = candidate_end
                    cluster_max_duration = candidate_duration
                    continue
                previous_cluster = clusters[-1]
                overlap_ms = max(
                    0.0,
                    min(cluster_end, candidate_end)
                    - max(cluster_start, candidate_start),
                )
                minimum_duration = min(
                    candidate_duration,
                    cluster_max_duration,
                )
                if (
                    minimum_duration > 0.0
                    and overlap_ms / minimum_duration >= 0.75
                    and abs(
                        candidate_start
                        - float(previous_cluster[0][1].start_ms)
                    )
                    <= 80.0
                ):
                    previous_cluster.append((candidate_id, candidate))
                    cluster_start = min(cluster_start, candidate_start)
                    cluster_end = max(cluster_end, candidate_end)
                    cluster_max_duration = max(
                        cluster_max_duration,
                        candidate_duration,
                    )
                else:
                    clusters.append([(candidate_id, candidate)])
                    cluster_start = candidate_start
                    cluster_end = candidate_end
                    cluster_max_duration = candidate_duration
            for cluster in clusters:
                if len(cluster) <= 1:
                    continue
                primary_id, _primary = max(
                    cluster,
                    key=lambda item: (
                        float(item[1].confidence),
                        float(item[1].duration_ms),
                        -float(item[1].start_ms),
                        item[0],
                    ),
                )
                alternative_counts[primary_id] = len(cluster) - 1
                ordered_alternatives = sorted(
                    (
                        (candidate_id, candidate)
                        for candidate_id, candidate in cluster
                        if candidate_id != primary_id
                    ),
                    key=lambda item: (
                        -float(item[1].confidence),
                        float(item[1].start_ms),
                        item[0],
                    ),
                )
                for rank, (candidate_id, _candidate) in enumerate(
                    ordered_alternatives,
                    start=1,
                ):
                    folded_primary[candidate_id] = primary_id
                    alternative_rank[candidate_id] = rank
        self._folded_candidate_primary = folded_primary
        self._fold_alternative_counts = alternative_counts
        self._fold_alternative_rank = alternative_rank
        self._candidate_source_object = None
        self._candidate_visual_revision += 1
        self._contour_clip_cache_key = None
        self._candidate_starts = [
            float(candidate.start_ms)
            for candidate in self.transcription_candidates
        ]
        self._candidate_ends = [
            float(candidate.start_ms) + float(candidate.duration_ms)
            for candidate in self.transcription_candidates
        ]
        block_size = self.CANDIDATE_QUERY_BLOCK_SIZE
        self._candidate_block_max_ends = [
            max(self._candidate_ends[start : start + block_size])
            for start in range(0, len(self._candidate_ends), block_size)
        ]
        self._candidate_end_audio_ms = max(
            self._candidate_ends,
            default=0.0,
        )
        self._candidate_id_set = frozenset(
            self._transcription_candidate_ids
        )
        self.transcription_candidates_visible = bool(visible)
        self._rebuild_candidate_continuity_projection()
        self._rebuild_contour_color_projection()
        self._rebuild_melody_line_projection()
        self._recalculate_content_end()
        self.update()

    def set_transcription_review(
        self,
        candidates,
        candidate_id,
        *,
        source_candidates=None,
        selected_ids=(),
        rejected_ids=(),
        pending_routes=(),
        applied_routes=(),
        invalid_ids=(),
        duplicate_ids=(),
        staged_ids=(),
        fragment_ids=(),
        continuity_ids=(),
        suppressed_ids=(),
        confidence_floor: float = 0.30,
        show_rejected_only: bool = False,
        audio_offset_ms: float = 0.0,
        visible: bool = True,
    ) -> None:
        candidate_values = tuple(candidates)
        source_candidate_values = (
            candidate_values
            if source_candidates is None
            else tuple(source_candidates)
        )
        source_timing_changed = (
            source_candidate_values is not self._candidate_source_timing_object
        )
        if source_timing_changed:
            self._candidate_source_timings = {
                str(candidate_id(candidate)): (
                    float(candidate.start_ms),
                    float(candidate.duration_ms),
                )
                for candidate in source_candidate_values
            }
            self._candidate_source_timing_object = source_candidate_values
        source_changed = (
            candidate_values is not self._candidate_source_object
        )
        if source_changed:
            self.set_transcription_candidates(
                candidate_values,
                visible=visible,
                candidate_id_resolver=candidate_id,
            )
            self._candidate_source_object = candidate_values
        if source_changed or source_timing_changed:
            self._candidate_time_warps = {}
            for displayed_id, displayed in zip(
                self._transcription_candidate_ids,
                self.transcription_candidates,
            ):
                source_timing = self._candidate_source_timings.get(
                    displayed_id
                )
                if source_timing is None:
                    continue
                source_start, source_duration = source_timing
                projected_start = float(displayed.start_ms)
                projected_duration = float(displayed.duration_ms)
                if (
                    math.isclose(
                        source_start,
                        projected_start,
                        abs_tol=0.5,
                    )
                    and math.isclose(
                        source_duration,
                        projected_duration,
                        abs_tol=0.5,
                    )
                ):
                    continue
                self._candidate_time_warps[displayed_id] = (
                    source_start,
                    source_start + source_duration,
                    projected_start,
                    projected_start + projected_duration,
                )
        selected_values = frozenset(str(value) for value in selected_ids)
        rejected_values = frozenset(str(value) for value in rejected_ids)
        pending_values = frozenset(
            str(getattr(route, "candidate_id", ""))
            for route in pending_routes
            if int(getattr(route, "track_id", -1)) == int(self.editor.track.track_id)
        )
        applied_values = frozenset(
            str(getattr(route, "candidate_id", "")) for route in applied_routes
        )
        invalid_values = frozenset(str(value) for value in invalid_ids)
        duplicate_values = frozenset(
            str(value) for value in duplicate_ids
        )
        staged_values = frozenset(str(value) for value in staged_ids)
        fragment_values = frozenset(
            str(value) for value in fragment_ids
        )
        continuity_values = frozenset(
            str(value) for value in continuity_ids
        )
        suppressed_values = frozenset(
            str(value) for value in suppressed_ids
        )
        normalized_confidence = max(
            0.0,
            min(1.0, float(confidence_floor)),
        )
        normalized_offset = float(audio_offset_ms)
        projection_key = (
            id(candidate_values),
            id(source_candidate_values),
            selected_values,
            rejected_values,
            pending_values,
            applied_values,
            invalid_values,
            duplicate_values,
            staged_values,
            fragment_values,
            continuity_values,
            suppressed_values,
            normalized_confidence,
            bool(show_rejected_only),
            round(normalized_offset, 6),
            bool(visible),
        )
        if (
            not source_changed
            and not source_timing_changed
            and projection_key == self._review_projection_key
        ):
            return
        self._review_projection_key = projection_key
        self._selected_candidate_ids = set(
            selected_values.intersection(self._candidate_id_set)
        )
        self._rejected_candidate_ids = set(rejected_values)
        self._pending_candidate_ids = set(pending_values)
        self._applied_candidate_ids = set(applied_values)
        self._invalid_candidate_ids = set(invalid_values)
        self._duplicate_candidate_ids = set(duplicate_values)
        self._staged_candidate_ids = set(staged_values)
        self._fragment_candidate_ids = set(fragment_values)
        self._continuity_candidate_ids = set(continuity_values)
        self._suppressed_candidate_ids = set(suppressed_values)
        self._confidence_floor = normalized_confidence
        self._show_rejected_only = bool(show_rejected_only)
        self._audio_offset_ms = normalized_offset
        self.transcription_candidates_visible = bool(visible)
        self._candidate_visual_revision += 1
        self._contour_clip_cache_key = None
        self._rebuild_candidate_continuity_projection()
        self._rebuild_contour_color_projection()
        self._recalculate_content_end()
        self.update()

    @property
    def selected_candidate_ids(self) -> frozenset[str]:
        return frozenset(self._selected_candidate_ids)

    def set_evidence_descriptor(self, descriptor, *, audio_offset_ms: float = 0.0) -> None:
        self._evidence.close()
        self._evidence_descriptor = descriptor
        self._audio_offset_ms = float(audio_offset_ms)
        self._contour_clip_cache_key = None
        if descriptor is not None:
            self._evidence.begin_source(descriptor)
        self.update()

    def set_evidence_layers(
        self,
        *,
        frame: bool = True,
        onset: bool = True,
        contour: bool = False,
    ) -> None:
        normalized = (bool(frame), bool(onset), bool(contour))
        current = (
            self._show_frame_evidence,
            self._show_onset_evidence,
            self._show_contour_evidence,
        )
        if normalized == current:
            return
        (
            self._show_frame_evidence,
            self._show_onset_evidence,
            self._show_contour_evidence,
        ) = normalized
        self.update()

    def set_contour_denoise_profile(self, value: str) -> None:
        normalized = str(value)
        if normalized not in {"low", "standard", "high"}:
            normalized = "standard"
        if normalized == self._contour_denoise_profile:
            return
        self._contour_denoise_profile = normalized
        self.update()

    def set_spectrogram_source(
        self,
        audio_path: str | Path | None,
        *,
        duration_ms: float = 0.0,
        audio_offset_ms: float = 0.0,
    ) -> None:
        """Attach an ephemeral reference source without changing project data."""

        previous_offset = self._audio_offset_ms
        self._audio_offset_ms = float(audio_offset_ms)
        normalized_path = str(audio_path or "")
        if not normalized_path:
            if self._spectrogram_audio_path:
                self._spectrogram.close()
                self._spectrogram_audio_path = ""
                self.update()
            return
        candidate = Path(normalized_path).expanduser().resolve(strict=False)
        source = self._spectrogram.source
        if source is not None and source.path == candidate:
            self._spectrogram.set_duration_ms(duration_ms)
            refreshed_source = self._spectrogram.source
            if (
                not math.isclose(
                    previous_offset,
                    self._audio_offset_ms,
                    abs_tol=0.001,
                )
                or refreshed_source != source
            ):
                # Duration discovery may cancel obsolete end tiles, while an
                # alignment edit repositions every ready tile.  Request a new
                # paint immediately instead of waiting for incidental input.
                self.update()
            return
        self._spectrogram.close()
        self._spectrogram_audio_path = ""
        try:
            self._spectrogram.begin_source(
                candidate,
                duration_ms=duration_ms,
            )
        except (OSError, ReferenceAudioFormatError):
            return
        self._spectrogram_audio_path = str(candidate)
        self.update()

    def set_spectrogram_visible(self, visible: bool) -> None:
        normalized = bool(visible)
        if normalized == self._show_spectrogram:
            return
        self._show_spectrogram = normalized
        if not normalized:
            self._spectrogram.cancel_pending()
        self.update()

    def set_reference_background_opacity(self, opacity: float) -> None:
        try:
            normalized = max(0.0, min(1.0, float(opacity)))
        except (TypeError, ValueError, OverflowError):
            normalized = 0.60
        if not math.isfinite(normalized):
            normalized = 0.60
        if math.isclose(
            normalized,
            self._reference_background_opacity,
            abs_tol=0.001,
        ):
            return
        self._reference_background_opacity = normalized
        self.update()

    def set_contour_opacity(self, opacity: float) -> None:
        try:
            normalized = max(0.0, min(1.0, float(opacity)))
        except (TypeError, ValueError, OverflowError):
            normalized = 0.82
        if not math.isfinite(normalized):
            normalized = 0.82
        if math.isclose(normalized, self._contour_opacity, abs_tol=0.001):
            return
        self._contour_opacity = normalized
        self.update()

    def set_melody_lines_visible(self, visible: bool) -> None:
        normalized = bool(visible)
        if normalized == self._show_melody_lines:
            return
        self._show_melody_lines = normalized
        self.update()

    def set_melody_line_roles_visible(
        self,
        roles: Iterable[str],
    ) -> None:
        normalized = frozenset(
            str(role)
            for role in roles
            if str(role) in MELODY_LINE_GUIDE_ROLES
        )
        if not normalized:
            normalized = frozenset({MELODY_LINE_PRIMARY_ROLE})
        if normalized == self._melody_line_roles_visible:
            return
        self._melody_line_roles_visible = normalized
        self.update()

    @property
    def melody_lines_available(self) -> bool:
        return bool(self._melody_line_segments)

    @property
    def melody_line_roles_visible(self) -> frozenset[str]:
        return self._melody_line_roles_visible

    def release_transcription_evidence(self) -> None:
        self._evidence.close()
        self._evidence_descriptor = None
        self._spectrogram.close()
        self._spectrogram_audio_path = ""

    def set_transcription_candidates_visible(self, visible: bool) -> None:
        normalized = bool(visible)
        if normalized == self.transcription_candidates_visible:
            return
        self.transcription_candidates_visible = normalized
        self._recalculate_content_end()
        self.update()

    def set_transcription_candidate_layer_visible(self, visible: bool) -> None:
        """Show provisional analysis blocks without affecting evidence layers."""

        normalized = bool(visible)
        if normalized == self._transcription_candidate_layer_visible:
            return
        self._transcription_candidate_layer_visible = normalized
        if not normalized:
            self._hovered_candidate_id = ""
        self.update()

    def set_transcription_candidate_opacity(self, opacity: float) -> None:
        """Set one global opacity multiplier for every analysis candidate."""

        try:
            normalized = float(opacity)
        except (TypeError, ValueError, OverflowError):
            normalized = 0.52
        if not math.isfinite(normalized):
            normalized = 0.52
        normalized = max(0.0, min(1.0, normalized))
        if math.isclose(
            normalized,
            self._transcription_candidate_opacity,
            abs_tol=0.001,
        ):
            return
        self._transcription_candidate_opacity = normalized
        self.update()

    def set_preload_progress(self, progress: float, state: str = "loading") -> None:
        self.preload_progress = max(0.0, min(1.0, float(progress)))
        self.preload_state = state if state in {"idle", "loading", "ready"} else "idle"
        self.update()

    def rebuild_note_index(self) -> None:
        previous_pitch_set = getattr(self, "note_pitch_set", frozenset())
        self.note_pitch_set = frozenset(
            int(note.pitch) for note in self.notes
        )
        if self.note_pitch_set != previous_pitch_set:
            self.invalidate_roll_background()
        self._note_order = sorted(range(len(self.notes)), key=lambda index: self.notes[index].start)
        self._note_starts = [float(self.notes[index].start) for index in self._note_order]
        self._note_ends = [
            float(self.notes[index].start) + float(self.notes[index].dur)
            for index in self._note_order
        ]
        block_size = self.CANDIDATE_QUERY_BLOCK_SIZE
        self._note_block_max_ends = [
            max(self._note_ends[start : start + block_size])
            for start in range(0, len(self._note_ends), block_size)
        ]
        self._max_note_duration = max((float(note.dur) for note in self.notes), default=0.0)
        self._note_end_ms = max(
            (float(note.start + note.dur) for note in self.notes),
            default=0.0,
        )
        self._recalculate_content_end()
        self._note_index_revision += 1
        self._visible_note_cache_key = None
        self._visible_note_cache = []

    def _recalculate_content_end(self) -> None:
        candidate_end = (
            self._candidate_end_audio_ms + self._audio_offset_ms
            if self.transcription_candidates_visible
            else 0.0
        )
        clip_scope = getattr(self.editor, "clip_scope", None)
        self.content_end_ms = (
            float(clip_scope.timeline_end_ms)
            if clip_scope is not None
            else max(self._note_end_ms, candidate_end)
        )

    def visible_note_indices(
        self,
        left_ms: float | None = None,
        right_ms: float | None = None,
    ) -> list[int]:
        left = self.scroll_ms if left_ms is None else float(left_ms)
        right = (
            self.time_at(self.width())
            if right_ms is None
            else float(right_ms)
        )
        explicit_range = left_ms is not None or right_ms is not None
        cache_key = (
            self._note_index_revision,
            round(left, 3),
            round(right, 3),
        )
        if not explicit_range and cache_key == self._visible_note_cache_key:
            return self._visible_note_cache
        hi = bisect_right(self._note_starts, right)
        # A single song-long note must not widen every later viewport to the
        # beginning of the track.  Block maximum ends retain that long note
        # while pruning blocks whose notes have all finished.
        query_left = left - 4.0 / max(1e-9, self.px_per_ms)
        visible: list[int] = []
        block_size = self.CANDIDATE_QUERY_BLOCK_SIZE
        last_block = (hi + block_size - 1) // block_size
        for block_index in range(last_block):
            if self._note_block_max_ends[block_index] < query_left:
                continue
            start = block_index * block_size
            stop = min(hi, start + block_size)
            for ordered_index in range(start, stop):
                if self._note_ends[ordered_index] >= query_left:
                    visible.append(self._note_order[ordered_index])
        if explicit_range:
            return visible
        self._visible_note_cache_key = cache_key
        self._visible_note_cache = visible
        return visible

    def visible_ghost_notes(
        self,
        left_ms: float | None = None,
        right_ms: float | None = None,
    ) -> list:
        left = self.scroll_ms if left_ms is None else float(left_ms)
        right = (
            self.time_at(self.width())
            if right_ms is None
            else float(right_ms)
        )
        hi = bisect_right(self._ghost_starts, right)
        query_left = left - 4.0 / max(1e-9, self.px_per_ms)
        values: list = []
        block_size = self.CANDIDATE_QUERY_BLOCK_SIZE
        last_block = (hi + block_size - 1) // block_size
        for block_index in range(last_block):
            if self._ghost_block_max_ends[block_index] < query_left:
                continue
            start = block_index * block_size
            stop = min(hi, start + block_size)
            values.extend(
                self.ghost_notes[index]
                for index in range(start, stop)
                if self._ghost_ends[index] >= query_left
            )
        return values

    def visible_transcription_candidates(self) -> list[TranscriptionCandidate]:
        if not self._transcription_candidate_layer_visible:
            return []
        return [candidate for _candidate_id, candidate in self._visible_candidate_pairs()]

    def visible_melody_line_segments(
        self,
        left_ms: float | None = None,
        right_ms: float | None = None,
    ) -> list[MelodyLineSegment]:
        """Query only path blocks intersecting the project-time viewport."""

        self._last_melody_line_query_inspections = 0
        if not self._show_melody_lines or not self.transcription_candidates_visible:
            return []
        left = self.scroll_ms if left_ms is None else float(left_ms)
        right = (
            self.time_at(self.width())
            if right_ms is None
            else float(right_ms)
        )
        audio_left = left - self._audio_offset_ms
        audio_right = right - self._audio_offset_ms
        hi = bisect_right(self._melody_line_starts, audio_right)
        query_left = audio_left - 2.0 / max(1e-9, self.px_per_ms)
        values: list[MelodyLineSegment] = []
        inspected = 0
        lod = melody_line_lod(self.px_per_beat)
        block_size = self.CANDIDATE_QUERY_BLOCK_SIZE
        last_block = (hi + block_size - 1) // block_size
        for block_index in range(last_block):
            if self._melody_line_block_max_ends[block_index] < query_left:
                continue
            start = block_index * block_size
            stop = min(hi, start + block_size)
            inspected += stop - start
            for index in range(start, stop):
                segment = self._melody_line_segments[index]
                source_visible = any(
                    (
                        candidate_index :=
                        self._transcription_candidate_id_to_index.get(
                            candidate_id
                        )
                    )
                    is not None
                    and self._candidate_is_visible(
                        candidate_id,
                        self.transcription_candidates[candidate_index],
                    )
                    for candidate_id in segment.source_candidate_ids
                )
                if (
                    self._melody_line_ends[index] >= query_left
                    and segment.role in self._melody_line_roles_visible
                    and source_visible
                    and melody_line_kind_visible(
                        segment.kind,
                        branch=segment.branch,
                        lod=lod,
                    )
                ):
                    values.append(segment)
        self._last_melody_line_query_inspections = inspected
        return values

    def _melody_line_points(
        self,
        segment: MelodyLineSegment,
    ) -> tuple[QPointF, QPointF]:
        return (
            QPointF(
                self.x_at_time(
                    segment.start_audio_ms + self._audio_offset_ms
                ),
                self.RULER_H
                + (self.pitch_top - segment.start_pitch + 0.5)
                * self.ROW_H,
            ),
            QPointF(
                self.x_at_time(
                    segment.end_audio_ms + self._audio_offset_ms
                ),
                self.RULER_H
                + (self.pitch_top - segment.end_pitch + 0.5)
                * self.ROW_H,
            ),
        )

    def melody_guide_at(
        self,
        position: QPointF,
    ) -> MelodyLineSegment | None:
        """Hit-test visible guides without changing any formal editor note."""

        if (
            not self.editor.transcription_mode_enabled
            or position.x() < self.KEY_W
            or position.y() < self.RULER_H
        ):
            return None
        tolerance = 5.5
        center_ms = self.time_at(position.x())
        half_window_ms = tolerance / max(1e-9, self.px_per_ms)
        candidates = self.visible_melody_line_segments(
            center_ms - half_window_ms,
            center_ms + half_window_ms,
        )
        hits: list[tuple[float, float, bool, str, MelodyLineSegment]] = []
        for segment in candidates:
            if not segment.source_candidate_ids:
                continue
            start, end = self._melody_line_points(segment)
            dx = end.x() - start.x()
            dy = end.y() - start.y()
            length_squared = dx * dx + dy * dy
            if length_squared <= 1e-9:
                distance = math.hypot(
                    position.x() - start.x(),
                    position.y() - start.y(),
                )
            else:
                ratio = max(
                    0.0,
                    min(
                        1.0,
                        (
                            (position.x() - start.x()) * dx
                            + (position.y() - start.y()) * dy
                        )
                        / length_squared,
                    ),
                )
                distance = math.hypot(
                    position.x() - (start.x() + ratio * dx),
                    position.y() - (start.y() + ratio * dy),
                )
            hit_radius = max(
                tolerance,
                melody_line_width(segment.confidence) + 2.0,
            )
            if distance <= hit_radius:
                hits.append(
                    (
                        distance,
                        -segment.confidence,
                        segment.branch,
                        segment.group_id,
                        segment,
                    )
                )
        if not hits:
            return None
        return min(hits, key=lambda item: item[:4])[-1]

    def _candidate_is_visible(
        self, candidate_id: str, candidate: TranscriptionCandidate
    ) -> bool:
        rejected = candidate_id in self._rejected_candidate_ids
        if rejected != self._show_rejected_only:
            return False
        if candidate_id in self._applied_candidate_ids:
            return False
        if candidate_id in self._staged_candidate_ids:
            return False
        return True

    def _visible_candidate_pairs(
        self,
        left_ms: float | None = None,
        right_ms: float | None = None,
    ) -> list[tuple[str, TranscriptionCandidate]]:
        self._last_candidate_query_inspections = 0
        if not self.transcription_candidates_visible:
            return []
        left = self.scroll_ms if left_ms is None else float(left_ms)
        right = (
            self.time_at(self.width())
            if right_ms is None
            else float(right_ms)
        )
        audio_left = left - self._audio_offset_ms
        audio_right = right - self._audio_offset_ms
        hi = bisect_right(self._candidate_starts, audio_right)
        # Candidate rectangles have a four-pixel minimum width.  Expand the
        # logical left boundary by that amount so exact interval filtering
        # preserves the existing edge-paint and hit-test semantics.
        query_left = audio_left - 4.0 / max(1e-9, self.px_per_ms)
        values: list[tuple[str, TranscriptionCandidate]] = []
        inspected = 0
        block_size = self.CANDIDATE_QUERY_BLOCK_SIZE
        last_block = (hi + block_size - 1) // block_size
        for block_index in range(last_block):
            if (
                self._candidate_block_max_ends[block_index]
                < query_left
            ):
                continue
            start = block_index * block_size
            stop = min(hi, start + block_size)
            inspected += stop - start
            for index in range(start, stop):
                if self._candidate_ends[index] < query_left:
                    continue
                candidate_id = self._transcription_candidate_ids[index]
                candidate = self.transcription_candidates[index]
                if self._candidate_is_visible(candidate_id, candidate):
                    values.append((candidate_id, candidate))
        self._last_candidate_query_inspections = inspected
        return values

    def candidate_rect(self, candidate: TranscriptionCandidate) -> QRectF:
        x = self.x_at_time(
            CANDIDATE_NOTE_POLICY.project_start_ms(
                candidate,
                self._audio_offset_ms,
            )
        )
        y = self.RULER_H + (self.pitch_top - int(candidate.pitch)) * self.ROW_H
        # Recognition results are guides, not a second set of editable notes.
        # Keep them visibly slimmer than formal notes so overlapping material
        # does not turn the roll into a solid wall of colour.
        vertical_inset = max(2.0, min(5.0, self.ROW_H * 0.22))
        return QRectF(
            x,
            y + vertical_inset,
            max(4.0, float(candidate.duration_ms) * self.px_per_ms),
            max(3.0, self.ROW_H - vertical_inset * 2.0),
        )

    def _expanded_fold_primaries(self) -> set[str]:
        expanded = {
            self._folded_candidate_primary.get(candidate_id, candidate_id)
            for candidate_id in self._selected_candidate_ids
        }
        if self._hovered_candidate_id:
            expanded.add(
                self._folded_candidate_primary.get(
                    self._hovered_candidate_id,
                    self._hovered_candidate_id,
                )
            )
        return expanded

    def _candidate_display_rect(
        self,
        candidate_id: str,
        candidate: TranscriptionCandidate,
        *,
        expanded_primaries: set[str] | None = None,
    ) -> QRectF:
        """Fan a hovered/selected fold into individually inspectable lanes."""

        rect = self.candidate_rect(candidate)
        primary_id = self._folded_candidate_primary.get(
            candidate_id,
            candidate_id,
        )
        alternatives = self._fold_alternative_counts.get(primary_id, 0)
        expanded = (
            self._expanded_fold_primaries()
            if expanded_primaries is None
            else expanded_primaries
        )
        if alternatives <= 0 or primary_id not in expanded:
            return rect
        rank = (
            0
            if candidate_id == primary_id
            else self._fold_alternative_rank.get(candidate_id, 1)
        )
        lane_count = min(4, alternatives + 1)
        lane = min(rank, lane_count - 1)
        lane_height = max(4.0, rect.height() / lane_count)
        overflow_rank = max(0, rank - (lane_count - 1))
        return QRectF(
            rect.left() + overflow_rank * 4.0,
            rect.top() + lane * lane_height,
            max(4.0, rect.width() - overflow_rank * 4.0),
            max(3.0, lane_height - 1.0),
        )

    def _candidate_is_displayed_in_fold(
        self,
        candidate_id: str,
        expanded_primaries: set[str],
    ) -> bool:
        """Match folded-candidate hit testing to what the painter exposes."""

        folded_primary = self._folded_candidate_primary.get(candidate_id)
        if folded_primary is None or folded_primary in expanded_primaries:
            return True
        return any(
            candidate_id in candidate_ids
            for candidate_ids in (
                self._selected_candidate_ids,
                self._rejected_candidate_ids,
                self._pending_candidate_ids,
                self._applied_candidate_ids,
                self._invalid_candidate_ids,
                self._duplicate_candidate_ids,
                self._staged_candidate_ids,
                self._fragment_candidate_ids,
                self._suppressed_candidate_ids,
            )
        )

    def candidate_at(self, pos: QPointF) -> str | None:
        if (
            not self._transcription_candidate_layer_visible
            or self._transcription_candidate_opacity <= 0.0
            or pos.x() < self.KEY_W
            or pos.y() < self.RULER_H
        ):
            return None
        left_ms = self.time_at(pos.x() - 3.0)
        right_ms = self.time_at(pos.x() + 3.0)
        expanded_primaries = self._expanded_fold_primaries()
        for candidate_id, candidate in reversed(
            self._visible_candidate_pairs(left_ms, right_ms)
        ):
            if self._candidate_display_rect(
                candidate_id,
                candidate,
                expanded_primaries=expanded_primaries,
            ).adjusted(
                -2.0,
                -2.0,
                2.0,
                2.0,
            ).contains(pos):
                primary_id = self._folded_candidate_primary.get(candidate_id)
                if primary_id is not None and primary_id not in expanded_primaries:
                    return primary_id
                return candidate_id
        return None

    def _voice_group_for_candidate(
        self, candidate_id: str
    ) -> object | None:
        group_id = self._candidate_group_ids.get(str(candidate_id), "")
        if not group_id:
            return None
        return next(
            (
                group
                for group in self._voice_groups
                if str(getattr(group, "group_id", "")) == group_id
            ),
            None,
        )

    def _adjacent_voice_groups(
        self, group_id: str
    ) -> tuple[object, ...]:
        groups = tuple(
            sorted(
                self._voice_groups,
                key=lambda group: (
                    float(getattr(group, "start_audio_ms", 0.0)),
                    float(getattr(group, "end_audio_ms", 0.0)),
                    str(getattr(group, "group_id", "")),
                ),
            )
        )
        index = next(
            (
                index
                for index, group in enumerate(groups)
                if str(getattr(group, "group_id", "")) == str(group_id)
            ),
            None,
        )
        if index is None:
            return ()
        adjacent: list[object] = []
        if index > 0:
            adjacent.append(groups[index - 1])
        if index + 1 < len(groups):
            adjacent.append(groups[index + 1])
        return tuple(adjacent)

    def _show_voice_group_context_menu(
        self,
        event,
        candidate_id: str,
    ) -> bool:
        group = self._voice_group_for_candidate(candidate_id)
        if group is None:
            return False
        group_id = str(getattr(group, "group_id", "") or "")
        if not group_id:
            return False
        menu = QMenu(self)
        split_action = menu.addAction(tr("在播放头处分割声部"))
        split_audio_ms = (
            float(self.playhead_ms) - float(self._audio_offset_ms)
        )
        split_action.setEnabled(
            float(getattr(group, "start_audio_ms", 0.0))
            < split_audio_ms
            < float(getattr(group, "end_audio_ms", 0.0))
        )
        adjacent = self._adjacent_voice_groups(group_id)
        merge_menu = menu.addMenu(tr("与相邻声部合并"))
        for other in adjacent:
            other_id = str(getattr(other, "group_id", "") or "")
            role = trv(voice_role_source_label(getattr(other, "role", "")))
            start_s = (
                float(getattr(other, "start_audio_ms", 0.0)) / 1000.0
            )
            action = merge_menu.addAction(
                trf("{role} · {time:.1f}s", role=role, time=start_s)
            )
            action.setData(other_id)
        merge_menu.setEnabled(bool(adjacent))
        role_menu = menu.addMenu(tr("修改声部角色"))
        role_actions: dict[object, str] = {}
        for role_name in (
            "primary_melody",
            "secondary_melody",
            "harmony",
            "bass",
            "rhythm",
            "pad",
            "ornament",
            "fx",
        ):
            action = role_menu.addAction(voice_role_label(role_name))
            action.setData(role_name)
            role_actions[action] = role_name
        color_menu = menu.addMenu(tr("声部颜色"))
        color_actions: dict[object, str] = {}
        for color in TRACK_COLORS:
            action = color_menu.addAction("■")
            action.setForeground(QColor(color))
            action.setData(str(color))
            color_actions[action] = str(color)
        chosen = menu.exec(event.globalPosition().toPoint())
        if chosen is None:
            return True
        if chosen is split_action:
            self.voice_group_split_requested.emit(
                group_id, float(self.playhead_ms)
            )
            return True
        parent_menu = chosen.parent()
        if parent_menu is merge_menu:
            other_id = str(chosen.data() or "")
            if other_id:
                self.voice_group_merge_requested.emit(group_id, other_id)
            return True
        color = color_actions.get(chosen)
        if color:
            self.voice_group_color_requested.emit(group_id, color)
            return True
        role_name = role_actions.get(chosen)
        if role_name:
            self.voice_group_role_requested.emit(group_id, role_name)
        return True

    def set_playhead(self, ms: float) -> None:
        old_x = self.x_at_time(self.playhead_ms)
        self.playhead_ms = max(0.0, float(ms))
        new_x = self.x_at_time(self.playhead_ms)
        for x in (old_x, new_x):
            if self.KEY_W - 110 <= x <= self.width() + 110:
                self.update(QRectF(x - 110, 0, 220, self.height()).toAlignedRect())

    def set_timeline_markers(self, markers: object) -> None:
        self.timeline_markers = list(normalize_timeline_markers(markers))
        self._timeline_marker_times = tuple(
            float(marker["time_ms"]) for marker in self.timeline_markers
        )
        self.update(QRectF(self.KEY_W, 0, self.width() - self.KEY_W, self.height()).toAlignedRect())

    def _paint_timeline_markers(self, painter: QPainter) -> None:
        self._marker_label_regions.clear()
        self._marker_delete_regions.clear()
        painter.save()
        visible_start = self.time_at(self.KEY_W)
        visible_end = self.time_at(self.width())
        first = bisect_left(self._timeline_marker_times, visible_start)
        last = bisect_right(self._timeline_marker_times, visible_end)
        for marker in self.timeline_markers[first:last]:
            x = self.x_at_time(float(marker["time_ms"]))
            if x < self.KEY_W or x > self.width():
                continue
            painter.fillRect(
                QRectF(x, self.TIME_RULER_H, 1.0, self.height() - self.TIME_RULER_H),
                QColor(229, 174, 69, 120),
            )
            label = str(marker["label"])
            width = min(184.0, max(64.0, painter.fontMetrics().horizontalAdvance(label) + 30.0))
            label_x = max(self.KEY_W + 92.0, min(x + 3.0, self.width() - width - 3.0))
            pill = QRectF(label_x, 4.0, width, 21.0)
            painter.setBrush(QColor(48, 40, 25, 246))
            painter.setPen(QPen(QColor("#d9a53f"), 1))
            painter.drawRoundedRect(pill, 4.0, 4.0)
            painter.setPen(QColor("#f1d9a3"))
            painter.drawText(pill.adjusted(7, 0, -22, 0), Qt.AlignVCenter, label)
            delete_rect = QRectF(pill.right() - 21.0, pill.top(), 21.0, pill.height())
            painter.setPen(QColor("#caa967"))
            painter.drawText(delete_rect, Qt.AlignCenter, "×")
            self._marker_label_regions.append((pill, marker))
            self._marker_delete_regions.append((delete_rect, marker))
        painter.restore()

    def set_edit_cursor(self, ms: float) -> None:
        old_x = self.x_at_time(self.edit_cursor_ms)
        constrain = getattr(self.editor, "constrain_timeline_time", None)
        self.edit_cursor_ms = (
            constrain(ms) if callable(constrain) else max(0.0, float(ms))
        )
        new_x = self.x_at_time(self.edit_cursor_ms)
        for x in (old_x, new_x):
            if self.KEY_W - 8 <= x <= self.width() + 8:
                self.update(QRectF(x - 8, self.RULER_H, 16, self.height() - self.RULER_H).toAlignedRect())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self.editor, "update_scrollbars"):
            self.editor.update_scrollbars()

    def note_rect(self, note) -> QRectF:
        x = self.x_at_time(note.start)
        y = self.RULER_H + (self.pitch_top - note.pitch) * self.ROW_H
        return QRectF(
            x,
            y + 1,
            max(4.0, note.dur * self.px_per_ms),
            self.ROW_H - 2,
        )

    def invalidate_roll_background(self) -> None:
        self._background_cache_key = None
        self._background_cache = QPixmap()

    @staticmethod
    def _snap_to_device_pixel(value: float, device_pixel_ratio: float) -> float:
        ratio = max(1.0, float(device_pixel_ratio))
        return round(float(value) * ratio) / ratio

    @classmethod
    def note_velocity_bar_rects(
        cls,
        note_rect: QRectF,
        velocity: int,
        device_pixel_ratio: float = 1.0,
    ) -> tuple[QRectF, QRectF] | None:
        """Return a pixel-aligned game-style velocity rail and active fill."""

        if (
            note_rect.width() < cls.NOTE_VELOCITY_MIN_WIDTH
            or note_rect.height() < cls.NOTE_VELOCITY_MIN_HEIGHT
        ):
            return None
        ratio = max(1.0, float(device_pixel_ratio))
        left = cls._snap_to_device_pixel(
            note_rect.left() + cls.NOTE_VELOCITY_SIDE_INSET,
            ratio,
        )
        right = cls._snap_to_device_pixel(
            note_rect.right() - cls.NOTE_VELOCITY_SIDE_INSET,
            ratio,
        )
        bottom = cls._snap_to_device_pixel(
            note_rect.bottom() - cls.NOTE_VELOCITY_BOTTOM_INSET,
            ratio,
        )
        height = max(
            1.0 / ratio,
            round(cls.NOTE_VELOCITY_BAR_HEIGHT * ratio) / ratio,
        )
        rail = QRectF(
            left,
            bottom - height,
            max(0.0, right - left),
            height,
        )
        bounded_velocity = max(0, min(127, int(velocity)))
        fill_width = rail.width() * bounded_velocity / 127.0
        if bounded_velocity:
            fill_width = max(1.0 / ratio, fill_width)
        fill_width = min(rail.width(), fill_width)
        fill = QRectF(rail.left(), rail.top(), fill_width, rail.height())
        return rail, fill

    def grid_rect(self) -> QRectF:
        # The scrollbars live in adjacent layout cells, outside this canvas.
        # Do not subtract their width a second time here.
        return QRectF(
            self.KEY_W,
            self.RULER_H,
            max(0.0, self.width() - self.KEY_W),
            max(0.0, self.height() - self.RULER_H),
        )

    def x_at_time(self, time_ms: float) -> float:
        return self.KEY_W + (float(time_ms) - self.scroll_ms) * self.px_per_ms

    def note_at(self, pos: QPointF) -> tuple[int | None, str]:
        if pos.x() < self.KEY_W or pos.y() < self.RULER_H:
            return None, ""
        for index in reversed(self.visible_note_indices()):
            rect = self.note_rect(self.notes[index])
            if rect.contains(pos):
                if rect.width() >= self.NOTE_RESIZE_VISUAL_MIN_WIDTH:
                    edge_width = min(5.0, rect.width() / 3.0)
                    if abs(pos.x() - rect.left()) <= edge_width:
                        return index, "resize_left"
                    if abs(pos.x() - rect.right()) <= edge_width:
                        return index, "resize_right"
                return index, "move"
        return None, ""

    def time_at(self, x: float) -> float:
        value = max(0.0, self.scroll_ms + (x - self.KEY_W) / self.px_per_ms)
        constrain = getattr(self.editor, "constrain_timeline_time", None)
        return constrain(value) if callable(constrain) else value

    def pitch_at(self, y: float) -> int:
        return max(0, min(127, self.pitch_top - int((y - self.RULER_H) // self.ROW_H)))

    def _roll_background(self) -> QPixmap:
        """Cache the time-independent piano bed and keyboard rendering."""

        uses_percussion_key_labels = bool(
            getattr(self.editor, "uses_percussion_key_labels", False)
        )
        uses_named_percussion_keys = bool(
            getattr(self.editor, "uses_named_percussion_keys", False)
        )
        cache_key = (
            self.width(),
            self.height(),
            int(self.pitch_top),
            round(float(self.ROW_H), 3),
            self.piano_pressed_pitch,
            self.piano_hover_pitch,
            uses_percussion_key_labels,
            uses_named_percussion_keys,
            bool(getattr(self.editor, "canonical_drum_lanes", False)),
            self.scale_pitch_classes,
            self.scale_root_pitch_class,
            self.font().toString(),
            round(self.devicePixelRatioF(), 3),
        )
        if (
            cache_key == self._background_cache_key
            and not self._background_cache.isNull()
        ):
            return self._background_cache

        dpr = max(1.0, float(self.devicePixelRatioF()))
        background = QPixmap(
            QSize(
                max(1, round(self.width() * dpr)),
                max(1, round(self.height() * dpr)),
            )
        )
        background.setDevicePixelRatio(dpr)
        painter = QPainter(background)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), QColor("#1c1d20"))
        grid = self.grid_rect()
        painter.fillRect(grid, QColor("#202125"))
        visible_rows = math.ceil(grid.height() / self.ROW_H)
        for row in range(visible_rows + 1):
            pitch = self.pitch_top - row
            y = self.RULER_H + row * self.ROW_H
            percussion_key_label = (
                self.editor.percussion_key_label(pitch)
                if uses_percussion_key_labels
                else None
            )
            black = pitch % 12 in (1, 3, 6, 8, 10)
            pressed = pitch == self.piano_pressed_pitch
            hovered = pitch == self.piano_hover_pitch
            lane_color = QColor(
                "#191a1d"
                if black
                else ("#24231f" if pitch % 12 == 0 else "#202125")
            )
            if self.scale_pitch_classes is not None:
                pitch_class = pitch % 12
                if pitch_class == self.scale_root_pitch_class:
                    lane_color = QColor("#2a2922")
                elif pitch_class in self.scale_pitch_classes:
                    lane_color = QColor("#23272a")
                else:
                    lane_color = QColor("#18191c")
            painter.fillRect(
                QRectF(
                    self.KEY_W,
                    y,
                    grid.width(),
                    self.ROW_H,
                ),
                lane_color,
            )
            painter.save()
            key_rect = QRectF(0, y, self.KEY_W, self.ROW_H)
            natural_gradient = QLinearGradient(
                key_rect.topLeft(),
                key_rect.topRight(),
            )
            if pressed and not black:
                natural_gradient.setColorAt(0.0, QColor("#43512f"))
                natural_gradient.setColorAt(0.72, QColor("#61763c"))
                natural_gradient.setColorAt(1.0, QColor("#83a543"))
            elif hovered and not black:
                natural_gradient.setColorAt(0.0, QColor("#303033"))
                natural_gradient.setColorAt(0.72, QColor("#39393d"))
                natural_gradient.setColorAt(1.0, QColor("#47474b"))
            else:
                natural_gradient.setColorAt(0.0, QColor("#29292c"))
                natural_gradient.setColorAt(0.72, QColor("#303033"))
                natural_gradient.setColorAt(1.0, QColor("#3a3a3e"))
            if pitch % 12 == 0 and not pressed:
                natural_gradient.setColorAt(1.0, QColor("#474238"))
            painter.fillRect(key_rect, natural_gradient)
            painter.setPen(QColor("#4b4b4f"))
            painter.drawLine(
                1,
                y + 1,
                self.KEY_W - 2,
                y + 1,
            )
            painter.setPen(QColor("#171719"))
            painter.drawLine(
                0,
                y + self.ROW_H - 1,
                self.KEY_W - 1,
                y + self.ROW_H - 1,
            )

            key_font = painter.font()
            if self.ROW_H < self.PIANO_FULL_LABEL_MIN_ROW_HEIGHT:
                key_font.setPixelSize(
                    max(7, min(9, round(self.ROW_H - 2)))
                )
            else:
                key_font.setPointSize(
                    max(7, key_font.pointSize() - 2)
                )
            key_font.setBold(black or percussion_key_label is not None)
            painter.setFont(key_font)
            if black:
                black_key_inset = (
                    1.0
                    if self.ROW_H < self.PIANO_FULL_LABEL_MIN_ROW_HEIGHT
                    else 3.0
                )
                black_rect = QRectF(
                    self.BLACK_KEY_X,
                    y + black_key_inset,
                    self.BLACK_KEY_W,
                    max(2.0, self.ROW_H - black_key_inset * 2.0),
                )
                black_gradient = QLinearGradient(
                    black_rect.topLeft(),
                    black_rect.topRight(),
                )
                if pressed:
                    black_gradient.setColorAt(
                        0.0,
                        QColor("#314024"),
                    )
                    black_gradient.setColorAt(
                        0.76,
                        QColor("#526635"),
                    )
                    black_gradient.setColorAt(
                        1.0,
                        QColor("#789742"),
                    )
                elif hovered:
                    black_gradient.setColorAt(
                        0.0,
                        QColor("#101311"),
                    )
                    black_gradient.setColorAt(
                        0.76,
                        QColor("#1d211e"),
                    )
                    black_gradient.setColorAt(
                        1.0,
                        QColor("#3a3d39"),
                    )
                else:
                    black_gradient.setColorAt(
                        0.0,
                        QColor("#090b0a"),
                    )
                    black_gradient.setColorAt(
                        0.76,
                        QColor("#111412"),
                    )
                    black_gradient.setColorAt(
                        1.0,
                        QColor("#292c29"),
                    )
                painter.fillRect(black_rect, black_gradient)
                painter.setPen(QColor("#050605"))
                painter.drawRect(black_rect)
                if self.ROW_H >= self.PIANO_FULL_LABEL_MIN_ROW_HEIGHT:
                    painter.setPen(
                        QColor(
                            "#fff0ca" if pressed else "#d5d0c7"
                        )
                    )
                    painter.drawText(
                        (
                            key_rect.adjusted(4, 0, -6, 0)
                            if uses_named_percussion_keys
                            else black_rect.adjusted(4, 0, -4, 0)
                        ),
                        Qt.AlignRight | Qt.AlignVCenter,
                        percussion_key_label or note_name(pitch),
                    )
            else:
                painter.setPen(
                    QColor(
                        "#fff0ca"
                        if pressed
                        else (
                            "#d8d3ca"
                            if pitch % 12
                            else "#f0d8a2"
                        )
                    )
                )
                show_natural_label = (
                    percussion_key_label is not None
                    or self.ROW_H >= self.PIANO_FULL_LABEL_MIN_ROW_HEIGHT
                    or pitch % 12 == 0
                    or pressed
                    or hovered
                )
                if show_natural_label:
                    painter.drawText(
                        key_rect.adjusted(4, 0, -6, 0),
                        Qt.AlignRight | Qt.AlignVCenter,
                        percussion_key_label or note_name(pitch),
                    )
            painter.restore()
            painter.setPen(
                QColor("#17181a" if black else "#303135")
            )
            painter.drawLine(
                self.KEY_W,
                y,
                self.width(),
                y,
            )
            if pitch % 12 == 0:
                painter.setPen(QColor(108, 109, 113, 70))
                painter.drawLine(
                    self.KEY_W,
                    y + self.ROW_H - 1,
                    self.width(),
                    y + self.ROW_H - 1,
                )
        painter.end()
        self._background_cache_key = cache_key
        self._background_cache = background
        return background

    def _evidence_tile_rect(self, tile) -> QRectF:
        project_tile_start = (
            float(tile.time_start_ms) + self._audio_offset_ms
        )
        project_tile_end = (
            float(tile.time_end_ms) + self._audio_offset_ms
        )
        highest_pitch = float(tile.pitch_max_exclusive) - 1.0
        top = self.RULER_H + (
            float(self.pitch_top) - highest_pitch
        ) * self.ROW_H
        bottom = self.RULER_H + (
            float(self.pitch_top) - float(tile.pitch_min) + 1.0
        ) * self.ROW_H
        return QRectF(
            self.x_at_time(project_tile_start),
            top,
            max(
                1.0,
                self.x_at_time(project_tile_end)
                - self.x_at_time(project_tile_start),
            ),
            max(1.0, bottom - top),
        )

    def _evidence_tile_ready(self, tile) -> None:
        """Repaint only the completed tile instead of the full piano roll."""

        try:
            dirty = self._evidence_tile_rect(tile).intersected(
                self.grid_rect()
            )
        except (AttributeError, TypeError, ValueError):
            return
        if not dirty.isEmpty():
            self.update(dirty.adjusted(-1, -1, 1, 1).toAlignedRect())

    def _visible_contour_time_warps(
        self,
        project_start_ms: float,
        project_end_ms: float,
    ) -> tuple[
        tuple[
            str,
            TranscriptionCandidate,
            tuple[float, float, float, float],
        ],
        ...,
    ]:
        if not self._candidate_time_warps:
            return ()
        return tuple(
            (candidate_id, candidate, self._candidate_time_warps[candidate_id])
            for candidate_id, candidate in self._visible_candidate_pairs(
                project_start_ms,
                project_end_ms,
            )
            if candidate_id in self._candidate_time_warps
        )

    def _contour_warp_segments_for_tile(
        self,
        tile,
        warps: tuple[
            tuple[
                str,
                TranscriptionCandidate,
                tuple[float, float, float, float],
            ],
            ...,
        ],
    ) -> tuple[tuple[QRectF, QRectF, QRectF], ...]:
        """Map raw contour image slices onto projected candidate time."""

        tile_start = float(tile.time_start_ms)
        tile_end = float(tile.time_end_ms)
        tile_duration = max(1e-9, tile_end - tile_start)
        image_width = max(1, int(tile.image.width()))
        image_height = max(1, int(tile.image.height()))
        tile_target = self._evidence_tile_rect(tile)
        segments: list[tuple[QRectF, QRectF, QRectF]] = []
        for _candidate_id, candidate, warp in warps:
            source_start, source_end, projected_start, projected_end = warp
            overlap_start = max(source_start, tile_start)
            overlap_end = min(source_end, tile_end)
            if overlap_end <= overlap_start or source_end <= source_start:
                continue
            source_fraction_start = (
                overlap_start - source_start
            ) / (source_end - source_start)
            source_fraction_end = (
                overlap_end - source_start
            ) / (source_end - source_start)
            target_start = projected_start + source_fraction_start * (
                projected_end - projected_start
            )
            target_end = projected_start + source_fraction_end * (
                projected_end - projected_start
            )
            source_rect = QRectF(
                (overlap_start - tile_start)
                / tile_duration
                * image_width,
                0.0,
                max(
                    1.0,
                    (overlap_end - overlap_start)
                    / tile_duration
                    * image_width,
                ),
                float(image_height),
            )
            target_rect = QRectF(
                self.x_at_time(target_start + self._audio_offset_ms),
                tile_target.top(),
                max(
                    1.0,
                    self.x_at_time(target_end + self._audio_offset_ms)
                    - self.x_at_time(target_start + self._audio_offset_ms),
                ),
                tile_target.height(),
            )
            candidate_clip = self.candidate_rect(candidate).adjusted(
                -2.0,
                -self.ROW_H * 2.0,
                2.0,
                self.ROW_H * 2.0,
            )
            segments.append((candidate_clip, target_rect, source_rect))
        return tuple(segments)

    def _paint_transcription_evidence(
        self,
        painter: QPainter,
        grid: QRectF,
        paint_left_ms: float,
        paint_right_ms: float,
    ) -> None:
        descriptor = self._evidence_descriptor
        if (
            descriptor is None
            or not self.transcription_candidates_visible
            or (
                self._reference_background_opacity <= 0.0
                and (
                    not self._show_contour_evidence
                    or self._contour_opacity <= 0.0
                )
            )
            or not (
                self._show_frame_evidence
                or self._show_onset_evidence
                or self._show_contour_evidence
            )
        ):
            return
        project_start = max(self.scroll_ms, float(paint_left_ms))
        project_end = min(
            self.time_at(self.width()),
            float(paint_right_ms),
        )
        if project_end <= project_start:
            return
        audio_start = project_start - self._audio_offset_ms
        audio_end = project_end - self._audio_offset_ms
        if audio_end <= 0.0:
            return
        contour_warps = (
            self._visible_contour_time_warps(project_start, project_end)
            if self._show_contour_evidence
            else ()
        )
        if contour_warps:
            audio_start = min(
                audio_start,
                *(warp[0] for _candidate_id, _candidate, warp in contour_warps),
            )
            audio_end = max(
                audio_end,
                *(warp[1] for _candidate_id, _candidate, warp in contour_warps),
            )
        visible_rows = max(
            1, math.ceil(max(0.0, grid.height()) / self.ROW_H)
        )
        pitch_max = max(
            self.MIN_PITCH, min(self.MAX_PITCH, int(self.pitch_top))
        )
        pitch_min = max(
            self.MIN_PITCH,
            min(pitch_max, pitch_max - visible_rows + 1),
        )
        layers = tuple(
            layer
            for layer, enabled in (
                ("frame", self._show_frame_evidence),
                ("onset", self._show_onset_evidence),
            )
            if enabled
        )
        tiles = self._evidence.request_visible(
            descriptor,
            start_ms=max(0.0, audio_start),
            end_ms=max(0.0, audio_end),
            pitch_min=pitch_min,
            pitch_max=pitch_max,
            pixels_per_ms=self.px_per_ms,
            layers=layers,
            include_contour=self._show_contour_evidence,
            contour_denoise=self._contour_denoise_profile,
            contour_color_revision=str(self._contour_color_revision),
            contour_color_spans=self._contour_color_spans,
            contour_default_emphasis=self._contour_default_emphasis,
            update_viewport=(
                project_end - project_start
                >= (
                    self.time_at(self.width()) - self.scroll_ms
                )
                * 0.75
            ),
        )
        painter.save()
        painter.setClipRect(grid)
        contour_clip = (
            self._transcription_contour_clip_path(
                grid,
                self.scroll_ms,
                self.time_at(self.width()),
            )
            if self._show_contour_evidence
            else QPainterPath()
        )
        warped_clip = QPainterPath()
        for _candidate_id, candidate, _warp in contour_warps:
            warped_clip.addRect(
                self.candidate_rect(candidate).adjusted(
                    -2.0,
                    -self.ROW_H * 2.0,
                    2.0,
                    self.ROW_H * 2.0,
                ).intersected(grid)
            )
        normal_contour_clip = (
            contour_clip.subtracted(warped_clip)
            if not warped_clip.isEmpty()
            else contour_clip
        )
        for tile in tiles:
            target = self._evidence_tile_rect(tile)
            if tile.layer == "contour":
                warp_segments = self._contour_warp_segments_for_tile(
                    tile,
                    contour_warps,
                )
                draw_normal = (
                    target.intersects(grid)
                    and not normal_contour_clip.isEmpty()
                )
                draw_warped = any(
                    target_rect.intersects(grid)
                    for _candidate_clip, target_rect, _source_rect
                    in warp_segments
                )
                if not draw_normal and not draw_warped:
                    continue
                painter.save()
                painter.setOpacity(self._contour_opacity)
                painter.setRenderHint(
                    QPainter.RenderHint.SmoothPixmapTransform,
                    True,
                )
                if draw_normal:
                    painter.save()
                    painter.setClipPath(
                        normal_contour_clip,
                        Qt.ClipOperation.IntersectClip,
                    )
                    painter.drawImage(target, tile.image)
                    painter.restore()
                for candidate_clip, target_rect, source_rect in warp_segments:
                    if not target_rect.intersects(grid):
                        continue
                    painter.save()
                    painter.setClipRect(
                        candidate_clip,
                        Qt.ClipOperation.IntersectClip,
                    )
                    painter.drawImage(target_rect, tile.image, source_rect)
                    painter.restore()
                painter.restore()
                continue
            if target.intersects(grid):
                painter.save()
                painter.setOpacity(self._reference_background_opacity)
                painter.setRenderHint(
                    QPainter.RenderHint.SmoothPixmapTransform,
                    False,
                )
                painter.drawImage(target, tile.image)
                painter.restore()
        painter.restore()

    def _transcription_contour_clip_path(
        self,
        grid: QRectF,
        paint_left_ms: float,
        paint_right_ms: float,
    ) -> QPainterPath:
        """Cache the candidate-shaped contour clip across playhead repaints."""

        key = (
            self._candidate_visual_revision,
            round(float(paint_left_ms), 3),
            round(float(paint_right_ms), 3),
            round(float(grid.left()), 2),
            round(float(grid.top()), 2),
            round(float(grid.width()), 2),
            round(float(grid.height()), 2),
            round(float(self.scroll_ms), 3),
            round(float(self.px_per_beat), 4),
            round(float(self.ROW_H), 3),
            int(self.pitch_top),
            round(float(self._audio_offset_ms), 3),
        )
        if key == self._contour_clip_cache_key:
            return self._contour_clip_cache
        path = QPainterPath()
        for _candidate_id, candidate in self._visible_candidate_pairs(
            paint_left_ms,
            paint_right_ms,
        ):
            clipped = self.candidate_rect(candidate).adjusted(
                -2.0,
                -self.ROW_H * 2.0,
                2.0,
                self.ROW_H * 2.0,
            ).intersected(grid)
            if not clipped.isEmpty():
                path.addRect(clipped)
        for _color, bridge in self._visible_candidate_continuity_rects(
            paint_left_ms,
            paint_right_ms,
        ):
            clipped = bridge.adjusted(
                0.0,
                -self.ROW_H * 2.0,
                0.0,
                self.ROW_H * 2.0,
            ).intersected(grid)
            if not clipped.isEmpty():
                path.addRect(clipped)
        self._contour_clip_cache_key = key
        self._contour_clip_cache = path
        self._contour_clip_build_count += 1
        return path

    def _paint_spectrogram_background(
        self,
        painter: QPainter,
        grid: QRectF,
        paint_left_ms: float,
        paint_right_ms: float,
    ) -> None:
        if (
            not self._show_spectrogram
            or not self._spectrogram_audio_path
            or not self.transcription_candidates_visible
            or self._reference_background_opacity <= 0.0
        ):
            return
        project_start = max(self.scroll_ms, float(paint_left_ms))
        project_end = min(
            self.time_at(self.width()),
            float(paint_right_ms),
        )
        if project_end <= project_start:
            return
        audio_start = project_start - self._audio_offset_ms
        audio_end = project_end - self._audio_offset_ms
        if audio_end <= 0.0:
            return
        visible_rows = max(
            1,
            math.ceil(max(0.0, grid.height()) / self.ROW_H),
        )
        pitch_max = max(
            self.MIN_PITCH,
            min(self.MAX_PITCH, int(self.pitch_top)),
        )
        pitch_min = max(
            self.MIN_PITCH,
            min(pitch_max, pitch_max - visible_rows + 1),
        )
        tiles = self._spectrogram.request_visible(
            start_ms=max(0.0, audio_start),
            end_ms=max(0.0, audio_end),
            pitch_min=pitch_min,
            pitch_max=pitch_max,
            pixels_per_ms=self.px_per_ms,
            update_viewport=(
                project_end - project_start
                >= (
                    self.time_at(self.width()) - self.scroll_ms
                )
                * 0.75
            ),
        )
        painter.save()
        painter.setClipRect(grid)
        painter.setOpacity(self._reference_background_opacity)
        for tile in tiles:
            target = self._evidence_tile_rect(tile)
            if target.intersects(grid):
                painter.drawImage(target, tile.image)
        painter.restore()

    def _paint_melody_lines(
        self,
        painter: QPainter,
        grid: QRectF,
        paint_left_ms: float,
        paint_right_ms: float,
    ) -> None:
        """Batch ready semantic paths; analysis never runs in this method."""

        if self._reference_background_opacity <= 0.0:
            return
        segments = self.visible_melody_line_segments(
            paint_left_ms,
            paint_right_ms,
        )
        if not segments:
            return
        paths: dict[tuple[str, int, bool, str], QPainterPath] = {}
        chord_labels: list[tuple[str, QPointF, float]] = []
        for segment in segments:
            confidence_bucket = melody_line_confidence_bucket(
                segment.confidence
            )
            key = (
                segment.role,
                confidence_bucket,
                bool(segment.branch),
                segment.kind,
            )
            path = paths.setdefault(key, QPainterPath())
            start, end = self._melody_line_points(segment)
            path.moveTo(start)
            end = QPointF(max(start.x() + 0.5, end.x()), end.y())
            if segment.kind == MELODY_LINE_CONNECTOR_KIND:
                span = max(0.5, end.x() - start.x())
                path.cubicTo(
                    QPointF(start.x() + span * 0.35, start.y()),
                    QPointF(start.x() + span * 0.65, end.y()),
                    end,
                )
            else:
                path.lineTo(end)
            if (
                segment.kind == MELODY_LINE_CHORD_SPAN_KIND
                and segment.label
                and end.x() - start.x() >= 34.0
            ):
                chord_labels.append(
                    (segment.label, start, segment.confidence)
                )

        colors = {
            MELODY_LINE_PRIMARY_ROLE: QColor("#f0b54d"),
            MELODY_LINE_BASS_ROLE: QColor("#54c3b9"),
            MELODY_LINE_HARMONY_ROLE: QColor("#a58bd5"),
        }
        painter.save()
        painter.setClipRect(grid)
        painter.setOpacity(self._reference_background_opacity)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        kind_order = {
            MELODY_LINE_CHORD_SPAN_KIND: 0,
            MELODY_LINE_CONTOUR_KIND: 1,
            MELODY_LINE_CONNECTOR_KIND: 2,
        }
        for (role, confidence_bucket, branch, kind), path in sorted(
            paths.items(),
            key=lambda item: (
                kind_order.get(item[0][3], 3),
                item[0][2],
                item[0][1],
                item[0][0],
            ),
        ):
            confidence = (
                confidence_bucket / MELODY_LINE_CONFIDENCE_BUCKETS
            )
            color = QColor(colors.get(role, QColor("#a9a49c")))
            if kind == MELODY_LINE_CHORD_SPAN_KIND:
                color.setAlpha(max(24, min(70, 28 + round(confidence * 42))))
                width = max(1.2, melody_line_width(confidence))
            else:
                color.setAlpha(
                    max(
                        32,
                        min(
                            118,
                            38
                            + round(confidence * 80)
                            - (12 if branch else 0),
                        ),
                    )
                )
                width = melody_line_width(confidence)
            pen = QPen(
                color,
                width,
                Qt.DashLine if branch else Qt.SolidLine,
            )
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

        if melody_line_lod(self.px_per_beat) <= 1:
            painter.setPen(QColor(224, 214, 239, 165))
            for label, anchor, confidence in chord_labels:
                if not grid.top() <= anchor.y() <= grid.bottom():
                    continue
                text_x = max(grid.left() + 22.0, anchor.x() + 5.0)
                painter.drawText(
                    QPointF(text_x, anchor.y() - 5.0),
                    f"{label} {round(confidence * 100)}%",
                )
        painter.restore()

    def _paint_unsupported_evidence_rows(
        self, painter: QPainter, grid: QRectF
    ) -> None:
        if not self.transcription_candidates_visible:
            return
        visible_rows = math.ceil(grid.height() / self.ROW_H)
        painter.save()
        painter.setClipRect(
            QRectF(self.KEY_W - 4, grid.top(), 8, grid.height())
        )
        for row in range(visible_rows + 1):
            pitch = self.pitch_top - row
            if self.MIN_PITCH <= pitch <= self.MAX_PITCH and self.editor.note_invalid(pitch):
                y = self.RULER_H + row * self.ROW_H
                painter.fillRect(
                    QRectF(self.KEY_W - 3, y + 2, 3, self.ROW_H - 4),
                    QColor(216, 100, 90, 138),
                )
        painter.restore()

    def _visible_harmony_segments(
        self, project_start_ms: float, project_end_ms: float
    ) -> tuple[object, ...]:
        analysis = self._harmony_analysis
        segments = tuple(
            getattr(analysis, "chord_segments", ()) or ()
        )
        if not segments or not self._harmony_segment_starts:
            return ()
        audio_start = float(project_start_ms) - self._audio_offset_ms
        audio_end = float(project_end_ms) - self._audio_offset_ms
        first = max(
            0,
            bisect_left(
                self._harmony_segment_starts,
                audio_start - self._max_harmony_segment_duration,
            ),
        )
        last = bisect_right(self._harmony_segment_starts, audio_end)
        return tuple(
            segment
            for segment in segments[first:last]
            if float(getattr(segment, "end_audio_ms", 0.0))
            > audio_start
            and float(getattr(segment, "start_audio_ms", 0.0))
            < audio_end
        )

    def _chord_segment_at(self, position: QPointF) -> object | None:
        if (
            position.x() < self.KEY_W
            or position.y() < self.TIME_RULER_H
            or position.y() >= self.RULER_H
        ):
            return None
        project_ms = self.time_at(position.x())
        for segment in self._visible_harmony_segments(
            project_ms - 1.0, project_ms + 1.0
        ):
            start_ms = (
                float(getattr(segment, "start_audio_ms", 0.0))
                + self._audio_offset_ms
            )
            end_ms = (
                float(getattr(segment, "end_audio_ms", 0.0))
                + self._audio_offset_ms
            )
            if start_ms <= project_ms < end_ms:
                return segment
        return None

    @staticmethod
    def _roman_degree(
        root_pc: int | None,
        key: object | None,
        quality: str = "",
    ) -> str:
        if root_pc is None or key is None:
            return ""
        key_root = getattr(key, "root_pc", None)
        mode = str(getattr(key, "mode", "") or "")
        if key_root is None or mode not in {"major", "minor"}:
            return ""
        interval = (int(root_pc) - int(key_root)) % 12
        table = (
            {0: "I", 2: "II", 4: "III", 5: "IV", 7: "V", 9: "VI", 11: "VII"}
            if mode == "major"
            else {
                0: "I",
                2: "II",
                3: "III",
                5: "IV",
                7: "V",
                8: "VI",
                10: "VII",
            }
        )
        roman = table.get(interval, "·")
        if roman == "·":
            return roman
        if quality in {"minor", "min7", "dim", "half_diminished7"}:
            roman = roman.lower()
        if quality == "dim":
            roman += "°"
        elif quality == "half_diminished7":
            roman += "ø"
        return roman

    def _chord_display_label(
        self,
        root_pc: int | None,
        quality: str,
        bass_pc: int | None = None,
    ) -> str:
        if root_pc is None or quality == "N":
            return "N"
        suffix = {
            "major": "",
            "minor": "m",
            "dim": "°",
            "sus2": "sus2",
            "sus4": "sus4",
            "maj7": "maj7",
            "7": "7",
            "min7": "m7",
            "half_diminished7": "ø7",
        }.get(quality, quality)
        label = f"{self.editor._pitch_class_label(int(root_pc))}{suffix}"
        if bass_pc is not None and int(bass_pc) != int(root_pc):
            label += f"/{self.editor._pitch_class_label(int(bass_pc))}"
        return label

    def _paint_harmony_lane(
        self,
        painter: QPainter,
        paint_left_ms: float,
        paint_right_ms: float,
    ) -> None:
        lane = QRectF(
            self.KEY_W,
            self.TIME_RULER_H,
            max(0.0, self.width() - self.KEY_W),
            self.CHORD_H,
        )
        painter.fillRect(lane, QColor("#202124"))
        painter.setPen(QPen(QColor(83, 76, 63, 150), 1))
        painter.drawLine(
            lane.left(), lane.top(), lane.right(), lane.top()
        )
        painter.drawLine(
            lane.left(), lane.bottom(), lane.right(), lane.bottom()
        )
        analysis = self._harmony_analysis
        if analysis is None:
            return
        conflict_ids = {
            str(getattr(conflict, "segment_id", ""))
            for conflict in getattr(analysis, "conflicts", ())
        }
        global_key = getattr(analysis, "global_key", None)
        for segment in self._visible_harmony_segments(
            paint_left_ms, paint_right_ms
        ):
            start_project_ms = (
                float(getattr(segment, "start_audio_ms", 0.0))
                + self._audio_offset_ms
            )
            end_project_ms = (
                float(getattr(segment, "end_audio_ms", 0.0))
                + self._audio_offset_ms
            )
            left = self.x_at_time(start_project_ms)
            right = self.x_at_time(end_project_ms)
            rect = QRectF(
                left + 1,
                self.TIME_RULER_H + 2,
                max(1.0, right - left - 2),
                self.CHORD_H - 4,
            ).intersected(lane)
            confidence = max(
                0.0,
                min(1.0, float(getattr(segment, "confidence", 0.0))),
            )
            quality = str(getattr(segment, "quality", "N") or "N")
            root_pc = getattr(segment, "root_pc", None)
            fill = QColor(
                "#61533c" if quality != "N" else "#35363a"
            )
            fill.setAlpha(64 + round(confidence * 80))
            painter.fillRect(rect, fill)
            segment_id = str(getattr(segment, "segment_id", ""))
            border = (
                QColor("#df9b54")
                if segment_id in conflict_ids
                else QColor("#7d725f")
            )
            painter.setPen(
                QPen(
                    border,
                    1.5
                    if bool(getattr(segment, "locked", False))
                    else 1.0,
                )
            )
            painter.drawRect(rect)
            if rect.width() < 24:
                continue
            chord = self._chord_display_label(
                root_pc,
                quality,
                getattr(segment, "bass_pc", None),
            )
            roman = self._roman_degree(root_pc, global_key, quality)
            label = chord + (f" · {roman}" if roman else "")
            if segment_id in conflict_ids:
                label += " ?"
            if bool(getattr(segment, "locked", False)):
                label = "◆ " + label
            painter.setPen(
                QColor("#e8dfcf" if confidence >= 0.45 else "#b8ab98")
            )
            painter.drawText(
                rect.adjusted(5, 0, -3, 0),
                Qt.AlignLeft | Qt.AlignVCenter,
                label,
            )

    def _paint_transcription_candidates(
        self,
        painter: QPainter,
        grid: QRectF,
        paint_left_ms: float,
        paint_right_ms: float,
    ) -> None:
        """Paint clean semantic blocks using orthogonal visual channels."""

        if (
            not self._transcription_candidate_layer_visible
            or self._transcription_candidate_opacity <= 0.0
        ):
            return
        painter.save()
        painter.setOpacity(self._transcription_candidate_opacity)

        # A bridge is presentation-only: individual onset caps, hit targets,
        # IDs and draft adoption remain unchanged.  It simply prevents an
        # evidence-backed false split from looking like unrelated blocks.
        if not self._show_rejected_only:
            for color_name, bridge in self._visible_candidate_continuity_rects(
                paint_left_ms,
                paint_right_ms,
            ):
                color = QColor(color_name)
                color.setAlpha(96)
                painter.fillRect(bridge, color)

        groups: dict[
            tuple[bool, str, int, str, int, float, object],
            list[QRectF],
        ] = defaultdict(list)
        invalid_lines: list[tuple[QPointF, QPointF]] = []
        rejected_lines: list[tuple[QPointF, QPointF]] = []
        onset_caps: list[QRectF] = []
        confidence_rails: dict[
            bool,
            list[tuple[QPointF, QPointF]],
        ] = defaultdict(list)
        pending_markers: list[QRectF] = []
        fragment_markers: list[QRectF] = []
        guidance_markers: list[QRectF] = []
        role_markers: dict[str, list[QRectF]] = defaultdict(list)
        labels: list[
            tuple[QRectF, int, float, float | None, str, str]
        ] = []
        beat_width = float(self.px_per_beat)
        show_detail = (
            beat_width > 160.0
            and self.ROW_H >= self.NOTE_TEXT_MIN_HEIGHT
        )
        show_onsets = show_detail
        expanded_fold_primaries = self._expanded_fold_primaries()
        for candidate_id, candidate in self._visible_candidate_pairs(
            paint_left_ms,
            paint_right_ms,
        ):
            if not self._candidate_is_displayed_in_fold(
                candidate_id,
                expanded_fold_primaries,
            ):
                continue
            rect = self._candidate_display_rect(
                candidate_id,
                candidate,
                expanded_primaries=expanded_fold_primaries,
            )
            if not rect.intersects(grid):
                continue
            invalid = (
                candidate_id in self._invalid_candidate_ids
                or self.editor._candidate_invalid_for_current_track(candidate)
            )
            duplicate = candidate_id in self._duplicate_candidate_ids
            rejected = candidate_id in self._rejected_candidate_ids
            pending = candidate_id in self._pending_candidate_ids
            fragment = candidate_id in self._fragment_candidate_ids
            suppressed = candidate_id in self._suppressed_candidate_ids
            selected = candidate_id in self._selected_candidate_ids
            hovered = candidate_id == self._hovered_candidate_id
            confidence = max(
                0.0,
                min(1.0, float(candidate.confidence)),
            )
            color_name = self._candidate_group_colors.get(
                candidate_id,
                "#5baaa4",
            )
            group_emphasis = self._candidate_group_emphases.get(
                candidate_id,
                1.0,
            )
            guided_instrument = self._candidate_guided_instrument_labels.get(
                candidate_id,
                "",
            )
            opacity_confidence = round(confidence * 7.0) / 7.0
            # Confidence is an opacity channel only.  The slider controls how
            # strongly weak evidence remains visible; it never filters it.
            visible_confidence = (
                self._confidence_floor
                + opacity_confidence * (1.0 - self._confidence_floor)
            )
            # Normal suggestions are deliberately outline-led.  Confidence
            # gets its own short lower rail instead of making strong results
            # look like opaque, already-committed notes.
            fill_alpha = 12 + round(visible_confidence * 54)
            if rejected:
                fill_alpha = min(fill_alpha, 24)
            elif suppressed:
                fill_alpha = min(fill_alpha, 18)
            elif beat_width < 40.0:
                fill_alpha = min(fill_alpha, 38)
            if not selected and not hovered:
                fill_alpha = max(
                    6,
                    min(255, round(fill_alpha * group_emphasis)),
                )

            if selected:
                outline_name = "#fff1c8"
                fill_alpha = max(fill_alpha, 82)
            elif hovered:
                outline_name = "#9edbff"
                fill_alpha = max(fill_alpha, 50)
            elif invalid:
                outline_name = "#e88479"
            elif duplicate:
                outline_name = "#99958e"
            elif pending:
                outline_name = "#8ae1d4"
            elif fragment:
                outline_name = "#e0a341"
            else:
                outline_name = color_name
            outline_alpha = 255 if selected else 104 + round(
                opacity_confidence * 92
            )
            if not selected and not hovered:
                outline_alpha = max(
                    52,
                    min(255, round(outline_alpha * group_emphasis)),
                )
            line_style = (
                Qt.DashLine
                if rejected or fragment or suppressed
                else Qt.SolidLine
            )
            groups[
                (
                    selected,
                    color_name,
                    fill_alpha,
                    outline_name,
                    outline_alpha,
                    2.0 if selected or invalid else 1.2,
                    line_style,
                )
            ].append(rect)
            if (
                not rejected
                and not suppressed
                and rect.width() >= 8.0
                and rect.height() >= 5.0
            ):
                left = rect.left() + 2.0
                usable_width = max(1.0, rect.width() - 4.0)
                confidence_rails[selected].append(
                    (
                        QPointF(left, rect.bottom() - 1.5),
                        QPointF(
                            left + usable_width * confidence,
                            rect.bottom() - 1.5,
                        ),
                    )
                )
            if invalid:
                invalid_lines.append(
                    (rect.topLeft(), rect.bottomRight())
                )
            if rejected:
                rejected_lines.append(
                    (
                        QPointF(rect.left(), rect.center().y()),
                        QPointF(rect.right(), rect.center().y()),
                    )
                )
            if show_onsets:
                onset_caps.append(
                    QRectF(
                        rect.left(),
                        rect.top() + 1,
                        min(2.0, rect.width()),
                        max(1.0, rect.height() - 2),
                    )
                )
            if pending:
                pending_markers.append(
                    QRectF(
                        max(rect.left(), rect.right() - 4),
                        rect.top() + 2,
                        3,
                        3,
                    )
                )
            if fragment:
                fragment_markers.append(
                    QRectF(
                        max(rect.left(), rect.right() - 4),
                        rect.top() + 1,
                        3,
                        3,
                    )
                )
            if guided_instrument and not rejected and not suppressed:
                guidance_markers.append(
                    QRectF(
                        rect.left() + 2.0,
                        rect.top() + 1.0,
                        max(1.0, rect.width() - 4.0),
                        2.0,
                    )
                )
            role = self._candidate_chord_roles.get(candidate_id, "")
            if show_detail and role and rect.width() >= 5:
                role_markers[role].append(
                    QRectF(
                        rect.left() + (2.0 if show_onsets else 0.0),
                        rect.top() + 2,
                        2,
                        max(1.0, rect.height() - 4),
                    )
                )
            if (
                rect.width() >= 42
                and rect.height() >= self.NOTE_TEXT_MIN_HEIGHT
                and (selected or hovered)
            ):
                labels.append(
                    (
                        rect,
                        int(candidate.pitch),
                        confidence,
                        self._candidate_group_confidences.get(candidate_id),
                        candidate_id,
                        guided_instrument,
                    )
                )

        # Selected blocks paint last so their neutral outline remains legible
        # without repurposing the instrument hue.
        for style, rects in sorted(
            groups.items(),
            key=lambda item: item[0][0],
        ):
            (
                _selected,
                color_name,
                fill_alpha,
                outline_name,
                outline_alpha,
                width,
                line_style,
            ) = style
            fill = QColor(color_name)
            fill.setAlpha(fill_alpha)
            outline = QColor(outline_name)
            outline.setAlpha(outline_alpha)
            painter.setBrush(fill)
            painter.setPen(QPen(outline, width, line_style))
            painter.drawRects(rects)

        # A two-pixel confidence rail is easier to compare than many labels
        # and remains readable without increasing the block's visual weight.
        for selected, lines in confidence_rails.items():
            rail_color = QColor("#f5d08a" if selected else "#7fc7e8")
            rail_color.setAlpha(205)
            painter.setPen(QPen(rail_color, 2.0, Qt.SolidLine, Qt.RoundCap))
            for start, end in lines:
                painter.drawLine(start, end)

        if onset_caps:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(224, 170, 90, 210))
            painter.drawRects(onset_caps)
        role_colors = {
            "root": QColor("#e1b45b"),
            "third": QColor("#82a9d8"),
            "fifth": QColor("#79bcb0"),
            "seventh": QColor("#aa8bd2"),
        }
        painter.setPen(Qt.NoPen)
        for role, rects in role_markers.items():
            painter.setBrush(role_colors.get(role, QColor("#aaa59d")))
            painter.drawRects(rects)
        if pending_markers:
            painter.setBrush(QColor("#b9f0e7"))
            painter.drawRects(pending_markers)
        if fragment_markers:
            painter.setBrush(QColor("#f0ae42"))
            painter.drawRects(fragment_markers)
        if guidance_markers:
            # A non-colour cue marks the user-guided instrument assignment on
            # both low- and high-confidence reference blocks.
            painter.setBrush(QColor("#f5d08a"))
            painter.drawRects(guidance_markers)
        if invalid_lines:
            painter.setPen(QPen(QColor("#e88479"), 1))
            for start, end in invalid_lines:
                painter.drawLine(start, end)
        if rejected_lines:
            painter.setPen(QPen(QColor(180, 138, 132, 190), 1))
            for start, end in rejected_lines:
                painter.drawLine(start, end)
        for (
            rect,
            pitch,
            confidence,
            classification_confidence,
            _candidate_id,
            guided_instrument,
        ) in labels:
            painter.setPen(QColor("#f0eee8"))
            alternatives = self._fold_alternative_counts.get(
                _candidate_id, 0
            )
            confidence_text = f"{confidence:.0%}"
            if classification_confidence is not None:
                confidence_text = trf(
                    "识别 {recognition}% · 分类 {classification}%",
                    recognition=round(confidence * 100.0),
                    classification=round(
                        max(0.0, min(1.0, classification_confidence))
                        * 100.0
                    ),
                )
            painter.drawText(
                rect.adjusted(6, 0, -3, 0),
                Qt.AlignLeft | Qt.AlignVCenter,
                (
                    (
                        trf("引导：{instrument} · ", instrument=guided_instrument)
                        if guided_instrument
                        else ""
                    )
                    + f"{note_name(pitch)} · {confidence_text}"
                    + (f" · +{alternatives}" if alternatives else "")
                ),
            )
        painter.restore()

    @staticmethod
    def _paint_marquee_overlay(painter: QPainter, rect: QRectF) -> None:
        """Paint a light marquee without inheriting a note-fill brush."""

        painter.save()
        painter.fillRect(rect, QColor(245, 165, 36, 18))
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor("#f5a524"), 1, Qt.DashLine))
        painter.drawRect(rect)
        painter.restore()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        # The roll is dominated by axis-aligned rectangles and one-pixel grid
        # lines.  Disabling antialiasing keeps dense 12k-note views within the
        # realtime repaint budget without changing their visual geometry.
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.drawPixmap(0, 0, self._roll_background())
        grid = self.grid_rect()
        paint_rect = _event.rect()
        paint_left_ms = self.time_at(
            max(float(self.KEY_W), float(paint_rect.left()))
        )
        paint_right_ms = self.time_at(
            max(float(self.KEY_W), float(paint_rect.right()))
        )
        visible_rows = math.ceil(grid.height() / self.ROW_H)
        self._paint_spectrogram_background(
            painter,
            grid,
            paint_left_ms,
            paint_right_ms,
        )
        self._paint_transcription_evidence(
            painter,
            grid,
            paint_left_ms,
            paint_right_ms,
        )
        self._paint_unsupported_evidence_rows(painter, grid)
        # Evidence sits below the editing grid.  Redraw horizontal guides after
        # the ready QImages so pitch rows remain legible at high intensity.
        evidence_overlays_grid = (
            self.transcription_candidates_visible
            and self._reference_background_opacity > 0.0
            and (
                (self._show_spectrogram and bool(self._spectrogram_audio_path))
                or (
                    self._evidence_descriptor is not None
                    and (
                        self._show_frame_evidence
                        or self._show_onset_evidence
                        or self._show_contour_evidence
                    )
                )
            )
        )
        if evidence_overlays_grid:
            for row in range(visible_rows + 1):
                pitch = self.pitch_top - row
                y = self.RULER_H + row * self.ROW_H
                painter.setPen(
                    QColor(24, 24, 26, 165)
                    if pitch % 12 in (1, 3, 6, 8, 10)
                    else QColor(52, 52, 56, 130)
                )
                painter.drawLine(self.KEY_W, y, self.width(), y)
                if pitch % 12 == 0:
                    painter.setPen(QColor(100, 80, 42, 42))
                    painter.drawLine(
                        self.KEY_W,
                        y + self.ROW_H - 1,
                        self.width(),
                        y + self.ROW_H - 1,
                    )
        painter.fillRect(QRectF(0, 0, self.width(), self.RULER_H), QColor("#2c2c30"))
        painter.fillRect(QRectF(0, 0, self.KEY_W, self.RULER_H), QColor("#242427"))
        grid_edge = QColor(91, 72, 37, 145)
        painter.fillRect(
            QRectF(self.KEY_W - 1, self.RULER_H, 1, grid.height()),
            grid_edge,
        )
        painter.fillRect(
            QRectF(self.KEY_W, self.RULER_H - 1, grid.width(), 1),
            grid_edge,
        )
        clip_scope = getattr(self.editor, "clip_scope", None)
        if clip_scope is not None:
            clip_left = self.x_at_time(clip_scope.timeline_start_ms)
            clip_right = self.x_at_time(clip_scope.timeline_end_ms)
            if clip_left > self.KEY_W:
                painter.fillRect(
                    QRectF(
                        self.KEY_W,
                        0,
                        min(self.width(), clip_left) - self.KEY_W,
                        self.height(),
                    ),
                    QColor(8, 8, 9, 185),
                )
            if clip_right < self.width():
                painter.fillRect(
                    QRectF(
                        max(self.KEY_W, clip_right),
                        0,
                        self.width() - max(self.KEY_W, clip_right),
                        self.height(),
                    ),
                    QColor(8, 8, 9, 185),
                )
            painter.setPen(QPen(QColor("#d3a24b"), 2))
            for boundary_x in (clip_left, clip_right):
                if self.KEY_W <= boundary_x <= self.width():
                    painter.drawLine(
                        boundary_x, 0, boundary_x, self.height()
                    )
        # Time-axis content must never paint over the fixed piano keyboard.
        # This matters after horizontal scrolling, when a long note's logical
        # rectangle can begin well to the left of the visible grid.
        painter.save()
        painter.setClipRect(QRectF(
            self.KEY_W, 0, max(0.0, self.width() - self.KEY_W), self.height()
        ))
        step_ms = self.editor.quantize_ms()
        beat_origin = float(getattr(self.editor, "beat_origin_ms", 0.0))
        right_ms = self.time_at(self.width())
        first = beat_origin + math.floor(
            (self.scroll_ms - beat_origin) / step_ms
        ) * step_ms
        t = first
        while t <= right_ms + step_ms:
            x = self.x_at_time(t)
            beat_position = (t - beat_origin) / self.beat_ms
            beat_index = round(beat_position)
            is_beat = abs(beat_position - beat_index) < .02
            is_measure = (
                beat_index % max(1, self.editor.time_sig) == 0
                and is_beat
            )
            if is_measure:
                grid_color = QColor(112, 88, 45, 135)
                grid_width = 1.5
            elif is_beat:
                grid_color = QColor(84, 73, 52, 105)
                grid_width = 1
            else:
                grid_color = QColor(52, 52, 56, 105)
                grid_width = 1
            painter.setPen(QPen(grid_color, grid_width))
            painter.drawLine(
                x,
                0 if is_measure else self.RULER_H,
                x,
                self.height(),
            )
            painter.drawLine(
                x,
                self.TIME_RULER_H - (9 if is_measure else (7 if is_beat else 4)),
                x,
                self.TIME_RULER_H - 3,
            )
            if is_measure:
                painter.setPen(QColor("#d8c7ab"))
                painter.drawText(
                    int(x + 4),
                    19,
                    str(beat_index // max(1, self.editor.time_sig) + 1),
                )
            t += step_ms
        grid_denominator = max(
            1,
            round(4.0 * self.beat_ms / max(0.001, step_ms)),
        )
        grid_label = f"{tr('网格')} 1/{grid_denominator}"
        label_width = max(
            72,
            painter.fontMetrics().horizontalAdvance(grid_label) + 18,
        )
        grid_label_rect = QRectF(
            self.KEY_W + 8,
            5,
            label_width,
            self.TIME_RULER_H - 10,
        )
        painter.fillRect(grid_label_rect, QColor("#1c1c1e"))
        painter.setPen(QPen(QColor(91, 72, 37, 145), 1))
        painter.drawRect(grid_label_rect)
        painter.setPen(QColor("#ffedd4"))
        painter.drawText(grid_label_rect, Qt.AlignCenter, grid_label)
        self._paint_timeline_markers(painter)
        self._paint_harmony_lane(
            painter,
            paint_left_ms,
            paint_right_ms,
        )
        self._paint_melody_lines(
            painter,
            grid,
            paint_left_ms,
            paint_right_ms,
        )
        transcription_range = self.transcription_time_range
        if transcription_range is not None:
            range_left = self.x_at_time(transcription_range[0])
            range_right = self.x_at_time(transcription_range[1])
            selection_rect = QRectF(
                min(range_left, range_right),
                self.RULER_H,
                abs(range_right - range_left),
                grid.height(),
            ).intersected(grid)
            painter.fillRect(selection_rect, QColor(245, 165, 36, 18))
            painter.setPen(QPen(QColor(172, 127, 57, 170), 1))
            painter.drawLine(
                range_left,
                self.RULER_H,
                range_left,
                self.height(),
            )
            painter.drawLine(
                range_right,
                self.RULER_H,
                range_right,
                self.height(),
            )
        if self.ghost_notes and self._ghost_opacity > 0.0:
            painter.save()
            painter.setOpacity(self._ghost_opacity)
            ghost_color_cache: dict[str, QColor] = {}
            for ghost in self.visible_ghost_notes(
                paint_left_ms,
                paint_right_ms,
            ):
                rect = self.note_rect(ghost)
                if not rect.intersects(grid):
                    continue
                color_key = str(ghost.color)
                reference_color = ghost_color_cache.get(color_key)
                if reference_color is None:
                    reference_color = QColor(color_key)
                    reference_color.setAlpha(220)
                    ghost_color_cache[color_key] = reference_color
                center_y = rect.center().y()
                painter.setBrush(reference_color)
                painter.setPen(
                    QPen(
                        reference_color,
                        max(1.25, min(2.5, rect.height() * 0.10)),
                        Qt.SolidLine,
                        Qt.RoundCap,
                    )
                )
                painter.drawLine(
                    QPointF(rect.left() + 2.0, center_y),
                    QPointF(rect.right() - 1.0, center_y),
                )
                painter.drawEllipse(
                    QPointF(rect.left() + 2.0, center_y),
                    2.2,
                    2.2,
                )
            painter.restore()
        self._paint_transcription_candidates(
            painter,
            grid,
            paint_left_ms,
            paint_right_ms,
        )
        selected = self.selected
        default_articulation = int(
            getattr(self.editor, "default_articulation_ntype", 0)
        )
        device_pixel_ratio = self.devicePixelRatioF()
        track_color = self._editable_note_base_color()
        normal_outline = self._bounded_note_color(
            track_color.lighter(112),
            maximum_value=168,
        )
        fill_colors: dict[tuple[int, int], QColor] = {}
        technique_colors: dict[int, QColor] = {}
        for index in self.visible_note_indices(
            paint_left_ms,
            paint_right_ms,
        ):
            note = self.notes[index]
            rect = self.note_rect(note)
            if not rect.intersects(grid):
                continue
            velocity = max(0, min(127, int(note.vel)))
            note_type = int(getattr(note, "ntype", 0))
            articulated = note_type != default_articulation
            technique_color = None
            if articulated:
                technique_color = technique_colors.get(note_type)
                if technique_color is None:
                    technique_color = self._technique_accent_color(note_type)
                    technique_colors[note_type] = technique_color
            fill_key = (velocity, note_type)
            fill = fill_colors.get(fill_key)
            if fill is None:
                fill = self._note_fill_color(note, track_color=track_color)
                fill_colors[fill_key] = fill
            if invalid := self.editor.note_invalid(note.pitch):
                fill = QColor("#624442")
            compact_height = rect.height() < self.NOTE_TEXT_MIN_HEIGHT
            body_inset = 0.5 if compact_height else 0.75
            body_rect = rect.adjusted(
                body_inset,
                body_inset,
                -body_inset,
                -body_inset,
            )
            corner_radius = min(
                1.25 if compact_height else 2.5,
                max(0.75, body_rect.height() * 0.14),
                max(0.75, body_rect.width() * 0.25),
            )
            # Flat blocks keep pitch, duration and selection legible without
            # a second decorative layer. Velocity is already encoded in the
            # fill value and repeated as one direct proportional bar below.
            painter.setBrush(fill)
            hovered = index == self.hovered_note_index
            note_outline_pen = QPen(
                QColor("#b85d58")
                if invalid
                else (
                    QColor("#ae8c52")
                    if index in selected
                    else (
                        QColor("#dbc18b")
                        if hovered
                        else (technique_color or normal_outline)
                    )
                ),
                (
                    1.5
                    if compact_height and (index in selected or invalid)
                    else (
                        2.0
                        if index in selected or invalid
                        else (1.5 if hovered else 1.0)
                    )
                ),
            )
            painter.setPen(note_outline_pen)
            painter.drawRoundedRect(
                body_rect,
                corner_radius,
                corner_radius,
            )
            velocity_rects = self.note_velocity_bar_rects(
                rect,
                velocity,
                device_pixel_ratio,
            )
            if velocity_rects is not None:
                velocity_rail, velocity_fill = velocity_rects
                painter.fillRect(velocity_rail, QColor(10, 11, 12, 155))
                painter.fillRect(
                    velocity_fill,
                    QColor(
                        "#ffe0a3"
                        if index in selected
                        else "#d8c7a3"
                    ),
                )
            if (
                rect.width() >= 28
                and rect.height() >= self.NOTE_TEXT_MIN_HEIGHT
            ):
                painter.save()
                # Preserve the outer time-grid clip. Replacing it here lets a
                # partially visible note paint its pitch label over the fixed
                # piano keyboard after horizontal scrolling.
                painter.setClipRect(
                    rect.adjusted(2, 1, -2, -1),
                    Qt.ClipOperation.IntersectClip,
                )
                label_font = painter.font()
                label_font.setPointSize(
                    max(
                        6,
                        label_font.pointSize()
                        - (2 if rect.width() < 34 else 1),
                    )
                )
                label_font.setBold(index in selected)
                painter.setFont(label_font)
                painter.setPen(self._note_text_color(fill))
                painter.drawText(
                    rect.adjusted(5, 0, -24 if articulated and rect.width() >= 52 else -2, 0),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    self.editor.note_block_label(note.pitch),
                )
                painter.restore()
            if (
                index in selected
                and rect.width() >= self.NOTE_RESIZE_VISUAL_MIN_WIDTH
                and rect.height() >= self.NOTE_RESIZE_HANDLE_MIN_HEIGHT
            ):
                handle = QColor("#b7a177")
                painter.fillRect(QRectF(rect.left() + 1, rect.top() + 3, 3, max(4, rect.height() - 6)), handle)
                painter.fillRect(QRectF(rect.right() - 3, rect.top() + 3, 3, max(4, rect.height() - 6)), handle)
            if articulated and technique_color is not None:
                technique_badge_color = QColor(technique_color)
                technique_badge_color.setAlpha(218)
                # Technique identity stays visible even when selection handles
                # are shown; the old left stripe was painted underneath them.
                painter.fillRect(
                    QRectF(
                        rect.left() + 1,
                        rect.top() + 1,
                        max(1.0, min(22.0, rect.width() - 2.0)),
                        1.0 if compact_height else 3.0,
                    ),
                    technique_badge_color,
                )
                if (
                    rect.width() >= 52
                    and rect.height() >= self.NOTE_TECHNIQUE_BADGE_MIN_HEIGHT
                ):
                    painter.save()
                    badge_rect = QRectF(
                        rect.right() - 23,
                        rect.top() + 4,
                        19,
                        max(8.0, rect.height() - 8),
                    )
                    painter.fillRect(badge_rect, QColor(15, 16, 17, 148))
                    badge_font = painter.font()
                    badge_font.setPointSize(max(6, badge_font.pointSize() - 2))
                    badge_font.setBold(True)
                    painter.setFont(badge_font)
                    painter.setPen(technique_badge_color)
                    painter.drawText(
                        badge_rect,
                        Qt.AlignCenter,
                        f"T{note_type}",
                    )
                    painter.restore()
        edit_x = self.x_at_time(self.edit_cursor_ms)
        if self.KEY_W <= edit_x <= self.width():
            painter.setPen(QPen(QColor("#63c7bd"), 1, Qt.DashLine))
            painter.drawLine(edit_x, self.RULER_H, edit_x, self.height())
            marker = QPainterPath()
            marker.moveTo(edit_x - 5, self.RULER_H)
            marker.lineTo(edit_x + 5, self.RULER_H)
            marker.lineTo(edit_x, self.RULER_H + 7)
            marker.closeSubpath()
            painter.fillPath(marker, QColor("#63c7bd"))
        play_x = self.x_at_time(self.playhead_ms)
        if self.KEY_W - 1 <= play_x <= self.width():
            # Keep the zero-position cursor inside the grid instead of hiding it
            # under the piano-key/grid divider.
            play_x = max(self.KEY_W + 2.0, min(self.width() - 3.0, play_x))
            playhead_color = QColor("#c59643")
            painter.fillRect(
                QRectF(play_x - 3, 0, 6, self.height()),
                QColor(197, 150, 67, 24),
            )
            painter.fillRect(
                QRectF(play_x - 1, 0, 2, self.height()),
                playhead_color,
            )
            marker = QPainterPath()
            marker.moveTo(play_x - 8, 0)
            marker.lineTo(play_x + 8, 0)
            marker.lineTo(play_x, 12)
            marker.closeSubpath()
            painter.fillPath(marker, playhead_color)
            time_text = self.editor.format_playback_time(self.playhead_ms)
            label_w = max(58, painter.fontMetrics().horizontalAdvance(time_text) + 10)
            label_x = min(self.width() - label_w - 3, max(self.KEY_W + 4, play_x + 7))
            label_rect = QRectF(label_x, 3, label_w, 20)
            painter.fillRect(label_rect, QColor(20, 20, 19, 225))
            painter.setPen(QPen(playhead_color, 1))
            painter.drawRect(label_rect)
            painter.setPen(QColor("#fff4d6"))
            painter.drawText(label_rect, Qt.AlignCenter, time_text)
        if self.preload_state != "idle":
            cache_y = self.RULER_H - 3
            if self.preload_state == "loading":
                painter.fillRect(QRectF(grid.left(), cache_y, grid.width(), 3), QColor("#30383a"))
                painter.fillRect(
                    QRectF(grid.left(), cache_y, grid.width() * self.preload_progress, 3),
                    QColor("#55b8ad"),
                )
            else:
                painter.fillRect(QRectF(grid.left(), cache_y + 1, grid.width(), 1), QColor("#477a74"))
        if not self.marquee.isNull():
            self._paint_marquee_overlay(painter, self.marquee)
        if self.creation_preview is not None:
            preview_rect = self.note_rect(self.creation_preview)
            painter.setBrush(QColor(245, 165, 36, 95))
            painter.setPen(QPen(QColor("#ffd27b"), 1, Qt.DashLine))
            painter.drawRect(preview_rect)
            if preview_rect.height() >= self.NOTE_TEXT_MIN_HEIGHT:
                painter.setPen(QColor("#fff4d6"))
                painter.drawText(
                    preview_rect.adjusted(5, 0, -3, 0),
                    Qt.AlignVCenter | Qt.AlignLeft,
                    f"{note_name(self.creation_preview.pitch)} · v{self.creation_preview.vel}",
                )
        if (
            not self.notes
            and not self.visible_transcription_candidates()
            and self.creation_preview is None
        ):
            empty_rect = grid.adjusted(24, 24, -24, -24)
            title_font = painter.font()
            title_font.setPointSize(max(15, title_font.pointSize() + 5))
            title_font.setBold(True)
            painter.setFont(title_font)
            painter.setPen(QColor("#d7c39a"))
            painter.drawText(empty_rect.adjusted(0, -22, 0, 0), Qt.AlignCenter, tr("双击空白处，写下第一个音符"))
            hint_font = painter.font()
            hint_font.setPointSize(max(9, hint_font.pointSize() - 5))
            hint_font.setBold(False)
            painter.setFont(hint_font)
            painter.setPen(QColor("#817b71"))
            painter.drawText(empty_rect.adjusted(0, 24, 0, 0), Qt.AlignCenter, tr("按 B 进入绘制模式 · Space 播放"))
        painter.restore()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            for rect, marker in reversed(self._marker_delete_regions):
                if rect.contains(event.position()):
                    self.marker_edit_requested.emit({"action": "delete", **marker})
                    event.accept()
                    return
        if event.button() == Qt.RightButton:
            for rect, marker in reversed(self._marker_label_regions):
                if not rect.contains(event.position()):
                    continue
                menu = QMenu(self)
                rename_action = menu.addAction(tr("重命名时间轴标记…"))
                delete_action = menu.addAction(tr("删除时间轴标记"))
                selected = menu.exec(event.globalPosition().toPoint())
                if selected is rename_action:
                    self.marker_edit_requested.emit({"action": "rename", **marker})
                elif selected is delete_action:
                    self.marker_edit_requested.emit({"action": "delete", **marker})
                event.accept()
                return
        if event.button() == Qt.RightButton:
            index, _mode = self.note_at(event.position())
            if index is not None:
                self.editor.delete_note_at(index)
                event.accept()
                return
            if self.editor.transcription_mode_enabled:
                candidate_id = self.candidate_at(event.position())
                if (
                    candidate_id is not None
                    and self._show_voice_group_context_menu(
                        event, candidate_id
                    )
                ):
                    event.accept()
                    return
            event.accept()
            return
        if (
            event.button() == Qt.LeftButton
            and event.position().x() >= self.KEY_W
            and self.TIME_RULER_H
            <= event.position().y()
            < self.RULER_H
        ):
            segment = self._chord_segment_at(event.position())
            if segment is not None:
                segment_id = str(
                    getattr(segment, "segment_id", "") or ""
                )
                if segment_id:
                    self.chord_segment_clicked.emit(segment_id)
            else:
                self.ruler_seek_requested.emit(
                    self.time_at(event.position().x())
                )
            event.accept()
            return
        if (
            event.button() == Qt.LeftButton
            and event.position().x() >= self.KEY_W
            and event.position().y() < self.TIME_RULER_H
            and self.editor.transcription_mode_enabled
        ):
            anchor = self.time_at(event.position().x())
            self._ruler_range_anchor = anchor
            self._ruler_range_moved = False
            self._drag_time_range = self.transcription_time_range
            self._ruler_range_endpoint = ""
            current_range = self._drag_time_range
            if current_range is not None:
                threshold = 7.0
                if abs(event.position().x() - self.x_at_time(current_range[0])) <= threshold:
                    self._ruler_range_endpoint = "start"
                elif abs(event.position().x() - self.x_at_time(current_range[1])) <= threshold:
                    self._ruler_range_endpoint = "end"
            event.accept()
            return
        if event.button() == Qt.LeftButton and event.position().x() >= self.KEY_W and event.position().y() < self.TIME_RULER_H:
            self.dragging_playhead = True
            seek_ms = self.time_at(event.position().x())
            self.set_edit_cursor(seek_ms)
            self.ruler_seek_requested.emit(seek_ms)
            event.accept()
            return
        if event.button() == Qt.LeftButton and event.position().x() < self.KEY_W and event.position().y() >= self.RULER_H:
            pitch = self.pitch_at(event.position().y())
            self.piano_key_dragging = True
            self.piano_pressed_pitch = pitch
            self.piano_hover_pitch = pitch
            self.update(QRectF(0, self.RULER_H, self.KEY_W, self.height() - self.RULER_H).toAlignedRect())
            self.editor.audition_pitch(pitch)
            event.accept()
            return
        if event.button() != Qt.LeftButton or event.position().x() < self.KEY_W or event.position().y() < self.RULER_H:
            return super().mousePressEvent(event)
        self.setFocus()
        self.press_pos = event.position()
        self.press_notes = list(self.notes)
        self.press_selected = set(self.selected)
        self.ctrl_press_index = None
        self.clone_base_notes = []
        index, mode = self.note_at(event.position())
        active_tool = str(getattr(self.editor, "active_note_tool", "select"))
        if index is not None and active_tool == "erase":
            self.editor.delete_note_at(index)
            event.accept()
            return
        if index is not None and active_tool == "split":
            self.editor.split_note_at(index, self.time_at(event.position().x()))
            event.accept()
            return
        mods = event.modifiers()
        candidate_review_active = (
            self.editor.transcription_mode_enabled
            and self.transcription_candidates_visible
            and self._transcription_candidate_layer_visible
            and bool(self.transcription_candidates)
            and active_tool == "select"
        )
        candidate_id = None
        guide = None
        if candidate_review_active:
            candidate_id = self.candidate_at(event.position())
            if candidate_id is None:
                guide = self.melody_guide_at(event.position())
        reference_hit = candidate_id is not None or guide is not None
        if index is not None and not reference_hit:
            if self._selected_candidate_ids:
                self._selected_candidate_ids.clear()
                self.candidate_selection_changed.emit(frozenset())
            touched = self.notes[index]
            self.editor.remember_note_creation_properties(touched)
            self.set_edit_cursor(float(touched.start))
            if mods & Qt.ControlModifier:
                # Delay the toggle until release so a Ctrl-drag can clone the
                # current selection without first removing the grabbed note.
                self.ctrl_press_index = index
                self.drag_mode = "pending_clone"
            elif mods & Qt.ShiftModifier and self.anchor_index is not None:
                lo, hi = sorted((self.anchor_index, index))
                self.selected.update(range(lo, hi + 1))
                self.drag_mode = mode
            else:
                if index not in self.selected:
                    self.selected = {index}
                self.drag_mode = mode
            self.anchor_index = index
            self.selection_changed.emit()
            self.update()
            self.ruler_seek_requested.emit(
                self.time_at(event.position().x())
            )
            if self.editor.draft_playback_state == "stopped":
                self.editor.audition_note(self.notes[index])
            return
        if candidate_review_active:
            additive = bool(mods & Qt.ControlModifier)
            hit_ids: set[str] = set()
            if candidate_id is not None:
                hit_ids.add(candidate_id)
            if guide is not None:
                hit_ids.update({
                    candidate_id
                    for candidate_id in guide.source_candidate_ids
                    if candidate_id in self._candidate_id_set
                })
            self._candidate_marquee_origin = event.position()
            self._candidate_marquee_additive = additive
            self._candidate_press_selected = set(
                self._selected_candidate_ids
            )
            self._candidate_press_hit_ids = hit_ids
            self.marquee = QRectF(event.position(), event.position())
            self.drag_mode = "candidate_marquee_pending"
            if not additive:
                self._selected_candidate_ids.clear()
            self.selected.clear()
            self.anchor_index = None
            if guide is not None:
                raw_start = self.time_at(event.position().x())
                self.set_edit_cursor(raw_start)
            raw_start = self.time_at(event.position().x())
            cursor_start = (
                raw_start
                if mods & Qt.AltModifier or not self.editor.snap_box.isChecked()
                else self.editor.snap_time(raw_start)
            )
            self.set_edit_cursor(cursor_start)
            self.ruler_seek_requested.emit(raw_start)
            self.selection_changed.emit()
            self.update()
            event.accept()
            return
        if not (mods & Qt.ControlModifier):
            self.selected.clear()
        raw_start = self.time_at(event.position().x())
        cursor_start = raw_start if mods & Qt.AltModifier or not self.editor.snap_box.isChecked() else self.editor.snap_time(raw_start)
        self.set_edit_cursor(cursor_start)
        self.ruler_seek_requested.emit(raw_start)
        if self.editor.draw_mode_button.isChecked():
            self.creation_anchor_ms = cursor_start
            self.creation_anchor_pitch = self.pitch_at(event.position().y())
            self.creation_preview = self.editor.build_created_note(
                pitch=self.creation_anchor_pitch,
                start_ms=cursor_start,
            )
            self.drag_mode = "draw_create"
        else:
            self.drag_mode = "pending_marquee"
        self.selection_changed.emit()
        self.update()

    def _update_candidate_marquee(self, pos: QPointF) -> None:
        origin = self._candidate_marquee_origin
        if origin is None:
            return
        if (
            self.drag_mode == "candidate_marquee_pending"
            and math.hypot(pos.x() - origin.x(), pos.y() - origin.y()) > 4.0
        ):
            self.drag_mode = "candidate_marquee"
        if self.drag_mode != "candidate_marquee":
            return

        self.marquee = QRectF(origin, pos).normalized()
        selected = (
            set(self._candidate_press_selected)
            if self._candidate_marquee_additive
            else set()
        )
        marquee_left_ms = self.time_at(
            max(float(self.KEY_W), self.marquee.left())
        )
        marquee_right_ms = self.time_at(
            max(float(self.KEY_W), self.marquee.right())
        )
        expanded_primaries = self._expanded_fold_primaries()
        for candidate_id, candidate in self._visible_candidate_pairs(
            marquee_left_ms,
            marquee_right_ms,
        ):
            if not self._candidate_is_displayed_in_fold(
                candidate_id,
                expanded_primaries,
            ):
                continue
            if self._candidate_display_rect(
                candidate_id,
                candidate,
                expanded_primaries=expanded_primaries,
            ).intersects(self.marquee):
                selected.add(candidate_id)
        if selected != self._selected_candidate_ids:
            self._selected_candidate_ids = selected
        note_hits = {
            index
            for index in self.visible_note_indices(
                marquee_left_ms,
                marquee_right_ms,
            )
            if self.note_rect(self.notes[index]).intersects(self.marquee)
        }
        note_selection = (
            self.press_selected.union(note_hits)
            if self._candidate_marquee_additive
            else note_hits
        )
        if note_selection != self.selected:
            self.selected = note_selection
            self.selection_changed.emit()
        self.update()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        if self._ruler_range_anchor is not None and event.buttons() & Qt.LeftButton:
            target = self.time_at(pos.x())
            self._ruler_range_moved = self._ruler_range_moved or abs(
                self.x_at_time(target) - self.x_at_time(self._ruler_range_anchor)
            ) >= 3.0
            current_range = self._drag_time_range
            if self._ruler_range_endpoint and current_range is not None:
                start_ms, end_ms = current_range
                if self._ruler_range_endpoint == "start":
                    start_ms = target
                else:
                    end_ms = target
                start_ms, end_ms = sorted((start_ms, end_ms))
            else:
                start_ms, end_ms = sorted((self._ruler_range_anchor, target))
            self._drag_time_range = (
                (start_ms, end_ms) if end_ms > start_ms else None
            )
            self.update()
            event.accept()
            return
        if self.dragging_playhead and event.buttons() & Qt.LeftButton:
            self.ruler_seek_requested.emit(self.time_at(pos.x()))
            event.accept()
            return
        over_piano = pos.x() < self.KEY_W and pos.y() >= self.RULER_H
        hover_pitch = self.pitch_at(pos.y()) if over_piano else None
        if hover_pitch != self.piano_hover_pitch:
            self.piano_hover_pitch = hover_pitch
            self.update(QRectF(0, self.RULER_H, self.KEY_W, self.height() - self.RULER_H).toAlignedRect())
        if self.piano_key_dragging and event.buttons() & Qt.LeftButton:
            if hover_pitch is not None and hover_pitch != self.piano_pressed_pitch:
                self.piano_pressed_pitch = hover_pitch
                self.update(QRectF(0, self.RULER_H, self.KEY_W, self.height() - self.RULER_H).toAlignedRect())
                self.editor.audition_pitch(hover_pitch)
            event.accept()
            return
        self.hover_changed.emit(self.time_at(pos.x()), self.pitch_at(pos.y()))
        candidate_marquee_active = self.drag_mode in {
            "candidate_marquee_pending",
            "candidate_marquee",
        }
        if not (event.buttons() & Qt.LeftButton) and not candidate_marquee_active:
            hovered_candidate_id = ""
            candidate_hit = None
            if (
                self.editor.transcription_mode_enabled
                and pos.x() >= self.KEY_W
                and pos.y() >= self.RULER_H
            ):
                candidate_hit = self.candidate_at(pos)
                if candidate_hit is not None:
                    hovered_candidate_id = candidate_hit
            guide_hit = (
                self.melody_guide_at(pos)
                if candidate_hit is None
                and str(getattr(self.editor, "active_note_tool", "select")) == "select"
                else None
            )
            if guide_hit is not None:
                self.setToolTip(
                    trf(
                        "{role}{branch_separator}{branch} · {confidence}% · {action}",
                        role=trv(voice_role_source_label(guide_hit.role)),
                        branch_separator=" · " if guide_hit.branch else "",
                        branch=trv("分支") if guide_hit.branch else "",
                        confidence=round(guide_hit.confidence * 100),
                        action=trv("点击定位候选"),
                    )
                )
            else:
                self.setToolTip("")
            if hovered_candidate_id != self._hovered_candidate_id:
                previous_id = self._hovered_candidate_id
                self._hovered_candidate_id = hovered_candidate_id
                for candidate_id in (previous_id, hovered_candidate_id):
                    candidate_index = self._transcription_candidate_id_to_index.get(
                        candidate_id
                    )
                    if candidate_index is not None:
                        self.update(
                            self.candidate_rect(
                                self.transcription_candidates[candidate_index]
                            )
                            .adjusted(-8.0, -4.0, 112.0, 4.0)
                            .toAlignedRect()
                        )
            if pos.x() < self.KEY_W:
                self.setCursor(Qt.PointingHandCursor)
            elif (
                self.TIME_RULER_H
                <= pos.y()
                < self.RULER_H
            ):
                self.setCursor(
                    Qt.PointingHandCursor
                    if self._chord_segment_at(pos) is not None
                    else Qt.ArrowCursor
                )
            elif pos.y() < self.TIME_RULER_H:
                self.setCursor(Qt.SizeHorCursor)
            else:
                _index, mode = self.note_at(pos)
                if _index != self.hovered_note_index:
                    previous_index = self.hovered_note_index
                    self.hovered_note_index = _index
                    for note_index in (previous_index, _index):
                        if note_index is not None and 0 <= note_index < len(self.notes):
                            self.update(
                                self.note_rect(self.notes[note_index])
                                .adjusted(-3, -3, 3, 3)
                                .toAlignedRect()
                            )
                if mode in ("resize_left", "resize_right"):
                    self.setCursor(Qt.SizeHorCursor)
                elif str(getattr(self.editor, "active_note_tool", "select")) == "erase":
                    self.setCursor(Qt.PointingHandCursor)
                elif str(getattr(self.editor, "active_note_tool", "select")) == "split":
                    self.setCursor(Qt.SplitHCursor)
                elif mode == "move":
                    self.setCursor(Qt.SizeAllCursor)
                elif guide_hit is not None:
                    self.setCursor(Qt.PointingHandCursor)
                else:
                    self.setCursor(
                        Qt.CrossCursor
                        if str(getattr(self.editor, "active_note_tool", "select")) == "draw"
                        else Qt.ArrowCursor
                    )
            return
        dx, dy = pos.x() - self.press_pos.x(), pos.y() - self.press_pos.y()
        if self.drag_mode in {"candidate_marquee_pending", "candidate_marquee"}:
            if not self._transcription_candidate_layer_visible:
                self._selected_candidate_ids = set(
                    self._candidate_press_selected
                )
                self.drag_mode = None
                self._candidate_marquee_origin = None
                self._candidate_marquee_additive = False
                self._candidate_press_selected.clear()
                self._candidate_press_hit_ids.clear()
                self.marquee = QRectF()
                self.update()
                return
            self._update_candidate_marquee(pos)
            return
        if self.drag_mode == "draw_create" and self.creation_preview is not None:
            current = self.time_at(pos.x())
            snap = self.editor.snap_box.isChecked() and not (event.modifiers() & Qt.AltModifier)
            if snap:
                current = self.editor.snap_time(current)
            start = min(self.creation_anchor_ms, current)
            duration = max(self.editor.minimum_duration_ms(), abs(current - self.creation_anchor_ms))
            if abs(dx) < 4:
                start = self.creation_anchor_ms
                duration = self.editor.default_note_duration()
            velocity = max(0, min(127, self.editor.default_note_velocity - round(dy * 1.5)))
            self.creation_preview = self.editor.constrain_note_to_scope(
                self.creation_preview._replace(
                    start=start, dur=duration, vel=velocity
                )
            )
            self.update()
            return
        if self.drag_mode == "pending_clone" and math.hypot(dx, dy) > 4 and self.ctrl_press_index is not None:
            source_indices = (
                sorted(self.press_selected)
                if self.ctrl_press_index in self.press_selected
                else [self.ctrl_press_index]
            )
            self.clone_base_notes = [self.press_notes[index] for index in source_indices]
            first = len(self.press_notes)
            self.notes = list(self.press_notes) + list(self.clone_base_notes)
            self.selected = set(range(first, first + len(self.clone_base_notes)))
            self.anchor_index = first + source_indices.index(self.ctrl_press_index)
            self.drag_mode = "clone_move"
            self.selection_changed.emit()
        if self.drag_mode == "pending_marquee" and math.hypot(dx, dy) > 4:
            self.drag_mode = "marquee"
        if self.drag_mode == "marquee":
            self.marquee = QRectF(self.press_pos, pos).normalized()
            hits = {
                i for i in self.visible_note_indices()
                if self.note_rect(self.notes[i]).intersects(self.marquee)
            }
            selected = self.press_selected.union(hits) if event.modifiers() & Qt.ControlModifier else hits
            if selected != self.selected:
                self.selected = selected
                self.selection_changed.emit()
            self.update()
            return
        if self.drag_mode == "clone_move" and self.clone_base_notes:
            dt = dx / self.px_per_ms
            if self.editor.snap_box.isChecked() and not (event.modifiers() & Qt.AltModifier):
                q = self.editor.quantize_ms()
                dt = round(dt / q) * q
            dt = max(dt, -min(note.start for note in self.clone_base_notes))
            dp = -round(dy / self.ROW_H)
            self.notes = list(self.press_notes) + self.editor.constrain_note_group_to_scope(
                note._replace(
                    start=note.start + dt,
                    pitch=max(0, min(127, note.pitch + dp)),
                )
                for note in self.clone_base_notes
            )
            self.update()
            return
        if self.drag_mode not in ("move", "resize_left", "resize_right") or not self.selected:
            return
        dt = dx / self.px_per_ms
        if self.editor.snap_box.isChecked() and not (event.modifiers() & Qt.AltModifier):
            q = self.editor.quantize_ms()
            dt = round(dt / q) * q
        dp = -round(dy / self.ROW_H)
        changed = list(self.press_notes)
        minimum = self.editor.minimum_duration_ms()
        for i in self.selected:
            old = self.press_notes[i]
            if self.drag_mode == "move":
                changed[i] = old._replace(
                    start=max(0.0, old.start + dt),
                    pitch=max(0, min(127, old.pitch + dp)),
                )
            elif self.drag_mode == "resize_right":
                anchor = self.press_notes[self.anchor_index] if self.anchor_index in self.selected else old
                factor = max(minimum / max(minimum, anchor.dur), (anchor.dur + dt) / max(minimum, anchor.dur))
                changed[i] = self.editor.constrain_note_to_scope(
                    old._replace(dur=max(minimum, old.dur * factor))
                )
            else:
                anchor = self.press_notes[self.anchor_index] if self.anchor_index in self.selected else old
                factor = max(minimum / max(minimum, anchor.dur), (anchor.dur - dt) / max(minimum, anchor.dur))
                new_dur = max(minimum, old.dur * factor)
                end = old.start + old.dur
                new_start = max(0.0, end - new_dur)
                changed[i] = self.editor.constrain_note_to_scope(
                    old._replace(start=new_start, dur=end - new_start)
                )
        if self.drag_mode == "move":
            constrained = self.editor.constrain_note_group_to_scope(
                changed[index] for index in sorted(self.selected)
            )
            for index, note in zip(sorted(self.selected), constrained):
                changed[index] = note
        self.notes = changed
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        if self._ruler_range_anchor is not None:
            anchor = self._ruler_range_anchor
            if self._ruler_range_moved and self._drag_time_range is not None:
                self.time_range_changed.emit(self._drag_time_range)
            else:
                self.ruler_seek_requested.emit(anchor)
            self._ruler_range_anchor = None
            self._ruler_range_endpoint = ""
            self._ruler_range_moved = False
            self._drag_time_range = None
            self.update()
            event.accept()
            return
        if self.piano_key_dragging:
            self.piano_key_dragging = False
            self.piano_pressed_pitch = None
            self.update(QRectF(0, self.RULER_H, self.KEY_W, self.height() - self.RULER_H).toAlignedRect())
            event.accept()
            return
        if self.dragging_playhead:
            self.dragging_playhead = False
            event.accept()
            return
        if self.drag_mode in {"candidate_marquee_pending", "candidate_marquee"}:
            if self._transcription_candidate_layer_visible:
                # Precision touchpads may coalesce the final move or report it
                # without a held-button flag.  The release position is the
                # authoritative final corner of the selection rectangle.
                self._update_candidate_marquee(event.position())
            else:
                self._selected_candidate_ids = set(
                    self._candidate_press_selected
                )
            if (
                self._transcription_candidate_layer_visible
                and self.drag_mode == "candidate_marquee_pending"
                and self._candidate_press_hit_ids
            ):
                selected = (
                    set(self._candidate_press_selected)
                    if self._candidate_marquee_additive
                    else set()
                )
                if (
                    self._candidate_marquee_additive
                    and self._candidate_press_hit_ids.issubset(selected)
                ):
                    selected.difference_update(
                        self._candidate_press_hit_ids
                    )
                else:
                    selected.update(self._candidate_press_hit_ids)
                self._selected_candidate_ids = selected
            final_candidate_selection = frozenset(
                self._selected_candidate_ids
            )
            previous_candidate_selection = frozenset(
                self._candidate_press_selected
            )
            self._candidate_marquee_origin = None
            self._candidate_marquee_additive = False
            self._candidate_press_selected.clear()
            self._candidate_press_hit_ids.clear()
            self.marquee = QRectF()
            self.drag_mode = ""
            self.update()
            if final_candidate_selection != previous_candidate_selection:
                self.candidate_selection_changed.emit(
                    final_candidate_selection
                )
            event.accept()
            return
        if self.drag_mode == "draw_create" and self.creation_preview is not None:
            self.editor.push_snapshot()
            self.notes.append(self.creation_preview)
            self.selected = {len(self.notes) - 1}
            self.anchor_index = len(self.notes) - 1
            self.editor.default_note_velocity = self.creation_preview.vel
            self.editor.last_note_duration_ms = self.creation_preview.dur
            self.set_edit_cursor(self.creation_preview.start + self.creation_preview.dur)
            self.notes_changed.emit()
            self.selection_changed.emit()
            self.editor.audition_note(self.notes[-1])
        elif self.drag_mode == "pending_clone" and self.ctrl_press_index is not None:
            if self.ctrl_press_index in self.press_selected:
                self.selected.discard(self.ctrl_press_index)
            else:
                self.selected.add(self.ctrl_press_index)
            self.selection_changed.emit()
        elif self.drag_mode == "clone_move" and self.notes != self.press_notes:
            self.editor.push_snapshot(self.press_notes, self.press_selected)
            self.notes_changed.emit()
            if self.anchor_index is not None:
                self.editor.audition_note(self.notes[self.anchor_index])
        elif self.drag_mode in ("move", "resize_left", "resize_right") and self.notes != self.press_notes:
            self.editor.push_snapshot(self.press_notes, self.press_selected)
            self.notes_changed.emit()
            if self.drag_mode == "move" and self.anchor_index is not None:
                before = self.press_notes[self.anchor_index]
                after = self.notes[self.anchor_index]
                if before.pitch != after.pitch:
                    self.editor.audition_note(after)
        self.marquee = QRectF()
        self.creation_preview = None
        self.ctrl_press_index = None
        self.clone_base_notes = []
        self.drag_mode = ""
        self.update()

    def leaveEvent(self, event) -> None:
        self.setToolTip("")
        if self._hovered_candidate_id:
            candidate_index = self._transcription_candidate_id_to_index.get(
                self._hovered_candidate_id
            )
            self._hovered_candidate_id = ""
            if candidate_index is not None:
                self.update(
                    self.candidate_rect(
                        self.transcription_candidates[candidate_index]
                    )
                    .adjusted(-8.0, -4.0, 112.0, 4.0)
                    .toAlignedRect()
                )
        if not self.piano_key_dragging and self.piano_hover_pitch is not None:
            self.piano_hover_pitch = None
            self.update(QRectF(0, self.RULER_H, self.KEY_W, self.height() - self.RULER_H).toAlignedRect())
        super().leaveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            for rect, marker in reversed(self._marker_label_regions):
                if rect.contains(event.position()):
                    self.marker_edit_requested.emit({"action": "rename", **marker})
                    event.accept()
                    return
        if (
            self.editor.transcription_mode_enabled
            and event.button() == Qt.LeftButton
            and not self.editor.draw_mode_button.isChecked()
        ):
            candidate_id = self.candidate_at(event.position())
            if candidate_id is not None:
                self._candidate_marquee_origin = None
                self._candidate_marquee_additive = False
                self._candidate_press_selected.clear()
                self._candidate_press_hit_ids.clear()
                self.marquee = QRectF()
                self.drag_mode = ""
                self.editor.promote_transcription_candidate(candidate_id)
                event.accept()
                return
        if (
            event.button() == Qt.LeftButton
            and not self.editor.draw_mode_button.isChecked()
            and event.position().x() >= self.KEY_W
            and event.position().y() >= self.RULER_H
            and self.note_at(event.position())[0] is None
        ):
            raw_start = self.time_at(event.position().x())
            start = (
                raw_start
                if event.modifiers() & Qt.AltModifier or not self.editor.snap_box.isChecked()
                else self.editor.snap_time(raw_start)
            )
            self.set_edit_cursor(start)
            self.editor.push_snapshot()
            self.notes.append(
                self.editor.build_created_note(
                    pitch=self.pitch_at(event.position().y()),
                    start_ms=start,
                )
            )
            self.selected = {len(self.notes) - 1}
            self.anchor_index = len(self.notes) - 1
            self.set_edit_cursor(start + self.notes[-1].dur)
            self.drag_mode = ""
            self.notes_changed.emit()
            self.selection_changed.emit()
            self.editor.audition_note(self.notes[-1])
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _pan_from_wheel_pixels(
        self,
        horizontal_pixels: float,
        vertical_pixels: float,
    ) -> tuple[bool, bool]:
        """Pan both piano-roll axes using screen-oriented wheel distances."""

        old_scroll_ms = float(self.scroll_ms)
        old_pitch_top = int(self.pitch_top)
        if not math.isclose(horizontal_pixels, 0.0, abs_tol=1e-9):
            self.scroll_ms = max(
                0.0,
                self.scroll_ms - horizontal_pixels / self.px_per_ms,
            )

        if not math.isclose(vertical_pixels, 0.0, abs_tol=1e-9):
            pending_rows = (
                self._touchpad_pitch_remainder_rows
                + vertical_pixels / max(1.0, float(self.ROW_H))
            )
            row_delta = math.trunc(pending_rows)
            self._touchpad_pitch_remainder_rows = pending_rows - row_delta
            if row_delta:
                pitch_min, pitch_max = self.editor.pitch_top_bounds()
                requested_pitch_top = self.pitch_top + row_delta
                self.pitch_top = max(
                    pitch_min,
                    min(pitch_max, requested_pitch_top),
                )
                if self.pitch_top != requested_pitch_top:
                    self._touchpad_pitch_remainder_rows = 0.0

        return (
            not math.isclose(old_scroll_ms, self.scroll_ms, abs_tol=1e-6),
            old_pitch_top != self.pitch_top,
        )

    def wheelEvent(self, event) -> None:
        angle_delta = event.angleDelta()
        pixel_delta = event.pixelDelta()
        modifiers = event.modifiers()

        if modifiers == Qt.NoModifier:
            pixel_x = float(pixel_delta.x())
            pixel_y = float(pixel_delta.y())
            if not (
                math.isclose(pixel_x, 0.0, abs_tol=1e-9)
                and math.isclose(pixel_y, 0.0, abs_tol=1e-9)
            ):
                horizontal_pixels = pixel_x
                vertical_pixels = pixel_y
            else:
                # Windows precision touchpads may report fine-grained angle
                # deltas instead of pixelDelta. Preserve both axes and scale
                # one conventional wheel notch to the legacy pan distance.
                horizontal_steps = max(
                    -8.0,
                    min(8.0, float(angle_delta.x()) / 120.0),
                )
                vertical_steps = max(
                    -8.0,
                    min(8.0, float(angle_delta.y()) / 120.0),
                )
                horizontal_pixels = horizontal_steps * self.px_per_beat
                vertical_pixels = vertical_steps * 3.0 * self.ROW_H
            if not (
                math.isclose(horizontal_pixels, 0.0, abs_tol=1e-9)
                and math.isclose(vertical_pixels, 0.0, abs_tol=1e-9)
            ):
                time_changed, _pitch_changed = self._pan_from_wheel_pixels(
                    horizontal_pixels,
                    vertical_pixels,
                )
                self.update()
                self.editor.update_scrollbars()
                if time_changed:
                    self.editor.velocity_lane.update()
                    self.editor.transcription_waveform.refresh()
                event.accept()
                return
            return super().wheelEvent(event)

        raw_delta = angle_delta.y() or angle_delta.x()
        if raw_delta:
            wheel_steps = float(raw_delta) / 120.0
        else:
            raw_delta = pixel_delta.y() or pixel_delta.x()
            # Smooth touchpads report pixels instead of the conventional
            # 120-unit wheel notch. Fifty pixels is a restrained one-notch
            # equivalent and keeps high-frequency updates continuous.
            wheel_steps = float(raw_delta) / 50.0 if raw_delta else 0.0
        if math.isclose(wheel_steps, 0.0, abs_tol=1e-9):
            return super().wheelEvent(event)
        wheel_steps = max(-8.0, min(8.0, wheel_steps))
        time_changed = False
        if modifiers & Qt.ControlModifier:
            anchor_x = max(self.KEY_W, min(self.width(), event.position().x()))
            anchor_time = self.time_at(anchor_x)
            new_zoom = max(
                self.MIN_PX_PER_BEAT,
                min(
                    self.MAX_PX_PER_BEAT,
                    self.px_per_beat * (1.15 ** wheel_steps),
                ),
            )
            self.px_per_beat = new_zoom
            self.scroll_ms = max(
                0.0,
                anchor_time - (anchor_x - self.KEY_W) / self.px_per_ms,
            )
            time_changed = True
            self.editor.editor_zoom.blockSignals(True)
            self.editor.editor_zoom.setValue(round(new_zoom))
            self.editor.editor_zoom.blockSignals(False)
        elif modifiers & Qt.AltModifier:
            anchor_y = max(
                float(self.RULER_H),
                min(float(self.height()), float(event.position().y())),
            )
            old_row_height = float(self.ROW_H)
            anchor_pitch = self.pitch_top - (
                anchor_y - self.RULER_H
            ) / old_row_height
            self.ROW_H = max(
                self.MIN_ROW_H,
                min(
                    self.MAX_ROW_H,
                    old_row_height * (1.12 ** wheel_steps),
                ),
            )
            self.pitch_top = round(
                anchor_pitch + (anchor_y - self.RULER_H) / self.ROW_H
            )
            self.editor.status.setText(
                trf("音块高度：{height}px", height=round(self.ROW_H))
            )
        elif modifiers & Qt.ShiftModifier:
            self.scroll_ms = max(
                0.0,
                self.scroll_ms - wheel_steps * self.beat_ms,
            )
            time_changed = True
        else:
            pitch_min, pitch_max = self.editor.pitch_top_bounds()
            self.pitch_top = max(
                pitch_min,
                min(
                    pitch_max,
                    self.pitch_top + (3 if wheel_steps > 0 else -3),
                ),
            )
        self.update()
        self.editor.update_scrollbars()
        if time_changed:
            self.editor.velocity_lane.update()
            self.editor.transcription_waveform.refresh()
        event.accept()

    def keyPressEvent(self, event) -> None:
        mods, key = event.modifiers(), event.key()
        if key == Qt.Key_Escape and self._selected_candidate_ids:
            self._selected_candidate_ids.clear()
            self.candidate_selection_changed.emit(frozenset())
            self.update()
            event.accept()
            return
        command = resolve_editor_key_command(
            key,
            mods,
            has_selection=bool(self.selected),
        )
        if command is None:
            return super().keyPressEvent(event)
        if command == "toggle_draw":
            if self.editor.draw_mode_button.isChecked():
                self.editor.select_tool_button.setChecked(True)
                self.editor._note_tool_changed(0)
            else:
                self.editor.draw_mode_button.setChecked(True)
                self.editor._note_tool_changed(1)
        elif command == "play_pause":
            if not event.isAutoRepeat():
                self.editor.toggle_draft_playback()
        elif command == "exit_draw":
            if not self.editor.draw_mode_button.isChecked():
                return super().keyPressEvent(event)
            self.editor.select_tool_button.setChecked(True)
            self.editor._note_tool_changed(0)
        elif command == "duplicate":
            self.editor.duplicate_selected()
        elif command in {"adjust_velocity", "adjust_velocity_coarse"}:
            self.editor.push_snapshot()
            step = 8 if command == "adjust_velocity_coarse" else 1
            delta = step if key == Qt.Key_Up else -step
            for index in self.selected:
                note = self.notes[index]
                self.notes[index] = note._replace(vel=max(0, min(127, note.vel + delta)))
            self.notes_changed.emit()
            self.selection_changed.emit()
        elif command in {
            "nudge_pitch",
            "transpose_octave",
            "nudge_time",
            "nudge_time_fine",
            "resize_duration",
            "resize_duration_fine",
        }:
            self.editor.push_snapshot()
            changed = list(self.notes)
            if command in {"nudge_pitch", "transpose_octave"}:
                step = 12 if command == "transpose_octave" else 1
                delta = step if key == Qt.Key_Up else -step
                for index in self.selected:
                    changed[index] = self.editor.constrain_note_to_scope(changed[index]._replace(
                        pitch=max(0, min(127, changed[index].pitch + delta))
                    ))
            else:
                fine = command in {"nudge_time_fine", "resize_duration_fine"}
                step = (
                    max(1.0, self.editor.quantize_ms() / 8.0)
                    if fine
                    else self.editor.quantize_ms()
                )
                delta = step if key == Qt.Key_Right else -step
                if command in {"resize_duration", "resize_duration_fine"}:
                    for index in self.selected:
                        changed[index] = self.editor.constrain_note_to_scope(changed[index]._replace(
                            dur=max(self.editor.minimum_duration_ms(), changed[index].dur + delta)
                        ))
                else:
                    delta = max(delta, -min(self.notes[index].start for index in self.selected))
                    for index in self.selected:
                        changed[index] = changed[index]._replace(
                            start=changed[index].start + delta
                        )
                    constrained = self.editor.constrain_note_group_to_scope(
                        changed[index] for index in sorted(self.selected)
                    )
                    for index, note in zip(sorted(self.selected), constrained):
                        changed[index] = note
            self.notes = changed
            self.notes_changed.emit()
            self.selection_changed.emit()
        elif command == "select_all":
            self.editor.select_all_notes()
        elif command == "redo":
            self.editor.redo()
        elif command == "undo":
            self.editor.undo()
        elif command == "copy":
            self.editor.copy_selected()
        elif command == "cut":
            self.editor.copy_selected()
            self.editor.delete_selected()
        elif command == "paste":
            self.editor.paste_notes()
        elif command == "delete":
            self.editor.delete_selected()
        event.accept()



class VelocityLaneCanvas(QWidget):
    """Discrete note-velocity lane with an explicit weighted brush."""

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.editor = editor
        self.before_notes: list = []
        self.before_selected: set[int] = set()
        self.active_point_time: float | None = None
        self.active_point_velocity = 0.0
        self.active_indices: tuple[int, ...] = ()
        self.active_weights: dict[int, float] = {}
        self.hover_velocity: int | None = None
        self.influence_beats = 2.0
        self.edit_mode = "brush"
        self.scope_mode = "track"
        self.game_velocity_boundaries: tuple[int, ...] = ()
        self.game_velocity_status = ""
        self.setMouseTracking(True)
        self.setCursor(Qt.SizeVerCursor)
        self.setMinimumHeight(104)
        self.setMaximumHeight(144)
        self.setToolTip(
            tr("拖动力度杆；柔化刷按时间距离衰减，滚轮可调整影响范围。")
        )

    def set_edit_mode(self, mode: str) -> None:
        self.edit_mode = "point" if mode == "point" else "brush"
        self.update()

    def set_scope_mode(self, mode: str) -> None:
        self.scope_mode = "selection" if mode == "selection" else "track"
        self.update()

    def set_influence_beats(self, beats: float) -> None:
        self.influence_beats = max(0.5, min(8.0, float(beats)))
        self.update()

    def set_game_velocity_boundaries(
        self,
        boundaries: Iterable[int],
        status: str = "",
    ) -> None:
        self.game_velocity_boundaries = tuple(sorted({
            int(value) for value in boundaries if 0 < int(value) < 128
        }))
        self.game_velocity_status = str(status)
        self.update()

    @property
    def influence_radius_ms(self) -> float:
        return max(self.editor.quantize_ms(), self.editor.canvas.beat_ms * self.influence_beats)

    def _velocity_at(self, y: float) -> int:
        usable = max(1.0, self.height() - 10.0)
        return max(0, min(127, round((1.0 - (y - 5.0) / usable) * 127)))

    def _y_for_velocity(self, velocity: float) -> float:
        bounded = max(0.0, min(127.0, float(velocity)))
        return 5.0 + (1.0 - bounded / 127.0) * max(1.0, self.height() - 10.0)

    def _visible_points(self) -> list[tuple[float, tuple[int, ...], float]]:
        return velocity_time_points(
            self.editor.canvas.notes,
            self.editor.canvas.visible_note_indices(),
        )

    def _point_for_index(self, index: int) -> tuple[float, tuple[int, ...], float]:
        note = self.editor.canvas.notes[index]
        onset = round(float(note.start), 3)
        indices = tuple(
            point_index
            for point_index, point_note in enumerate(self.editor.canvas.notes)
            if round(float(point_note.start), 3) == onset
        )
        velocity = sum(float(self.editor.canvas.notes[item].vel) for item in indices) / len(indices)
        return onset, indices, velocity

    def _bar_rect(self, index: int) -> QRectF:
        """Compatibility hit rectangle; the velocity lane now paints points."""
        onset, _indices, velocity = self._point_for_index(index)
        x = self.editor.canvas.x_at_time(onset)
        y = self._y_for_velocity(velocity)
        return QRectF(x - 6.0, y - 6.0, 12.0, 12.0)

    def _point_at(self, x: float) -> tuple[float, tuple[int, ...], float] | None:
        candidates = self._visible_points()
        if not candidates:
            return None
        nearest = min(
            candidates,
            key=lambda point: abs(self.editor.canvas.x_at_time(point[0]) - x),
        )
        if abs(self.editor.canvas.x_at_time(nearest[0]) - x) > 9.0:
            return None
        return nearest

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#1a1b1e"))
        painter.fillRect(QRectF(0, 0, self.editor.canvas.KEY_W, self.height()), QColor("#242427"))
        for value in (32, 64, 96, 127):
            y = self._y_for_velocity(value)
            painter.setPen(QColor("#34353a" if value != 127 else "#4a4b50"))
            painter.drawLine(QPointF(self.editor.canvas.KEY_W, y), QPointF(self.width(), y))
            painter.setPen(QColor("#8d8b84"))
            painter.drawText(
                QRectF(3, y - 8, self.editor.canvas.KEY_W - 8, 16),
                Qt.AlignRight | Qt.AlignVCenter,
                str(value),
            )

        painter.setPen(QColor("#9d8a67"))
        painter.drawText(QRectF(4, self.height() - 22, self.editor.canvas.KEY_W - 8, 18),
                         Qt.AlignCenter, tr("音符力度"))
        curve_rect = QRectF(
            self.editor.canvas.KEY_W,
            0,
            max(0.0, self.width() - self.editor.canvas.KEY_W),
            self.height(),
        )
        painter.save()
        painter.setClipRect(curve_rect)

        if self.active_point_time is not None:
            left = self.editor.canvas.x_at_time(
                self.active_point_time - self.influence_radius_ms
            )
            right = self.editor.canvas.x_at_time(
                self.active_point_time + self.influence_radius_ms
            )
            gradient = QLinearGradient(left, 0, right, 0)
            gradient.setColorAt(0.0, QColor(213, 163, 78, 0))
            gradient.setColorAt(0.5, QColor(213, 163, 78, 45))
            gradient.setColorAt(1.0, QColor(213, 163, 78, 0))
            painter.fillRect(QRectF(left, 0, max(1.0, right - left), self.height()), gradient)

        for boundary in self.game_velocity_boundaries:
            y = self._y_for_velocity(boundary)
            pen = QPen(QColor(87, 158, 205, 120), 1.0, Qt.DashLine)
            painter.setPen(pen)
            painter.drawLine(QPointF(self.editor.canvas.KEY_W, y), QPointF(self.width(), y))
            painter.setPen(QColor(119, 184, 224, 185))
            painter.drawText(QRectF(self.editor.canvas.KEY_W + 5, y - 15, 72, 14),
                             Qt.AlignLeft | Qt.AlignVCenter, trf("游戏层 {value}", value=boundary))

        points = self._visible_points()
        if points:
            path = QPainterPath()
            for point_index, (onset, _indices, velocity) in enumerate(points):
                x = self.editor.canvas.x_at_time(onset)
                y = self._y_for_velocity(velocity)
                if point_index == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            painter.setPen(QPen(QColor(199, 154, 80, 45), 0.8))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

            for onset, indices, velocity in points:
                x = self.editor.canvas.x_at_time(onset)
                values = [float(self.editor.canvas.notes[index].vel) for index in indices]
                low_y = self._y_for_velocity(min(values))
                high_y = self._y_for_velocity(max(values))
                selected_indices = [
                    index for index in indices if index in self.editor.canvas.selected
                ]
                selected = bool(selected_indices)
                marker_velocity = (
                    float(self.editor.canvas.notes[selected_indices[0]].vel)
                    if len(selected_indices) == 1
                    else velocity
                )
                y = self._y_for_velocity(marker_velocity)
                active = self.active_point_time is not None and math.isclose(
                    onset, self.active_point_time, abs_tol=0.001,
                )
                weight = max((self.active_weights.get(index, 0.0) for index in indices), default=0.0)
                stem = QColor("#e0aa50" if selected or active else "#777980")
                if weight > 0.0:
                    stem = QColor(224, 170, 80, 105 + round(150 * weight))
                painter.setPen(QPen(stem, 2.0 if selected or weight > 0.0 else 1.2))
                painter.drawLine(QPointF(x, self._y_for_velocity(0)), QPointF(x, y))
                if len(indices) > 1 and not math.isclose(low_y, high_y):
                    painter.setPen(QPen(QColor("#b9a277"), 2.0))
                    painter.drawLine(QPointF(x, high_y), QPointF(x, low_y))
                    painter.drawLine(QPointF(x - 3, high_y), QPointF(x + 3, high_y))
                    painter.drawLine(QPointF(x - 3, low_y), QPointF(x + 3, low_y))
                    for item_index, note_index in enumerate(indices):
                        note_y = self._y_for_velocity(self.editor.canvas.notes[note_index].vel)
                        offset = -5.0 + 10.0 * item_index / max(1, len(indices) - 1)
                        tick_color = QColor(
                            "#ffe1a3" if note_index in self.editor.canvas.selected else "#9e927e"
                        )
                        painter.setPen(QPen(tick_color, 1.2))
                        painter.drawLine(QPointF(x + offset - 2, note_y),
                                         QPointF(x + offset + 2, note_y))
                painter.setPen(QPen(QColor("#ffe1a3" if selected or active else "#a4a5a9"), 1))
                painter.setBrush(QColor("#e0aa50" if selected or active else "#73757a"))
                size = 10.0 if selected or active else 7.0 + 3.0 * weight
                painter.drawEllipse(QRectF(x - size / 2, y - size / 2, size, size))
        painter.restore()

        if self.game_velocity_status:
            painter.setPen(QColor("#7f9eaf"))
            painter.drawText(QRectF(self.editor.canvas.KEY_W + 8, 3,
                                    max(0, self.width() - self.editor.canvas.KEY_W - 12), 18),
                             Qt.AlignRight | Qt.AlignVCenter, self.game_velocity_status)

        if self.hover_velocity is not None:
            y = self._y_for_velocity(self.hover_velocity)
            painter.setPen(QColor("#d9a441"))
            painter.drawLine(QPointF(self.editor.canvas.KEY_W, y), QPointF(self.width(), y))
            badge = QRectF(
                5,
                max(3.0, min(self.height() - 45.0, y - 11.0)),
                self.editor.canvas.KEY_W - 10,
                22,
            )
            painter.fillRect(badge, QColor("#5d451e"))
            painter.setPen(QColor("#fff2d2"))
            painter.drawText(badge, Qt.AlignCenter, str(self.hover_velocity))

    def _apply_drag(self, target_velocity: int) -> None:
        if self.active_point_time is None or not self.before_notes:
            return
        delta = float(target_velocity) - self.active_point_velocity
        for index, weight in self.active_weights.items():
            source = self.before_notes[index]
            velocity = max(0, min(127, round(float(source.vel) + delta * weight)))
            self.editor.canvas.notes[index] = source._replace(vel=velocity)
        self.editor.canvas.update()
        self.update()

    def _prepare_drag(self, point: tuple[float, tuple[int, ...], float]) -> None:
        onset, point_indices, average_velocity = point
        selected_here = tuple(index for index in point_indices if index in self.before_selected)
        anchor_indices = selected_here if len(selected_here) == 1 else point_indices
        if self.edit_mode == "point":
            candidate_indices = anchor_indices
        else:
            candidate_indices = tuple(self.editor.canvas.visible_note_indices(
                onset - self.influence_radius_ms,
                onset + self.influence_radius_ms,
            ))
            if self.scope_mode == "selection" and self.before_selected:
                candidate_indices = tuple(index for index in candidate_indices
                                          if index in self.before_selected)
            if not candidate_indices:
                candidate_indices = anchor_indices
        self.active_indices = tuple(sorted(set(candidate_indices)))
        self.active_weights = {}
        for index in self.active_indices:
            weight = (1.0 if self.edit_mode == "point" else velocity_neighbor_weight(
                float(self.before_notes[index].start) - onset,
                self.influence_radius_ms,
            ))
            if weight > 0.0:
                self.active_weights[index] = weight
        self.active_point_velocity = (
            float(self.before_notes[anchor_indices[0]].vel)
            if len(anchor_indices) == 1
            else average_velocity
        )
        self.editor.canvas.selected = set(anchor_indices)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        point = self._point_at(event.position().x())
        if point is None:
            return
        onset, indices, velocity = point
        self.before_notes = list(self.editor.canvas.notes)
        self.before_selected = set(self.editor.canvas.selected)
        self.active_point_time = onset
        self._prepare_drag(point)
        self.hover_velocity = self._velocity_at(event.position().y())
        self.editor.canvas.selection_changed.emit()
        self._apply_drag(self.hover_velocity)

    def mouseMoveEvent(self, event) -> None:
        self.hover_velocity = self._velocity_at(event.position().y())
        if event.buttons() & Qt.LeftButton and self.active_point_time is not None:
            self._apply_drag(self.hover_velocity)
            return
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if (
            event.button() == Qt.LeftButton
            and self.before_notes
            and self.editor.canvas.notes != self.before_notes
        ):
            self.editor.push_snapshot(self.before_notes, self.before_selected)
            self.editor.canvas.notes_changed.emit()
        self.before_notes = []
        self.before_selected = set()
        self.active_point_time = None
        self.active_indices = ()
        self.active_weights = {}
        self.update()

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if not delta:
            event.ignore()
            return
        self.set_influence_beats(self.influence_beats + (0.5 if delta > 0 else -0.5))
        callback = getattr(self.editor, "_sync_velocity_radius_control", None)
        if callable(callback):
            callback()
        self.editor.status.setText(
            trf("力度曲线影响范围：前后 {beats:.1f} 拍", beats=self.influence_beats)
        )
        self.update()
        event.accept()

    def leaveEvent(self, event) -> None:
        if self.active_point_time is None:
            self.hover_velocity = None
            self.update()
        super().leaveEvent(event)
