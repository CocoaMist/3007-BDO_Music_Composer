"""Focused MIDI optimization dialog and its isolated Qt worker."""

from __future__ import annotations

import json
from pathlib import Path
import traceback

from PySide6.QtCore import QObject, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from bdo_midi import BDO_INSTRUMENT_NAMES
from bdo_music_composer.audio.bdo_audio_validation import (
    verified_instrument_articulations,
)
from bdo_music_composer.audio.bdo_sample_renderer import (
    sample_map_evidence_sha256,
)
from bdo_music_composer.app.crash_logging import append_crash_log
from bdo_music_composer.ui.editor.editor_articulation_data import BDO_ARTICULATIONS
from bdo_music_composer.editor.editor_models import (
    BDO_EDITOR_PITCH_RANGES,
    TrackState,
    game_supported_pitches,
)
from bdo_music_composer.ui.i18n import tr, tr_joinv, trf, trfv, trv
from optimization import OptimizerConfig
from optimization.plugin_api import InvalidOptimizationPreview, OptimizationIntensity
from optimization.plugin_host import (
    BUILTIN_SAFE_ID,
    HostOptimizationError,
    analyse_with_algorithm,
    discover_host_algorithms,
    optimizer_plugin_dir,
)
from bdo_music_composer.core.project_paths import (
    USER_DATA_DIR,
    WWISE_MIDI_MAP_PATH,
)


AUDIO_VALIDATION_PATH = USER_DATA_DIR / "out" / "bdo" / "bdo_audio_validation_matrix.json"


_OPTIMIZER_HOST_MESSAGE_SOURCES = {
    "optimizer input contains duplicate track IDs": "优化器输入包含重复轨道 ID",
    "optimizer target scope references an unknown track": "优化目标范围引用了未知轨道",
    "song exceeds the optimizer note limit": "曲目超过优化器音符上限",
    "song exceeds the optimizer beat limit": "曲目超过优化器节拍上限",
    "the editor changed after analysis; analyse again": "分析后工程已变化；请重新分析",
    "preview algorithm identity does not match manifest": "预览算法标识与清单不一致",
    "plugins may not remove complete source tracks": (
        "算法不得删除完整的源轨道"
    ),
    "note pitch, velocity, or ntype is outside the wire range": (
        "音符的音高、力度或 ntype 超出协议范围"
    ),
    "note timing must be finite, non-negative, and non-zero": (
        "音符时间必须有限、非负且时值不为零"
    ),
    "derived drum notes require BDO pitch 48..64 and ntype=99": (
        "派生鼓音必须使用 BDO 音高 48..64 和 ntype=99"
    ),
    "preview may not duplicate or invent unsupported manual articulations": (
        "预览不得复制或新增不受支持的手动奏法"
    ),
    "preview may not add noncanonical drum pitches or note types": (
        "预览不得新增非规范鼓音高或音符类型"
    ),
    "drum tracks must use the canonical BDO drum-set instrument": (
        "鼓轨必须使用规范的 BDO 架子鼓乐器"
    ),
    "whole-track and indexed note operations may not be mixed": (
        "不得混用整轨操作与按索引音符操作"
    ),
    "preview source fingerprint does not match its request": (
        "预览源指纹与请求不一致"
    ),
    "a preview may set each source instrument only once": (
        "预览对每个源乐器只能设置一次"
    ),
    "a preview may contain only one global effect change": (
        "预览最多只能包含一次全局效果修改"
    ),
    "single-track optimization may not write global effects": (
        "单轨优化不得写入全局效果"
    ),
    "effect values must be in [0, 100]": "效果值必须在 [0, 100] 范围内",
    "single-track optimization may not create tracks": (
        "单轨优化不得创建轨道"
    ),
    "derived tracks must contain at least one note": (
        "派生轨道必须至少包含一个音符"
    ),
    "derived track references an unknown source track": (
        "派生轨道引用了未知源轨道"
    ),
    "preview exceeds the host song-note limit": (
        "预览超过主程序的曲目音符上限"
    ),
    "cannot materialize notes without a host Note prototype": (
        "缺少主程序 Note 原型，无法生成音符"
    ),
    "cannot create a derived track without a source track": (
        "缺少源轨道，无法创建派生轨道"
    ),
    "bundle contains too many files": "算法包包含过多文件",
    "bundle expands beyond the 16 GiB limit": "算法包解压后超过 16 GiB 上限",
    "bundle is missing manifest.json": "算法包缺少 manifest.json",
    "manifest root must be an object": "算法包清单根节点必须是对象",
    "plugin_id must be a stable lowercase identifier": (
        "plugin_id 必须是稳定的小写标识符"
    ),
    "version must be a path-safe identifier": "version 必须是路径安全的标识符",
    "intensities and scopes must be arrays": "intensities 和 scopes 必须是数组",
    "capabilities must be an array": "capabilities 必须是数组",
    "requires_safe_prepass must be a boolean": (
        "requires_safe_prepass 必须是布尔值"
    ),
    "plugins must support conservative, balanced, and deep": (
        "算法必须支持 conservative、balanced 和 deep"
    ),
    "plugin scopes are invalid": "算法 scopes 无效",
    "entrypoint must use module:function": "entrypoint 必须使用 module:function 格式",
    "entrypoint contains an invalid Python identifier": (
        "entrypoint 包含无效的 Python 标识符"
    ),
    "display_name must not be empty": "display_name 不能为空",
    "bundle is missing payload/": "算法包缺少 payload/ 目录",
    "external algorithm descriptor has no bundle": "外部算法描述缺少算法包",
    "optimizer plugin returned an incompatible preview object": (
        "优化算法返回了不兼容的预览对象"
    ),
    "plugin object must provide analyse(request, environment)": (
        "算法对象必须提供 analyse(request, environment)"
    ),
    "duplicate plugin ID; all copies disabled": "算法 ID 重复；所有副本均已禁用",
}

def _optimizer_host_message_value(message: object) -> object:
    """Translate recognized host validation text, never plugin-owned output."""

    text = str(message)
    source = _OPTIMIZER_HOST_MESSAGE_SOURCES.get(text)
    if source is not None:
        return trv(source)
    prefixed_sources = (
        ("cannot read optimizer bundle: ", "无法读取优化算法包：{value}"),
        ("unsafe bundle path: ", "算法包包含不安全路径：{value}"),
        (
            "symbolic links are not allowed in bundles: ",
            "算法包不允许符号链接：{value}",
        ),
        ("manifest fields invalid; ", "算法包清单字段无效：{value}"),
        ("unsupported bundle schema: ", "不支持的算法包 schema：{value}"),
        ("unsupported optimizer API: ", "不支持的优化器 API：{value}"),
        ("entrypoint is not callable: ", "entrypoint 不可调用：{value}"),
        ("unknown BDO instrument ID: ", "未知 BDO 乐器 ID：{value}"),
        ("stale note replacement for track ", "轨道 {value} 的音符替换已过期"),
        ("insert index outside track ", "插入索引超出轨道 {value} 的范围"),
        ("note index outside track ", "音符索引超出轨道 {value} 的范围"),
        (
            "stale indexed note operation for track ",
            "轨道 {value} 的索引音符操作已过期",
        ),
        (
            "duplicate indexed note operation for track ",
            "轨道 {value} 存在重复的索引音符操作",
        ),
        (
            "operation writes outside target scope: ",
            "操作写入了目标范围外的轨道：{value}",
        ),
        (
            "stale instrument replacement for track ",
            "轨道 {value} 的乐器替换已过期",
        ),
    )
    for prefix, template in prefixed_sources:
        if text.startswith(prefix):
            return trfv(template, value=text[len(prefix):])
    infixed_sources = (
        (
            "pitch ",
            " is unsupported for BDO instrument ",
            "音高 {value} 不受 BDO 乐器 {instrument_id} 支持",
        ),
        (
            "ntype ",
            " is unsupported for BDO instrument ",
            "ntype {value} 不受 BDO 乐器 {instrument_id} 支持",
        ),
    )
    for prefix, separator, template in infixed_sources:
        if not text.startswith(prefix):
            continue
        value, found, instrument_id = text[len(prefix):].partition(separator)
        if found and value and instrument_id:
            return trfv(
                template,
                value=value,
                instrument_id=instrument_id,
            )
    return text

def _optimizer_diagnostic_value(message: object) -> object:
    text = str(message)
    item, separator, reason = text.partition(": ")
    if not separator:
        return _optimizer_host_message_value(text)
    reason_value = _optimizer_host_message_value(reason)
    if isinstance(reason_value, str) and reason_value == reason:
        return text
    return trfv("{item}: {reason}", item=item, reason=reason_value)

class OptimizerAnalysisWorker(QThread):
    """Run optimizer code away from the GUI thread."""

    succeeded = Signal(object)
    failed = Signal(str, str, bool)

    def __init__(self, arguments: tuple, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.arguments = arguments

    def run(self) -> None:
        try:
            session = analyse_with_algorithm(*self.arguments)
        except Exception as exc:
            self.failed.emit(
                str(exc) or type(exc).__name__,
                traceback.format_exc(),
                isinstance(exc, HostOptimizationError),
            )
        else:
            self.succeeded.emit(session)

class MidiOptimizeDialog(QDialog):
    """Small host UI over the versioned optimizer-plugin contract."""

    INTENSITIES = (
        ("保守", OptimizationIntensity.CONSERVATIVE),
        ("均衡", OptimizationIntensity.BALANCED),
        ("深入", OptimizationIntensity.DEEP),
    )

    def __init__(
        self,
        parent: "MidiToBdoWindow",
        target_track_id: int | None = None,
        source_tracks: list[TrackState] | None = None,
        *,
        scope_locked: bool = False,
    ) -> None:
        super().__init__(parent)
        self.parent_window = parent
        self.target_track_id = target_track_id
        self.scope_locked = bool(scope_locked)
        self.source_tracks = list(source_tracks) if source_tracks is not None else parent.tracks
        self.track_checks: dict[int, QCheckBox] = {}
        self.available_algorithms = ()
        self.algorithms = ()
        self.discovery_diagnostics: tuple[str, ...] = ()
        self.session = None
        self._applied_result = None
        self._analysis_started_once = False
        self._analysis_error: tuple[str, bool, bool] | None = None
        self.analysis_worker: OptimizerAnalysisWorker | None = None
        self.setObjectName("MidiOptimizeDialog")
        self.setProperty("uiSurface", "workflow")
        self.setWindowTitle(tr("MIDI 优化"))
        self.resize(820, 430)
        self.setMinimumSize(720, 410)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(10)

        header_card = QFrame()
        header_card.setObjectName("OptimizerHeader")
        header_card.setProperty("uiRole", "dialogHeader")
        header = QVBoxLayout(header_card)
        header.setContentsMargins(16, 12, 16, 12)
        header.setSpacing(4)
        title = QLabel(tr("MIDI 优化"))
        title.setObjectName("OptimizerTitle")
        header.addWidget(title)
        subtitle = QLabel(tr(
            "选择作用范围，分析预览后再应用；不会跳过游戏安全校验。"
        ))
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        header.addWidget(subtitle)
        layout.addWidget(header_card)

        scope_card = QFrame()
        scope_card.setObjectName("OptimizerOptions")
        scope_card.setProperty("uiRole", "workflowSection")
        scope_selector = QGridLayout(scope_card)
        scope_selector.setContentsMargins(14, 12, 14, 12)
        scope_selector.setHorizontalSpacing(10)
        scope_selector.setVerticalSpacing(6)
        scope_selector.addWidget(QLabel(tr("优化范围")), 0, 0)
        self.scope_combo = QComboBox()
        self._populate_scope_combo()
        self.scope_combo.setEnabled(not self.scope_locked)
        scope_selector.addWidget(self.scope_combo, 0, 1, 1, 3)
        self.scope_summary_label = QLabel()
        self.scope_summary_label.setObjectName("OptimizerScopeSummary")
        self.scope_summary_label.setWordWrap(True)
        scope_selector.addWidget(self.scope_summary_label, 1, 0, 1, 4)
        self.scope_help_label = QLabel()
        self.scope_help_label.setObjectName("Muted")
        self.scope_help_label.setWordWrap(True)
        scope_selector.addWidget(self.scope_help_label, 2, 0, 1, 4)
        layout.addWidget(scope_card)

        selector_card = QFrame()
        selector_card.setObjectName("OptimizerOptions")
        selector_card.setProperty("uiRole", "workflowSection")
        selector = QGridLayout(selector_card)
        selector.setContentsMargins(14, 12, 14, 12)
        selector.setHorizontalSpacing(10)
        selector.addWidget(QLabel(tr("优化算法")), 0, 0)
        self.algorithm_combo = QComboBox()
        # Built-ins use catalog source keys; individual third-party rows are
        # skipped so a plugin name that happens to equal a UI word stays exact.
        self.algorithm_combo.currentIndexChanged.connect(self._algorithm_changed)
        selector.addWidget(self.algorithm_combo, 0, 1, 1, 3)
        self.open_plugins_button = QPushButton(tr("算法包目录"))
        self.open_plugins_button.clicked.connect(self._open_plugin_directory)
        selector.addWidget(self.open_plugins_button, 0, 4)
        self.refresh_plugins_button = QPushButton(tr("刷新"))
        self.refresh_plugins_button.clicked.connect(self._reload_algorithms)
        selector.addWidget(self.refresh_plugins_button, 0, 5)
        selector.addWidget(QLabel(tr("优化强度")), 1, 0)
        self.intensity_combo = QComboBox()
        for label, value in self.INTENSITIES:
            self.intensity_combo.addItem(tr(label), value.value)
        self.intensity_combo.setCurrentIndex(1)
        self.intensity_combo.currentIndexChanged.connect(self._invalidate_preview)
        selector.addWidget(self.intensity_combo, 1, 1, 1, 2)
        self.algorithm_description = QLabel()
        self.algorithm_description.setWordWrap(True)
        self.algorithm_description.setObjectName("Muted")
        selector.addWidget(self.algorithm_description, 2, 0, 1, 6)
        layout.addWidget(selector_card)

        self.summary_label = QLabel(tr("选择算法和强度，然后分析优化。"))
        self.summary_label.setObjectName("OptimizerSummary")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        self.analyse_button = QPushButton(tr("分析优化"))
        self.analyse_button.setProperty("kind", "primary")
        self.analyse_button.clicked.connect(self._analyse)
        action_row.addWidget(self.analyse_button)
        layout.addLayout(action_row)

        self.details_button = QPushButton(tr("详细信息 ▸"))
        self.details_button.setCheckable(True)
        self.details_button.toggled.connect(self._toggle_details)
        layout.addWidget(self.details_button)

        self.details_container = QWidget()
        details = QVBoxLayout(self.details_container)
        details.setContentsMargins(0, 0, 0, 0)
        self.capability_label = QLabel()
        self.capability_label.setWordWrap(True)
        self.capability_label.setObjectName("Muted")
        details.addWidget(self.capability_label)

        scope_card = QFrame()
        scope_card.setObjectName("OptimizerOptions")
        scope_layout = QGridLayout(scope_card)
        scope_layout.setContentsMargins(12, 8, 12, 8)
        self.global_scope_header = QLabel(tr("允许写入的轨道"))
        scope_layout.addWidget(self.global_scope_header, 0, 0, 1, 2)
        for index, track in enumerate(self.source_tracks):
            box = QCheckBox(trf(
                "轨道 {track_id} · {track}",
                track_id=track.track_id,
                track=track.display_name,
            ))
            box.setChecked(True)
            box.stateChanged.connect(self._invalidate_preview)
            self.track_checks[int(track.track_id)] = box
            scope_layout.addWidget(box, 1 + index // 2, index % 2)
        self.single_scope_label = QLabel()
        self.single_scope_label.setWordWrap(True)
        scope_layout.addWidget(
            self.single_scope_label,
            1 + (len(self.source_tracks) + 1) // 2,
            0,
            1,
            2,
        )
        details.addWidget(scope_card)

        self.report_text = QTextEdit()
        self.report_text.setReadOnly(True)
        self.report_text.setObjectName("OptimizerReport")
        details.addWidget(self.report_text, stretch=1)
        layout.addWidget(self.details_container)

        buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        self.button_box = buttons
        self.apply_button = buttons.button(QDialogButtonBox.Apply)
        self.apply_button.setText(tr("应用预览"))
        self.apply_button.setEnabled(False)
        buttons.button(QDialogButtonBox.Cancel).setText(tr("取消"))
        self.apply_button.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.scope_combo.currentIndexChanged.connect(self._scope_changed)
        self._update_scope_presentation()
        self._toggle_details(False)
        self._reload_algorithms()

    def _scope_token(self) -> str:
        return (
            "global"
            if self.target_track_id is None
            else f"track:{int(self.target_track_id)}"
        )

    def _populate_scope_combo(self) -> None:
        selected_token = self._scope_token()
        self.scope_combo.blockSignals(True)
        self.scope_combo.clear()
        self.scope_combo.addItem(tr("整个工程"), "global")
        selected_index = 0
        known_track_ids: set[int] = set()
        for track in self.source_tracks:
            track_id = int(track.track_id)
            known_track_ids.add(track_id)
            token = f"track:{track_id}"
            self.scope_combo.addItem(
                trf(
                    "单轨 · Track {track_id} · {track}",
                    track_id=track_id,
                    track=track.display_name,
                ),
                token,
            )
            if token == selected_token:
                selected_index = self.scope_combo.count() - 1
        if (
            self.target_track_id is not None
            and int(self.target_track_id) not in known_track_ids
        ):
            token = f"track:{int(self.target_track_id)}"
            self.scope_combo.addItem(
                trf(
                    "单轨 · Track {track_id} · {track}",
                    track_id=int(self.target_track_id),
                    track=trv("未知轨道"),
                ),
                token,
            )
            selected_index = self.scope_combo.count() - 1
        self.scope_combo.setCurrentIndex(selected_index)
        self.scope_combo.setProperty(
            "i18nSkipItemIndexes",
            tuple(range(self.scope_combo.count())),
        )
        self.scope_combo.blockSignals(False)

    def _scope_changed(self, _index: int = -1) -> None:
        token = str(self.scope_combo.currentData() or "global")
        if token.startswith("track:"):
            try:
                self.target_track_id = int(token.partition(":")[2])
            except ValueError:
                self.target_track_id = None
        else:
            self.target_track_id = None
        self._update_scope_presentation()
        self._filter_algorithms_for_scope()

    def _scope_track(self) -> TrackState | None:
        if self.target_track_id is None:
            return None
        return next(
            (
                track
                for track in self.source_tracks
                if int(track.track_id) == int(self.target_track_id)
            ),
            None,
        )

    def _update_scope_presentation(self) -> None:
        global_scope = self.target_track_id is None
        self.global_scope_header.setVisible(global_scope)
        for box in self.track_checks.values():
            box.setVisible(global_scope)
        self.single_scope_label.setVisible(not global_scope)
        if global_scope:
            self.scope_help_label.setText(tr(
                "全局模式读取全部轨道；静音和独奏不改变作用域，"
                "可在“详细信息”中限制允许写入的轨道。"
            ))
        else:
            track = self._scope_track()
            target_name = track.display_name if track else trv("未知轨道")
            self.single_scope_label.setText(trf(
                "目标：Track {track_id} · {track}",
                track_id=self.target_track_id,
                track=target_name,
            ))
            scope_help = (
                "范围锁定为当前草稿轨道；读取全曲上下文，但只写入该轨道。"
                if self.scope_locked
                else "读取全曲乐理与配器上下文，但只写入当前轨道。"
            )
            self.scope_help_label.setText(tr(scope_help))
        self._update_scope_summary()

    @property
    def scope(self) -> str:
        return "single_track" if self.target_track_id is not None else "global"

    def _target_track_ids(self) -> frozenset[int]:
        if self.target_track_id is not None:
            return frozenset({self.target_track_id})
        return frozenset(track_id for track_id, box in self.track_checks.items() if box.isChecked())

    def _selected_algorithm(self):
        return self.algorithm_combo.currentData()

    def _selected_intensity(self) -> OptimizationIntensity:
        return OptimizationIntensity(str(self.intensity_combo.currentData()))

    def _reload_algorithms(self) -> None:
        discovery = discover_host_algorithms()
        self.discovery_diagnostics = discovery.diagnostics
        self.available_algorithms = tuple(discovery.algorithms)
        self._filter_algorithms_for_scope()

    def _filter_algorithms_for_scope(self) -> None:
        """Filter cached descriptors without rescanning algorithm packages."""

        previous = getattr(self._selected_algorithm(), "algorithm_id", None)
        self.algorithms = tuple(
            item
            for item in self.available_algorithms
            if self.scope in item.scopes
        )
        self.algorithm_combo.blockSignals(True)
        self.algorithm_combo.clear()
        selected_index = 0
        skipped_item_indexes: list[int] = []
        for index, descriptor in enumerate(self.algorithms):
            display_name = descriptor.localized_display_name(
                tr,
                format_translate=trf,
            )
            self.algorithm_combo.addItem(display_name, descriptor)
            if descriptor.algorithm_id != BUILTIN_SAFE_ID:
                skipped_item_indexes.append(index)
            if descriptor.algorithm_id == previous:
                selected_index = index
        if self.algorithms:
            self.algorithm_combo.setCurrentIndex(selected_index)
        self.algorithm_combo.setProperty(
            "i18nSkipItemIndexes",
            tuple(skipped_item_indexes),
        )
        self.algorithm_combo.blockSignals(False)
        self._algorithm_changed()

    def _algorithm_changed(self, _index: int = -1) -> None:
        descriptor = self._selected_algorithm()
        if descriptor is None:
            self.algorithm_description.setProperty("i18nSkipText", False)
            self.algorithm_description.setText(tr("没有可用的优化算法。"))
            self.capability_label.clear()
            self.analyse_button.setEnabled(False)
        else:
            builtin = descriptor.algorithm_id == BUILTIN_SAFE_ID
            self.algorithm_description.setProperty("i18nSkipText", False)
            prepass = (
                trv(" · 先运行游戏安全预处理")
                if descriptor.requires_safe_prepass
                else ""
            )
            description = (
                trv(descriptor.description)
                if builtin
                else descriptor.description
            )
            self.algorithm_description.setText(trf(
                "{description}{prepass}",
                description=description,
                prepass=prepass,
            ))
            capability_sources = descriptor.localized_capabilities()
            scope_sources = descriptor.localized_scopes()
            capabilities = (
                tr_joinv(
                    capability_sources,
                    translate_values=builtin,
                )
                if capability_sources
                else trv("诊断")
            )
            scopes = tr_joinv(scope_sources, translate_values=builtin)
            self.capability_label.setText(trf(
                "版本 {version} · 能力：{capabilities} · 作用域：{scopes}",
                version=descriptor.version,
                capabilities=capabilities,
                scopes=scopes,
            ))
            self.analyse_button.setEnabled(True)
        self._invalidate_preview()

    def _invalidate_preview(self, _value: int = 0) -> None:
        self._update_scope_summary()
        self.session = None
        self._applied_result = None
        self._analysis_error = None
        self.apply_button.setEnabled(False)
        self._render_idle_preview()

    def _render_idle_preview(self) -> None:
        if self._selected_algorithm() is None:
            self.summary_label.setText(tr("没有可用的优化算法。"))
        elif self.analysis_worker is not None:
            self.summary_label.setText(tr("正在分析优化…"))
        elif self._analysis_started_once:
            self.summary_label.setText(tr("设置已更新，点击分析优化刷新预览。"))
        else:
            self.summary_label.setText(tr("选择算法和强度，然后分析优化。"))
        diagnostics = [
            trf(
                "算法包：{item}",
                item=_optimizer_diagnostic_value(item),
            )
            for item in self.discovery_diagnostics
        ]
        self.report_text.setPlainText("\n".join(diagnostics))

    def _update_scope_summary(self) -> None:
        if self.target_track_id is None:
            selected = len(self._target_track_ids())
            self.scope_summary_label.setText(trf(
                "整个工程 · 可写轨道 {selected}/{total} · 可调整全局效果",
                selected=selected,
                total=len(self.source_tracks),
            ))
            return
        self.scope_summary_label.setText(trf(
            "单轨 · Track {track_id} · 读取全曲上下文 · 不修改全局效果",
            track_id=self.target_track_id,
        ))

    def _toggle_details(self, visible: bool) -> None:
        self.details_container.setVisible(visible)
        self.details_button.setText(
            tr("详细信息 ▾" if visible else "详细信息 ▸")
        )
        self.resize(820, 720 if visible else 430)

    def _base_config(self) -> OptimizerConfig:
        supported_pitches = {
            instrument_id: pitches
            for instrument_id in BDO_EDITOR_PITCH_RANGES
            if (pitches := game_supported_pitches(instrument_id))
        }
        verified_articulations = set()
        if (
            AUDIO_VALIDATION_PATH.is_file()
            and WWISE_MIDI_MAP_PATH.is_file()
        ):
            try:
                payload = json.loads(AUDIO_VALIDATION_PATH.read_text(encoding="utf-8"))
                verified_articulations = set(
                    verified_instrument_articulations(
                        payload,
                        sample_map_evidence_sha256(WWISE_MIDI_MAP_PATH),
                    )
                )
            except (OSError, ValueError, TypeError, KeyError):
                verified_articulations = set()
        return OptimizerConfig(
            target_track_ids=self._target_track_ids(),
            supported_pitches=supported_pitches,
            verified_articulations=frozenset(verified_articulations),
            lyric_events=[dict(event) for event in self.parent_window.lyric_events],
            current_reverb=self.parent_window.reverb,
            current_delay=self.parent_window.delay,
            current_chorus=self.parent_window.chorus,
            allow_global_effect_write=self.target_track_id is None,
        )

    def _analyse(self) -> None:
        if self.analysis_worker is not None:
            return
        descriptor = self._selected_algorithm()
        if descriptor is None:
            return
        if not self._target_track_ids():
            self.summary_label.setText(tr("请至少选择一条允许写入的轨道。"))
            return
        self._analysis_started_once = True
        self._set_analysis_busy(True)
        self.summary_label.setText(tr("正在分析优化…"))
        arguments = (
            descriptor,
            self.source_tracks,
            self.parent_window.bpm_override or self.parent_window.bpm,
            self.parent_window.time_sig,
            BDO_ARTICULATIONS,
            self._base_config(),
            self._selected_intensity(),
            self.scope,
            frozenset(BDO_INSTRUMENT_NAMES),
        )
        worker = OptimizerAnalysisWorker(arguments, self)
        self.analysis_worker = worker
        worker.succeeded.connect(self._analysis_succeeded)
        worker.failed.connect(self._analysis_failed)
        worker.finished.connect(self._analysis_finished)
        worker.start()

    def _set_analysis_busy(self, busy: bool) -> None:
        self.analyse_button.setEnabled(not busy and self._selected_algorithm() is not None)
        self.scope_combo.setEnabled(not busy and not self.scope_locked)
        self.algorithm_combo.setEnabled(not busy)
        self.intensity_combo.setEnabled(not busy)
        self.open_plugins_button.setEnabled(not busy)
        self.refresh_plugins_button.setEnabled(not busy)
        for box in self.track_checks.values():
            box.setEnabled(not busy)
        cancel_button = self.button_box.button(QDialogButtonBox.Cancel)
        cancel_button.setEnabled(not busy)

    def _analysis_succeeded(self, session: object) -> None:
        self.session = session
        self._analysis_error = None
        self._render_analysis_session()

    def _render_analysis_session(self) -> None:
        session = self.session
        if session is None:
            return
        preview = session.localized_preview(tr, format_translate=trf)
        preview_summary = preview.summary or tr("分析完成")
        self.summary_label.setText(trf(
            "{summary} · 修改操作 {count}",
            summary=preview_summary,
            count=len(preview.operations),
        ))
        lines = list(preview.details)
        lines.extend(trf("诊断：{item}", item=item) for item in preview.diagnostics)
        lines.extend(
            trf(
                "算法包：{item}",
                item=_optimizer_diagnostic_value(item),
            )
            for item in self.discovery_diagnostics
        )
        if not lines:
            lines.append(tr("当前输入没有需要应用的修改。"))
        self.report_text.setPlainText("\n".join(lines))
        self.apply_button.setEnabled(bool(preview.operations))

    def _render_analysis_failure(self) -> None:
        if self._analysis_error is None:
            return
        message, builtin, host_owned = self._analysis_error
        message_value = (
            _optimizer_host_message_value(message)
            if host_owned
            else message
        )
        self.summary_label.setText(trf(
            "分析失败：{message}",
            message=message_value,
        ))
        guidance = (
            tr("安全优化未应用任何修改。请先运行转换检查；处理阻断项后再试。")
            if builtin
            else tr("算法未应用任何修改。请检查算法包，或切换到 BDO 游戏安全优化。")
        )
        self.report_text.setPlainText(f"{guidance}\n\n{message_value}")
        self.apply_button.setEnabled(False)

    def retranslate_dynamic_content(self) -> None:
        """Re-render structured preview text after a live locale switch."""

        self._populate_scope_combo()
        self._update_scope_presentation()
        if self.session is not None:
            self._render_analysis_session()
        elif self._analysis_error is not None:
            self._render_analysis_failure()
        else:
            self._render_idle_preview()

    def _analysis_failed(
        self,
        message: str,
        traceback_text: str,
        host_owned: bool = False,
    ) -> None:
        descriptor = self._selected_algorithm()
        builtin = descriptor is not None and descriptor.bundle is None
        append_crash_log(
            "Built-in optimizer analysis failed"
            if builtin
            else "Optimizer plugin analysis failed",
            traceback_text,
        )
        self.session = None
        self._analysis_error = (message, builtin, bool(host_owned))
        self._render_analysis_failure()

    def _analysis_finished(self) -> None:
        worker = self.analysis_worker
        self.analysis_worker = None
        self._set_analysis_busy(False)
        if worker is not None:
            worker.deleteLater()

    def reject(self) -> None:
        if self.analysis_worker is not None:
            return
        super().reject()

    def _open_plugin_directory(self) -> None:
        directory = optimizer_plugin_dir()
        directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    def optimized_tracks(self) -> list[TrackState]:
        if self.session is None:
            raise InvalidOptimizationPreview("no analysed optimization preview is available")
        if self._applied_result is None:
            self._applied_result = self.session.apply(self.source_tracks)
        return self._applied_result[0]

    def optimized_effects(self) -> tuple[int, int, tuple[int, int, int] | None] | None:
        if self.session is None:
            return None
        if self._applied_result is None:
            self._applied_result = self.session.apply(self.source_tracks)
        effect = self._applied_result[1]
        if effect is None:
            return None
        return effect.reverb, effect.delay, effect.chorus
