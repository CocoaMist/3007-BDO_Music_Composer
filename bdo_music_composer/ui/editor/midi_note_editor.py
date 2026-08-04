"""Packaged MIDI note editor dialog and host-facing integration boundary."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import replace
import math
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollBar,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from bdo_music_composer.editor.bdo_instrument_adaptation import (
    assess_game_draft,
    articulation_supports_pitch,
    articulation_trigger_pitches,
    instrument_editor_display_adaptation,
)
from bdo_midi import (
    BDO_INSTRUMENT_NAMES,
    BDO_NOTE_MAX,
    BDO_NOTE_MIN,
    Note,
    _GM_TO_BDO_DRUM,
)
from bdo_midi.instruments import localized_bdo_instrument_name
from bdo_music_composer.audio.bdo_realtime_audio import AudioEngineError
from bdo_music_composer.audio.reference_audio_controller import (
    synchronize_reference_audio,
)
from bdo_music_composer.audio.bdo_sample_renderer import (
    sample_map_velocity_boundaries,
)
from bdo_music_composer.transcription.bdo_transcription import (
    TranscriptionCandidate,
    TranscriptionResult,
    transcription_backend_quick_status,
)
from bdo_music_composer.transcription.bdo_transcription_assist import LockedChordReview
from bdo_music_composer.transcription.bdo_transcription_harmony import ChordSegment
from bdo_music_composer.transcription.muscriptor_backend import (
    muscriptor_backend_status,
)
from bdo_music_composer.transcription.reference_melody_guidance import (
    build_reference_melody_guidance,
)
from bdo_music_composer.transcription.reference_timbre import (
    build_reference_timbre_prediction,
    merge_reference_timbre_evidence,
)
from bdo_music_composer.transcription.bdo_transcription_policy import CANDIDATE_NOTE_POLICY
from bdo_music_composer.transcription.rhythm_alignment import (
    RhythmAlignmentSidecar,
)
from bdo_music_composer.transcription.bdo_transcription_session import (
    CandidateRoute,
    TranscriptionEditorCommit,
    TranscriptionEditorCommitReport,
    TranscriptionSessionState,
)
from bdo_music_composer.ui.editor.editor_articulation_data import (
    BDO_ARTICULATIONS,
    BDO_ARTICULATION_USAGE_HINTS,
)
from .editor_shortcut_hud import (
    EditorShortcutHelpDialog,
    EditorShortcutHud,
)
from .editor_shortcuts import editor_shortcut_spec
from bdo_music_composer.editor.editor_models import (
    BDO_DRUM_MAX,
    BDO_DRUM_MIN,
    GhostNoteProjection,
    TrackState,
    game_supported_pitches,
    note_name,
    same_onset_articulation_indices,
    track_uses_canonical_drum_lanes,
)
from bdo_music_composer.editor.editor_commands import (
    next_non_overlapping_paste_origin,
)
from bdo_music_composer.ui.theme.fluent_theme import (
    FluentSymbol,
    fluent_icon_size,
    set_fluent_symbol,
)
from bdo_music_composer.ui.i18n import tr, trf, trfv, trv
from .piano_roll_canvas import PianoRollCanvas, VelocityLaneCanvas
from bdo_music_composer.editor.pitch_transform import (
    PitchTransformPlan,
    track_uses_percussion_pitch_semantics,
    transpose_notes,
)
from bdo_music_composer.core.project_paths import WWISE_MIDI_MAP_PATH
from bdo_music_composer.project.project_schema import (
    normalize_reference_layer_settings,
)
from bdo_music_composer.ui.transcription.transcription_editor_qt import (
    TranscriptionEditorPanel,
    TranscriptionWaveformLane,
)
from bdo_music_composer.ui.transcription_ui_helpers import (
    transcription_cleanup_ui_labels,
)
from bdo_music_composer.ui.ui_controls import ElidedLabel, PillButton
from bdo_music_composer.ui.ui_notifications import show_global_toast
from bdo_music_composer.ui.ui_preferences_qt import EditorUiPreferenceBinding


BDO_SAMPLE_MAP_PATH = WWISE_MIDI_MAP_PATH
EDITOR_VERBOSE_CONTROLS_MIN_WIDTH = 1420


def _ui_bdo_instrument_name(instrument_id: int) -> str:
    return localized_bdo_instrument_name(int(instrument_id), tr)


def _ui_bdo_instrument_source(instrument_id: int) -> str:
    numeric_id = int(instrument_id)
    return BDO_INSTRUMENT_NAMES.get(numeric_id, f"BDO 0x{numeric_id:02X}")


class _VelocityMappingSignals(QObject):
    finished = Signal(int, object, str)


class _VelocityMappingTask(QRunnable):
    def __init__(self, request_id: int, track: TrackState, note: Note) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.instrument_id = int(track.bdo_instrument_id)
        self.synth_mode = str(track.marnian_synth_mode)
        self.pitch = int(note.pitch)
        self.ntype = int(note.ntype)
        self.signals = _VelocityMappingSignals()

    @Slot()
    def run(self) -> None:
        try:
            boundaries = sample_map_velocity_boundaries(
                BDO_SAMPLE_MAP_PATH,
                self.instrument_id,
                self.pitch,
                self.ntype,
                self.synth_mode,
            )
            error = ""
        except (OSError, ValueError, KeyError, TypeError) as exc:
            boundaries = ()
            error = str(exc)
        self.signals.finished.emit(self.request_id, boundaries, error)


class MidiNoteEditorDialog(QDialog):
    notes_applied = Signal(object)
    REFERENCE_TRAILING_BEATS = 4.0
    FREE_AUTHORING_TRAILING_BEATS = 12.0
    FREE_AUTHORING_TRAILING_VIEWPORTS = 1.5

    def __init__(
        self,
        parent,
        track: TrackState,
        bpm: int,
        time_sig: int,
        transpose: int = 0,
        *,
        transcription_mode: bool = False,
        pitch_plan: PitchTransformPlan | None = None,
    ) -> None:
        super().__init__(parent)
        self._velocity_mapping_pool = QThreadPool(self)
        self._velocity_mapping_pool.setMaxThreadCount(1)
        self._velocity_mapping_request = 0
        self._velocity_mapping_key: tuple[int, int, int, str] | None = None
        self._velocity_mapping_tasks: dict[int, _VelocityMappingTask] = {}
        self.setObjectName("MidiNoteEditorDialog")
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
        )
        self.track, self.bpm, self.time_sig = (
            track,
            int(bpm or 120),
            int(time_sig or 4),
        )
        self.pitch_transform_plan = (
            pitch_plan
            if isinstance(pitch_plan, PitchTransformPlan)
            else PitchTransformPlan(int(transpose))
        )
        self.transpose = self.pitch_transform_plan.effective_track_semitones(
            track
        )
        self.instrument_adaptation = instrument_editor_display_adaptation(
            int(track.bdo_instrument_id)
        )
        self.canonical_drum_lanes = track_uses_canonical_drum_lanes(track)
        self.default_articulation_ntype = (
            99 if self.canonical_drum_lanes else 0
        )
        legacy_track_articulation = getattr(track, "articulation_type", None)
        self.legacy_track_articulation = (
            int(legacy_track_articulation)
            if legacy_track_articulation is not None
            and not track.is_percussion
            and int(track.bdo_instrument_id) != 0x0D
            else None
        )
        initial_notes = [
            note._replace(ntype=self.legacy_track_articulation)
            if self.legacy_track_articulation is not None
            else note
            for note in track.notes
        ]
        self._initial_pitch_focus_pending = True
        self.beat_origin_ms = float(getattr(parent, "beat_origin_ms", 0.0))
        self.undo_stack: list[
            tuple[
                list,
                set[int],
                set[CandidateRoute],
                set[CandidateRoute],
                dict[int, int],
                str,
                str,
            ]
        ] = []
        self.redo_stack: list[
            tuple[
                list,
                set[int],
                set[CandidateRoute],
                set[CandidateRoute],
                dict[int, int],
                str,
                str,
            ]
        ] = []
        self.clipboard: list = []
        self.last_applied = list(initial_notes)
        self.staged_primary_routes: set[CandidateRoute] = set()
        self.staged_copy_routes: set[CandidateRoute] = set()
        self.staged_new_track_specs: dict[int, int] = {}
        self.staged_analysis_cache_key = ""
        self.staged_analysis_fingerprint = ""
        self._transcription_mode_requested = bool(transcription_mode)
        self.updating_fields = False
        self.draft_playback_state = "stopped"
        self.playhead_ms = 0.0
        self.draft_reference_last_resync_at = 0.0
        self.playback_timer = QTimer(self)
        self.playback_timer.setInterval(16)
        self.playback_timer.timeout.connect(self.poll_draft_playback)
        self.audition_timer = QTimer(self)
        self.audition_timer.setInterval(25)
        self.audition_timer.timeout.connect(self._poll_note_audition)
        self.audition_stop_timer = QTimer(self)
        self.audition_stop_timer.setSingleShot(True)
        self.audition_stop_timer.timeout.connect(self._stop_note_audition)
        self.audition_pending = False
        self.audition_note_name = ""
        self.transcription_mode_enabled = False
        self.transcription_candidates: tuple[TranscriptionCandidate, ...] = ()
        self.transcription_result: TranscriptionResult | None = None
        self.transcription_rhythm_alignment: RhythmAlignmentSidecar | None = None
        self.transcription_rhythm_projection_enabled = True
        self.transcription_audition_source = "combined"
        self._spectrogram_reference_audio: object | None = None
        self._transcription_annotation_projection_cache = None
        self._transcription_display_projection_cache = None
        self._transcription_rhythm_candidate_cache = None
        self._melody_guidance_cache = None
        self._eligible_candidate_cache: tuple[
            tuple,
            tuple[str, ...],
        ] | None = None
        self.draft_reference_only = False
        self.default_note_velocity = 100
        self.last_note_duration_ms = 0.0
        self._last_selected_note_properties: tuple[int, float, int] | None = None
        self._draft_autosave_revision = 0
        self._invalid_pitch_cache: dict[int, bool] = {}
        self._invalid_note_count = 0
        self._hover_status_key: tuple[int, int] | None = None
        self.setWindowTitle(
            trf("编辑音符 · {track}", track=track.display_name)
        )
        self.setMinimumSize(920, 680)
        available = QApplication.primaryScreen().availableGeometry() if QApplication.primaryScreen() else None
        if available is None:
            self.resize(1440, 860)
        else:
            self.resize(
                max(self.minimumWidth(), min(1560, available.width() - 72)),
                max(self.minimumHeight(), min(960, available.height() - 72)),
            )
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 4)
        root.setSpacing(3)

        def add_inset(widget: QWidget, object_name: str) -> None:
            shell = QWidget()
            shell.setObjectName(object_name)
            shell_layout = QHBoxLayout(shell)
            shell_layout.setContentsMargins(8, 0, 8, 0)
            shell_layout.setSpacing(0)
            shell_layout.addWidget(widget)
            root.addWidget(shell)

        toolbar_frame = QFrame()
        toolbar_frame.setObjectName("EditorToolbar")
        toolbar_frame.setFixedHeight(42)
        toolbar = QHBoxLayout(toolbar_frame)
        toolbar.setContentsMargins(10, 3, 8, 3)
        toolbar.setSpacing(6)
        self.editor_title_block = QWidget()
        title_layout = QVBoxLayout(self.editor_title_block)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)
        instrument_name = _ui_bdo_instrument_name(track.bdo_instrument_id)
        title = ElidedLabel(track.display_name, maximum_hint_width=180)
        title.setObjectName("EditorTrackTitle")
        title.setProperty("i18nSkipText", True)
        title.setToolTip(instrument_name)
        title.setAccessibleDescription(instrument_name)
        title_layout.addWidget(title)
        self.track_meta = ElidedLabel(maximum_hint_width=210)
        self.track_meta.setObjectName("EditorTrackMeta")
        title_layout.addWidget(self.track_meta)
        toolbar.addWidget(self.editor_title_block)
        toolbar.addSpacing(10)
        self.editor_transport_frame = QFrame()
        self.editor_transport_frame.setObjectName("EditorTransport")
        transport = QHBoxLayout(self.editor_transport_frame)
        transport.setContentsMargins(4, 1, 5, 1)
        transport.setSpacing(4)
        self.draft_play_button = PillButton(tr("播放"), "primary", FluentSymbol.PLAY)
        self.draft_play_button.clicked.connect(self.toggle_draft_playback)
        transport.addWidget(self.draft_play_button)
        self.draft_stop_button = PillButton(tr("停止"), "ghost", FluentSymbol.STOP)
        self.draft_stop_button.clicked.connect(self.stop_draft)
        transport.addWidget(self.draft_stop_button)
        self.loop_box = QCheckBox(tr("循环"))
        transport.addWidget(self.loop_box)
        self.playback_time_label = QLabel("0:00.000 / 0:00.000")
        self.playback_time_label.setObjectName("EditorTime")
        self.playback_time_label.setFixedWidth(152)
        transport.addWidget(self.playback_time_label)
        toolbar.addWidget(self.editor_transport_frame)
        toolbar.addStretch(1)
        self.editor_toolbar_action_buttons: dict[str, PillButton] = {}
        for label, callback in (("撤销", self.undo), ("重做", self.redo)):
            button = PillButton(tr(label), "ghost")
            button.clicked.connect(callback)
            toolbar.addWidget(button)
            self.editor_toolbar_action_buttons[label] = button
        self.shortcut_help_button = PillButton(tr("快捷键"), "ghost")
        self.shortcut_help_button.setToolTip(tr("查看完整快捷键（F1）"))
        self.shortcut_help_button.setAccessibleName(tr("查看完整快捷键"))
        self.shortcut_help_button.clicked.connect(self.show_shortcut_help)
        toolbar.addWidget(self.shortcut_help_button)
        self.editor_optimize_button = PillButton(
            tr("优化此轨"),
            "secondary",
            FluentSymbol.OPTIMIZE,
        )
        self.editor_optimize_button.clicked.connect(self.optimize_draft)
        toolbar.addWidget(self.editor_optimize_button)
        toolbar.addSpacing(5)
        self.cancel_button = PillButton(tr("放弃"), "ghost")
        self.cancel_button.setToolTip(tr("取消"))
        self.cancel_button.setAccessibleName(tr("取消"))
        self.cancel_button.clicked.connect(self.reject)
        toolbar.addWidget(self.cancel_button)
        self.confirm_button = PillButton(tr("完成"), "convert")
        self.confirm_button.setToolTip(tr("应用并关闭"))
        self.confirm_button.setAccessibleName(tr("应用并关闭"))
        self.confirm_button.clicked.connect(self.accept_with_apply)
        toolbar.addWidget(self.confirm_button)
        add_inset(toolbar_frame, "EditorToolbarInset")

        inspector = QFrame()
        inspector.setObjectName("NoteInspectorTop")
        inspector.setFixedHeight(34)
        inspector_layout = QHBoxLayout(inspector)
        inspector_layout.setContentsMargins(6, 3, 6, 3)
        inspector_layout.setSpacing(5)
        self.draw_mode_button = PillButton(tr("绘制 B"), "ghost")
        self.draw_mode_button.setObjectName("DrawMode")
        self.draw_mode_button.setCheckable(True)
        self.draw_mode_button.setFixedHeight(26)
        self.draw_mode_button.setToolTip(
            tr("绘制模式：拖动可同时设置音符长度与力度（B）")
        )
        self.draw_mode_button.toggled.connect(self._toggle_draw_mode)
        inspector_layout.addWidget(self.draw_mode_button, 0, Qt.AlignVCenter)
        self.note_mode_button = PillButton(tr("音符"), "ghost")
        self.note_mode_button.setObjectName("InspectorMode")
        self.note_mode_button.setFixedHeight(26)
        self.note_mode_button.setCheckable(True)
        self.note_mode_button.clicked.connect(lambda: self._set_top_inspector_mode("note"))
        inspector_layout.addWidget(self.note_mode_button, 0, Qt.AlignVCenter)
        self.articulation_mode_button = PillButton(tr("奏法"), "ghost")
        self.articulation_mode_button.setObjectName("InspectorMode")
        self.articulation_mode_button.setFixedHeight(26)
        self.articulation_mode_button.setCheckable(True)
        self.articulation_mode_button.clicked.connect(lambda: self._set_top_inspector_mode("articulation"))
        inspector_layout.addWidget(
            self.articulation_mode_button, 0, Qt.AlignVCenter
        )
        self.grid_mode_button = PillButton(tr("显示"), "ghost")
        self.grid_mode_button.setObjectName("InspectorMode")
        self.grid_mode_button.setFixedHeight(26)
        self.grid_mode_button.setCheckable(True)
        self.grid_mode_button.clicked.connect(lambda: self._set_top_inspector_mode("grid"))
        inspector_layout.addWidget(self.grid_mode_button, 0, Qt.AlignVCenter)

        self.quantize_quick = QFrame()
        self.quantize_quick.setObjectName("EditorQuantizeQuick")
        self.quantize_quick.setFixedHeight(26)
        quantize_quick_layout = QHBoxLayout(self.quantize_quick)
        quantize_quick_layout.setContentsMargins(5, 0, 3, 0)
        quantize_quick_layout.setSpacing(5)
        self.quantize_quick_label = QLabel(tr("量化"))
        self.quantize_quick_label.setObjectName("QuantizeQuickLabel")
        quantize_quick_layout.addWidget(self.quantize_quick_label)
        self.quantize_combo = QComboBox()
        self.quantize_combo.setObjectName("QuantizeGridCombo")
        for label, divisor in (
            ("1/4", 1),
            ("1/8", 2),
            ("1/16", 4),
            ("1/32", 8),
            ("1/64", 16),
        ):
            self.quantize_combo.addItem(label, divisor)
        self.quantize_combo.setCurrentIndex(0)
        # The themed combo reserves a 20 px arrow plus horizontal padding.
        # Keep four-character grids such as 1/16 and 1/32 fully readable even
        # in the compact inspector instead of relying on a clipped size hint.
        self.quantize_combo.setMinimumContentsLength(4)
        self.quantize_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.quantize_combo.setFixedWidth(92)
        self.quantize_combo.setFixedHeight(26)
        self.quantize_combo.setAccessibleName(tr("量化"))
        self.quantize_combo.setToolTip(tr("量化"))
        self.quantize_combo.currentIndexChanged.connect(
            self._quantize_grid_changed
        )
        quantize_quick_layout.addWidget(self.quantize_combo)
        inspector_layout.addWidget(self.quantize_quick, 0, Qt.AlignVCenter)

        self.velocity_toggle = PillButton(tr("力度"), "ghost", FluentSymbol.CURVE)
        self.velocity_toggle.setObjectName("VelocityToggle")
        self.velocity_toggle.setCheckable(True)
        self.velocity_toggle.setFixedHeight(26)
        self.velocity_toggle.setToolTip(tr("显示音符力度；可点调或用柔化刷影响周边音符"))
        self.velocity_toggle.toggled.connect(self._toggle_velocity_lane)
        inspector_layout.addWidget(self.velocity_toggle, 0, Qt.AlignVCenter)

        self.ghost_box = QToolButton()
        self.ghost_box.setObjectName("TrackReferenceToggle")
        self.ghost_box.setText(tr("其他轨"))
        self.ghost_box.setAccessibleName(tr("其他轨道参考"))
        self.ghost_box.setToolTip(
            tr("点击开关其他轨参照；箭头可调整透明度")
        )
        self.ghost_box.setCheckable(True)
        self.ghost_box.setChecked(False)
        self.ghost_box.setFixedHeight(26)
        self.ghost_box.setPopupMode(
            QToolButton.ToolButtonPopupMode.MenuButtonPopup
        )
        self.ghost_box.toggled.connect(self._toggle_ghost_notes)
        self.ghost_opacity_menu = QMenu(self.ghost_box)
        self.ghost_opacity_popup = QWidget(self.ghost_opacity_menu)
        ghost_opacity_layout = QHBoxLayout(self.ghost_opacity_popup)
        ghost_opacity_layout.setContentsMargins(8, 5, 8, 5)
        ghost_opacity_layout.setSpacing(6)
        self.ghost_opacity_caption = QLabel(
            tr("透明度"),
            self.ghost_opacity_popup,
        )
        self.ghost_opacity_slider = QSlider(
            Qt.Horizontal,
            self.ghost_opacity_popup,
        )
        self.ghost_opacity_slider.setObjectName(
            "TrackReferenceOpacitySlider"
        )
        self.ghost_opacity_slider.setRange(0, 100)
        self.ghost_opacity_slider.setValue(30)
        self.ghost_opacity_slider.setFixedWidth(120)
        self.ghost_opacity_slider.setAccessibleName(
            tr("其他轨道参照透明度")
        )
        self.ghost_opacity_slider.setToolTip(self.ghost_box.toolTip())
        self.ghost_opacity_caption.setBuddy(self.ghost_opacity_slider)
        self.ghost_opacity_slider.valueChanged.connect(
            self._ghost_opacity_changed
        )
        self.ghost_opacity_label = QLabel(
            "30%",
            self.ghost_opacity_popup,
        )
        self.ghost_opacity_label.setFixedWidth(38)
        ghost_opacity_layout.addWidget(self.ghost_opacity_caption)
        ghost_opacity_layout.addWidget(self.ghost_opacity_slider)
        ghost_opacity_layout.addWidget(self.ghost_opacity_label)
        ghost_opacity_action = QWidgetAction(self.ghost_opacity_menu)
        ghost_opacity_action.setDefaultWidget(self.ghost_opacity_popup)
        self.ghost_opacity_menu.addAction(ghost_opacity_action)
        self.ghost_box.setMenu(self.ghost_opacity_menu)
        inspector_layout.addWidget(self.ghost_box, 0, Qt.AlignVCenter)

        self.note_controls = QWidget()
        self.note_controls.setFixedHeight(26)
        note_layout = QHBoxLayout(self.note_controls)
        note_layout.setContentsMargins(3, 0, 0, 0)
        note_layout.setSpacing(7)
        self.selection_summary = QLabel(tr("未选择音符"))
        self.selection_summary.setObjectName("InspectorSelection")
        self.selection_summary.setWordWrap(False)
        self.selection_summary.setMinimumWidth(145)
        self.selection_summary.setMaximumWidth(190)
        note_layout.addWidget(self.selection_summary)
        self.pitch_edit = QLineEdit()
        self.start_edit = QLineEdit()
        self.duration_edit = QLineEdit()
        self.velocity_edit = QLineEdit()
        self.note_field_labels: list[QLabel] = []
        self.note_field_groups: list[QWidget] = []
        for label, widget, field in (("音高", self.pitch_edit, "pitch"), ("开始 ms", self.start_edit, "start"), ("时值 ms", self.duration_edit, "dur"), ("力度", self.velocity_edit, "vel")):
            widget.editingFinished.connect(lambda f=field, w=widget: self.apply_field(f, w.text()))
            widget.setFixedWidth(64 if field in ("pitch", "vel") else 72)
            group = QWidget()
            group_layout = QHBoxLayout(group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(4)
            field_label = QLabel(tr(label))
            field_label.setObjectName("Muted")
            field_label.setBuddy(widget)
            widget.setAccessibleName(tr(label))
            self.note_field_labels.append(field_label)
            self.note_field_groups.append(group)
            group_layout.addWidget(field_label)
            group_layout.addWidget(widget)
            note_layout.addWidget(group)

        self.articulation_combo = QComboBox()
        supported = list(BDO_ARTICULATIONS.get(track.bdo_instrument_id, []))
        supported_by_type = {
            int(ntype): str(label) for ntype, label in supported
        }

        def articulation_ui_label(ntype: int, source_label: str) -> str:
            translated = str(tr(source_label))
            if ntype == 0 and source_label != "普通":
                return f"{tr('普通')}（{translated}）"
            return translated

        available_articulations: list[tuple[int, str]] = []
        default_source = supported_by_type.get(
            self.default_articulation_ntype,
            "打击乐" if self.default_articulation_ntype == 99 else "普通",
        )
        available_articulations.append(
            (
                self.default_articulation_ntype,
                articulation_ui_label(
                    self.default_articulation_ntype,
                    default_source,
                ),
            )
        )
        available_articulations.extend(
            (int(ntype), articulation_ui_label(int(ntype), str(label)))
            for ntype, label in supported
            if int(ntype) != self.default_articulation_ntype
        )
        known = {ntype for ntype, _label in available_articulations}
        available_articulations.extend(
            (
                ntype,
                str(trf("未知奏法 type {ntype}", ntype=ntype)),
            )
            for ntype in sorted({
                int(getattr(note, "ntype", 0)) for note in initial_notes
            } - known)
        )
        self.available_articulations = tuple(available_articulations)
        self.articulation_labels_by_type = dict(self.available_articulations)
        for ntype, label in self.available_articulations:
            self.articulation_combo.addItem(label, ntype)
            hint_source = BDO_ARTICULATION_USAGE_HINTS.get(ntype)
            if hint_source:
                self.articulation_combo.setItemData(
                    self.articulation_combo.count() - 1,
                    tr(hint_source),
                    Qt.ToolTipRole,
                )
        default_index = self.articulation_combo.findData(
            self.default_articulation_ntype
        )
        if default_index >= 0:
            self.articulation_combo.setCurrentIndex(default_index)
        self.articulation_combo.currentIndexChanged.connect(self.apply_articulation)
        note_layout.addStretch(1)
        inspector_layout.addWidget(
            self.note_controls, 1, Qt.AlignVCenter
        )

        self.articulation_controls = QWidget()
        articulation_layout = QHBoxLayout(self.articulation_controls)
        articulation_layout.setContentsMargins(3, 0, 0, 0)
        articulation_layout.setSpacing(6)
        self.articulation_combo.setObjectName("ArticulationCombo")
        self.articulation_combo.setMinimumWidth(172)
        self.articulation_combo.setFixedHeight(26)
        articulation_layout.addWidget(
            self.articulation_combo,
            0,
            Qt.AlignVCenter,
        )
        self.articulation_preview_button = QPushButton("")
        self.articulation_preview_button.setObjectName(
            "ArticulationPreview"
        )
        self.articulation_preview_button.setCursor(Qt.PointingHandCursor)
        set_fluent_symbol(
            self.articulation_preview_button,
            FluentSymbol.PLAY,
        )
        self.articulation_preview_button.setIconSize(fluent_icon_size())
        self.articulation_preview_button.setFixedSize(30, 26)
        articulation_preview_label = f"{tr('点击试听')} · {tr('奏法')}"
        self.articulation_preview_button.setToolTip(
            articulation_preview_label
        )
        self.articulation_preview_button.setAccessibleName(
            articulation_preview_label
        )
        self.articulation_preview_button.setEnabled(False)
        self.articulation_preview_button.clicked.connect(
            lambda: self.preview_selected_articulation(force=True)
        )
        articulation_layout.addWidget(
            self.articulation_preview_button,
            0,
            Qt.AlignVCenter,
        )
        self.articulation_buttons: dict[int, QPushButton] = {}
        for ntype, label in self.available_articulations[:4]:
            button = QPushButton(label)
            button.setObjectName("ArticulationChip")
            button.setCheckable(True)
            # State is synchronized explicitly with the full dropdown.  Qt's
            # auto-exclusive mode cannot clear the last visible button when a
            # technique outside this compact shortcut set is selected.
            button.setAutoExclusive(False)
            button.setFixedHeight(26)
            button.setProperty("ntype", ntype)
            button.clicked.connect(lambda _checked=False, value=ntype: self._choose_articulation(value))
            hint_source = BDO_ARTICULATION_USAGE_HINTS.get(ntype)
            if hint_source:
                button.setToolTip(tr(hint_source))
            articulation_layout.addWidget(button, 0, Qt.AlignVCenter)
            self.articulation_buttons[ntype] = button
        self.articulation_overflow_button = QPushButton("")
        self.articulation_overflow_button.setObjectName("ArticulationChip")
        self.articulation_overflow_button.setCheckable(True)
        self.articulation_overflow_button.setAutoExclusive(False)
        self.articulation_overflow_button.setFixedHeight(26)
        self.articulation_overflow_button.clicked.connect(
            lambda: self._choose_articulation(
                int(
                    self.articulation_overflow_button.property("ntype")
                    or self.default_articulation_ntype
                )
            )
        )
        self.articulation_overflow_button.hide()
        articulation_layout.addWidget(
            self.articulation_overflow_button,
            0,
            Qt.AlignVCenter,
        )
        articulation_layout.addStretch(1)
        inspector_layout.addWidget(
            self.articulation_controls, 1, Qt.AlignVCenter
        )

        self.grid_controls = QWidget()
        grid_layout = QHBoxLayout(self.grid_controls)
        grid_layout.setContentsMargins(3, 0, 0, 0)
        grid_layout.setSpacing(12)
        self.snap_box = QCheckBox(tr("吸附"))
        self.snap_box.setChecked(True)
        grid_layout.addWidget(self.snap_box)
        self.note_preview_box = QCheckBox(tr("点击试听"))
        self.note_preview_box.setChecked(True)
        grid_layout.addWidget(self.note_preview_box)
        editor_zoom_label = QLabel(tr("水平缩放"))
        grid_layout.addWidget(editor_zoom_label)
        self.editor_zoom = QSlider(Qt.Horizontal)
        self.editor_zoom.setRange(
            round(PianoRollCanvas.MIN_PX_PER_BEAT),
            round(PianoRollCanvas.MAX_PX_PER_BEAT),
        )
        self.editor_zoom.setValue(92)
        self.editor_zoom.setFixedWidth(150)
        self.editor_zoom.setAccessibleName(tr("水平缩放"))
        zoom_hint = tr(
            "触控板双指滑动：平移；Ctrl+滚轮：时间缩放；Alt+滚轮：音块高度"
        )
        editor_zoom_label.setToolTip(zoom_hint)
        self.editor_zoom.setToolTip(zoom_hint)
        editor_zoom_label.setBuddy(self.editor_zoom)
        self.editor_zoom.valueChanged.connect(self.set_zoom)
        grid_layout.addWidget(self.editor_zoom)
        grid_layout.addStretch(1)
        inspector_layout.addWidget(
            self.grid_controls, 1, Qt.AlignVCenter
        )
        add_inset(inspector, "EditorInspectorInset")
        self._set_top_inspector_mode("note")

        self.transcription_panel = TranscriptionEditorPanel(self)
        self.transcription_panel.setVisible(False)
        # Compatibility aliases keep the analysis-worker adapter small while
        # all visible controls now live in the embedded panel.
        self.transcription_hint = self.transcription_panel.status_label
        self.transcription_progress = self.transcription_panel.status_label
        self.transcription_analyze_button = self.transcription_panel.analyze_button
        self.transcription_accept_button = (
            self.transcription_panel.write_current_track_button
        )
        self.transcription_clear_button = (
            self.transcription_panel.clear_staging_button
        )
        self.transcription_panel.load_audio_requested.connect(
            self._load_reference_audio_from_editor
        )
        self.transcription_panel.unload_audio_requested.connect(
            self._unload_reference_audio_from_editor
        )
        self.transcription_panel.analyze_requested.connect(
            self.start_transcription_analysis
        )
        self.transcription_panel.redecode_requested.connect(
            self._redecode_transcription_range
        )
        self.transcription_panel.analysis_mode_changed.connect(
            self._transcription_analysis_mode_changed
        )
        self.transcription_panel.sensitivity_changed.connect(
            self._transcription_sensitivity_changed
        )
        self.transcription_panel.cleanup_profile_changed.connect(
            self._transcription_cleanup_profile_changed
        )
        self.transcription_panel.confidence_changed.connect(
            lambda _value: self._sync_shared_transcription_projection()
        )
        self.transcription_panel.candidate_visibility_changed.connect(
            self._transcription_candidate_visibility_changed
        )
        self.transcription_panel.candidate_opacity_changed.connect(
            self._transcription_candidate_opacity_changed
        )
        self.transcription_panel.timbre_grouping_changed.connect(
            self._transcription_timbre_grouping_changed
        )
        self.transcription_panel.external_instrument_labels_changed.connect(
            self._transcription_external_instrument_labels_changed
        )
        self.transcription_panel.contour_denoise_changed.connect(
            self._transcription_contour_denoise_changed
        )
        self.transcription_panel.contour_opacity_changed.connect(
            self._transcription_contour_opacity_changed
        )
        self.transcription_panel.melody_guidance_changed.connect(
            self._transcription_melody_guidance_changed
        )
        self.transcription_panel.show_rejected_changed.connect(
            lambda _value: self._sync_shared_transcription_projection()
        )
        self.transcription_panel.show_suppressed_changed.connect(
            lambda _value: self._sync_shared_transcription_projection()
        )
        self.transcription_panel.select_fragments_requested.connect(
            self._select_suspected_transcription_fragments
        )
        self.transcription_panel.evidence_layers_changed.connect(
            self._transcription_evidence_layers_changed
        )
        self.transcription_panel.melody_lines_visibility_changed.connect(
            self._transcription_melody_lines_visibility_changed
        )
        self.transcription_panel.melody_line_roles_changed.connect(
            self._transcription_melody_line_roles_changed
        )
        self.transcription_panel.spectrogram_visibility_changed.connect(
            self._transcription_spectrogram_visibility_changed
        )
        self.transcription_panel.reference_background_opacity_changed.connect(
            self._transcription_reference_background_opacity_changed
        )
        self.transcription_panel.align_audio_requested.connect(
            self._align_reference_audio_to_playhead
        )
        self.transcription_panel.beat_origin_requested.connect(
            self._set_playhead_as_beat_origin
        )
        self.transcription_panel.rhythm_diagnostic_requested.connect(
            self._start_transcription_rhythm_diagnostic
        )
        self.transcription_panel.rhythm_projection_enabled_changed.connect(
            self._transcription_rhythm_projection_changed
        )
        self.transcription_panel.clear_range_requested.connect(
            self._clear_transcription_range
        )
        self.transcription_panel.review_undo_requested.connect(
            self._undo_transcription_review
        )
        self.transcription_panel.review_redo_requested.connect(
            self._redo_transcription_review
        )
        self.transcription_panel.reject_requested.connect(
            self._reject_transcription_candidates
        )
        self.transcription_panel.restore_requested.connect(
            self._restore_transcription_candidates
        )
        self.transcription_panel.write_current_track_requested.connect(
            self.accept_transcription_candidates
        )
        self.transcription_panel.copy_to_track_requested.connect(
            self._stage_transcription_copy
        )
        self.transcription_panel.clear_staging_requested.connect(
            self._clear_transcription_staging
        )
        root.addWidget(self.transcription_panel)
        parent_config = getattr(parent, "config", {})
        if not isinstance(parent_config, dict):
            parent_config = {}
        reference_layer_settings = normalize_reference_layer_settings(
            getattr(parent, "reference_layer_settings", None)
        )
        if parent is not None:
            parent.reference_layer_settings = reference_layer_settings
        blocked = self.ghost_box.blockSignals(True)
        self.ghost_box.setChecked(
            bool(reference_layer_settings["ghost_visible"])
        )
        self.ghost_box.blockSignals(blocked)
        ghost_opacity_percent = int(
            reference_layer_settings["ghost_opacity_percent"]
        )
        blocked = self.ghost_opacity_slider.blockSignals(True)
        self.ghost_opacity_slider.setValue(ghost_opacity_percent)
        self.ghost_opacity_slider.blockSignals(blocked)
        self.ghost_opacity_label.setText(f"{ghost_opacity_percent}%")
        transcription_ui_config = (
            parent_config.get("transcription_ui", {})
            if isinstance(parent_config.get("transcription_ui", {}), dict)
            else {}
        )
        configured_layers = {
            layer
            for layer in ("frame", "onset", "contour")
            if bool(reference_layer_settings[f"{layer}_visible"])
        }
        self.transcription_panel.set_evidence_layers(configured_layers)
        self.transcription_panel.set_melody_lines_visible(
            bool(reference_layer_settings["melody_lines_visible"])
        )
        self.transcription_panel.set_spectrogram_visible(
            bool(reference_layer_settings["spectrogram_visible"])
        )
        self.transcription_panel.set_reference_background_opacity(
            int(reference_layer_settings["background_opacity_percent"])
            / 100.0
        )
        self.transcription_panel.set_contour_opacity(
            int(reference_layer_settings["contour_opacity_percent"])
            / 100.0
        )
        self.transcription_panel.set_melody_guidance_enabled(
            bool(reference_layer_settings["melody_guidance_enabled"])
        )
        self.transcription_panel.set_candidate_layer_visible(
            bool(reference_layer_settings["candidate_visible"])
        )
        self.transcription_panel.set_candidate_opacity(
            int(reference_layer_settings["candidate_opacity_percent"])
            / 100.0
        )
        muscriptor_executable = str(
            transcription_ui_config.get("muscriptor_executable", "") or ""
        )
        external_available, _external_reason = muscriptor_backend_status(
            muscriptor_executable
        )
        self.transcription_panel.set_external_instrument_labels_available(
            external_available
        )
        self.transcription_panel.set_timbre_grouping_enabled(
            bool(reference_layer_settings["timbre_grouping_enabled"])
        )
        self.transcription_panel.set_external_instrument_labels_enabled(
            bool(
                reference_layer_settings[
                    "external_instrument_labels_enabled"
                ]
            )
        )
        self.transcription_panel.set_contour_denoise(
            str(reference_layer_settings["contour_denoise"])
        )
        configured_guide_roles = transcription_ui_config.get(
            "melody_line_roles",
            ("primary_melody",),
        )
        if isinstance(configured_guide_roles, (list, tuple, set)):
            self.transcription_panel.set_melody_line_roles(
                str(role) for role in configured_guide_roles
            )
        # Disclosure is ephemeral: every editor opens in the compact state.
        # Layer visibility remains persisted independently, but old expanded
        # panels must not turn the next session back into a wall of controls.
        self.transcription_panel.set_advanced_controls_expanded(False)
        self.transcription_panel.set_diagnostic_evidence_expanded(False)

        workspace = QFrame()
        workspace.setObjectName("EditorWorkspace")
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        roll = QGridLayout()
        roll.setContentsMargins(0, 0, 0, 0)
        roll.setSpacing(0)
        self.canvas = PianoRollCanvas(self)
        self.canvas.setToolTip(
            tr("触控板双指滑动：平移；Ctrl+滚轮：时间缩放；Alt+滚轮：音块高度")
        )
        self.canvas.set_ghost_opacity(ghost_opacity_percent / 100.0)
        self.canvas.set_reference_background_opacity(
            int(reference_layer_settings["background_opacity_percent"])
            / 100.0
        )
        self.canvas.set_contour_opacity(
            int(reference_layer_settings["contour_opacity_percent"])
            / 100.0
        )
        self.canvas.set_transcription_candidate_layer_visible(
            bool(reference_layer_settings["candidate_visible"])
        )
        self.canvas.set_transcription_candidate_opacity(
            int(reference_layer_settings["candidate_opacity_percent"])
            / 100.0
        )
        self.canvas.set_contour_denoise_profile(
            str(reference_layer_settings["contour_denoise"])
        )
        self.canvas.set_melody_line_roles_visible(
            self.transcription_panel.melody_line_roles
        )
        self.canvas.set_notes(list(initial_notes))
        self.shortcut_hud = EditorShortcutHud(self.canvas)
        self.canvas.selection_changed.connect(self.refresh_fields)
        self.canvas.notes_changed.connect(self._notes_changed)
        self.canvas.hover_changed.connect(self._hover_changed)
        self.canvas.ruler_seek_requested.connect(self.seek_draft)
        self.canvas.candidate_selection_changed.connect(
            self._transcription_selection_changed
        )
        self.canvas.time_range_changed.connect(
            self._transcription_range_changed
        )
        self.canvas.chord_segment_clicked.connect(
            self._transcription_chord_segment_clicked
        )
        self.canvas.voice_group_split_requested.connect(
            self._split_transcription_voice_group
        )
        self.canvas.voice_group_merge_requested.connect(
            self._merge_transcription_voice_groups
        )
        self.canvas.voice_group_color_requested.connect(
            self._set_transcription_voice_group_color
        )
        self.canvas.voice_group_role_requested.connect(
            self._set_transcription_voice_group_role
        )
        self.pitch_scroll = QScrollBar(Qt.Vertical)
        self.pitch_scroll.setObjectName("PianoPitchScroll")
        self.pitch_scroll.setRange(0, 0)
        self.pitch_scroll.valueChanged.connect(self.set_pitch_scroll)
        self.time_scroll = QScrollBar(Qt.Horizontal)
        self.time_scroll.setObjectName("PianoTimeScroll")
        self.time_scroll.valueChanged.connect(self.set_time_scroll)
        roll.addWidget(self.canvas, 0, 0)
        roll.addWidget(self.pitch_scroll, 0, 1)
        workspace_layout.addLayout(roll, 1)
        self.transcription_waveform = TranscriptionWaveformLane(
            self.canvas, workspace
        )
        self.transcription_waveform.setVisible(False)
        self.transcription_waveform.seek_requested.connect(self.seek_draft)
        workspace_layout.addWidget(self.transcription_waveform)
        self.velocity_panel = QFrame()
        self.velocity_panel.setObjectName("VelocityPanel")
        velocity_panel_layout = QVBoxLayout(self.velocity_panel)
        velocity_panel_layout.setContentsMargins(0, 0, 0, 0)
        velocity_panel_layout.setSpacing(0)
        velocity_header = QFrame()
        velocity_header.setObjectName("VelocityHeader")
        velocity_header_layout = QHBoxLayout(velocity_header)
        velocity_header_layout.setContentsMargins(self.canvas.KEY_W, 2, 8, 2)
        velocity_header_layout.setSpacing(6)
        velocity_title = QLabel(tr("音符力度 0–127（非轨道音量）"))
        velocity_title.setObjectName("VelocityTitle")
        velocity_header_layout.addWidget(velocity_title)
        self.velocity_point_button = QPushButton(tr("点调"))
        self.velocity_point_button.setObjectName("VelocityModeButton")
        self.velocity_point_button.setCheckable(True)
        self.velocity_point_button.clicked.connect(lambda: self._set_velocity_mode("point"))
        velocity_header_layout.addWidget(self.velocity_point_button)
        self.velocity_brush_button = QPushButton(tr("柔化刷"))
        self.velocity_brush_button.setObjectName("VelocityModeButton")
        self.velocity_brush_button.setCheckable(True)
        self.velocity_brush_button.setChecked(True)
        self.velocity_brush_button.clicked.connect(lambda: self._set_velocity_mode("brush"))
        velocity_header_layout.addWidget(self.velocity_brush_button)
        self.velocity_radius_combo = QComboBox()
        self.velocity_radius_combo.setObjectName("VelocityRadiusCombo")
        for beats in (0.5, 1.0, 2.0, 4.0, 8.0):
            self.velocity_radius_combo.addItem(trf("影响 ±{beats:g} 拍", beats=beats), beats)
        self.velocity_radius_combo.setCurrentIndex(2)
        self.velocity_radius_combo.currentIndexChanged.connect(self._velocity_radius_changed)
        velocity_header_layout.addWidget(self.velocity_radius_combo)
        self.velocity_scope_combo = QComboBox()
        self.velocity_scope_combo.setObjectName("VelocityScopeCombo")
        self.velocity_scope_combo.addItem(tr("范围：全轨"), "track")
        self.velocity_scope_combo.addItem(tr("范围：所选"), "selection")
        self.velocity_scope_combo.currentIndexChanged.connect(self._velocity_scope_changed)
        velocity_header_layout.addWidget(self.velocity_scope_combo)
        velocity_header_layout.addStretch(1)
        velocity_panel_layout.addWidget(velocity_header)
        self.velocity_lane = VelocityLaneCanvas(self)
        velocity_panel_layout.addWidget(self.velocity_lane)
        self.velocity_panel.setVisible(False)
        workspace_layout.addWidget(self.velocity_panel)
        scroll_row = QHBoxLayout()
        scroll_row.setContentsMargins(0, 0, 0, 0)
        scroll_row.setSpacing(0)
        scroll_row.addWidget(self.time_scroll, 1)
        scroll_corner = QWidget()
        scroll_corner.setObjectName("PianoScrollCorner")
        scroll_corner.setFixedSize(12, 12)
        scroll_row.addWidget(scroll_corner)
        workspace_layout.addLayout(scroll_row)
        root.addWidget(workspace, 1)

        footer = QFrame()
        footer.setObjectName("EditorFooter")
        footer.setFixedHeight(27)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(8, 2, 8, 2)
        self.status = QLabel()
        self.status.setObjectName("Muted")
        footer_layout.addWidget(self.status, 1)
        music_volume_label = QLabel(tr("音乐音量"))
        music_volume_label.setObjectName("Muted")
        footer_layout.addWidget(music_volume_label)
        self.music_volume_slider = QSlider(Qt.Horizontal)
        self.music_volume_slider.setObjectName("EditorMusicVolume")
        self.music_volume_slider.setRange(0, 100)
        reference_audio = getattr(parent, "reference_audio", None)
        initial_music_volume = (
            int(reference_audio.volume_percent)
            if reference_audio is not None
            else 50
        )
        self.music_volume_slider.setValue(initial_music_volume)
        self.music_volume_slider.setFixedWidth(112)
        self.music_volume_slider.setToolTip(tr("调整参考音频音量"))
        self.music_volume_slider.setAccessibleName(tr("音乐音量"))
        music_volume_label.setBuddy(self.music_volume_slider)
        self.music_volume_slider.valueChanged.connect(self._set_editor_music_volume)
        footer_layout.addWidget(self.music_volume_slider)
        self.music_volume_value = QLabel(f"{initial_music_volume}%")
        self.music_volume_value.setObjectName("Muted")
        self.music_volume_value.setFixedWidth(38)
        footer_layout.addWidget(self.music_volume_value)
        self.transcription_mode_toggle = QCheckBox(tr("音乐参考"))
        self.transcription_mode_toggle.setObjectName("TranscriptionModeToggle")
        self.transcription_mode_toggle.setToolTip(
            tr("在当前音符编辑器中显示音乐参考、分析证据、候选和参考波形")
        )
        self.transcription_mode_toggle.toggled.connect(
            self._set_transcription_mode_enabled
        )
        footer_layout.addWidget(self.transcription_mode_toggle)
        add_inset(footer, "EditorFooterInset")
        self.ui_preference_binding = EditorUiPreferenceBinding(self, parent_config, self._persist_parent_config)
        self._toggle_ghost_notes(self.ghost_box.isChecked())
        self.finished.connect(lambda _result: self.stop_draft())
        self.shortcut_help_spec = editor_shortcut_spec("show_shortcuts")
        self.shortcut_help_shortcut = QShortcut(
            QKeySequence(self.shortcut_help_spec.key_source),
            self,
        )
        self.shortcut_help_shortcut.setContext(Qt.WindowShortcut)
        self.shortcut_help_shortcut.setAutoRepeat(False)
        self.shortcut_help_shortcut.activated.connect(self.show_shortcut_help)
        self._shortcut_help_dialog: EditorShortcutHelpDialog | None = None
        self._recalculate_invalid_note_count()
        self._update_track_meta()
        self.refresh_fields()
        self._apply_editor_responsive_density()
        QTimer.singleShot(0, self.update_scrollbars)
        if self._transcription_mode_requested:
            QTimer.singleShot(
                0, lambda: self.transcription_mode_toggle.setChecked(True)
            )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_editor_responsive_density()

    @staticmethod
    def _set_editor_compact_button(
        button: QPushButton,
        source_text: str,
        compact_text: str,
        compact: bool,
    ) -> None:
        full_text = tr(source_text)
        button.setToolTip(full_text)
        button.setAccessibleName(full_text)
        if compact:
            button.setText(compact_text)
            compact_width = max(
                34,
                min(72, button.fontMetrics().horizontalAdvance(compact_text) + 18),
            )
            button.setFixedWidth(compact_width)
        else:
            button.setMinimumWidth(0)
            button.setMaximumWidth(16777215)
            button.setText(full_text)

    def _apply_editor_responsive_density(self) -> None:
        """Keep both editor command rows usable at the supported 920 px width."""

        if not hasattr(self, "editor_title_block"):
            return
        compact = self.width() < EDITOR_VERBOSE_CONTROLS_MIN_WIDTH
        if getattr(self, "_editor_controls_compact", None) == compact:
            return
        self._editor_controls_compact = compact

        self.editor_title_block.setMaximumWidth(150 if compact else 16777215)
        self._set_editor_compact_button(
            self.draft_play_button,
            "播放",
            "",
            compact,
        )
        self._set_editor_compact_button(
            self.draft_stop_button,
            "停止",
            "",
            compact,
        )
        self.loop_box.setToolTip(tr("循环"))
        self.loop_box.setAccessibleName(tr("循环"))
        self.loop_box.setText("" if compact else tr("循环"))
        self.playback_time_label.setFixedWidth(126 if compact else 152)

        for source, compact_text in (
            ("撤销", "↶"),
            ("重做", "↷"),
        ):
            self._set_editor_compact_button(
                self.editor_toolbar_action_buttons[source],
                source,
                compact_text,
                compact,
            )
        self._set_editor_compact_button(
            self.shortcut_help_button,
            "快捷键",
            "?",
            compact,
        )
        self._set_editor_compact_button(
            self.editor_optimize_button,
            "优化此轨",
            "",
            compact,
        )
        self._set_editor_compact_button(
            self.cancel_button,
            "放弃",
            tr("放弃"),
            compact,
        )
        self._set_editor_compact_button(
            self.confirm_button,
            "完成",
            tr("完成"),
            compact,
        )

        for button, source, compact_text in (
            (self.draw_mode_button, "绘制 B", tr("绘制")),
            (self.note_mode_button, "音符", tr("音符")),
            (self.articulation_mode_button, "奏法", tr("奏法")),
            (self.grid_mode_button, "显示", tr("显示")),
            (self.velocity_toggle, "力度", tr("力度")),
        ):
            self._set_editor_compact_button(
                button,
                source,
                compact_text,
                compact,
            )
        for label in self.note_field_labels:
            label.setVisible(not compact)
        self.quantize_quick_label.setVisible(not compact)
        self.quantize_combo.setFixedWidth(88 if compact else 92)
        self.selection_summary.setMinimumWidth(70 if compact else 145)
        self.selection_summary.setMaximumWidth(120 if compact else 190)
        self.ghost_box.setText(tr("参照") if compact else tr("其他轨"))
        self.ghost_box.setFixedWidth(58 if compact else 88)
        self.editor_title_block.updateGeometry()
        self.editor_transport_frame.updateGeometry()

    def quantize_ms(self) -> float:
        return self.canvas.beat_ms / int(self.quantize_combo.currentData() or 4)

    def _quantize_grid_changed(self, _index: int) -> None:
        """Refresh the existing snap grid after the shared preset changes."""

        if hasattr(self, "canvas"):
            self.canvas.update()
        if hasattr(self, "time_scroll"):
            self.time_scroll.setSingleStep(max(1, round(self.quantize_ms())))

    def select_all_notes(self) -> None:
        """Select every editable draft note regardless of the focused control."""

        self.canvas.selected = set(range(len(self.canvas.notes)))
        self.canvas.anchor_index = 0 if self.canvas.notes else None
        self.canvas.selection_changed.emit()
        self.canvas.update()

    def show_shortcut_help(self) -> None:
        """Open a non-modal reference that can remain beside the editor."""

        dialog = self._shortcut_help_dialog
        if dialog is None:
            dialog = EditorShortcutHelpDialog(self)
            dialog.destroyed.connect(
                lambda: setattr(self, "_shortcut_help_dialog", None)
            )
            self._shortcut_help_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _set_editor_music_volume(self, value: int) -> None:
        normalized = max(0, min(100, int(value)))
        self.music_volume_value.setText(f"{normalized}%")
        reference_audio = getattr(self.parent(), "reference_audio", None)
        if reference_audio is not None:
            reference_audio.set_volume_percent(normalized)

    def _set_transcription_mode_enabled(self, enabled: bool) -> None:
        if (
            self.transcription_mode_enabled
            and not enabled
            and self.draft_playback_state != "stopped"
        ):
            # stop_draft must still see transcription mode enabled so it also
            # stops the Qt reference player before the mode is switched off.
            self.stop_draft()
        self.transcription_mode_enabled = bool(enabled)
        self.transcription_panel.set_draft_note_count(len(self.canvas.notes))
        self.transcription_panel.setVisible(self.transcription_mode_enabled)
        self.transcription_waveform.setVisible(self.transcription_mode_enabled)
        self.canvas.set_transcription_candidates_visible(
            self.transcription_mode_enabled
        )
        self.canvas.set_transcription_candidate_layer_visible(
            self.transcription_panel.candidate_layer_visible
        )
        if self.transcription_mode_enabled:
            self._sync_shared_transcription_projection()
        else:
            self._release_transcription_visual_resources()
        self.update_scrollbars()

    def _toggle_transcription_analysis(self) -> None:
        parent_worker = getattr(
            self.parent(),
            "workspace_transcription_worker",
            None,
        )
        if parent_worker is not None and parent_worker.isRunning():
            self._cancel_transcription_analysis()
            return
        self.start_transcription_analysis()

    def _has_transcription_staging(self) -> bool:
        return bool(
            self.staged_primary_routes
            or self.staged_copy_routes
            or self.staged_new_track_specs
        )

    def _capture_staging_identity(self) -> None:
        if self.staged_analysis_cache_key or self.staged_analysis_fingerprint:
            return
        session = getattr(self.parent(), "transcription_session", None)
        state = getattr(session, "state", None)
        self.staged_analysis_cache_key = str(
            getattr(state, "cache_key", "") or ""
        )
        self.staged_analysis_fingerprint = str(
            getattr(state, "analysis_fingerprint", "") or ""
        )

    def _clear_staging_identity_if_empty(self) -> None:
        if self._has_transcription_staging():
            return
        self.staged_analysis_cache_key = ""
        self.staged_analysis_fingerprint = ""

    def _warn_staging_blocks_analysis(self) -> bool:
        if not self._has_transcription_staging():
            return False
        QMessageBox.warning(
            self,
            tr("存在未提交候选草稿"),
            tr("请先应用、撤销或清除本次暂存，再更换音频或重新分析。"),
        )
        return True

    # Public host-facing facade.  The main window must not reach through the
    # dialog into its panel/canvas implementation details.
    def has_transcription_staging(self) -> bool:
        return self._has_transcription_staging()

    def warn_transcription_staging_blocked(self) -> bool:
        return self._warn_staging_blocks_analysis()

    def eligible_transcription_candidate_ids(
        self,
        *,
        include_routed: bool = False,
    ) -> tuple[str, ...]:
        return self._eligible_transcription_candidate_ids(
            include_routed=include_routed
        )

    def refresh_transcription_projection(self) -> None:
        self._sync_shared_transcription_projection()

    def release_transcription_resources(self) -> None:
        self._bind_spectrogram_reference_audio(None)
        self._release_transcription_visual_resources()

    def _release_transcription_visual_resources(self) -> None:
        """Release heavy tiles while keeping the projection reloadable."""
        self.canvas.release_transcription_evidence()
        # The descriptor still belongs to ``transcription_result``. Reset the
        # UI-side identity so a later Music Reference enable reopens it even
        # when the cache key itself has not changed.
        self._canvas_evidence_cache_key = None
        self.transcription_waveform.release_reference_audio()

    def _bind_spectrogram_reference_audio(self, controller: object | None) -> None:
        previous = self._spectrogram_reference_audio
        if previous is controller:
            return
        if previous is not None:
            signal = getattr(previous, "timeline_changed", None)
            if signal is not None:
                try:
                    signal.disconnect(self._refresh_canvas_spectrogram)
                except (RuntimeError, TypeError):
                    pass
        self._spectrogram_reference_audio = controller
        if controller is not None:
            signal = getattr(controller, "timeline_changed", None)
            if signal is not None:
                signal.connect(self._refresh_canvas_spectrogram)

    def _refresh_canvas_spectrogram(self, *_args) -> None:
        reference_audio = self._spectrogram_reference_audio
        has_audio = bool(
            reference_audio is not None
            and getattr(reference_audio, "audio_path", None)
        )
        # ``timeline_changed`` is emitted even for silent project restores
        # (``notify=False``).  Keep the primary analysis action keyed to that
        # live controller state instead of relying on an unrelated display
        # option, such as timbre grouping, to trigger a full projection sync.
        self.transcription_panel.set_audio_loaded(
            has_audio,
            display_name=(
                str(
                    getattr(
                        reference_audio,
                        "display_name",
                        Path(str(reference_audio.audio_path)).name,
                    )
                )
                if has_audio
                else ""
            ),
        )
        self.canvas.set_spectrogram_source(
            reference_audio.audio_path if has_audio else None,
            duration_ms=(
                float(getattr(reference_audio, "duration_ms", 0.0) or 0.0)
                if has_audio
                else 0.0
            ),
            audio_offset_ms=(
                float(
                    getattr(
                        self.parent(),
                        "reference_audio_offset_ms",
                        getattr(reference_audio, "project_offset_ms", 0.0),
                    )
                    or 0.0
                )
                if reference_audio is not None
                else 0.0
            ),
        )

    def set_transcription_status(self, status: object) -> None:
        self.transcription_panel.set_status(status)

    def set_transcription_analysis_ui(
        self,
        busy: bool,
        progress: int | None = None,
        *,
        status: object | None = None,
        available: bool | None = None,
        unavailable_reason: object = "",
    ) -> None:
        if available is not None:
            self.transcription_panel.set_analysis_available(
                bool(available),
                unavailable_reason,
            )
        if status is not None:
            self.transcription_panel.set_status(status)
        self.transcription_panel.set_analysis_busy(busy, progress)
        self.draft_play_button.setEnabled(not bool(busy))

    def _load_reference_audio_from_editor(self) -> None:
        if self._warn_staging_blocks_analysis():
            return
        reference_audio = getattr(self.parent(), "reference_audio", None)
        if reference_audio is not None:
            reference_audio.choose_audio(self)

    def _unload_reference_audio_from_editor(self) -> None:
        if self._warn_staging_blocks_analysis():
            return
        reference_audio = getattr(self.parent(), "reference_audio", None)
        if reference_audio is not None:
            reference_audio.set_audio_path(None)

    def start_transcription_analysis(self) -> None:
        if self._warn_staging_blocks_analysis():
            return
        reference_audio = getattr(self.parent(), "reference_audio", None)
        audio_path = str(getattr(reference_audio, "audio_path", "") or "")
        if not audio_path:
            QMessageBox.warning(
                self,
                tr("无法开始扒谱"),
                tr("请先载入 MP3/WAV 参考音频"),
            )
            return
        if (
            self.track.is_percussion
            or int(self.track.bdo_instrument_id) == 0x0D
        ):
            QMessageBox.warning(
                self,
                tr("当前轨道不适合自动扒谱"),
                tr("Basic Pitch 不识别游戏鼓件映射；请在旋律乐器轨道中审阅候选"),
            )
            return
        retained_playhead = self.playhead_ms
        self.stop_draft()
        self.set_draft_playhead(retained_playhead)
        parent = self.parent()
        start_shared = getattr(
            parent,
            "_start_workspace_transcription_analysis",
            None,
        )
        if not callable(start_shared):
            QMessageBox.warning(
                self,
                tr("扒谱分析失败"),
                tr("主窗口扒谱会话不可用"),
            )
            return
        self.transcription_hint.setText(
            tr("正在使用主窗口扒谱会话分析；正式音符不会自动改变")
        )
        start_shared()

    def _transcription_annotation_projection(
        self,
        session,
        postprocess_report,
    ) -> tuple[
        dict[str, object],
        frozenset[str],
        frozenset[str],
    ]:
        """Return stable annotation/fragment projections for one evidence set."""

        session_annotations = session.annotations
        report_annotations = (
            tuple(postprocess_report.annotations)
            if postprocess_report is not None
            else ()
        )
        cached = self._transcription_annotation_projection_cache
        if (
            cached is not None
            and cached[0] is session
            and cached[1] is session_annotations
            and cached[2] is report_annotations
        ):
            return cached[3], cached[4], cached[5]

        annotation_by_id = {
            item.candidate_id: item
            for item in session_annotations
        }
        annotation_by_id.update(
            {
                item.candidate_id: item
                for item in report_annotations
            }
        )
        fragment_ids = frozenset(
            candidate_id
            for candidate_id, annotation in annotation_by_id.items()
            if {
                "review_fragment",
                "pitch_flicker",
            }.intersection(annotation.flags)
        )
        continuity_ids = frozenset(
            candidate_id
            for candidate_id, annotation in annotation_by_id.items()
            if "cleanup_candidate" in annotation.flags
        )
        self._transcription_annotation_projection_cache = (
            session,
            session_annotations,
            report_annotations,
            annotation_by_id,
            fragment_ids,
            continuity_ids,
        )
        return annotation_by_id, fragment_ids, continuity_ids

    def _transcription_display_projection(
        self,
        candidates: tuple[TranscriptionCandidate, ...],
        postprocess_report,
        *,
        show_suppressed: bool,
    ) -> tuple[
        tuple[TranscriptionCandidate, ...],
        frozenset[str],
    ]:
        """Return one identity-stable active/suppressed candidate projection."""

        suppressed_candidates = (
            tuple(postprocess_report.suppressed_candidates)
            if postprocess_report is not None and show_suppressed
            else ()
        )
        cached = self._transcription_display_projection_cache
        if (
            cached is not None
            and cached[0] is candidates
            and cached[1] is suppressed_candidates
            and cached[2] is bool(show_suppressed)
        ):
            return cached[3], cached[4]

        display_candidates = candidates + suppressed_candidates
        suppressed_ids = frozenset(
            candidate.candidate_id
            for candidate in suppressed_candidates
        )
        self._transcription_display_projection_cache = (
            candidates,
            suppressed_candidates,
            bool(show_suppressed),
            display_candidates,
            suppressed_ids,
        )
        return display_candidates, suppressed_ids

    def set_transcription_rhythm_alignment(
        self,
        alignment: RhythmAlignmentSidecar | None,
    ) -> None:
        """Bind a disposable timing view without replacing session candidates."""

        parent = self.parent()
        session = getattr(parent, "transcription_session", None)
        cache_key = str(
            getattr(getattr(session, "state", None), "cache_key", "") or ""
        )
        candidates = tuple(getattr(session, "candidates", ()))
        if alignment is not None and not alignment.is_current(
            evidence_cache_key=cache_key,
            candidates=candidates,
        ):
            alignment = None
        if self.transcription_rhythm_alignment == alignment:
            return
        self.transcription_rhythm_alignment = alignment
        self._transcription_display_projection_cache = None
        self._transcription_rhythm_candidate_cache = None
        self._transcription_candidate_flag_cache = None
        self._eligible_candidate_cache = None
        self._sync_shared_transcription_projection()

    def _transcription_rhythm_projection_changed(self, enabled: bool) -> None:
        self.transcription_rhythm_projection_enabled = bool(enabled)
        self._transcription_display_projection_cache = None
        self._transcription_rhythm_candidate_cache = None
        self._transcription_candidate_flag_cache = None
        self._sync_shared_transcription_projection()

    def _effective_transcription_candidate(
        self,
        candidate: TranscriptionCandidate,
    ) -> TranscriptionCandidate:
        alignment = self.transcription_rhythm_alignment
        if alignment is None or not self.transcription_rhythm_projection_enabled:
            return candidate
        projected = alignment.apply_to(candidate)
        return (
            projected
            if isinstance(projected, TranscriptionCandidate)
            else candidate
        )

    def _melody_guidance_notes(
        self,
        state: TranscriptionSessionState,
        offset_ms: float,
        candidates: tuple[TranscriptionCandidate, ...],
    ) -> tuple[Note, ...]:
        """Exclude notes materialized from candidates from weak guidance."""

        current_track_id = int(self.track.track_id)
        routed_ids = {
            str(route.candidate_id)
            for route in (
                *state.pending_routes,
                *state.applied_routes,
                *self.staged_primary_routes,
                *self.staged_copy_routes,
            )
            if int(route.track_id) == current_track_id
        }
        if not routed_ids:
            return tuple(self.canvas.notes)
        candidates_by_id = {
            str(getattr(candidate, "candidate_id", "")): candidate
            for candidate in candidates
            if str(getattr(candidate, "candidate_id", "")) in routed_ids
        }
        excluded: set[int] = set()
        for candidate_id in sorted(candidates_by_id):
            candidate = candidates_by_id[candidate_id]
            matches = [
                index
                for index, note in enumerate(self.canvas.notes)
                if index not in excluded
                and int(note.pitch) == int(candidate.pitch)
                and CANDIDATE_NOTE_POLICY.matches_note(
                    candidate, note, offset_ms
                )
            ]
            if not matches:
                continue
            project_start = CANDIDATE_NOTE_POLICY.project_start_ms(
                candidate, offset_ms
            )
            excluded.add(
                min(
                    matches,
                    key=lambda index: (
                        abs(
                            float(self.canvas.notes[index].start)
                            - project_start
                        ),
                        index,
                    ),
                )
            )
        return tuple(
            note
            for index, note in enumerate(self.canvas.notes)
            if index not in excluded
        )

    def _sync_shared_transcription_projection(self) -> None:
        parent = self.parent()
        session = getattr(parent, "transcription_session", None)
        if session is None:
            return
        offset_ms = float(getattr(parent, "reference_audio_offset_ms", 0.0))
        self.transcription_candidates = tuple(session.candidates)
        alignment = self.transcription_rhythm_alignment
        if alignment is None or not self.transcription_rhythm_projection_enabled:
            effective_candidates = self.transcription_candidates
        else:
            rhythm_cache_key = (
                id(self.transcription_candidates),
                alignment.identity,
            )
            rhythm_cache = self._transcription_rhythm_candidate_cache
            if rhythm_cache is not None and rhythm_cache[0] == rhythm_cache_key:
                effective_candidates = rhythm_cache[1]
            else:
                effective_candidates = tuple(
                    self._effective_transcription_candidate(candidate)
                    for candidate in self.transcription_candidates
                )
                self._transcription_rhythm_candidate_cache = (
                    rhythm_cache_key,
                    effective_candidates,
                )
        self.transcription_result = getattr(
            parent,
            "transcription_result",
            None,
        )
        postprocess_report = (
            self.transcription_result.postprocess_report
            if self.transcription_result is not None
            else None
        )
        (
            display_candidates,
            suppressed_ids,
        ) = self._transcription_display_projection(
            effective_candidates,
            postprocess_report,
            show_suppressed=(
                self.transcription_panel.show_suppressed_checkbox.isChecked()
            ),
        )
        _annotation_by_id, fragment_ids, continuity_ids = (
            self._transcription_annotation_projection(
                session,
                postprocess_report,
            )
        )
        state = session.state
        tolerance = CANDIDATE_NOTE_POLICY.onset_tolerance_ms
        flag_cache_key = (
            id(session),
            id(self.transcription_candidates),
            int(self.canvas._note_index_revision),
            round(offset_ms, 6),
            int(self.track.bdo_instrument_id),
            int(self.transpose),
            round(tolerance, 6),
            (
                ""
                if self.transcription_rhythm_alignment is None
                else self.transcription_rhythm_alignment.identity
            ),
            self.transcription_rhythm_projection_enabled,
        )
        cached_flags = getattr(
            self,
            "_transcription_candidate_flag_cache",
            None,
        )
        if (
            cached_flags is not None
            and cached_flags[0] == flag_cache_key
        ):
            invalid_ids = cached_flags[1]
            duplicate_ids = cached_flags[2]
        else:
            invalid_values: set[str] = set()
            duplicate_values: set[str] = set()
            notes_by_pitch: dict[
                int,
                tuple[list[float], list[Note]],
            ] = {}
            grouped_notes: dict[int, list[Note]] = defaultdict(list)
            for note in self.canvas.notes:
                grouped_notes[int(note.pitch)].append(note)
            for pitch, notes in grouped_notes.items():
                ordered = sorted(notes, key=lambda note: float(note.start))
                notes_by_pitch[pitch] = (
                    [float(note.start) for note in ordered],
                    ordered,
                )
            for candidate in effective_candidates:
                candidate_id = session.candidate_id(candidate)
                if self._candidate_invalid_for_current_track(candidate):
                    invalid_values.add(candidate_id)
                    continue
                starts, notes = notes_by_pitch.get(
                    int(candidate.pitch),
                    ([], []),
                )
                window_start, window_end = (
                    CANDIDATE_NOTE_POLICY.match_window(
                        candidate,
                        offset_ms,
                    )
                )
                first = bisect_left(starts, window_start)
                last = bisect_right(starts, window_end)
                if any(
                    CANDIDATE_NOTE_POLICY.matches_note(
                        candidate,
                        note,
                        offset_ms,
                    )
                    for note in notes[first:last]
                ):
                    duplicate_values.add(candidate_id)
            invalid_ids = frozenset(invalid_values)
            duplicate_ids = frozenset(duplicate_values)
            self._transcription_candidate_flag_cache = (
                flag_cache_key,
                invalid_ids,
                duplicate_ids,
            )

        staged_ids = {
            route.candidate_id
            for route in (*self.staged_primary_routes, *self.staged_copy_routes)
        }
        confidence_floor = self.transcription_panel.confidence_floor
        self.canvas.set_transcription_review(
            display_candidates,
            session.candidate_id,
            source_candidates=self.transcription_candidates,
            selected_ids=state.selected_candidate_ids,
            rejected_ids=state.rejected_candidate_ids,
            pending_routes=state.pending_routes,
            applied_routes=state.applied_routes,
            invalid_ids=invalid_ids,
            duplicate_ids=duplicate_ids,
            staged_ids=staged_ids,
            fragment_ids=fragment_ids,
            continuity_ids=continuity_ids,
            suppressed_ids=suppressed_ids,
            confidence_floor=confidence_floor,
            show_rejected_only=(
                self.transcription_panel.show_rejected_checkbox.isChecked()
            ),
            audio_offset_ms=offset_ms,
            visible=self.transcription_mode_enabled,
        )
        self.canvas.set_transcription_candidate_layer_visible(
            self.transcription_panel.candidate_layer_visible
        )
        self.canvas.set_transcription_candidate_opacity(
            self.transcription_panel.candidate_opacity
        )
        descriptor = (
            self.transcription_result.evidence_descriptor
            if self.transcription_result is not None
            else None
        )
        descriptor_key = str(getattr(descriptor, "cache_key", "") or "")
        if descriptor_key != getattr(self, "_canvas_evidence_cache_key", ""):
            self.canvas.set_evidence_descriptor(
                descriptor,
                audio_offset_ms=offset_ms,
            )
            self._canvas_evidence_cache_key = descriptor_key
        self._transcription_evidence_layers_changed(
            self.transcription_panel.visible_evidence_layers
        )

        reference_audio = getattr(parent, "reference_audio", None)
        has_audio = bool(
            reference_audio is not None and reference_audio.audio_path
        )
        self._bind_spectrogram_reference_audio(reference_audio)
        self._refresh_canvas_spectrogram()
        self.canvas.set_spectrogram_visible(
            self.transcription_panel.spectrogram_visible
        )
        self.canvas.set_melody_lines_visible(
            self.transcription_panel.melody_lines_visible
        )
        self.transcription_panel.set_melody_lines_available(
            self.canvas.melody_lines_available
        )
        self.transcription_panel.set_sensitivity(state.sensitivity)
        self.transcription_panel.set_analysis_mode(state.analysis_mode)
        self.transcription_panel.set_cleanup_profile(
            state.cleanup_profile
        )
        self.transcription_panel.set_range_available(state.region is not None)
        self.transcription_panel.set_staging_locked(
            self._has_transcription_staging()
        )
        available, reason = transcription_backend_quick_status()
        self.transcription_panel.set_analysis_available(available, reason)
        action_ids = set(self._eligible_transcription_candidate_ids())
        current_track_id = int(self.track.track_id)
        applied_elsewhere_ids = {
            route.candidate_id
            for route in state.applied_routes
            if int(route.track_id) != current_track_id
        }
        current_route_ids = {
            route.candidate_id
            for route in (*state.pending_routes, *state.applied_routes)
            if int(route.track_id) == current_track_id
        }
        include_current_copy = bool(
            action_ids.intersection(
                applied_elsewhere_ids.difference(current_route_ids)
            )
        )
        self.transcription_panel.set_copy_targets(
            getattr(parent, "tracks", ()),
            current_track_id=current_track_id,
            include_current=include_current_copy,
        )
        self.transcription_waveform.set_reference_audio(reference_audio)
        self.transcription_waveform.set_audio_offset_ms(offset_ms)
        self.transcription_waveform.set_time_range(state.region)
        self.transcription_waveform.set_playhead_ms(self.playhead_ms)
        harmony = getattr(parent, "harmony_analysis", None)
        instrument_analysis = getattr(
            parent, "instrument_match_analysis", None
        )
        reference_settings = normalize_reference_layer_settings(
            getattr(parent, "reference_layer_settings", None)
        )
        timbre_enabled = bool(
            reference_settings["timbre_grouping_enabled"]
        )
        reference_timbre_analysis = getattr(
            parent, "reference_timbre_analysis", None
        )
        reference_timbre_prediction = getattr(
            parent, "reference_timbre_prediction", None
        )
        if (
            timbre_enabled
            and reference_timbre_prediction is None
            and instrument_analysis is not None
            and self.transcription_candidates
        ):
            reference_timbre_prediction = build_reference_timbre_prediction(
                cache_key=str(
                    getattr(self.transcription_result, "cache_key", "") or ""
                ),
                candidates=self.transcription_candidates,
                voice_groups=tuple(instrument_analysis.groups),
            )
        display_timbre_analysis = (
            merge_reference_timbre_evidence(
                reference_timbre_analysis,
                reference_timbre_prediction,
            )
            if reference_timbre_analysis is not None
            else reference_timbre_prediction
        )
        groups = (
            tuple(display_timbre_analysis.groups)
            if timbre_enabled and display_timbre_analysis is not None
            else tuple(instrument_analysis.groups)
            if instrument_analysis is not None
            else ()
        )
        matches_by_group = (
            dict(instrument_analysis.matches)
            if instrument_analysis is not None
            else {}
        )
        parent_config = getattr(parent, "config", {})
        transcription_ui_config = (
            parent_config.get("transcription_ui", {})
            if isinstance(parent_config, dict)
            and isinstance(
                parent_config.get("transcription_ui", {}), dict
            )
            else {}
        )
        voice_group_colors = transcription_ui_config.get(
            "voice_group_colors", {}
        )
        if not isinstance(voice_group_colors, dict):
            voice_group_colors = {}
        guidance_enabled = bool(
            reference_settings["melody_guidance_enabled"]
        )
        target_instrument_id = int(self.track.bdo_instrument_id)
        target_instrument_label = _ui_bdo_instrument_name(
            target_instrument_id
        )
        route_revision = tuple(
            sorted(
                (
                    str(route.candidate_id),
                    int(route.track_id),
                )
                for route in (
                    *state.pending_routes,
                    *state.applied_routes,
                    *self.staged_primary_routes,
                    *self.staged_copy_routes,
                )
            )
        )
        guidance_cache_key = (
            id(effective_candidates),
            tuple(id(group) for group in groups),
            int(self.canvas._note_index_revision),
            route_revision,
            round(float(self.canvas.beat_ms), 6),
            round(offset_ms, 6),
            guidance_enabled,
            target_instrument_id,
            target_instrument_label,
        )
        guidance_cache = self._melody_guidance_cache
        if (
            guidance_cache is not None
            and guidance_cache[0] == guidance_cache_key
        ):
            guidance = guidance_cache[1]
        else:
            guidance = build_reference_melody_guidance(
                candidates=effective_candidates,
                groups=groups,
                notes=self._melody_guidance_notes(
                    state,
                    offset_ms,
                    effective_candidates,
                ),
                beat_ms=self.canvas.beat_ms,
                audio_offset_ms=offset_ms,
                enabled=guidance_enabled,
                target_instrument_id=target_instrument_id,
                target_instrument_label=target_instrument_label,
            )
            self._melody_guidance_cache = (
                guidance_cache_key,
                guidance,
            )
        self.canvas.set_transcription_assist_projection(
            voice_groups=groups,
            harmony_analysis=harmony,
            group_colors=voice_group_colors,
            melody_guidance=guidance,
        )
        self.transcription_panel.set_melody_guidance_analysis(guidance)
        self.transcription_panel.set_timbre_analysis(
            display_timbre_analysis if timbre_enabled else None,
            busy=bool(
                timbre_enabled
                and getattr(parent, "reference_timbre_analysis_busy", False)
            ),
            error=bool(
                timbre_enabled
                and getattr(parent, "reference_timbre_analysis_error", False)
            ),
        )
        assist_review = getattr(
            parent, "transcription_assist_review", None
        )
        confirmed_by_group = {
            str(item.group_id): int(item.confirmed_instrument_id)
            for item in (
                assist_review.active_voice_groups
                if assist_review is not None
                else ()
            )
            if item.confirmed_instrument_id is not None
        }
        key_review = (
            getattr(assist_review, "active_key_override", None)
            if assist_review is not None
            else None
        )
        harmony_panel_view = (
            {
                "global_key": harmony.global_key,
                "chord_segments": harmony.chord_segments,
                "conflicts": harmony.conflicts,
                "key_locked": bool(
                    key_review is not None and key_review.locked
                ),
            }
            if harmony is not None
            else None
        )
        self.transcription_panel.set_harmony_analysis(
            harmony_panel_view
        )
        active_group = (
            parent._active_voice_group()
            if instrument_analysis is not None
            and hasattr(parent, "_active_voice_group")
            else None
        )
        if active_group is not None:
            parent.active_voice_group_id = active_group.group_id
            matches = matches_by_group.get(active_group.group_id, ())
            match_views = []
            for match in matches:
                reasons = [
                    trfv(
                        "音域覆盖 {coverage}%",
                        coverage=round(match.pitch_coverage * 100),
                    ),
                    trfv(
                        "角色适配 {score}%",
                        score=round(match.role_score * 100),
                    ),
                ]
                warnings = []
                if match.pitch_coverage < 0.999:
                    warnings.append(
                        trfv(
                            "有 {percent}% 的候选超出该乐器可用音域",
                            percent=round(
                                (1.0 - match.pitch_coverage) * 100
                            ),
                        )
                    )
                if match.role_score < 0.50:
                    warnings.append(trv("该乐器与当前声部角色适配较弱"))
                if match.timbre_score is None:
                    warnings.append(trv("无本地音色证据"))
                    reasons.append(trv("按音域、角色和奏法排序"))
                else:
                    reasons.append(
                        trfv(
                            "本地音色相似 {score}%",
                            score=round(match.timbre_score * 100),
                        )
                    )
                match_views.append(
                    {
                        "instrument_id": match.instrument_id,
                        "instrument_name": trv(_ui_bdo_instrument_source(
                            match.instrument_id,
                        )),
                        "total_score": match.total_score,
                        "pitch_coverage": match.pitch_coverage,
                        "reasons": tuple(reasons),
                        "warnings": tuple(warnings),
                    }
                )
            self.transcription_panel.set_voice_group_matches(
                active_group,
                match_views,
                confirmed_instrument_id=confirmed_by_group.get(
                    active_group.group_id
                ),
            )
            group_index = next(
                (
                    index
                    for index, group in enumerate(groups)
                    if group.group_id == active_group.group_id
                ),
                -1,
            )
        else:
            self.transcription_panel.clear_voice_group_matches()
            group_index = -1
        low_harmony_count = (
            sum(
                segment.quality != "N"
                and float(segment.confidence) < 0.55
                for segment in harmony.chord_segments
            )
            + len(harmony.conflicts)
            if harmony is not None
            else 0
        )
        uncertain_instrument_count = (
            sum(
                (
                    group.group_id not in confirmed_by_group
                    or confirmed_by_group[group.group_id]
                    not in {
                        match.instrument_id
                        for match in matches_by_group.get(
                            group.group_id, ()
                        )
                    }
                )
                and (
                    not matches_by_group.get(group.group_id)
                    or matches_by_group[
                        group.group_id
                    ][0].timbre_score is None
                )
                for group in groups
            )
            if instrument_analysis is not None
            else 0
        )
        track_lookup = {
            int(track.track_id): track
            for track in getattr(parent, "tracks", ())
        }
        pending_problem_count = 0
        for route in state.pending_routes:
            candidate = session.candidate_for_id(route.candidate_id)
            target = track_lookup.get(int(route.track_id))
            if (
                candidate is None
                or target is None
                or parent._candidate_invalid_for_track(candidate, target)
            ):
                pending_problem_count += 1
        folded_duplicate_count = len(
            self.canvas._folded_candidate_primary
        )
        active_fragment_ids = {
            candidate_id
            for candidate_id in fragment_ids
            if session.candidate_for_id(candidate_id) is not None
        }
        review_count = (
            pending_problem_count
            + len(invalid_ids)
            + len(duplicate_ids)
            + folded_duplicate_count
            + len(active_fragment_ids)
            + low_harmony_count
            + uncertain_instrument_count
        )
        self.transcription_panel.set_phrase_state(
            index=group_index,
            total=len(groups),
            loop_enabled=bool(
                getattr(parent, "loop_current_voice_group", False)
            ),
            review_count=review_count,
        )
        self.transcription_panel.set_assist_available(
            harmony is not None or bool(groups)
        )
        self.transcription_panel.set_fragment_state(
            suspected_count=len(active_fragment_ids),
        )

        routable_ids = action_ids.difference(invalid_ids, duplicate_ids)
        applied_ids = {
            route.candidate_id for route in state.applied_routes
        }
        primary_ids = routable_ids.difference(applied_ids)
        copy_targets = [
            track
            for track in getattr(parent, "tracks", ())
            if (
                int(track.track_id) != current_track_id
                or include_current_copy
            )
            and not track.is_percussion
            and int(track.bdo_instrument_id) != 0x0D
        ]
        self.transcription_panel.set_action_state(
            write_enabled=bool(primary_ids)
            and not bool(
                getattr(parent, "transcription_analysis_busy", False)
            ),
            copy_enabled=bool(routable_ids and copy_targets)
            and not bool(
                getattr(parent, "transcription_analysis_busy", False)
            ),
            reject_enabled=bool(action_ids)
            and not bool(
                getattr(parent, "transcription_analysis_busy", False)
            ),
            rejected_count=len(state.rejected_candidate_ids),
            can_undo=bool(
                getattr(
                    parent,
                    "_can_undo_transcription_review",
                    lambda: session.commands.can_undo,
                )()
            ),
            can_redo=bool(
                getattr(
                    parent,
                    "_can_redo_transcription_review",
                    lambda: session.commands.can_redo,
                )()
            ),
            staging_count=len(
                set((*self.staged_primary_routes, *self.staged_copy_routes))
            ),
            candidate_count=(
                len(self.transcription_candidates)
                + len(
                    tuple(postprocess_report.suppressed_candidates)
                    if postprocess_report is not None
                    else ()
                )
            ),
            draft_note_count=len(self.canvas.notes),
        )
        if self.transcription_candidates:
            self.transcription_panel.set_status(
                trf(
                    "识别到 {count} 个参考音块 · 框选后采纳为草稿",
                    count=len(self.transcription_candidates),
                )
            )
        elif has_audio:
            self.transcription_panel.set_status(tr("尚未分析"))
            self.transcription_panel.set_fragment_state()
        else:
            self.transcription_panel.set_status(
                tr("载入音频，然后分析")
            )
            self.transcription_panel.set_fragment_state()
        self.update_scrollbars()

    def _eligible_transcription_candidate_ids(
        self, *, include_routed: bool = False
    ) -> tuple[str, ...]:
        parent = self.parent()
        session = getattr(parent, "transcription_session", None)
        if session is None:
            return ()
        state = session.state
        offset_ms = float(
            getattr(parent, "reference_audio_offset_ms", 0.0)
        )
        cache_key = (
            id(session),
            id(session.candidates),
            state.selected_candidate_ids,
            state.rejected_candidate_ids,
            state.region,
            () if include_routed else state.pending_routes,
            () if include_routed else state.applied_routes,
            round(offset_ms, 6),
            bool(include_routed),
        )
        cached = self._eligible_candidate_cache
        if cached is not None and cached[0] == cache_key:
            return cached[1]
        result = session.eligible_candidate_ids(
            reference_audio_offset_ms=offset_ms,
            include_routed=include_routed,
        )
        self._eligible_candidate_cache = (cache_key, result)
        return result

    def _cancel_transcription_analysis(self) -> None:
        worker = getattr(
            self.parent(),
            "workspace_transcription_worker",
            None,
        )
        if worker is None or not worker.isRunning():
            return
        cancel = getattr(worker, "cancel", None)
        if callable(cancel):
            cancel()
        self.transcription_panel.set_status(tr("正在取消…"))
        self.transcription_panel.set_analysis_busy(True)

    def _candidate_invalid_for_current_track(
        self,
        candidate: TranscriptionCandidate,
    ) -> bool:
        parent = self.parent()
        if not CANDIDATE_NOTE_POLICY.project_timing_is_valid(
            candidate,
            float(getattr(parent, "reference_audio_offset_ms", 0.0)),
        ):
            return True
        supported = game_supported_pitches(
            int(self.track.bdo_instrument_id),
            self.track.marnian_synth_mode,
        )
        return not CANDIDATE_NOTE_POLICY.pitch_is_valid_for_melodic_track(
            candidate.pitch,
            is_percussion=self.track.is_percussion,
            instrument_id=self.track.bdo_instrument_id,
            transpose=self.transpose,
            supported_pitches=supported,
        )

    def _append_transcription_candidates(
        self,
        candidate_ids: Iterable[str],
    ) -> tuple[int, int, int]:
        """Promote candidates through the same validation and undo boundary."""

        parent = self.parent()
        shared_session = getattr(parent, "transcription_session", None)
        if shared_session is None:
            return 0, 0, 0
        wanted_ids = {str(candidate_id) for candidate_id in candidate_ids}
        if not wanted_ids:
            return 0, 0, 0
        accepted: list[Note] = []
        accepted_routes: set[CandidateRoute] = set()
        invalid = 0
        duplicates = 0
        notes_by_pitch: dict[int, tuple[list[float], list[Note]]] = {}
        grouped_notes: dict[int, list[Note]] = defaultdict(list)
        for note in self.canvas.notes:
            grouped_notes[int(note.pitch)].append(note)
        for pitch, notes in grouped_notes.items():
            ordered = sorted(notes, key=lambda note: float(note.start))
            notes_by_pitch[pitch] = (
                [float(note.start) for note in ordered],
                ordered,
            )
        already_applied = {
            route.candidate_id
            for route in shared_session.state.applied_routes
        }
        offset_ms = float(getattr(parent, "reference_audio_offset_ms", 0.0))
        for raw_candidate in self.transcription_candidates:
            candidate_id = shared_session.candidate_id(raw_candidate)
            if candidate_id not in wanted_ids:
                continue
            if candidate_id in already_applied:
                continue
            candidate = self._effective_transcription_candidate(raw_candidate)
            if self._candidate_invalid_for_current_track(candidate):
                invalid += 1
                continue
            starts, indexed_notes = notes_by_pitch.setdefault(
                int(candidate.pitch),
                ([], []),
            )
            window_start, window_end = CANDIDATE_NOTE_POLICY.match_window(
                candidate,
                offset_ms,
            )
            first = bisect_left(starts, window_start)
            last = bisect_right(starts, window_end)
            if any(
                CANDIDATE_NOTE_POLICY.matches_note(
                    candidate,
                    note,
                    offset_ms,
                )
                for note in indexed_notes[first:last]
            ):
                duplicates += 1
                continue
            accepted_note = CANDIDATE_NOTE_POLICY.to_note(
                candidate,
                offset_ms,
            )
            accepted.append(accepted_note)
            insertion = bisect_right(starts, float(accepted_note.start))
            starts.insert(insertion, float(accepted_note.start))
            indexed_notes.insert(insertion, accepted_note)
            accepted_routes.add(
                CandidateRoute(candidate_id, int(self.track.track_id))
            )
        if not accepted:
            return 0, invalid, duplicates
        self.push_snapshot()
        first_index = len(self.canvas.notes)
        self.canvas.notes.extend(accepted)
        self.staged_primary_routes.update(accepted_routes)
        self._capture_staging_identity()
        self.canvas.selected = set(
            range(first_index, len(self.canvas.notes))
        )
        self.canvas.anchor_index = first_index
        self._notes_changed()
        self.refresh_fields()
        self._sync_shared_transcription_projection()
        return len(accepted), invalid, duplicates

    def promote_transcription_candidate(self, candidate_id: str) -> bool:
        """Create one editable note by double-clicking its visual candidate."""

        accepted, invalid, duplicates = self._append_transcription_candidates(
            (str(candidate_id),)
        )
        if accepted:
            self.transcription_panel.set_status(tr("已创建当前轨音符"))
            return True
        if invalid:
            self.transcription_panel.set_status(
                tr("候选音高不适用于当前轨道")
            )
        elif duplicates:
            self.transcription_panel.set_status(
                tr("当前位置已有相同音符")
            )
        return False

    def accept_transcription_candidates(self) -> None:
        if not self.transcription_candidates:
            return
        eligible_ids = set(self._eligible_transcription_candidate_ids())
        if not eligible_ids:
            self.transcription_hint.setText(
                tr("请先选择候选或设置 A–B 区间")
            )
            return
        accepted, invalid, duplicates = self._append_transcription_candidates(
            eligible_ids
        )
        if not accepted:
            self.transcription_hint.setText(trf(
                "没有可写入候选 · 重复 {duplicates} · 越界 {invalid}",
                duplicates=duplicates,
                invalid=invalid,
            ))
            return
        self.transcription_hint.setText(trf(
            "已写入草稿 {accepted} 个 · 跳过重复 {duplicates} · 越界 {invalid}",
            accepted=accepted,
            duplicates=duplicates,
            invalid=invalid,
        ))

    def show_game_adaptation_check(self) -> None:
        """Report game-fit facts without changing the current draft."""

        report = assess_game_draft(
            int(self.track.bdo_instrument_id),
            self.edited_notes(),
        )
        if not report.note_count:
            QMessageBox.information(
                self,
                tr("游戏适配检查"),
                tr("当前草稿没有音符。请先采纳参考音块或手动创建音符。"),
            )
            return
        pitch_evidence = (
            tr("已使用游戏音域证据")
            if report.pitch_evidence_known
            else tr("缺少已验证乐器音域，仅检查全局音高范围")
        )
        body = trf(
            "乐器：{instrument}\n"
            "草稿：{notes} 个音符\n"
            "发布分段：{chunks} 段（每段最多 {limit}，导出时自动拆分）\n"
            "音域问题：{pitch}\n"
            "奏法问题：{articulation}\n"
            "时间问题：{timing}\n"
            "力度问题：{velocity}\n"
            "证据：{evidence}\n\n"
            "此检查不会移动、删除、量化或改写任何音符。",
            instrument=_ui_bdo_instrument_name(
                int(self.track.bdo_instrument_id)
            ),
            notes=report.note_count,
            chunks=report.track_chunk_count,
            limit=report.track_chunk_limit,
            pitch=len(report.invalid_pitch_indices),
            articulation=len(report.unsupported_articulation_indices),
            timing=len(report.invalid_timing_indices),
            velocity=len(report.invalid_velocity_indices),
            evidence=pitch_evidence,
        )
        if report.ready and report.pitch_evidence_known:
            QMessageBox.information(
                self,
                tr("游戏适配检查通过"),
                body,
            )
        elif report.ready:
            QMessageBox.information(
                self,
                tr("游戏适配基础检查完成"),
                body,
            )
        else:
            QMessageBox.warning(
                self,
                tr("游戏适配发现需要处理的问题"),
                body,
            )

    def continue_creation_from_transcription(self) -> None:
        """Keep the draft and leave the reference-review presentation."""

        if not self.canvas.notes:
            return
        self.transcription_mode_toggle.setChecked(False)
        self.status.setText(
            tr("音乐参考已收起；草稿保持可编辑，点击“完成”后写回项目。")
        )
        self.canvas.setFocus(Qt.FocusReason.OtherFocusReason)

    def _stage_transcription_copy(
        self,
        track_id: int,
        candidate_ids_override: Iterable[str] | None = None,
    ) -> None:
        parent = self.parent()
        session = getattr(parent, "transcription_session", None)
        if session is None:
            return
        target = next(
            (
                track
                for track in getattr(parent, "tracks", ())
                if int(track.track_id) == int(track_id)
            ),
            None,
        )
        if (
            target is None
            or target.is_percussion
            or int(target.bdo_instrument_id) == 0x0D
        ):
            self.transcription_panel.set_status(tr("目标轨道不可用"))
            return
        candidate_ids = (
            {
                str(candidate_id)
                for candidate_id in candidate_ids_override
            }
            if candidate_ids_override is not None
            else set(
                self._eligible_transcription_candidate_ids(
                    include_routed=True
                )
            )
        )
        # Voice-group/Top-3 actions pass an explicit candidate override and
        # therefore do not travel through the selected/A-B eligibility helper.
        # Keep rejection as an independent hard gate at the staging boundary.
        candidate_ids.difference_update(
            session.state.rejected_candidate_ids
        )
        if not candidate_ids:
            self.transcription_panel.set_status(
                tr("请先选择候选或设置 A–B 区间")
            )
            return
        supported = game_supported_pitches(
            int(target.bdo_instrument_id), target.marnian_synth_mode
        )
        routes: set[CandidateRoute] = set()
        candidates_by_id: dict[str, TranscriptionCandidate] = {}
        already_routed = set(
            (*session.state.pending_routes, *session.state.applied_routes)
        )
        for candidate_id in session.order_candidate_ids(candidate_ids):
            candidate = session.candidate_for_id(candidate_id)
            if candidate is None:
                continue
            invalid = (
                not CANDIDATE_NOTE_POLICY.project_timing_is_valid(
                    candidate,
                    float(
                        getattr(
                            parent,
                            "reference_audio_offset_ms",
                            0.0,
                        )
                    ),
                )
                or not CANDIDATE_NOTE_POLICY.pitch_is_valid_for_melodic_track(
                    candidate.pitch,
                    is_percussion=track_uses_percussion_pitch_semantics(target),
                    instrument_id=target.bdo_instrument_id,
                    transpose=self.pitch_transform_plan.effective_track_semitones(
                        target
                    ),
                    supported_pitches=supported,
                )
            )
            if not invalid:
                route = CandidateRoute(candidate_id, int(track_id))
                if route not in already_routed:
                    routes.add(route)
                    candidates_by_id[candidate_id] = candidate
        routes.difference_update(self.staged_copy_routes)
        if not routes:
            self.transcription_panel.set_status(tr("没有可复制的候选"))
            return
        self.push_snapshot()
        first = len(self.canvas.notes)
        if int(track_id) == int(self.track.track_id):
            offset_ms = float(
                getattr(parent, "reference_audio_offset_ms", 0.0)
            )
            additions: list[Note] = []
            notes_by_pitch: dict[
                int,
                tuple[list[float], list[Note]],
            ] = {}
            grouped_notes: dict[int, list[Note]] = defaultdict(list)
            for note in self.canvas.notes:
                grouped_notes[int(note.pitch)].append(note)
            for pitch, notes in grouped_notes.items():
                ordered = sorted(
                    notes,
                    key=lambda note: float(note.start),
                )
                notes_by_pitch[pitch] = (
                    [float(note.start) for note in ordered],
                    ordered,
                )
            for route in sorted(routes):
                candidate = candidates_by_id[route.candidate_id]
                starts, indexed_notes = notes_by_pitch.setdefault(
                    int(candidate.pitch),
                    ([], []),
                )
                window_start, window_end = (
                    CANDIDATE_NOTE_POLICY.match_window(
                        candidate,
                        offset_ms,
                    )
                )
                first = bisect_left(starts, window_start)
                last = bisect_right(starts, window_end)
                if any(
                    CANDIDATE_NOTE_POLICY.matches_note(
                        candidate,
                        note,
                        offset_ms,
                    )
                    for note in indexed_notes[first:last]
                ):
                    continue
                addition = CANDIDATE_NOTE_POLICY.to_note(
                    candidate,
                    offset_ms,
                )
                additions.append(addition)
                insertion = bisect_right(
                    starts,
                    float(addition.start),
                )
                starts.insert(insertion, float(addition.start))
                indexed_notes.insert(insertion, addition)
            self.canvas.notes.extend(additions)
        self.staged_copy_routes.update(routes)
        self._capture_staging_identity()
        if len(self.canvas.notes) > first:
            self.canvas.selected = set(range(first, len(self.canvas.notes)))
            self.canvas.anchor_index = first
            self._notes_changed()
        self.transcription_panel.set_status(
            trf("已暂存 {count} 个候选", count=len(routes))
        )
        self._sync_shared_transcription_projection()

    def _voice_group_candidate_ids(
        self, group_id: str
    ) -> tuple[str, ...]:
        analysis = getattr(
            self.parent(), "instrument_match_analysis", None
        )
        if analysis is None:
            return ()
        group = next(
            (
                item
                for item in analysis.groups
                if item.group_id == str(group_id)
            ),
            None,
        )
        return () if group is None else tuple(group.candidate_ids)

    def _stage_voice_group_routes(
        self, group_id: str, track_id: int
    ) -> None:
        candidate_ids = self._voice_group_candidate_ids(group_id)
        if not candidate_ids:
            self.transcription_panel.set_status(tr("声部已失效"))
            return
        self._stage_transcription_copy(
            int(track_id),
            candidate_ids_override=candidate_ids,
        )

    def _stage_new_voice_group_track(
        self, group_id: str, instrument_id: int
    ) -> None:
        parent = self.parent()
        session = getattr(parent, "transcription_session", None)
        candidate_ids = set(self._voice_group_candidate_ids(group_id))
        if session is None or not candidate_ids:
            self.transcription_panel.set_status(tr("声部已失效"))
            return
        candidate_ids.difference_update(
            session.state.rejected_candidate_ids
        )
        if not candidate_ids:
            self.transcription_panel.set_status(tr("没有可复制的候选"))
            return
        if (
            int(instrument_id) not in BDO_INSTRUMENT_NAMES
            or int(instrument_id) in {0x04, 0x05, 0x0D}
        ):
            self.transcription_panel.set_status(tr("目标轨道不可用"))
            return
        reserved_ids = {
            int(track.track_id) for track in getattr(parent, "tracks", ())
        }.union(
            int(route.track_id)
            for route in (
                *session.state.pending_routes,
                *session.state.applied_routes,
                *self.staged_primary_routes,
                *self.staged_copy_routes,
            )
        ).union(self.staged_new_track_specs)
        new_track_id = max(reserved_ids, default=-1) + 1
        supported = game_supported_pitches(int(instrument_id))
        routes: set[CandidateRoute] = set()
        for candidate_id in session.order_candidate_ids(candidate_ids):
            candidate = session.candidate_for_id(candidate_id)
            if candidate is None:
                continue
            if (
                CANDIDATE_NOTE_POLICY.project_timing_is_valid(
                    candidate,
                    float(
                        getattr(
                            parent,
                            "reference_audio_offset_ms",
                            0.0,
                        )
                    ),
                )
                and CANDIDATE_NOTE_POLICY.pitch_is_valid_for_melodic_track(
                    candidate.pitch,
                    is_percussion=False,
                    instrument_id=int(instrument_id),
                    transpose=self.pitch_transform_plan.effective_semitones(
                        new_track_id
                    ),
                    supported_pitches=supported,
                )
            ):
                routes.add(CandidateRoute(candidate_id, new_track_id))
        if not routes:
            self.transcription_panel.set_status(
                tr("该乐器音域内没有可暂存候选")
            )
            return
        self.push_snapshot()
        self.staged_new_track_specs[new_track_id] = int(instrument_id)
        self.staged_copy_routes.update(routes)
        self._capture_staging_identity()
        self.transcription_panel.set_status(
            trf(
                "已暂存新轨 · {instrument} · {count} 个候选",
                instrument=trv(_ui_bdo_instrument_source(int(instrument_id))),
                count=len(routes),
            )
        )
        self._sync_shared_transcription_projection()

    def _clear_transcription_staging(self) -> None:
        if not self._has_transcription_staging():
            return
        self.push_snapshot()
        self.staged_primary_routes.clear()
        self.staged_copy_routes.clear()
        self.staged_new_track_specs.clear()
        self._clear_staging_identity_if_empty()
        self.transcription_panel.set_status(
            tr("已清除本次暂存；草稿音符保留为手工编辑")
        )
        self._sync_shared_transcription_projection()

    def _transcription_selection_changed(self, candidate_ids) -> None:
        parent = self.parent()
        session = getattr(parent, "transcription_session", None)
        if session is None:
            return
        session.set_selection(candidate_ids)
        activate = getattr(
            parent, "_activate_voice_group_for_candidates", None
        )
        if callable(activate):
            activate(candidate_ids)
        autosave = getattr(parent, "_autosave_project", None)
        if callable(autosave):
            autosave("transcription selection")
        self._sync_shared_transcription_projection()

    def _transcription_range_changed(self, value) -> None:
        parent = self.parent()
        setter = getattr(parent, "_set_transcription_region", None)
        if callable(setter):
            setter(value)
        self._sync_shared_transcription_projection()

    def _clear_transcription_range(self) -> None:
        self._transcription_range_changed(None)

    def _update_reference_layer_settings(self, **updates: object) -> None:
        parent = self.parent()
        if parent is None:
            return
        previous = normalize_reference_layer_settings(
            getattr(parent, "reference_layer_settings", None)
        )
        merged = dict(previous)
        merged.update(updates)
        normalized = normalize_reference_layer_settings(merged)
        if normalized == previous:
            return
        parent.reference_layer_settings = normalized
        autosave = getattr(parent, "_autosave_project", None)
        if callable(autosave) and not bool(
            getattr(parent, "loading_project", False)
        ):
            autosave("reference layers")

    def _transcription_evidence_layers_changed(self, layers) -> None:
        visible = {str(layer) for layer in layers}
        self.canvas.set_evidence_layers(
            frame="frame" in visible,
            onset="onset" in visible,
            contour="contour" in visible,
        )
        self._update_reference_layer_settings(
            frame_visible="frame" in visible,
            onset_visible="onset" in visible,
            contour_visible="contour" in visible,
        )
        parent = self.parent()
        parent_config = getattr(parent, "config", None)
        if isinstance(parent_config, dict):
            ui_config = parent_config.setdefault("transcription_ui", {})
            if isinstance(ui_config, dict):
                ui_config["diagnostic_evidence_layers"] = sorted(visible)
                self._persist_parent_config()

    def _transcription_spectrogram_visibility_changed(
        self,
        visible: bool,
    ) -> None:
        self.canvas.set_spectrogram_visible(bool(visible))
        self._update_reference_layer_settings(
            spectrogram_visible=bool(visible)
        )

    def _transcription_melody_lines_visibility_changed(
        self,
        visible: bool,
    ) -> None:
        self.canvas.set_melody_lines_visible(bool(visible))
        self._update_reference_layer_settings(
            melody_lines_visible=bool(visible)
        )

    def _transcription_reference_background_opacity_changed(
        self,
        opacity: float,
    ) -> None:
        normalized = max(0.0, min(1.0, float(opacity)))
        self.canvas.set_reference_background_opacity(normalized)
        self._update_reference_layer_settings(
            background_opacity_percent=round(normalized * 100.0)
        )

    def _transcription_contour_opacity_changed(self, opacity: float) -> None:
        normalized = max(0.0, min(1.0, float(opacity)))
        self.canvas.set_contour_opacity(normalized)
        self._update_reference_layer_settings(
            contour_opacity_percent=round(normalized * 100.0)
        )

    def _transcription_melody_guidance_changed(self, enabled: bool) -> None:
        self._update_reference_layer_settings(
            melody_guidance_enabled=bool(enabled)
        )
        self._sync_shared_transcription_projection()

    def _transcription_candidate_visibility_changed(
        self,
        visible: bool,
    ) -> None:
        if hasattr(self, "canvas"):
            self.canvas.set_transcription_candidate_layer_visible(
                bool(visible)
            )
        self._update_reference_layer_settings(
            candidate_visible=bool(visible)
        )

    def _transcription_candidate_opacity_changed(
        self,
        opacity: float,
    ) -> None:
        normalized = max(0.0, min(1.0, float(opacity)))
        if hasattr(self, "canvas"):
            self.canvas.set_transcription_candidate_opacity(normalized)
        self._update_reference_layer_settings(
            candidate_opacity_percent=round(normalized * 100.0)
        )

    def _transcription_timbre_grouping_changed(self, enabled: bool) -> None:
        normalized = bool(enabled)
        self._update_reference_layer_settings(
            timbre_grouping_enabled=normalized
        )
        parent = self.parent()
        setter = getattr(
            parent,
            "_set_reference_timbre_grouping_enabled",
            None,
        )
        if callable(setter):
            setter(normalized)
        self._sync_shared_transcription_projection()

    def _transcription_external_instrument_labels_changed(
        self,
        enabled: bool,
    ) -> None:
        normalized = bool(enabled)
        self._update_reference_layer_settings(
            external_instrument_labels_enabled=normalized
        )
        parent = self.parent()
        setter = getattr(
            parent,
            "_set_reference_instrument_labels_enabled",
            None,
        )
        if callable(setter):
            setter(normalized)

    def _transcription_contour_denoise_changed(self, value: str) -> None:
        normalized = (
            str(value)
            if str(value) in {"low", "standard", "high"}
            else "standard"
        )
        if hasattr(self, "canvas"):
            self.canvas.set_contour_denoise_profile(normalized)
        self._update_reference_layer_settings(
            contour_denoise=normalized
        )

    def _transcription_melody_line_roles_changed(
        self,
        roles: object,
    ) -> None:
        normalized = (
            frozenset(str(role) for role in roles)
            if isinstance(roles, (set, frozenset, list, tuple))
            else frozenset()
        )
        self.canvas.set_melody_line_roles_visible(normalized)
        parent = self.parent()
        parent_config = getattr(parent, "config", None)
        if not isinstance(parent_config, dict):
            return
        ui_config = parent_config.setdefault("transcription_ui", {})
        if isinstance(ui_config, dict):
            ui_config["melody_line_roles"] = sorted(
                self.canvas.melody_line_roles_visible
            )
            self._persist_parent_config()

    @staticmethod
    def _pitch_class_label(root_pc: int | None) -> str:
        if root_pc is None:
            return "N"
        return (
            "C",
            "C♯",
            "D",
            "D♯",
            "E",
            "F",
            "F♯",
            "G",
            "G♯",
            "A",
            "A♯",
            "B",
        )[int(root_pc) % 12]

    def _edit_transcription_key(self, _current: object) -> None:
        parent = self.parent()
        harmony = getattr(parent, "harmony_analysis", None)
        if harmony is None:
            return
        options: list[tuple[str, int, str]] = []
        candidates = (
            harmony.global_key,
            *tuple(harmony.global_key.alternatives),
        )
        seen: set[tuple[int, str]] = set()
        for item in candidates:
            if item.root_pc is None or item.mode is None:
                continue
            identity = (int(item.root_pc), str(item.mode))
            if identity in seen:
                continue
            seen.add(identity)
            options.append(
                (
                    f"{self._pitch_class_label(identity[0])} {identity[1]}",
                    identity[0],
                    identity[1],
                )
            )
        for mode in ("major", "minor"):
            for root_pc in range(12):
                identity = (root_pc, mode)
                if identity not in seen:
                    options.append(
                        (
                            f"{self._pitch_class_label(root_pc)} {mode}",
                            root_pc,
                            mode,
                        )
                    )
        selected, accepted = QInputDialog.getItem(
            self,
            tr("编辑主调"),
            tr("选择或输入主调："),
            [item[0] for item in options],
            0,
            True,
        )
        if not accepted:
            return
        normalized = str(selected).strip().replace("#", "♯")
        match = next(
            (item for item in options if item[0] == normalized),
            None,
        )
        if match is None:
            parts = normalized.split()
            roots = {
                self._pitch_class_label(root_pc).casefold(): root_pc
                for root_pc in range(12)
            }
            if len(parts) != 2 or parts[0].casefold() not in roots:
                QMessageBox.warning(
                    self,
                    tr("无法识别主调"),
                    tr("请输入例如 C major 或 A minor。"),
                )
                return
            mode = parts[1].casefold()
            if mode not in {"major", "minor"}:
                QMessageBox.warning(
                    self,
                    tr("无法识别主调"),
                    tr("仅支持 major 或 minor。"),
                )
                return
            match = (normalized, roots[parts[0].casefold()], mode)
        parent._set_assist_key_override(
            match[1],
            match[2],
            manual=True,
            locked=self.transcription_panel.assist_panel.harmony_summary.key_lock_checkbox.isChecked(),
        )

    def _lock_transcription_key(self, locked: bool) -> None:
        parent = self.parent()
        harmony = getattr(parent, "harmony_analysis", None)
        if harmony is None or harmony.global_key.root_pc is None:
            return
        current_review = parent.transcription_assist_review.key_override
        if not locked and (
            current_review is None or not current_review.manual
        ):
            parent._clear_assist_key_override()
            return
        parent._set_assist_key_override(
            harmony.global_key.root_pc,
            harmony.global_key.mode,
            manual=bool(
                current_review is not None and current_review.manual
            ),
            locked=bool(locked),
        )

    def _harmony_segment(self, segment_id: str) -> ChordSegment | None:
        harmony = getattr(self.parent(), "harmony_analysis", None)
        if harmony is None:
            return None
        return next(
            (
                segment
                for segment in harmony.chord_segments
                if segment.segment_id == str(segment_id)
            ),
            None,
        )

    def _review_for_harmony_segment(
        self, segment: ChordSegment
    ) -> LockedChordReview | None:
        return next(
            (
                item
                for item in self.parent().transcription_assist_review.locked_chord_segments
                if item.segment_id == segment.segment_id
                or (
                    math.isclose(
                        item.start_audio_ms,
                        segment.start_audio_ms,
                        abs_tol=0.5,
                    )
                    and math.isclose(
                        item.end_audio_ms,
                        segment.end_audio_ms,
                        abs_tol=0.5,
                    )
                )
            ),
            None,
        )

    def _transcription_chord_segment_clicked(
        self, segment_id: str
    ) -> None:
        self.transcription_panel.set_assist_expanded(True)
        self.transcription_panel.assist_panel.harmony_summary.set_current_segment(
            segment_id
        )

    def _split_transcription_voice_group(
        self, group_id: str, project_ms: float
    ) -> None:
        callback = getattr(
            self.parent(), "_split_transcription_voice_group", None
        )
        if callable(callback):
            callback(str(group_id), float(project_ms))

    def _merge_transcription_voice_groups(
        self, first_group_id: str, second_group_id: str
    ) -> None:
        callback = getattr(
            self.parent(), "_merge_transcription_voice_groups", None
        )
        if callable(callback):
            callback(str(first_group_id), str(second_group_id))

    def _set_transcription_voice_group_color(
        self, group_id: str, color: str
    ) -> None:
        callback = getattr(
            self.parent(), "_set_transcription_voice_group_color", None
        )
        if callable(callback):
            callback(str(group_id), str(color))

    def _set_transcription_voice_group_role(
        self, group_id: str, role: str
    ) -> None:
        callback = getattr(
            self.parent(), "_set_transcription_voice_group_role", None
        )
        if callable(callback):
            callback(str(group_id), str(role))

    def _edit_transcription_chord(self, segment_id: str) -> None:
        segment = self._harmony_segment(segment_id)
        if segment is None:
            return
        qualities = (
            "major",
            "minor",
            "dim",
            "sus2",
            "sus4",
            "maj7",
            "7",
            "min7",
            "half_diminished7",
        )
        options = ["N"] + [
            f"{self._pitch_class_label(root_pc)} {quality}"
            for root_pc in range(12)
            for quality in qualities
        ]
        current = (
            "N"
            if segment.quality == "N" or segment.root_pc is None
            else (
                f"{self._pitch_class_label(segment.root_pc)} "
                f"{segment.quality}"
            )
        )
        selected, accepted = QInputDialog.getItem(
            self,
            tr("编辑和弦段"),
            tr("选择和弦；不会自动改动音符："),
            options,
            max(0, options.index(current) if current in options else 0),
            False,
        )
        if not accepted:
            return
        if selected == "N":
            root_pc, quality, bass_pc = None, "N", None
        else:
            root_label, quality = str(selected).split(" ", 1)
            root_pc = next(
                index
                for index in range(12)
                if self._pitch_class_label(index) == root_label
            )
            bass_labels = [
                self._pitch_class_label(index) for index in range(12)
            ]
            bass_label, bass_ok = QInputDialog.getItem(
                self,
                tr("选择低音"),
                tr("选择转位低音："),
                bass_labels,
                root_pc,
                False,
            )
            if not bass_ok:
                return
            bass_pc = bass_labels.index(str(bass_label))
        self.parent()._set_assist_chord_review(
            segment,
            root_pc=root_pc,
            quality=quality,
            bass_pc=bass_pc,
            manual=True,
            locked=self.transcription_panel.assist_panel.harmony_summary.chord_lock_checkbox.isChecked(),
        )

    def _lock_transcription_chord(
        self, segment_id: str, locked: bool
    ) -> None:
        segment = self._harmony_segment(segment_id)
        if segment is None:
            return
        current_review = self._review_for_harmony_segment(segment)
        if not locked and (
            current_review is None or not current_review.manual
        ):
            self.parent()._remove_assist_chord_review(segment.segment_id)
            return
        self.parent()._set_assist_chord_review(
            segment,
            manual=bool(
                current_review is not None and current_review.manual
            ),
            locked=bool(locked),
        )

    def _split_transcription_chord(self, segment_id: str) -> None:
        segment = self._harmony_segment(segment_id)
        if segment is None:
            return
        callback = getattr(
            self.parent(), "_split_transcription_chord_segment", None
        )
        if callable(callback):
            callback(segment.segment_id, float(self.playhead_ms))

    def _merge_transcription_chord_with_next(
        self, segment_id: str
    ) -> None:
        harmony = getattr(self.parent(), "harmony_analysis", None)
        if harmony is None:
            return
        segments = tuple(harmony.chord_segments)
        index = next(
            (
                index
                for index, segment in enumerate(segments)
                if segment.segment_id == str(segment_id)
            ),
            -1,
        )
        if index < 0 or index + 1 >= len(segments):
            return
        first = segments[index]
        second = segments[index + 1]

        def label(segment: ChordSegment) -> str:
            if segment.root_pc is None or segment.quality == "N":
                return "N"
            return (
                f"{self._pitch_class_label(segment.root_pc)} "
                f"{segment.quality}"
            )

        options = (
            trf("保留当前段 · {chord}", chord=label(first)),
            trf("保留下一段 · {chord}", chord=label(second)),
        )
        selected, accepted = QInputDialog.getItem(
            self,
            tr("合并和弦段"),
            tr("选择合并后保留的和弦；不会自动改动音符："),
            options,
            0,
            False,
        )
        if not accepted:
            return
        retained = first if str(selected) == options[0] else second
        callback = getattr(
            self.parent(), "_merge_transcription_chord_segments", None
        )
        if callable(callback):
            callback(
                first.segment_id,
                second.segment_id,
                retained.segment_id,
            )

    def _navigate_transcription_phrase(self, direction: int) -> None:
        callback = getattr(self.parent(), "_navigate_voice_group", None)
        if callable(callback):
            callback(int(direction))

    def _loop_transcription_phrase(self, enabled: bool) -> None:
        callback = getattr(self.parent(), "_set_voice_group_loop", None)
        if callable(callback):
            callback(bool(enabled))

    def _open_transcription_review_queue(self) -> None:
        callback = getattr(
            self.parent(), "_open_transcription_review_queue", None
        )
        if callable(callback):
            callback()

    def _confirm_transcription_instrument_match(
        self, group_id: object, instrument_id: int
    ) -> None:
        callback = getattr(
            self.parent(), "_confirm_assist_instrument_match", None
        )
        if callable(callback):
            callback(str(group_id), int(instrument_id))

    def _stage_transcription_group_to_existing_track(
        self, group_id: object, instrument_id: int
    ) -> None:
        tracks = [
            track
            for track in getattr(self.parent(), "tracks", ())
            if not track.is_percussion
            and int(track.bdo_instrument_id) == int(instrument_id)
        ]
        if not tracks:
            QMessageBox.information(
                self,
                tr("没有匹配的现有轨"),
                tr("请使用“新建该乐器轨”，或先在主时间轴新建对应乐器。"),
            )
            return
        labels = [
            trf(
                "{track} · {instrument}",
                track=track.display_name,
                instrument=trv(_ui_bdo_instrument_source(track.bdo_instrument_id)),
            )
            for track in tracks
        ]
        label, accepted = QInputDialog.getItem(
            self,
            tr("暂存到现有轨"),
            tr("选择目标轨；Apply 前不会修改工程："),
            labels,
            0,
            False,
        )
        if not accepted:
            return
        target = tracks[labels.index(str(label))]
        self._stage_voice_group_routes(
            str(group_id),
            int(target.track_id),
        )

    def _stage_transcription_group_to_new_track(
        self, group_id: object, instrument_id: int
    ) -> None:
        QMessageBox.information(
            self,
            tr("新建乐器轨"),
            tr("该声部会在 Apply 时与音符一起原子新建轨道。"),
        )
        self._stage_new_voice_group_track(
            str(group_id),
            int(instrument_id),
        )

    def _set_transcription_audition_source(self, source: str) -> None:
        previous_state = self.draft_playback_state
        retained_playhead = float(self.playhead_ms)
        self.transcription_audition_source = str(source)
        if previous_state in {"playing", "paused", "loading"}:
            self.stop_draft()
            self.set_draft_playhead(retained_playhead, follow=True)
            if previous_state in {"playing", "loading"}:
                QTimer.singleShot(0, self.play_draft)
        labels = {
            "combined": "工程 + 原音",
            "original": "原音",
            "candidate_a": "游戏候选 A",
            "candidate_b": "游戏候选 B",
        }
        source_key = labels.get(str(source))
        self.transcription_panel.set_status(
            trf(
                "试听源：{source}；继续使用上方唯一播放控制。",
                source=(trv(source_key) if source_key is not None else str(source)),
            )
        )

    def _redecode_transcription_range(self) -> None:
        if self._warn_staging_blocks_analysis():
            return
        callback = getattr(
            self.parent(), "_redecode_transcription_range", None
        )
        if callable(callback):
            callback()

    def _transcription_sensitivity_changed(self, sensitivity: str) -> None:
        callback = getattr(
            self.parent(), "_transcription_sensitivity_changed", None
        )
        if callable(callback):
            callback(sensitivity)

    def _transcription_cleanup_profile_changed(
        self,
        cleanup_profile: str,
    ) -> None:
        callback = getattr(
            self.parent(),
            "_transcription_cleanup_profile_changed",
            None,
        )
        if callable(callback):
            callback(cleanup_profile)

    def _start_transcription_rhythm_diagnostic(self) -> None:
        callback = getattr(
            self.parent(),
            "_start_transcription_rhythm_diagnostic",
            None,
        )
        if callable(callback):
            callback()

    def _transcription_analysis_mode_changed(
        self, analysis_mode: str,
    ) -> None:
        if self._warn_staging_blocks_analysis():
            self.transcription_panel.set_analysis_mode(
                self.transcription_session.state.analysis_mode
            )
            return
        callback = getattr(
            self.parent(), "_transcription_analysis_mode_changed", None
        )
        if callable(callback):
            callback(analysis_mode)

    def _reject_transcription_candidates(self) -> None:
        callback = getattr(
            self.parent(), "_reject_transcription_candidates", None
        )
        if callable(callback):
            callback()

    def _restore_transcription_candidates(self) -> None:
        callback = getattr(
            self.parent(), "_restore_transcription_candidates", None
        )
        if callable(callback):
            callback()

    def _select_suspected_transcription_fragments(self) -> None:
        callback = getattr(
            self.parent(),
            "_select_suspected_transcription_fragments",
            None,
        )
        if callable(callback):
            callback()

    def _undo_transcription_review(self) -> None:
        callback = getattr(self.parent(), "_undo_transcription_review", None)
        if callable(callback):
            callback()

    def _redo_transcription_review(self) -> None:
        callback = getattr(self.parent(), "_redo_transcription_review", None)
        if callable(callback):
            callback()

    def _align_reference_audio_to_playhead(self) -> None:
        if self._warn_staging_blocks_analysis():
            return
        parent = self.parent()
        reference_audio = getattr(parent, "reference_audio", None)
        if reference_audio is None or not reference_audio.audio_path:
            self.transcription_panel.set_status(tr("请先载入参考音频。"))
            return
        audio_position = float(reference_audio.player.position())
        parent._set_reference_alignment(
            float(self.playhead_ms) - audio_position,
            float(getattr(parent, "beat_origin_ms", 0.0)),
            autosave=True,
        )
        self.beat_origin_ms = float(getattr(parent, "beat_origin_ms", 0.0))
        self._sync_shared_transcription_projection()

    def _set_playhead_as_beat_origin(self) -> None:
        parent = self.parent()
        parent._set_reference_alignment(
            float(getattr(parent, "reference_audio_offset_ms", 0.0)),
            float(self.playhead_ms),
            autosave=True,
        )
        self.beat_origin_ms = float(self.playhead_ms)
        self.canvas.update()
        self.transcription_panel.set_status(
            tr("第一拍锚点已更新；正式音符位置未移动。")
        )

    def _toggle_ghost_notes(self, enabled: bool) -> None:
        self.ghost_opacity_caption.setEnabled(bool(enabled))
        self.ghost_opacity_slider.setEnabled(bool(enabled))
        self.ghost_opacity_label.setEnabled(bool(enabled))
        self._update_reference_layer_settings(
            ghost_visible=bool(enabled)
        )
        parent = self.parent()
        if not enabled or not parent or not hasattr(parent, "tracks"):
            if hasattr(self, "canvas"):
                self.canvas.set_ghost_notes([])
            return
        notes = [
            GhostNoteProjection(
                note=note,
                track_id=int(item.track_id),
                instrument_id=int(item.bdo_instrument_id),
                color=str(item.color),
            )
            for item in parent.tracks
            if int(item.track_id) != int(self.track.track_id) and not item.muted
            for note in item.notes
        ]
        if hasattr(self, "canvas"):
            self.canvas.set_ghost_notes(notes)

    def _ghost_opacity_changed(self, value: int) -> None:
        normalized = max(0, min(100, int(value)))
        self.ghost_opacity_label.setText(f"{normalized}%")
        if hasattr(self, "canvas"):
            self.canvas.set_ghost_opacity(normalized / 100.0)
        self._update_reference_layer_settings(
            ghost_opacity_percent=normalized
        )

    def _set_top_inspector_mode(self, mode: str) -> None:
        show_notes = mode == "note"
        show_articulation = mode == "articulation"
        self.note_controls.setVisible(show_notes)
        self.articulation_controls.setVisible(show_articulation)
        self.grid_controls.setVisible(mode == "grid")
        self.note_mode_button.setChecked(show_notes)
        self.articulation_mode_button.setChecked(show_articulation)
        self.grid_mode_button.setChecked(mode == "grid")
        if show_articulation and self.isVisible():
            show_global_toast(self, tr("选择音符后即可批量应用奏法。"))
        elif mode == "grid" and self.isVisible():
            show_global_toast(
                self,
                tr("双击新建 · Ctrl+拖动复制 · Alt 临时取消吸附 · Ctrl+D 复制"),
            )

    def _toggle_draw_mode(self, enabled: bool) -> None:
        if hasattr(self, "canvas"):
            self.canvas.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)
            self.canvas.update()
        if hasattr(self, "status"):
            self._update_shortcut_hud()
            self._update_status()

    def _update_shortcut_hud(self) -> None:
        if not hasattr(self, "shortcut_hud"):
            return
        if self.draw_mode_button.isChecked():
            context = EditorShortcutHud.DRAW_CONTEXT
        elif self.canvas.selected:
            context = EditorShortcutHud.SELECTION_CONTEXT
        else:
            context = EditorShortcutHud.SELECT_CONTEXT
        self.shortcut_hud.set_context(context)

    def _toggle_velocity_lane(self, visible: bool) -> None:
        self.velocity_panel.setVisible(visible)
        if visible:
            self._request_velocity_mapping_hint()
        QTimer.singleShot(0, self.update_scrollbars)

    def _set_velocity_mode(self, mode: str) -> None:
        point_mode = mode == "point"
        self.velocity_point_button.setChecked(point_mode)
        self.velocity_brush_button.setChecked(not point_mode)
        self.velocity_lane.set_edit_mode("point" if point_mode else "brush")

    def _velocity_radius_changed(self) -> None:
        beats = self.velocity_radius_combo.currentData()
        if beats is not None:
            self.velocity_lane.set_influence_beats(float(beats))

    def _sync_velocity_radius_control(self) -> None:
        target = self.velocity_lane.influence_beats
        best = min(
            range(self.velocity_radius_combo.count()),
            key=lambda index: abs(float(self.velocity_radius_combo.itemData(index)) - target),
        )
        self.velocity_radius_combo.blockSignals(True)
        self.velocity_radius_combo.setCurrentIndex(best)
        self.velocity_radius_combo.blockSignals(False)

    def _velocity_scope_changed(self) -> None:
        self.velocity_lane.set_scope_mode(
            str(self.velocity_scope_combo.currentData() or "track")
        )

    def _request_velocity_mapping_hint(self) -> None:
        if not self.velocity_panel.isVisible():
            return
        chosen_indices = sorted(self.canvas.selected)
        if len(chosen_indices) != 1:
            self._velocity_mapping_request += 1
            self._velocity_mapping_key = None
            self.velocity_lane.set_game_velocity_boundaries(
                (), tr("选择一个音符可查看游戏采样层"),
            )
            return
        note = self.canvas.notes[chosen_indices[0]]
        key = (
            int(self.track.bdo_instrument_id), int(note.pitch), int(note.ntype),
            str(self.track.marnian_synth_mode),
        )
        if key == self._velocity_mapping_key:
            return
        self._velocity_mapping_key = key
        self._velocity_mapping_request += 1
        request_id = self._velocity_mapping_request
        self.velocity_lane.set_game_velocity_boundaries(
            (), tr("正在读取 Wwise 力度分层…"),
        )
        task = _VelocityMappingTask(request_id, self.track, note)
        task.signals.finished.connect(self._velocity_mapping_ready)
        self._velocity_mapping_tasks[request_id] = task
        self._velocity_mapping_pool.start(task)

    @Slot(int, object, str)
    def _velocity_mapping_ready(
        self, request_id: int, boundaries: object, error: str
    ) -> None:
        self._velocity_mapping_tasks.pop(request_id, None)
        if request_id != self._velocity_mapping_request:
            return
        values = tuple(int(value) for value in boundaries)
        if error:
            status = tr("Wwise 映射暂不可用")
        elif values:
            status = tr("虚线为 Wwise 路由分层；不代表实测响度")
        else:
            status = tr("当前音符没有独立的 Wwise 力度分层")
        self.velocity_lane.set_game_velocity_boundaries(values, status)

    def draft_duration_ms(self) -> float:
        end = (
            self.canvas.content_end_ms
            if hasattr(self, "canvas")
            else max((note.start + note.dur for note in self.track.notes), default=0.0)
        )
        if self.transcription_mode_enabled:
            reference_audio = getattr(self.parent(), "reference_audio", None)
            if reference_audio is not None:
                end = max(
                    end,
                    float(
                        getattr(
                            reference_audio,
                            "project_end_ms",
                            reference_audio.duration_ms,
                        )
                    ),
                )
        return max(self.canvas.beat_ms if hasattr(self, "canvas") else 60000.0 / max(1, self.bpm), end + 60000.0 / max(1, self.bpm))

    @staticmethod
    def format_playback_time(ms: float) -> str:
        ms = max(0, round(ms))
        minutes, remainder = divmod(ms, 60000)
        seconds, millis = divmod(remainder, 1000)
        return f"{minutes}:{seconds:02d}.{millis:03d}"

    def set_draft_playhead(self, ms: float, follow: bool = False) -> None:
        duration = self.draft_duration_ms()
        self.playhead_ms = max(0.0, min(float(ms), duration))
        if hasattr(self, "canvas"):
            self.canvas.set_playhead(self.playhead_ms)
        if hasattr(self, "transcription_waveform"):
            self.transcription_waveform.set_playhead_ms(self.playhead_ms)
        if hasattr(self, "playback_time_label"):
            self.playback_time_label.setText(
                f"{self.format_playback_time(self.playhead_ms)} / {self.format_playback_time(duration)}"
            )
        if follow and hasattr(self, "time_scroll"):
            visible_ms = max(1.0, (self.canvas.width() - self.canvas.KEY_W) / self.canvas.px_per_ms)
            left, right = self.canvas.scroll_ms, self.canvas.scroll_ms + visible_ms
            if self.playhead_ms < left + visible_ms * .08 or self.playhead_ms > right - visible_ms * .08:
                self.time_scroll.setValue(round(max(0.0, self.playhead_ms - visible_ms * .45)))

    def seek_draft(self, ms: float) -> None:
        self.set_draft_playhead(ms, follow=True)
        if self.draft_playback_state in ("playing", "paused"):
            parent = self.parent()
            if (
                parent
                and hasattr(parent, "realtime_audio")
                and not self.draft_reference_only
            ):
                try:
                    parent.realtime_audio.seek(self.playhead_ms)
                except AudioEngineError as exc:
                    self.stop_draft()
                    QMessageBox.warning(self, tr("定位失败"), str(exc))
            reference_audio = getattr(parent, "reference_audio", None)
            if (
                self.transcription_mode_enabled
                and self.transcription_audition_source
                in {"original", "combined"}
                and reference_audio is not None
                and reference_audio.audio_path
            ):
                self._sync_draft_reference_audio(
                    self.playhead_ms,
                    play=self.draft_playback_state == "playing",
                    force=True,
                )

    def _sync_draft_reference_audio(
        self,
        project_ms: float,
        *,
        play: bool,
        force: bool = False,
    ) -> bool:
        """Keep the editor reference stream on the shared project clock."""

        reference_audio = getattr(self.parent(), "reference_audio", None)
        if reference_audio is None or not reference_audio.audio_path:
            return False
        self.draft_reference_last_resync_at = synchronize_reference_audio(
            reference_audio, project_ms, play=play, force=force,
            last_resync_at=self.draft_reference_last_resync_at,
        )
        converter = getattr(reference_audio, "project_to_audio", None)
        audio_ms = (
            float(converter(project_ms))
            if callable(converter)
            else float(project_ms) - float(
                getattr(
                    reference_audio,
                    "project_offset_ms",
                    getattr(reference_audio, "offset_ms", 0.0),
                )
            )
        )
        duration_ms = float(getattr(reference_audio, "duration_ms", 0.0))
        return bool(
            play and audio_ms >= 0.0
            and (duration_ms <= 0.0 or audio_ms < duration_ms)
        )

    def _start_draft_reference_only(
        self,
        reference_audio: object,
        *,
        status_text: str,
    ) -> bool:
        """Start the shared reference transport without a zero-event clock."""

        if not getattr(reference_audio, "audio_path", ""):
            return False
        reference_start = max(
            0.0,
            float(getattr(reference_audio, "project_start_ms", 0.0)),
        )
        start_ms = max(float(self.playhead_ms), reference_start)
        duration_ms = float(getattr(reference_audio, "duration_ms", 0.0))
        reference_end = float(
            getattr(
                reference_audio,
                "project_end_ms",
                reference_start + duration_ms,
            )
        )
        if duration_ms > 0.0 and start_ms >= reference_end:
            start_ms = reference_start
        self.parent()._stop_preview(reset_playhead=False)
        self.set_draft_playhead(start_ms, follow=True)
        if not self._sync_draft_reference_audio(
            start_ms,
            play=True,
            force=True,
        ):
            return False
        self.draft_reference_only = True
        self._set_draft_playback_state("playing")
        self.playback_timer.start()
        self.status.setText(tr(status_text))
        return True

    def poll_draft_playback(self) -> None:
        parent = self.parent()
        if not parent or not hasattr(parent, "realtime_audio"):
            self.playback_timer.stop()
            return
        reference_audio = getattr(parent, "reference_audio", None)
        shared_range = (
            getattr(
                getattr(parent, "transcription_session", None),
                "state",
                None,
            ).region
            if (
                self.transcription_mode_enabled
                and self.loop_box.isChecked()
                and getattr(
                    getattr(parent, "transcription_session", None),
                    "state",
                    None,
                )
                is not None
            )
            else None
        )
        if self.draft_reference_only:
            if reference_audio is None or not reference_audio.audio_path:
                self.stop_draft()
                return
            position = float(
                getattr(
                    reference_audio,
                    "project_position_ms",
                    reference_audio.player.position(),
                )
            )
            self.set_draft_playhead(position, follow=True)
            if self.draft_playback_state == "paused":
                return
            if shared_range is not None and position >= shared_range[1]:
                self._sync_draft_reference_audio(
                    shared_range[0],
                    play=True,
                    force=True,
                )
                self.set_draft_playhead(shared_range[0], follow=True)
                return
            reference_start = max(
                0.0,
                float(getattr(reference_audio, "project_start_ms", 0.0)),
            )
            reference_end = float(
                getattr(
                    reference_audio,
                    "project_end_ms",
                    reference_start
                    + float(getattr(reference_audio, "duration_ms", 0.0)),
                )
            )
            if (
                not reference_audio.is_playing
                or (
                    float(getattr(reference_audio, "duration_ms", 0.0)) > 0.0
                    and position >= reference_end - 1.0
                )
            ):
                if self.loop_box.isChecked():
                    self._sync_draft_reference_audio(
                        reference_start,
                        play=True,
                        force=True,
                    )
                    self.set_draft_playhead(reference_start, follow=True)
                else:
                    self.stop_draft()
            return
        try:
            if self.draft_playback_state == "loading":
                status = parent.realtime_audio.get_status()
                progress = status.preload_progress if status.preload_total else 0.0
                self.canvas.set_preload_progress(progress, "loading")
                self.status.setText(trf(
                    "正在准备游戏音源… {loaded}/{total}",
                    loaded=status.preload_loaded, total=status.preload_total,
                ))
                result = parent.realtime_audio.finish_loading(self.playhead_ms)
                if result is None:
                    return
                self.canvas.set_preload_progress(1.0, "ready")
                parent.realtime_audio.play()
                self._set_draft_playback_state("playing")
                self.status.setText(tr("游戏音源已缓存 · 开始试听"))
                if (
                    self.transcription_mode_enabled
                    and self.transcription_audition_source == "combined"
                    and reference_audio is not None
                    and reference_audio.audio_path
                ):
                    self._sync_draft_reference_audio(
                        self.playhead_ms,
                        play=True,
                        force=True,
                    )
            status = parent.realtime_audio.get_status()
            self.set_draft_playhead(status.position_ms, follow=self.draft_playback_state == "playing")
            if (
                shared_range is not None
                and status.state == "playing"
                and status.position_ms >= shared_range[1]
            ):
                self.seek_draft(shared_range[0])
                parent.realtime_audio.play()
                if (
                    self.transcription_audition_source == "combined"
                    and
                    reference_audio is not None
                    and reference_audio.audio_path
                ):
                    self._sync_draft_reference_audio(
                        shared_range[0],
                        play=True,
                        force=True,
                    )
                return
            if (
                self.transcription_mode_enabled
                and self.transcription_audition_source == "combined"
                and reference_audio is not None
                and reference_audio.audio_path
                and status.state == "playing"
            ):
                self._sync_draft_reference_audio(
                    status.position_ms,
                    play=True,
                )
            if status.position_ms >= status.duration_ms - 1 and status.duration_ms > 0:
                if (
                    self.transcription_mode_enabled
                    and self.transcription_audition_source == "combined"
                    and reference_audio is not None
                    and reference_audio.is_playing
                    and float(
                        getattr(
                            reference_audio,
                            "project_position_ms",
                            reference_audio.player.position(),
                        )
                    )
                    < float(
                        getattr(
                            reference_audio,
                            "project_end_ms",
                            self.draft_duration_ms(),
                        )
                    ) - 1
                ):
                    self.draft_reference_only = True
                elif self.loop_box.isChecked():
                    self.seek_draft(0.0)
                    parent.realtime_audio.play()
                    if (
                        self.transcription_mode_enabled
                        and self.transcription_audition_source == "combined"
                        and reference_audio is not None
                        and reference_audio.audio_path
                    ):
                        self._sync_draft_reference_audio(
                            0.0,
                            play=True,
                            force=True,
                        )
                else:
                    self.stop_draft()
            elif status.state == "paused" and self.draft_playback_state == "playing":
                self._set_draft_playback_state("paused")
        except AudioEngineError as exc:
            self.playback_timer.stop()
            parent.realtime_audio.cancel_loading()
            self.canvas.set_preload_progress(0.0, "idle")
            self._set_draft_playback_state("stopped")
            QMessageBox.warning(self, tr("试听失败"), str(exc))

    def set_zoom(self, value: int) -> None:
        if math.isclose(self.canvas.px_per_beat, float(value)):
            return
        self.canvas.px_per_beat = float(value)
        self.canvas.update()
        self.velocity_lane.update()
        self.transcription_waveform.refresh()
        self.update_scrollbars()

    def focus_transcription_time_range(
        self, start_ms: float, end_ms: float
    ) -> None:
        start_ms, end_ms = sorted((float(start_ms), float(end_ms)))
        duration_ms = max(self.canvas.beat_ms * 0.5, end_ms - start_ms)
        viewport_width = max(
            120.0, float(self.canvas.width() - self.canvas.KEY_W)
        )
        target_px_per_beat = max(
            round(self.canvas.MIN_PX_PER_BEAT),
            min(
                round(self.canvas.MAX_PX_PER_BEAT),
                round(
                    viewport_width
                    * self.canvas.beat_ms
                    / (duration_ms * 1.25)
                ),
            ),
        )
        self.editor_zoom.setValue(target_px_per_beat)
        visible_ms = viewport_width / max(
            1e-9, self.canvas.px_per_ms
        )
        centered_start = max(
            0.0,
            (start_ms + end_ms - visible_ms) * 0.5,
        )
        self.update_scrollbars()
        self.set_time_scroll(round(centered_start))

    def update_scrollbars(self) -> None:
        if not hasattr(self, "time_scroll"):
            return
        visible_ms = max(1.0, (self.canvas.width() - self.canvas.KEY_W) / self.canvas.px_per_ms)
        reference_audio = getattr(self.parent(), "reference_audio", None)
        has_reference_audio = bool(
            getattr(reference_audio, "audio_path", "")
        )
        trailing_workspace_ms = (
            self.canvas.beat_ms * self.REFERENCE_TRAILING_BEATS
            if has_reference_audio
            else max(
                self.canvas.beat_ms * self.FREE_AUTHORING_TRAILING_BEATS,
                visible_ms * self.FREE_AUTHORING_TRAILING_VIEWPORTS,
            )
        )
        content_end = self.canvas.content_end_ms + trailing_workspace_ms
        maximum = max(0, round(content_end - visible_ms))
        # Keep the canvas' sub-millisecond cursor anchor during wheel zoom.
        # The integer scrollbar mirrors the nearest position without forcing
        # that presentation limitation back into the editor time domain.
        scroll_ms = float(
            max(0.0, min(float(maximum), float(self.canvas.scroll_ms)))
        )
        time_changed = not math.isclose(scroll_ms, self.canvas.scroll_ms, abs_tol=1e-6)
        self.canvas.scroll_ms = scroll_ms
        self.time_scroll.blockSignals(True)
        self.time_scroll.setRange(0, maximum)
        self.time_scroll.setPageStep(max(1, round(visible_ms)))
        self.time_scroll.setSingleStep(max(1, round(self.quantize_ms())))
        self.time_scroll.setValue(round(scroll_ms))
        self.time_scroll.blockSignals(False)

        if self._initial_pitch_focus_pending:
            self.canvas.pitch_top = self._recommended_initial_pitch_top()
            self._initial_pitch_focus_pending = False
        pitch_min, pitch_max = self.pitch_top_bounds()
        pitch_top = max(pitch_min, min(pitch_max, int(self.canvas.pitch_top)))
        pitch_changed = pitch_top != self.canvas.pitch_top
        self.canvas.pitch_top = pitch_top
        self.pitch_scroll.blockSignals(True)
        self.pitch_scroll.setRange(0, pitch_max - pitch_min)
        self.pitch_scroll.setPageStep(self.visible_pitch_rows())
        self.pitch_scroll.setSingleStep(1)
        # Scrollbar value grows downwards while MIDI pitches grow upwards.
        self.pitch_scroll.setValue(pitch_max - pitch_top)
        self.pitch_scroll.blockSignals(False)
        if time_changed:
            self.velocity_lane.update()
            self.transcription_waveform.refresh()
        if time_changed or pitch_changed:
            self.canvas.update()
        self.set_draft_playhead(self.playhead_ms)

    def visible_pitch_rows(self) -> int:
        grid_height = max(0, self.canvas.height() - self.canvas.RULER_H)
        return max(1, math.ceil(grid_height / self.canvas.ROW_H))

    def _recommended_initial_pitch_top(self) -> int:
        """Focus the first view without hiding or rewriting any pitch row."""

        visible_rows = min(
            self.canvas.MAX_PITCH - self.canvas.MIN_PITCH + 1,
            self.visible_pitch_rows(),
        )
        if self.canvas.notes:
            low = min(int(note.pitch) for note in self.canvas.notes)
            high = max(int(note.pitch) for note in self.canvas.notes)
            if high - low + 1 > max(1, visible_rows - 3):
                target = high + 1
            else:
                target = round((low + high + visible_rows - 1) / 2.0)
        elif self.instrument_adaptation is not None:
            low, high = self.instrument_adaptation.recommended_visible_range
            target = round((low + high + visible_rows - 1) / 2.0)
        else:
            target = 84
        minimum_top = self.canvas.MIN_PITCH + visible_rows - 1
        return max(
            minimum_top,
            min(self.canvas.MAX_PITCH, int(target)),
        )

    def pitch_top_bounds(self) -> tuple[int, int]:
        pitch_max = self.canvas.MAX_PITCH
        visible_rows = min(
            pitch_max - self.canvas.MIN_PITCH + 1,
            self.visible_pitch_rows(),
        )
        pitch_min = self.canvas.MIN_PITCH + visible_rows - 1
        return pitch_min, pitch_max

    def set_time_scroll(self, value: int) -> None:
        value = float(max(self.time_scroll.minimum(), min(self.time_scroll.maximum(), int(value))))
        if self.time_scroll.value() != round(value):
            self.time_scroll.blockSignals(True)
            self.time_scroll.setValue(round(value))
            self.time_scroll.blockSignals(False)
        if math.isclose(value, self.canvas.scroll_ms, abs_tol=1e-6):
            return
        self.canvas.scroll_ms = value
        self.canvas.update()
        self.velocity_lane.update()
        self.transcription_waveform.refresh()

    def set_pitch_scroll(self, value: int) -> None:
        pitch_min, pitch_max = self.pitch_top_bounds()
        scroll_value = max(0, min(pitch_max - pitch_min, int(value)))
        pitch_top = pitch_max - scroll_value
        if self.pitch_scroll.value() != scroll_value:
            self.pitch_scroll.blockSignals(True)
            self.pitch_scroll.setValue(scroll_value)
            self.pitch_scroll.blockSignals(False)
        if pitch_top == self.canvas.pitch_top:
            return
        self.canvas.pitch_top = pitch_top
        self.canvas.update()

    def optimize_draft(self) -> None:
        parent = self.parent()
        if not parent or not hasattr(parent, "tracks"):
            return
        draft_tracks = [
            replace(item, notes=self.edited_notes()) if int(item.track_id) == int(self.track.track_id) else item
            for item in parent.tracks
        ]
        dialog = parent.create_midi_optimize_dialog(
            int(self.track.track_id),
            source_tracks=draft_tracks,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        optimized = next(
            (item for item in dialog.optimized_tracks() if int(item.track_id) == int(self.track.track_id)),
            None,
        )
        if optimized is None:
            return
        self.push_snapshot()
        self.canvas.notes = list(optimized.notes)
        self.canvas.selected.clear()
        self.canvas.anchor_index = None
        self._notes_changed()
        self.refresh_fields()
        self.update_scrollbars()
        self.status.setText(trf(
            "单轨优化完成 · 当前草稿 {count} 音符 · 点击应用或确定后写回",
            count=len(self.canvas.notes),
        ))

    def toggle_draft_playback(self) -> None:
        if self.draft_playback_state == "loading":
            return
        if self.draft_playback_state == "playing":
            self.pause_draft()
        elif self.draft_playback_state == "paused":
            self.resume_draft()
        else:
            self.play_draft()

    def _set_draft_playback_state(self, state: str) -> None:
        self.draft_playback_state = state
        labels = {"stopped": "播放", "loading": "准备中…", "playing": "暂停", "paused": "继续"}
        label = tr(labels.get(state, "播放"))
        self.draft_play_button.setToolTip(label)
        self.draft_play_button.setAccessibleName(label)
        self.draft_play_button.setText(
            "" if getattr(self, "_editor_controls_compact", False) else label
        )
        self.draft_play_button.setEnabled(state != "loading")

    def play_draft(self) -> None:
        parent = self.parent()
        if not parent or not hasattr(parent, "realtime_audio"):
            return
        self.audition_timer.stop()
        self.audition_stop_timer.stop()
        self.audition_pending = False
        shared_range = (
            getattr(
                getattr(parent, "transcription_session", None),
                "state",
                None,
            ).region
            if (
                self.transcription_mode_enabled
                and self.loop_box.isChecked()
                and getattr(
                    getattr(parent, "transcription_session", None),
                    "state",
                    None,
                )
                is not None
            )
            else None
        )
        if (
            shared_range is not None
            and not shared_range[0] <= self.playhead_ms < shared_range[1]
        ):
            self.set_draft_playhead(shared_range[0], follow=True)
        reference_audio = getattr(parent, "reference_audio", None)
        if (
            self.transcription_mode_enabled
            and self.transcription_audition_source == "original"
            and reference_audio is not None
            and reference_audio.audio_path
        ):
            self._start_draft_reference_only(
                reference_audio,
                status_text="正在播放参考原音",
            )
            return
        draft_track = replace(
            self.track,
            notes=self.edited_notes(),
            muted=False,
            solo=False,
        )
        if (
            self.transcription_mode_enabled
            and self.transcription_audition_source
            in {"candidate_a", "candidate_b"}
        ):
            active_group = parent._active_voice_group()
            analysis = parent.instrument_match_analysis
            match_index = (
                0
                if self.transcription_audition_source == "candidate_a"
                else 1
            )
            matches = (
                analysis.matches_for_group(active_group.group_id)
                if analysis is not None and active_group is not None
                else ()
            )
            if active_group is None or match_index >= len(matches):
                self.transcription_panel.set_status(
                    tr("当前声部没有可试听的该候选")
                )
                return
            wanted_ids = set(active_group.candidate_ids)
            selected_instrument_id = int(
                matches[match_index].instrument_id
            )
            supported_pitches = game_supported_pitches(
                selected_instrument_id
            )
            audition_candidates = [
                candidate
                for candidate in parent.transcription_session.candidates
                if parent.transcription_session.candidate_id(candidate)
                in wanted_ids
            ]
            if (
                not audition_candidates
                or any(
                    (
                        not CANDIDATE_NOTE_POLICY.project_timing_is_valid(
                            candidate,
                            float(parent.reference_audio_offset_ms),
                        )
                        or not CANDIDATE_NOTE_POLICY.pitch_is_valid_for_melodic_track(
                            candidate.pitch,
                            is_percussion=False,
                            instrument_id=selected_instrument_id,
                            transpose=self.transpose,
                            supported_pitches=supported_pitches,
                        )
                    )
                    for candidate in audition_candidates
                )
            ):
                self.transcription_panel.set_status(
                    tr("游戏候选含移调后不可用的音高，已停止试听。")
                )
                return
            audition_notes = [
                CANDIDATE_NOTE_POLICY.to_note(
                    candidate,
                    float(parent.reference_audio_offset_ms),
                )._replace(
                    pitch=int(candidate.pitch) + int(self.transpose)
                )
                for candidate in audition_candidates
            ]
            draft_track = replace(
                self.track,
                notes=audition_notes,
                bdo_instrument_id=selected_instrument_id,
                display_name=_ui_bdo_instrument_name(selected_instrument_id),
                muted=False,
                solo=False,
            )
        else:
            draft_track = replace(
                draft_track,
                notes=list(transpose_notes(draft_track.notes, self.transpose)),
            )
        if (
            self.transcription_mode_enabled
            and self.transcription_audition_source == "combined"
            and not draft_track.notes
            and reference_audio is not None
            and reference_audio.audio_path
        ):
            self._start_draft_reference_only(
                reference_audio,
                status_text="仅播放参考音频",
            )
            return
        blockers = parent._realtime_preview_blockers([draft_track])
        use_generic_preview = bool(blockers)
        if blockers:
            if (
                self.transcription_mode_enabled
                and self.transcription_audition_source
                in {"candidate_a", "candidate_b"}
            ):
                self.transcription_panel.set_status(
                    tr("游戏候选音源不可用；没有回退播放原音。")
                )
                return
            if (
                self.transcription_mode_enabled
                and self.transcription_audition_source
                in {"original", "combined"}
                and reference_audio is not None
                and reference_audio.audio_path
            ):
                self._start_draft_reference_only(
                    reference_audio,
                    status_text="仅播放参考音频",
                )
                return
        try:
            parent._stop_preview(reset_playhead=False)
            self.draft_reference_only = False
            if use_generic_preview and hasattr(
                parent.realtime_audio,
                "load_procedural_project_async",
            ):
                parent.realtime_audio.load_procedural_project_async(
                    [draft_track],
                    self.playhead_ms,
                    parent.reverb,
                    parent.delay,
                    parent.chorus,
                )
            elif use_generic_preview:
                self.status.setText(tr("通用 MIDI 预览不可用"))
                return
            else:
                parent.realtime_audio.load_project_async(
                    [draft_track], BDO_SAMPLE_MAP_PATH, self.playhead_ms,
                    parent.reverb, parent.delay, parent.chorus,
                )
            self.canvas.set_preload_progress(0.0, "loading")
            self._set_draft_playback_state("loading")
            self.status.setText(
                tr(
                    "正在准备通用 MIDI 预览…"
                    if use_generic_preview
                    else "正在准备游戏音源…"
                )
            )
            self.playback_timer.start()
        except AudioEngineError as exc:
            self.canvas.set_preload_progress(0.0, "idle")
            self._set_draft_playback_state("stopped")
            QMessageBox.warning(self, tr("试听失败"), str(exc))

    def audition_note(self, note, *, force: bool = False) -> None:
        """Asynchronously audition one editor note with the current game instrument."""
        if (
            not force
            and hasattr(self, "note_preview_box")
            and not self.note_preview_box.isChecked()
        ):
            return
        parent = self.parent()
        if not parent or not hasattr(parent, "realtime_audio"):
            return
        audition_track = replace(
            self.track,
            notes=[
                note._replace(
                    pitch=int(note.pitch) + int(self.transpose),
                    start=0.0,
                    dur=max(180.0, min(650.0, float(note.dur))),
                )
            ],
            muted=False,
            solo=False,
        )
        use_generic_preview = bool(
            parent._realtime_preview_blockers([audition_track])
        )
        try:
            if self.draft_playback_state != "stopped":
                self.stop_draft()
            elif getattr(parent, "realtime_preview_active", False) or getattr(parent, "realtime_preview_loading", False):
                parent._stop_preview(reset_playhead=False)
            self.audition_stop_timer.stop()
            self.audition_pending = True
            articulation_label = self.articulation_labels_by_type.get(
                int(getattr(note, "ntype", self.default_articulation_ntype)),
                f"type {int(getattr(note, 'ntype', self.default_articulation_ntype))}",
            )
            self.audition_note_name = (
                f"{note_name(note.pitch)} · {articulation_label}"
            )
            if use_generic_preview and hasattr(
                parent.realtime_audio,
                "load_procedural_project_async",
            ):
                parent.realtime_audio.load_procedural_project_async(
                    [audition_track],
                    0.0,
                    parent.reverb,
                    parent.delay,
                    parent.chorus,
                )
            elif use_generic_preview:
                self.audition_pending = False
                self.status.setText(tr("通用 MIDI 预览不可用"))
                return
            else:
                parent.realtime_audio.load_project_async(
                    [audition_track], BDO_SAMPLE_MAP_PATH, 0.0,
                    parent.reverb, parent.delay, parent.chorus,
                )
            self.status.setText(trf("正在准备音符试听… {note}", note=self.audition_note_name))
            self.audition_timer.start()
        except AudioEngineError as exc:
            self.audition_pending = False
            self.audition_timer.stop()
            self.status.setText(trf("音符试听不可用：{message}", message=str(exc)))

    def audition_pitch(self, pitch: int) -> None:
        self.audition_note(Note(
            max(0, min(127, int(pitch))), self.default_note_velocity, 0.0,
            self.default_note_duration(), self.current_articulation(),
        ))

    def preview_selected_articulation(self, *, force: bool = False) -> None:
        """Audition one stable representative of the current selection."""

        if not self.canvas.selected:
            return
        index = self.canvas.anchor_index
        if index not in self.canvas.selected:
            index = min(self.canvas.selected)
        if index is None or not 0 <= index < len(self.canvas.notes):
            return
        self.audition_note(self.canvas.notes[index], force=force)

    def _poll_note_audition(self) -> None:
        if not self.audition_pending:
            self.audition_timer.stop()
            return
        parent = self.parent()
        if not parent or not hasattr(parent, "realtime_audio"):
            self.audition_pending = False
            self.audition_timer.stop()
            return
        try:
            result = parent.realtime_audio.finish_audition_loading()
            if result is None:
                return
            self.audition_pending = False
            self.audition_timer.stop()
            audible_ms = max(1.0, float(result.get("duration_ms", 1.0)))
            self.audition_stop_timer.start(max(1, math.ceil(audible_ms + 30.0)))
            self.status.setText(trf("试听 {note}", note=self.audition_note_name))
        except AudioEngineError as exc:
            self.audition_pending = False
            self.audition_timer.stop()
            self.status.setText(trf("音符试听不可用：{message}", message=str(exc)))

    def _stop_note_audition(self) -> None:
        parent = self.parent()
        if parent and hasattr(parent, "realtime_audio"):
            parent.realtime_audio.clear_playback()
        self.audition_pending = False
        self.audition_timer.stop()

    def pause_draft(self) -> None:
        parent = self.parent()
        if not parent or not hasattr(parent, "realtime_audio"):
            return
        try:
            if not self.draft_reference_only:
                parent.realtime_audio.pause()
            reference_audio = getattr(parent, "reference_audio", None)
            if (
                self.transcription_mode_enabled
                and self.transcription_audition_source
                in {"original", "combined"}
                and reference_audio is not None
            ):
                reference_audio.pause()
            self._set_draft_playback_state("paused")
            self.playback_timer.start()
        except AudioEngineError as exc:
            self.canvas.set_preload_progress(0.0, "idle")
            self._set_draft_playback_state("stopped")
            QMessageBox.warning(self, tr("试听失败"), str(exc))

    def resume_draft(self) -> None:
        parent = self.parent()
        if not parent or not hasattr(parent, "realtime_audio"):
            return
        try:
            if not self.draft_reference_only:
                parent.realtime_audio.play()
            reference_audio = getattr(parent, "reference_audio", None)
            if (
                self.transcription_mode_enabled
                and self.transcription_audition_source
                in {"original", "combined"}
                and reference_audio is not None
                and reference_audio.audio_path
            ):
                self._sync_draft_reference_audio(
                    self.playhead_ms,
                    play=True,
                    force=True,
                )
            self._set_draft_playback_state("playing")
            self.playback_timer.start()
        except AudioEngineError as exc:
            self.canvas.set_preload_progress(0.0, "idle")
            self._set_draft_playback_state("stopped")
            QMessageBox.warning(self, tr("试听失败"), str(exc))

    def stop_draft(self) -> None:
        self.playback_timer.stop()
        self.audition_timer.stop()
        self.audition_stop_timer.stop()
        self.audition_pending = False
        parent = self.parent()
        if parent and hasattr(parent, "realtime_audio"):
            try:
                # The editor shares the main-window audio engine.  Transport
                # Stop must discard queued PCM without tearing down the output
                # thread and decode pools; application shutdown owns the full
                # engine stop.
                parent.realtime_audio.clear_playback()
            except AudioEngineError:
                pass
        reference_audio = getattr(parent, "reference_audio", None)
        if self.transcription_mode_enabled and reference_audio is not None:
            reference_audio.stop()
        self.draft_reference_only = False
        if hasattr(self, "draft_play_button"):
            self._set_draft_playback_state("stopped")
        if hasattr(self, "canvas"):
            self.canvas.set_preload_progress(0.0, "idle")
            self.set_draft_playhead(0.0)

    def closeEvent(self, event) -> None:
        self.audition_timer.stop()
        self.audition_stop_timer.stop()
        self.audition_pending = False
        self.stop_draft()
        self.release_transcription_resources()
        self._velocity_mapping_request += 1
        self._velocity_mapping_pool.clear()
        super().closeEvent(event)

    def reject(self) -> None:
        super().reject()

    def accept(self) -> None:
        super().accept()

    def minimum_duration_ms(self) -> float:
        return max(1.0, self.quantize_ms() / 8.0)

    def default_note_duration(self) -> float:
        return self.last_note_duration_ms if self.last_note_duration_ms > 0 else self.quantize_ms()

    def remember_note_creation_properties(self, note: Note) -> None:
        """Remember creative properties without copying pitch or position."""

        velocity = max(0, min(127, int(note.vel)))
        duration_ms = max(self.minimum_duration_ms(), float(note.dur))
        articulation = int(note.ntype)
        self._last_selected_note_properties = (
            velocity,
            duration_ms,
            articulation,
        )
        self.default_note_velocity = velocity
        self.last_note_duration_ms = duration_ms

    def build_created_note(
        self,
        *,
        pitch: int,
        start_ms: float,
        duration_ms: float | None = None,
        velocity: int | None = None,
        articulation: int | None = None,
    ) -> Note:
        """Create a note using the last selected note as the property template."""

        template = self._last_selected_note_properties
        inherited_velocity = template[0] if template is not None else self.default_note_velocity
        inherited_duration = template[1] if template is not None else self.default_note_duration()
        inherited_articulation = template[2] if template is not None else self.current_articulation()
        return Note(
            max(0, min(127, int(pitch))),
            max(0, min(127, int(inherited_velocity if velocity is None else velocity))),
            max(0.0, float(start_ms)),
            max(
                self.minimum_duration_ms(),
                float(inherited_duration if duration_ms is None else duration_ms),
            ),
            int(inherited_articulation if articulation is None else articulation),
        )

    def snap_time(self, value: float) -> float:
        if not self.snap_box.isChecked():
            return max(0.0, value)
        q = self.quantize_ms()
        return max(
            0.0,
            self.beat_origin_ms
            + round((value - self.beat_origin_ms) / q) * q,
        )

    def current_articulation(self) -> int:
        value = self.articulation_combo.currentData()
        return int(
            self.default_articulation_ntype if value is None else value
        )

    def note_invalid(self, pitch: int) -> bool:
        pitch = int(pitch)
        cached = self._invalid_pitch_cache.get(pitch)
        if cached is not None:
            return cached
        if self.track.bdo_instrument_id == 0x0d:
            if self.canonical_drum_lanes:
                legal = (
                    self.instrument_adaptation.legal_pitches
                    if self.instrument_adaptation is not None
                    else frozenset(range(BDO_DRUM_MIN, BDO_DRUM_MAX + 1))
                )
                result = pitch not in legal
            else:
                mapped = _GM_TO_BDO_DRUM.get(pitch)
                result = (
                    mapped is None
                    or mapped < BDO_DRUM_MIN
                    or mapped > BDO_DRUM_MAX
                )
        else:
            supported = game_supported_pitches(
                self.track.bdo_instrument_id, self.track.marnian_synth_mode
            )
            converted = pitch + self.transpose
            result = converted not in supported if supported is not None else not (BDO_NOTE_MIN <= converted <= BDO_NOTE_MAX)
        self._invalid_pitch_cache[pitch] = result
        return result

    def _recalculate_invalid_note_count(self) -> None:
        self._invalid_note_count = sum(1 for note in self.canvas.notes if self.note_invalid(note.pitch))

    def snapshot(
        self,
    ) -> tuple[
        list,
        set[int],
        set[CandidateRoute],
        set[CandidateRoute],
        dict[int, int],
        str,
        str,
    ]:
        return (
            list(self.canvas.notes),
            set(self.canvas.selected),
            set(self.staged_primary_routes),
            set(self.staged_copy_routes),
            dict(self.staged_new_track_specs),
            self.staged_analysis_cache_key,
            self.staged_analysis_fingerprint,
        )

    def push_snapshot(self, notes=None, selected=None) -> None:
        self.undo_stack.append(
            (
                list(self.canvas.notes if notes is None else notes),
                set(self.canvas.selected if selected is None else selected),
                set(self.staged_primary_routes),
                set(self.staged_copy_routes),
                dict(self.staged_new_track_specs),
                self.staged_analysis_cache_key,
                self.staged_analysis_fingerprint,
            )
        )
        if len(self.undo_stack) > 200: self.undo_stack.pop(0)
        self.redo_stack.clear()

    def _restore(self, state) -> None:
        if self.draft_playback_state != "stopped":
            self.stop_draft()
        self.canvas.notes, self.canvas.selected = list(state[0]), set(state[1])
        self.staged_primary_routes = set(state[2]) if len(state) > 2 else set()
        self.staged_copy_routes = set(state[3]) if len(state) > 3 else set()
        has_track_specs = len(state) > 4 and isinstance(state[4], dict)
        self.staged_new_track_specs = (
            dict(state[4]) if has_track_specs else {}
        )
        cache_index = 5 if has_track_specs else 4
        fingerprint_index = 6 if has_track_specs else 5
        self.staged_analysis_cache_key = (
            str(state[cache_index]) if len(state) > cache_index else ""
        )
        self.staged_analysis_fingerprint = (
            str(state[fingerprint_index])
            if len(state) > fingerprint_index
            else ""
        )
        self._clear_staging_identity_if_empty()
        self._notes_changed()
        self.refresh_fields()

    def undo(self) -> None:
        if self.undo_stack:
            self.redo_stack.append(self.snapshot()); self._restore(self.undo_stack.pop())

    def redo(self) -> None:
        if self.redo_stack:
            self.undo_stack.append(self.snapshot()); self._restore(self.redo_stack.pop())

    def delete_selected(self) -> None:
        if not self.canvas.selected: return
        self.push_snapshot()
        self.canvas.notes = [n for i, n in enumerate(self.canvas.notes) if i not in self.canvas.selected]
        self.canvas.selected.clear(); self._notes_changed(); self.refresh_fields()

    def delete_note_at(self, index: int) -> None:
        if index < 0 or index >= len(self.canvas.notes):
            return
        self.push_snapshot()
        del self.canvas.notes[index]
        self.canvas.selected = {
            selected - 1 if selected > index else selected
            for selected in self.canvas.selected
            if selected != index
        }
        if self.canvas.anchor_index == index:
            self.canvas.anchor_index = None
        elif self.canvas.anchor_index is not None and self.canvas.anchor_index > index:
            self.canvas.anchor_index -= 1
        self._notes_changed()
        self.refresh_fields()

    def copy_selected(self) -> None:
        chosen = [self.canvas.notes[i] for i in sorted(self.canvas.selected)]
        if chosen:
            origin = min(n.start for n in chosen)
            self.clipboard = [n._replace(start=n.start - origin) for n in chosen]

    def paste_notes(self) -> None:
        if not self.clipboard:
            return
        self.push_snapshot()
        requested_origin = self.snap_time(self.canvas.edit_cursor_ms)
        origin = next_non_overlapping_paste_origin(
            self.canvas.notes,
            self.clipboard,
            requested_origin,
            grid_step_ms=(
                self.quantize_ms()
                if self.snap_box.isChecked()
                else None
            ),
            grid_origin_ms=self.beat_origin_ms,
        )
        first = len(self.canvas.notes)
        self.canvas.notes.extend(n._replace(start=origin + n.start) for n in self.clipboard)
        self.canvas.selected = set(range(first, len(self.canvas.notes)))
        self.canvas.anchor_index = first
        self.canvas.set_edit_cursor(max(
            note.start + note.dur for note in self.canvas.notes[first:]
        ))
        self._notes_changed(); self.refresh_fields()

    def duplicate_selected(self) -> None:
        chosen = [self.canvas.notes[index] for index in sorted(self.canvas.selected)]
        if not chosen:
            return
        self.push_snapshot()
        start = min(note.start for note in chosen)
        end = max(note.start + note.dur for note in chosen)
        span = max(self.quantize_ms(), end - start)
        offset = math.ceil(span / self.quantize_ms()) * self.quantize_ms()
        first = len(self.canvas.notes)
        self.canvas.notes.extend(note._replace(start=note.start + offset) for note in chosen)
        self.canvas.selected = set(range(first, len(self.canvas.notes)))
        self.canvas.anchor_index = first
        self.canvas.set_edit_cursor(max(
            note.start + note.dur for note in self.canvas.notes[first:]
        ))
        self._notes_changed()
        self.refresh_fields()

    def apply_field(self, field: str, text: str) -> None:
        if self.updating_fields or not self.canvas.selected or text.strip() in ("", "—"): return
        try: value = float(text) if field in ("start", "dur") else int(text)
        except ValueError: self.refresh_fields(); return
        if field == "pitch": value = max(0, min(127, int(value)))
        elif field == "vel": value = max(0, min(127, int(value)))
        elif field == "start": value = max(0.0, float(value))
        else: value = max(self.minimum_duration_ms(), float(value))
        self.push_snapshot()
        for i in self.canvas.selected: self.canvas.notes[i] = self.canvas.notes[i]._replace(**{field: value})
        self._notes_changed(); self.refresh_fields()

    def _choose_articulation(self, ntype: int) -> None:
        ntype = int(ntype)
        if (
            ntype != self.default_articulation_ntype
            and ntype == self.current_articulation()
        ):
            # Clicking the active technique again behaves like releasing an
            # effect pedal and returns the selection to the ordinary sound.
            ntype = self.default_articulation_ntype
        index = self.articulation_combo.findData(ntype)
        if index < 0:
            return
        if index == self.articulation_combo.currentIndex():
            self.apply_articulation()
        else:
            self.articulation_combo.setCurrentIndex(index)

    def apply_articulation(self) -> None:
        if self.updating_fields or not self.canvas.selected: return
        value = self.current_articulation()
        target_indices = same_onset_articulation_indices(
            self.canvas.notes,
            self.canvas.selected,
        )
        invalid_indices = [
            index
            for index in target_indices
            if not articulation_supports_pitch(
                self.track.bdo_instrument_id,
                value,
                self.canvas.notes[index].pitch,
            )
        ]
        if invalid_indices:
            trigger_pitches = articulation_trigger_pitches(
                self.track.bdo_instrument_id,
                value,
            )
            assert trigger_pitches
            articulation_label = self.articulation_labels_by_type.get(
                value,
                f"type {value}",
            )
            show_global_toast(
                self,
                trf(
                    "奏法 {articulation} 仅支持 {pitch_range}，"
                    "未修改 {count} 个越界音符。",
                    articulation=articulation_label,
                    pitch_range=(
                        f"{note_name(min(trigger_pitches))}–"
                        f"{note_name(max(trigger_pitches))}"
                    ),
                    count=len(invalid_indices),
                ),
                kind="warning",
            )
            # Restore the selector/chip to the notes' actual unchanged state.
            self.refresh_fields()
            return
        if all(int(getattr(self.canvas.notes[i], "ntype", 0)) == value for i in target_indices): return
        self.push_snapshot()
        for i in target_indices: self.canvas.notes[i] = self.canvas.notes[i]._replace(ntype=value)
        self._notes_changed()
        self.refresh_fields()
        self.preview_selected_articulation()

    def refresh_fields(self) -> None:
        self.updating_fields = True
        chosen = [self.canvas.notes[i] for i in sorted(self.canvas.selected)]
        preferred_index = (
            self.canvas.anchor_index
            if self.canvas.anchor_index in self.canvas.selected
            else next(iter(self.canvas.selected))
            if len(self.canvas.selected) == 1
            else None
        )
        if preferred_index is not None:
            self.remember_note_creation_properties(
                self.canvas.notes[preferred_index]
            )
        has_selection = bool(chosen)
        for group in self.note_field_groups:
            group.setVisible(has_selection)
        if not chosen:
            self.selection_summary.setText(tr("未选择音符"))
        elif len(chosen) == 1:
            note = chosen[0]
            self.selection_summary.setText(trf(
                "已选择 1 个音符 · {note} · {start} ms",
                note=note_name(note.pitch), start=f"{note.start:.0f}",
            ))
        else:
            self.selection_summary.setText(trf(
                "已选择 {count} 个音符 · 可批量修改共同属性", count=len(chosen)
            ))
        for widget, field in ((self.pitch_edit, "pitch"), (self.start_edit, "start"), (self.duration_edit, "dur"), (self.velocity_edit, "vel")):
            values = [getattr(n, field) for n in chosen]
            widget.setEnabled(bool(chosen)); widget.setText("" if not values else (str(round(values[0], 3)) if all(v == values[0] for v in values) else "—"))
        if chosen:
            types = {int(getattr(n, "ntype", 0)) for n in chosen}
            if len(types) == 1:
                index = self.articulation_combo.findData(next(iter(types)))
                if index >= 0: self.articulation_combo.setCurrentIndex(index)
            else:
                self.articulation_combo.setCurrentIndex(-1)
                self.articulation_combo.setPlaceholderText("—")
        self.articulation_combo.setEnabled(bool(chosen))
        selected_type = next(iter(types)) if chosen and len(types) == 1 else None
        for ntype, button in self.articulation_buttons.items():
            button.setEnabled(bool(chosen))
            button.setChecked(ntype == selected_type)
        overflow_selected = (
            selected_type is not None
            and selected_type not in self.articulation_buttons
        )
        if overflow_selected:
            self.articulation_overflow_button.setText(
                self.articulation_labels_by_type.get(
                    selected_type,
                    f"type {selected_type}",
                )
            )
            self.articulation_overflow_button.setProperty(
                "ntype",
                selected_type,
            )
            self.articulation_overflow_button.setToolTip(
                self.articulation_combo.itemData(
                    self.articulation_combo.findData(selected_type),
                    Qt.ToolTipRole,
                )
                or ""
            )
        self.articulation_overflow_button.setEnabled(bool(chosen))
        self.articulation_overflow_button.setChecked(overflow_selected)
        self.articulation_overflow_button.setVisible(overflow_selected)
        self.articulation_preview_button.setEnabled(bool(chosen))
        self.updating_fields = False
        self._request_velocity_mapping_hint()
        self.note_controls.updateGeometry()
        self._update_shortcut_hud()
        self._update_status()

    def _hover_changed(self, ms: float, pitch: int) -> None:
        key = (int(ms // 25.0), int(pitch))
        if key == self._hover_status_key:
            return
        self._hover_status_key = key
        self._update_status(ms, pitch)

    def _update_status(self, ms: float = 0.0, pitch: int | None = None) -> None:
        pos = f" · {ms:.0f} ms · {note_name(pitch)}" if pitch is not None else ""
        warning = (
            trfv(" · 越界 {count}", count=self._invalid_note_count)
            if self._invalid_note_count
            else ""
        )
        self.status.setText(trf(
            "已选 {selected} · 共 {total} 音符{position}{warning}",
            selected=len(self.canvas.selected), total=len(self.canvas.notes),
            position=pos, warning=warning,
        ))

    def _notes_changed(self) -> None:
        if self.draft_playback_state != "stopped":
            self.stop_draft()
        self._reconcile_staged_primary_routes()
        self.canvas.rebuild_note_index()
        self._recalculate_invalid_note_count()
        self._update_track_meta()
        self.canvas.update(); self.velocity_lane.update(); self._update_status(); self.update_scrollbars()
        checkpoint = getattr(
            self.parent(),
            "_autosave_note_editor_draft",
            None,
        )
        if callable(checkpoint) and checkpoint(self, "note block edit"):
            self._draft_autosave_revision += 1
        if self.transcription_mode_enabled:
            self._sync_shared_transcription_projection()
            schedule = getattr(
                self.parent(),
                "_schedule_transcription_assist_refresh",
                None,
            )
            if callable(schedule):
                schedule()

    def _reconcile_staged_primary_routes(self) -> None:
        current_track_id = int(self.track.track_id)
        current_copy_routes = {
            route
            for route in self.staged_copy_routes
            if int(route.track_id) == current_track_id
        }
        current_routes = set(self.staged_primary_routes).union(
            current_copy_routes
        )
        if not current_routes:
            return
        session = getattr(self.parent(), "transcription_session", None)
        if session is None:
            self.staged_primary_routes.clear()
            self.staged_copy_routes.difference_update(current_copy_routes)
            self._clear_staging_identity_if_empty()
            return
        offset_ms = float(
            getattr(self.parent(), "reference_audio_offset_ms", 0.0)
        )
        unused_note_indices = set(range(len(self.canvas.notes)))
        notes_by_pitch: dict[
            int,
            tuple[list[float], list[int]],
        ] = {}
        grouped_indices: dict[int, list[int]] = defaultdict(list)
        for index, note in enumerate(self.canvas.notes):
            grouped_indices[int(note.pitch)].append(index)
        for pitch, indices in grouped_indices.items():
            ordered = sorted(
                indices,
                key=lambda index: float(
                    self.canvas.notes[index].start
                ),
            )
            notes_by_pitch[pitch] = (
                [
                    float(self.canvas.notes[index].start)
                    for index in ordered
                ],
                ordered,
            )
        survivors: set[CandidateRoute] = set()
        for route in sorted(current_routes):
            candidate = session.candidate_for_id(route.candidate_id)
            if candidate is None:
                continue
            starts, indices = notes_by_pitch.get(
                int(candidate.pitch),
                ([], []),
            )
            project_start = CANDIDATE_NOTE_POLICY.project_start_ms(
                candidate,
                offset_ms,
            )
            window_start, window_end = CANDIDATE_NOTE_POLICY.match_window(
                candidate,
                offset_ms,
            )
            first = bisect_left(starts, window_start)
            last = bisect_right(starts, window_end)
            matches = [
                index
                for index in indices[first:last]
                if index in unused_note_indices
                if CANDIDATE_NOTE_POLICY.matches_note(
                    candidate,
                    self.canvas.notes[index],
                    offset_ms,
                )
            ]
            if not matches:
                continue
            chosen = min(
                matches,
                key=lambda index: (
                    abs(
                        float(self.canvas.notes[index].start)
                        - project_start
                    ),
                    index,
                ),
            )
            unused_note_indices.remove(chosen)
            survivors.add(route)
        self.staged_primary_routes.intersection_update(survivors)
        self.staged_copy_routes.difference_update(current_copy_routes)
        self.staged_copy_routes.update(
            route
            for route in current_copy_routes
            if route in survivors
        )
        self._clear_staging_identity_if_empty()

    def _update_track_meta(self) -> None:
        if hasattr(self, "track_meta"):
            self.track_meta.setText(
                f"♫ {len(self.canvas.notes) if hasattr(self, 'canvas') else len(self.track.notes)}"
                f"   ·   {self.bpm} BPM   ·   {self.time_sig}/4"
            )

    def edited_notes(self) -> list:
        return sorted(self.canvas.notes, key=lambda n: (n.start, n.pitch, n.dur))

    def apply_notes(self) -> TranscriptionEditorCommitReport | None:
        notes = self.edited_notes()
        parent = self.parent()
        commit = getattr(parent, "_commit_note_editor", None)
        if callable(commit):
            state = getattr(
                getattr(parent, "transcription_session", None),
                "state",
                TranscriptionSessionState(),
            )
            request = TranscriptionEditorCommit(
                int(self.track.track_id),
                tuple(notes),
                tuple(self.staged_primary_routes),
                tuple(self.staged_copy_routes),
                (
                    self.staged_analysis_cache_key
                    if self._has_transcription_staging()
                    else str(getattr(state, "cache_key", "") or "")
                ),
                (
                    self.staged_analysis_fingerprint
                    if self._has_transcription_staging()
                    else str(
                        getattr(state, "analysis_fingerprint", "") or ""
                    )
                ),
                tuple(sorted(self.staged_new_track_specs.items())),
            )
            report = commit(request)
            if report is None:
                return None
            successful = set(report.applied_routes)
            self.staged_primary_routes.difference_update(successful)
            self.staged_copy_routes.difference_update(successful)
            staged_target_ids = {
                route.track_id for route in self.staged_copy_routes
            }
            self.staged_new_track_specs = {
                track_id: instrument_id
                for track_id, instrument_id
                in self.staged_new_track_specs.items()
                if track_id in staged_target_ids
            }
            self._clear_staging_identity_if_empty()
            self.last_applied = list(notes)
            self._sync_shared_transcription_projection()
            if report.unresolved_routes:
                self.transcription_panel.set_status(
                    trf(
                        "部分候选未提交 · 失效 {invalid} · 孤立 {orphaned}",
                        invalid=report.invalid_count,
                        orphaned=report.orphaned_count,
                    )
                )
            return report
        self.last_applied = list(notes)
        self.notes_applied.emit(notes)
        return TranscriptionEditorCommitReport(project_changed=True)

    def accept_with_apply(self) -> None:
        report = self.apply_notes()
        if report is not None and not report.unresolved_routes:
            self.accept()

    def _persist_parent_config(self) -> None:
        """Ask the owning window to persist its already-updated UI config."""

        callback = getattr(self.parentWidget(), "persist_ui_config", None)
        if callable(callback):
            callback()
