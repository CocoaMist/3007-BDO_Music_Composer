"""Focused dialogs for track pitch and per-track BDO effects.

The dialogs depend on a small structural track contract instead of importing
the main GUI module.  The main window remains responsible only for opening the
dialogs and applying accepted values.
"""

from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from bdo_midi.instruments import (
    MARNIAN_SYNTH_INSTRUMENT_IDS,
    MARNIAN_SYNTH_MODE_OFFSETS,
    localized_bdo_instrument_name,
)
from bdo_track_effects import (
    GAME_PERCENT_MAX,
    MasterEffects,
    TRACK_CHORUS_SEND_INDEX,
    TRACK_DELAY_SEND_INDEX,
    TRACK_REVERB_SEND_INDEX,
    raw_track_settings,
)
from i18n import tr, trf
from pitch_transform import PitchTransformPlan


class TrackDialogState(Protocol):
    """Minimal editor-track surface consumed by these dialogs."""

    track_id: int
    display_name: str
    bdo_instrument_id: int
    bdo_track_settings: tuple[int, ...]
    marnian_synth_mode: str


_MARNIAN_SYNTH_MODE_LABELS = {
    "basic": "单声道（Basic）",
    "stereo": "双声（Stereo）",
    "super": "增强（Super）",
    "superoct": "超级增强（Super Octave）",
}
MARNIAN_SYNTH_MODES = tuple(
    (_MARNIAN_SYNTH_MODE_LABELS[mode], mode)
    for mode in MARNIAN_SYNTH_MODE_OFFSETS
)


def _instrument_name(instrument_id: int) -> str:
    return localized_bdo_instrument_name(int(instrument_id), tr)


class TrackPitchDialog(QDialog):
    """Explicit per-track octave adaptation over the global key transpose."""

    OCTAVE_CHOICES = (-24, -12, 0, 12, 24)

    def __init__(
        self,
        parent: QWidget,
        track: TrackDialogState,
        plan: PitchTransformPlan,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("轨道八度"))
        self.setModal(True)
        self.setMinimumWidth(420)
        self.track = track
        self.plan = plan

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        title = QLabel(track.display_name)
        title.setProperty("i18nSkip", True)
        title.setObjectName("TrackTitle")
        layout.addWidget(title)

        hint = QLabel(
            tr(
                "只做声部八度适配，不改动工程中的原始音符；试听、检查和导出会使用同一结果。"
            )
        )
        hint.setWordWrap(True)
        hint.setObjectName("Muted")
        layout.addWidget(hint)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        layout.addLayout(form)
        self.octave_offset = QComboBox()
        self.octave_offset.setObjectName("TrackOctaveOffset")
        for offset in self.OCTAVE_CHOICES:
            if offset == 0:
                label = tr("跟随全局")
            else:
                label = trf(
                    "{octaves:+d} 个八度（{semitones:+d} 半音）",
                    octaves=offset // 12,
                    semitones=offset,
                )
            self.octave_offset.addItem(label, offset)
        current = plan.override_for(track.track_id)
        current_offset = current.semitones if current is not None else 0
        current_index = self.octave_offset.findData(current_offset)
        self.octave_offset.setCurrentIndex(
            current_index if current_index >= 0 else self.octave_offset.findData(0)
        )
        form.addRow(tr("声部八度"), self.octave_offset)

        self.effective_label = QLabel()
        self.effective_label.setObjectName("Muted")
        self.effective_label.setWordWrap(True)
        layout.addWidget(self.effective_label)
        self.octave_offset.currentIndexChanged.connect(
            self._refresh_effective_label
        )
        self._refresh_effective_label()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _refresh_effective_label(self) -> None:
        effective = (
            self.plan.global_semitones + self.selected_octave_offset()
        )
        self.effective_label.setText(
            trf(
                "全局 {global_transpose:+d} + 轨道 {track_transpose:+d} = 最终 {effective:+d} 半音",
                global_transpose=self.plan.global_semitones,
                track_transpose=self.selected_octave_offset(),
                effective=effective,
            )
        )

    def selected_octave_offset(self) -> int:
        return int(self.octave_offset.currentData() or 0)


class TrackFxDialog(QDialog):
    def __init__(self, parent: QWidget, track: TrackDialogState) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("轨道 FX"))
        self.setModal(True)
        self.setMinimumWidth(380)
        self.track = track
        try:
            self._original_track_settings = raw_track_settings(
                track.bdo_track_settings
            )
        except ValueError:
            self._original_track_settings = (0,) * 8
        self._effect_dirty: set[int] = set()
        self._effect_fields: dict[int, QSpinBox] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        title = QLabel(_instrument_name(track.bdo_instrument_id))
        title.setObjectName("TrackTitle")
        layout.addWidget(title)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        layout.addLayout(form)

        for label, index, object_name, help_text in (
            (
                "混响发送",
                TRACK_REVERB_SEND_INDEX,
                "TrackReverbSend",
                "混响发送：控制此轨道进入共享混响的比例；0 为干声。",
            ),
            (
                "延迟发送",
                TRACK_DELAY_SEND_INDEX,
                "TrackDelaySend",
                "延迟发送：控制此轨道进入回声总线的比例；主“延迟反馈”决定重复次数与衰减。",
            ),
            (
                "合唱发送",
                TRACK_CHORUS_SEND_INDEX,
                "TrackChorusSend",
                "合唱发送：控制此轨道进入合唱/Flanger 总线的比例；用于加宽并产生流动感。",
            ),
        ):
            field = QSpinBox()
            field.setObjectName(object_name)
            field.setRange(0, GAME_PERCENT_MAX)
            raw_value = int(self._original_track_settings[index])
            field.setValue(max(0, min(GAME_PERCENT_MAX, raw_value)))
            tooltip = tr(help_text)
            if raw_value > GAME_PERCENT_MAX:
                tooltip += "\n" + trf(
                    "导入原值 {value}；修改后按 0–100 写入。",
                    value=raw_value,
                )
            field.setToolTip(tooltip)
            field.valueChanged.connect(
                lambda _value, effect_index=index: self._effect_dirty.add(
                    effect_index
                )
            )
            self._effect_fields[index] = field
            form.addRow(label, field)

        is_marnian = track.bdo_instrument_id in MARNIAN_SYNTH_INSTRUMENT_IDS
        self.marnian_mode: QComboBox | None = None
        if is_marnian:
            self.marnian_mode = QComboBox()
            for label, value in MARNIAN_SYNTH_MODES:
                self.marnian_mode.addItem(tr(label), value)
            mode_index = self.marnian_mode.findData(track.marnian_synth_mode)
            self.marnian_mode.setCurrentIndex(mode_index if mode_index >= 0 else 0)
            form.addRow(tr("音源模式"), self.marnian_mode)

        if is_marnian:
            mode_hint = QLabel(tr("Basic 默认；其他模式待验证"))
            mode_hint.setWordWrap(True)
            mode_hint.setObjectName("Muted")
            layout.addWidget(mode_hint)
        preview_hint = QLabel(tr("游戏参数 · 本地 FX 试听为未校准近似"))
        preview_hint.setObjectName("Muted")
        layout.addWidget(preview_hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_marnian_synth_mode(self) -> str:
        if self.marnian_mode is None:
            return "basic"
        return str(self.marnian_mode.currentData() or "basic")

    def selected_track_settings(self) -> tuple[int, ...]:
        """Return edited Aux sends while preserving untouched wire bytes."""

        settings = list(self._original_track_settings)
        for index in self._effect_dirty:
            settings[index] = self._effect_fields[index].value()
        return tuple(settings)

    def track_effects_changed(self) -> bool:
        return bool(self._effect_dirty)

    def changed_send_indices(self) -> frozenset[int]:
        """Return only Aux fields explicitly edited in this dialog."""

        return frozenset(self._effect_dirty)


class MasterEffectsDialog(QDialog):
    """Edit score-wide effect parameters without touching track Aux sends."""

    def __init__(
        self,
        parent: QWidget,
        current: MasterEffects | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("MasterEffectsDialog")
        self.setWindowTitle(tr("全局主效果"))
        self.setModal(True)
        self.resize(720, 500)
        self.setMinimumSize(620, 440)

        self._original = current or MasterEffects()
        self._dirty_fields: set[str] = set()
        self._fields: dict[str, QSpinBox] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("SettingsHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(22, 18, 22, 16)
        header_layout.setSpacing(4)
        title = QLabel(tr("全局主效果"))
        title.setObjectName("SettingsTitle")
        subtitle = QLabel(
            tr(
                "整首曲子共用这些参数；轨道使用多少效果仍由每条轨道的 FX 发送量决定。"
            )
        )
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        layout.addWidget(header)

        body = QWidget()
        body.setObjectName("MasterEffectsContent")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(22, 20, 22, 22)
        body_layout.setSpacing(14)

        scope = QFrame()
        scope.setObjectName("EffectScopeNotice")
        scope_layout = QVBoxLayout(scope)
        scope_layout.setContentsMargins(14, 11, 14, 11)
        scope_layout.setSpacing(4)
        scope_title = QLabel(tr("作用范围"))
        scope_title.setObjectName("EffectScopeTitle")
        scope_detail = QLabel(
            tr("这里仅修改全局参数，不会改动任何轨道的混响、延迟或合唱发送量。")
        )
        scope_detail.setObjectName("Muted")
        scope_detail.setWordWrap(True)
        preview_note = QLabel(
            tr("游戏参数 · 本地 FX 试听为未校准近似")
        )
        preview_note.setObjectName("EffectPreviewNote")
        preview_note.setWordWrap(True)
        scope_layout.addWidget(scope_title)
        scope_layout.addWidget(scope_detail)
        scope_layout.addWidget(preview_note)
        body_layout.addWidget(scope)

        ambience, ambience_layout = self._section(
            "混响与延迟",
            "混响时间控制空间尾音；延迟反馈控制回声重复次数。",
        )
        ambience_grid = self._effect_grid()
        ambience_layout.addLayout(ambience_grid)
        self.reverb = self._new_field(
            "MasterReverbTime",
            "混响时间",
            "reverb_time",
            self._original.reverb_time,
            "混响时间：控制混响尾音长度；本地试听按 0.2–8.0 秒近似。",
        )
        self.delay = self._new_field(
            "MasterDelayFeedback",
            "延迟反馈",
            "delay_feedback",
            self._original.delay_feedback,
            "延迟反馈：控制回声返回延迟线的比例；越高，重复越多。本地试听固定约 250 ms。",
        )
        self._add_field(ambience_grid, 0, 0, "混响时间", self.reverb)
        self._add_field(ambience_grid, 0, 2, "延迟反馈", self.delay)
        body_layout.addWidget(ambience)

        chorus, chorus_layout = self._section(
            "合唱（游戏中为 Flanger）",
            "反馈决定旋动感，LFO 深度决定摆动幅度，LFO 频率决定摆动速度。",
        )
        chorus_grid = self._effect_grid()
        chorus_layout.addLayout(chorus_grid)
        self.chorus_feedback = self._new_field(
            "MasterChorusFeedback",
            "合唱反馈",
            "chorus_feedback",
            self._original.chorus_feedback,
            "合唱反馈：控制调制延迟的反馈强度；越高，梳状与旋动感越明显。",
        )
        self.chorus_depth = self._new_field(
            "MasterChorusLfoDepth",
            "LFO 深度",
            "chorus_lfo_depth",
            self._original.chorus_lfo_depth,
            "LFO 深度：控制合唱延迟时间的摆动幅度；越高，空间宽度与音高摆动越明显。",
        )
        self.chorus_freq = self._new_field(
            "MasterChorusLfoFrequency",
            "LFO 频率",
            "chorus_lfo_frequency",
            self._original.chorus_lfo_frequency,
            "LFO 频率：控制合唱起伏速度；越高，流动越快。",
        )
        self._add_field(chorus_grid, 0, 0, "合唱反馈", self.chorus_feedback)
        self._add_field(chorus_grid, 0, 2, "LFO 深度", self.chorus_depth)
        self._add_field(chorus_grid, 1, 0, "LFO 频率", self.chorus_freq)
        body_layout.addWidget(chorus)
        body_layout.addStretch(1)
        layout.addWidget(body, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Apply | QDialogButtonBox.Cancel
        )
        buttons.setObjectName("MasterEffectsButtons")
        buttons.button(QDialogButtonBox.Apply).setText(tr("应用"))
        buttons.button(QDialogButtonBox.Apply).setProperty("kind", "convert")
        buttons.button(QDialogButtonBox.Cancel).setText(tr("取消"))
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _section(title_text: str, description: str) -> tuple[QFrame, QVBoxLayout]:
        section = QFrame()
        section.setObjectName("SettingsSection")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(16, 14, 16, 15)
        section_layout.setSpacing(9)
        section_layout.setAlignment(Qt.AlignTop)
        title = QLabel(tr(title_text))
        title.setObjectName("SettingsSectionTitle")
        detail = QLabel(tr(description))
        detail.setObjectName("Muted")
        detail.setWordWrap(True)
        section_layout.addWidget(title)
        section_layout.addWidget(detail)
        return section, section_layout

    @staticmethod
    def _effect_grid() -> QGridLayout:
        grid = QGridLayout()
        grid.setContentsMargins(0, 2, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        for column in (1, 3, 5):
            grid.setColumnStretch(column, 1)
        return grid

    @staticmethod
    def _add_field(
        grid: QGridLayout,
        row: int,
        column: int,
        label: str,
        field: QSpinBox,
    ) -> None:
        grid.addWidget(
            QLabel(tr(label)),
            row,
            column,
            alignment=Qt.AlignRight | Qt.AlignVCenter,
        )
        grid.addWidget(field, row, column + 1)

    def _new_field(
        self,
        object_name: str,
        accessible_name: str,
        field_name: str,
        raw_value: int,
        help_text: str,
    ) -> QSpinBox:
        field = QSpinBox()
        field.setObjectName(object_name)
        field.setRange(0, GAME_PERCENT_MAX)
        field.setValue(max(0, min(GAME_PERCENT_MAX, int(raw_value))))
        field.setFixedWidth(92)
        tooltip = tr(help_text)
        if int(raw_value) > GAME_PERCENT_MAX:
            tooltip += "\n" + trf(
                "导入原值 {value}；修改后按 0–100 写入。",
                value=int(raw_value),
            )
        field.setToolTip(tooltip)
        field.setAccessibleName(tr(accessible_name))
        field.valueChanged.connect(
            lambda _value, name=field_name: self._dirty_fields.add(name)
        )
        self._fields[field_name] = field
        return field

    def selected_master_effects(self) -> MasterEffects:
        """Preserve unedited imported bytes above the current UI range."""

        values = {
            "reverb_time": self._original.reverb_time,
            "delay_feedback": self._original.delay_feedback,
            "chorus_feedback": self._original.chorus_feedback,
            "chorus_lfo_depth": self._original.chorus_lfo_depth,
            "chorus_lfo_frequency": self._original.chorus_lfo_frequency,
        }
        for name in self._dirty_fields:
            values[name] = self._fields[name].value()
        return MasterEffects(**values)
