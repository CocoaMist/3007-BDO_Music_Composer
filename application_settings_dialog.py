"""Application settings dialog and its background import worker.

The main window supplies current values through a deliberately small structural
contract.  Accepted values are still applied by the window, keeping persistence
and playback lifecycle out of the dialog layer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, cast

from PySide6.QtCore import QObject, QThread, Qt, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from audio_source_settings import (
    classify_audio_source,
    default_game_music_dir,
    displayed_audio_source,
    preview_source_mode,
)
from bdo_sample_pack import PACK_SUFFIX
from bdo_score import read_bdo_score
from i18n import LANGUAGE_CHOICES, tr, trf
from project_paths import GAME_ART_CACHE_DIR, USER_DATA_DIR
from tools.import_bdo_game_art import (
    GameArtImportError,
    import_game_instrument_art,
)
from ui_controls import PillButton
from ui_notifications import show_global_toast


DEFAULT_OUTDIR = USER_DATA_DIR / "out" / "bdo"


class SettingsHost(Protocol):
    language: str
    char_name: str
    bpm_override: int | None
    transpose: int
    output_dir_path: str
    game_music_dir_path: str
    owner_id: int
    apply_sustain: bool
    flatten_tempo: bool
    velocity_mode: str
    vel_step: tuple[int, int] | int | None
    vel_floor: int | None
    vel_range: tuple[int, int] | None
    audio_sources: dict[str, str]
    instrument_art_dir: str


class GameArtImportWorker(QThread):
    """Decrypt the allow-listed game sprite into a local cache off the GUI thread."""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        paz_root: str | Path,
        cache_root: str | Path,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.paz_root = Path(paz_root)
        self.cache_root = Path(cache_root)

    def run(self) -> None:
        try:
            report = import_game_instrument_art(
                self.paz_root,
                self.cache_root,
            )
        except (OSError, GameArtImportError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc) or type(exc).__name__)
        else:
            self.succeeded.emit(report)

class SettingsDialog(QDialog):
    def __init__(self, parent: SettingsHost) -> None:
        super().__init__(cast(QWidget, parent))
        self.game_art_worker: GameArtImportWorker | None = None
        self._game_art_pending_paz_root = ""
        self.selected_paz_root = str(
            parent.audio_sources.get("paz_root", "") or ""
        )
        self.setObjectName("SettingsDialog")
        self.setProperty("uiSurface", "utility")
        self.setWindowTitle(tr("设置"))
        self.setModal(True)
        self.resize(920, 680)
        self.setMinimumSize(760, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("SettingsHeader")
        header.setProperty("uiRole", "dialogHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(24, 14, 24, 13)
        header_layout.setSpacing(2)
        title = QLabel(tr("设置"))
        title.setObjectName("SettingsTitle")
        title.setProperty("uiRole", "dialogTitle")
        subtitle = QLabel(
            tr("导出、解析、试听与界面设置；保存后立即应用相关更改。")
        )
        self.settings_subtitle = subtitle
        subtitle.setWordWrap(True)
        subtitle.setObjectName("Muted")
        subtitle.setProperty("uiRole", "dialogSubtitle")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        layout.addWidget(header)

        content = QWidget()
        content.setObjectName("SettingsContent")
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self.settings_nav = QListWidget()
        self.settings_nav.setObjectName("SettingsNav")
        self.settings_nav.setProperty("i18nTranslateItems", True)
        self.settings_nav.setFixedWidth(164)
        self.settings_nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.settings_nav.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.settings_pages = QStackedWidget()
        self.settings_pages.setObjectName("SettingsPages")
        general_scroll, general_page_layout = self._settings_page(
            "SettingsScroll", "SettingsGeneralPage"
        )
        midi_scroll, midi_page_layout = self._settings_page(
            "SettingsMidiScroll", "SettingsMidiPage"
        )
        audio_scroll, audio_page_layout = self._settings_page(
            "SettingsAudioScroll", "SettingsAudioPage"
        )
        for label, page in (
            (tr("通用与导出"), general_scroll),
            (tr("MIDI 与力度"), midi_scroll),
            (tr("音源与外观"), audio_scroll),
        ):
            self.settings_nav.addItem(label)
            self.settings_pages.addWidget(page)
        self.settings_nav.currentRowChanged.connect(self.settings_pages.setCurrentIndex)
        self.settings_nav.setCurrentRow(0)
        content_layout.addWidget(self.settings_nav)
        content_layout.addWidget(self.settings_pages, stretch=1)
        layout.addWidget(content, stretch=1)

        general, general_layout = self._section(
            "基础导出",
            "角色名会写入乐谱；BPM 与移调会在导出时应用。",
        )
        form = self._form_layout()
        general_layout.addLayout(form)
        general_page_layout.addWidget(general)

        self.language = QComboBox()
        self.language.setProperty("i18nSkipItems", True)
        for code, label in LANGUAGE_CHOICES:
            self.language.addItem(tr(label), code)
        language_index = self.language.findData(parent.language)
        self.language.setCurrentIndex(language_index if language_index >= 0 else 0)
        form.addRow(tr("界面语言"), self.language)

        self.char_name = QLineEdit(parent.char_name)
        form.addRow(tr("写入角色名"), self.char_name)

        self.bpm_override = QSpinBox()
        self.bpm_override.setRange(0, 240)
        self.bpm_override.setSpecialValueText(tr("使用 MIDI"))
        self.bpm_override.setValue(parent.bpm_override or 0)
        form.addRow(tr("BPM 覆盖"), self.bpm_override)

        self.transpose = QSpinBox()
        self.transpose.setRange(-48, 48)
        self.transpose.setSuffix(tr(" 半音"))
        self.transpose.setValue(parent.transpose)
        form.addRow(tr("移调"), self.transpose)

        output, output_layout = self._section(
            "输出目录",
            "分别设置导出保存位置和游戏曲谱安装位置。",
        )
        general_page_layout.addWidget(output)
        output_row = QHBoxLayout()
        output_row.setContentsMargins(0, 0, 0, 0)
        output_row.setSpacing(6)
        self.output_dir = QLineEdit(parent.output_dir_path)
        self.output_dir.setObjectName("OutputDirectoryEdit")
        self.output_dir.setPlaceholderText(tr("输出目录"))
        output_row.addWidget(self.output_dir, stretch=1)
        browse_output = PillButton(tr("选择"), "secondary")
        browse_output.setObjectName("BrowseOutputDirectoryButton")
        browse_output.clicked.connect(self._browse_output_folder)
        output_row.addWidget(browse_output)
        open_output = PillButton(tr("打开"), "ghost")
        open_output.setObjectName("OpenOutputDirectoryButton")
        open_output.clicked.connect(self._open_output_folder)
        output_row.addWidget(open_output)
        output_layout.addLayout(output_row)

        game_music_row = QHBoxLayout()
        game_music_row.setContentsMargins(0, 0, 0, 0)
        game_music_row.setSpacing(6)
        self.game_music_dir = QLineEdit(parent.game_music_dir_path)
        self.game_music_dir.setObjectName("GameMusicDirectoryEdit")
        self.game_music_dir.setPlaceholderText(tr("游戏曲谱目录"))
        game_music_row.addWidget(self.game_music_dir, stretch=1)
        browse_game_music = PillButton(tr("选择"), "secondary")
        browse_game_music.setObjectName("BrowseGameMusicDirectoryButton")
        browse_game_music.clicked.connect(self._browse_game_music_folder)
        game_music_row.addWidget(browse_game_music)
        open_game_music = PillButton(tr("打开"), "ghost")
        open_game_music.setObjectName("OpenGameMusicDirectoryButton")
        open_game_music.clicked.connect(self._open_game_music_folder)
        game_music_row.addWidget(open_game_music)
        output_layout.addLayout(
            self._labeled_row("游戏曲谱目录", game_music_row)
        )

        owner, owner_layout = self._section(
            "游戏编辑权限",
            "选择一份游戏内保存的曲谱，读取角色名和 Owner ID。",
        )
        general_page_layout.addWidget(owner)
        self.owner_id = parent.owner_id
        owner_row = QHBoxLayout()
        self.owner_load_button = PillButton(tr("从游戏曲谱读取"), "secondary")
        self.owner_load_button.setMinimumWidth(124)
        self.owner_load_button.setMaximumWidth(220)
        self.owner_load_button.clicked.connect(self._load_owner_id)
        self.owner_status = QLabel()
        self.owner_status.setObjectName("OwnerStatus")
        self.owner_status.setWordWrap(True)
        self.owner_status.setMinimumWidth(0)
        self.owner_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        owner_row.addWidget(self.owner_load_button, alignment=Qt.AlignTop)
        owner_row.addWidget(self.owner_status, stretch=1)
        owner_layout.addLayout(owner_row)
        self._refresh_owner_status()

        parsing, parsing_layout = self._section(
            "MIDI 解析",
            "这两项会影响 MIDI 读入方式；修改后会重新载入当前文件。",
        )
        midi_page_layout.addWidget(parsing)
        self.apply_sustain = QCheckBox(tr("读取并展开 MIDI sustain 踏板"))
        self.apply_sustain.setChecked(parent.apply_sustain)
        parsing_layout.addWidget(self.apply_sustain)

        self.flatten_tempo = QCheckBox(tr("忽略中途 tempo 变化，按主 BPM 拉平"))
        self.flatten_tempo.setChecked(parent.flatten_tempo)
        parsing_layout.addWidget(self.flatten_tempo)

        velocity, vel_layout = self._section(
            "力度处理",
            "选择一种输出力度策略；下方仅显示当前策略需要的参数。",
        )
        midi_page_layout.addWidget(velocity)
        modes = QFrame()
        modes.setObjectName("SettingsModeRow")
        modes_layout = QGridLayout(modes)
        modes_layout.setContentsMargins(0, 0, 0, 0)
        for column in range(5):
            modes_layout.setColumnStretch(column, 1)
        vel_layout.setSpacing(9)
        self.vel_radios: dict[str, QRadioButton] = {
            "layered": QRadioButton(tr("分层")),
            "stepped": QRadioButton(tr("阶梯")),
            "rescale": QRadioButton(tr("重映射")),
            "floor": QRadioButton(tr("抬底")),
            "off": QRadioButton(tr("禁用")),
        }
        for column, (mode, radio) in enumerate(self.vel_radios.items()):
            radio.setChecked(parent.velocity_mode == mode)
            radio.toggled.connect(self._sync_velocity_controls)
            modes_layout.addWidget(radio, 0, column)
        vel_layout.addWidget(modes)

        self.vel_step_base = QSpinBox()
        self.vel_step_base.setRange(0, 127)
        step_base = parent.vel_step[0] if isinstance(parent.vel_step, tuple) else (parent.vel_floor or 36)
        step_size = parent.vel_step[1] if isinstance(parent.vel_step, tuple) else (parent.vel_step or 12)
        self.vel_step_base.setValue(step_base)
        self.vel_step = QSpinBox()
        self.vel_step.setRange(1, 64)
        self.vel_step.setValue(step_size)
        step_row = QHBoxLayout()
        step_row.addWidget(QLabel(tr("底")))
        step_row.addWidget(self.vel_step_base)
        step_row.addWidget(QLabel(tr("步长")))
        step_row.addWidget(self.vel_step)
        self.vel_step_row = QWidget()
        self.vel_step_row.setLayout(self._labeled_row("阶梯参数", step_row))
        vel_layout.addWidget(self.vel_step_row)

        self.vel_min = QSpinBox()
        self.vel_min.setRange(1, 127)
        self.vel_min.setValue((parent.vel_range or (28, 112))[0])
        self.vel_max = QSpinBox()
        self.vel_max.setRange(1, 127)
        self.vel_max.setValue((parent.vel_range or (28, 112))[1])
        range_row = QHBoxLayout()
        range_row.addWidget(QLabel(tr("最小")))
        range_row.addWidget(self.vel_min)
        range_row.addWidget(QLabel(tr("最大")))
        range_row.addWidget(self.vel_max)
        self.vel_range_row = QWidget()
        self.vel_range_row.setLayout(self._labeled_row("重映射范围", range_row))
        vel_layout.addWidget(self.vel_range_row)

        self.vel_floor = QSpinBox()
        self.vel_floor.setRange(0, 127)
        self.vel_floor.setValue(parent.vel_floor or 36)
        floor_row = QHBoxLayout()
        floor_row.addWidget(self.vel_floor)
        floor_row.addStretch(1)
        self.vel_floor_row = QWidget()
        self.vel_floor_row.setLayout(self._labeled_row("抬底值", floor_row))
        vel_layout.addWidget(self.vel_floor_row)

        audio, audio_layout = self._section(
            "本地音源包",
            "切换或锁定试听音源；仅用于本机试听，不会写入曲谱，也不会上传。",
        )
        audio_page_layout.addWidget(audio)
        self.preview_mode = QComboBox()
        self.preview_mode.setProperty("i18nSkipItems", True)
        for label, mode in (
            ("自动选择音源", "auto"),
            ("锁定本地 BDO 音源", "bdo"),
            ("锁定内置通用 MIDI", "generic"),
        ):
            self.preview_mode.addItem(tr(label), mode)
        preview_mode_index = self.preview_mode.findData(
            preview_source_mode(parent.audio_sources)
        )
        self.preview_mode.setCurrentIndex(max(0, preview_mode_index))
        preview_mode_form = self._form_layout()
        preview_mode_form.addRow(tr("试听音源"), self.preview_mode)
        audio_layout.addLayout(preview_mode_form)
        self.audio_source = QLineEdit(displayed_audio_source(parent.audio_sources))
        self.audio_source.setReadOnly(True)
        self.audio_source.setPlaceholderText(tr("未选择"))
        audio_source_row = QWidget()
        audio_source_layout = QHBoxLayout(audio_source_row)
        audio_source_layout.setContentsMargins(0, 0, 0, 0)
        audio_source_layout.setSpacing(6)
        audio_source_layout.addWidget(self.audio_source, stretch=1)
        sample_pack_button = PillButton(tr("音源包"), "secondary")
        sample_pack_button.setToolTip(tr("选择 .bdosamples 音源包"))
        sample_pack_button.clicked.connect(self._browse_sample_pack)
        audio_source_layout.addWidget(sample_pack_button)
        audio_folder_button = PillButton(tr("文件夹"), "secondary")
        audio_folder_button.setToolTip(tr("选择已准备好的本地 BDO 音源目录"))
        audio_folder_button.clicked.connect(self._browse_audio_folder)
        audio_source_layout.addWidget(audio_folder_button)
        clear_audio_button = PillButton(tr("清除"), "ghost")
        clear_audio_button.clicked.connect(self.audio_source.clear)
        audio_source_layout.addWidget(clear_audio_button)
        audio_layout.addWidget(audio_source_row)

        self.instrument_art_dir = QLineEdit(parent.instrument_art_dir)
        self.instrument_art_dir.setReadOnly(True)
        self.instrument_art_dir.setPlaceholderText(tr("内置原创图标"))
        art_source_row = QWidget()
        art_source_layout = QHBoxLayout(art_source_row)
        art_source_layout.setContentsMargins(0, 0, 0, 0)
        art_source_layout.setSpacing(6)
        art_source_layout.addWidget(self.instrument_art_dir, stretch=1)
        art_folder_button = PillButton(tr("轨道背景"), "secondary")
        art_folder_button.setToolTip(
            tr("选择本地乐器图片目录；未设置时使用内置原创图标")
        )
        art_folder_button.clicked.connect(self._browse_instrument_art_folder)
        art_source_layout.addWidget(art_folder_button)
        self.game_art_button = PillButton(tr("游戏图"), "secondary")
        self.game_art_button.setToolTip(
            tr("从本机游戏 PAZ 解密乐器图；只写入本地缓存")
        )
        self.game_art_button.clicked.connect(self._import_game_art)
        art_source_layout.addWidget(self.game_art_button)
        clear_art_button = PillButton(tr("清除"), "ghost")
        clear_art_button.clicked.connect(self.instrument_art_dir.clear)
        art_source_layout.addWidget(clear_art_button)
        audio_layout.addWidget(art_source_row)

        general_page_layout.addStretch(1)
        midi_page_layout.addStretch(1)
        audio_page_layout.addStretch(1)

        self.settings_buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.settings_buttons.setObjectName("SettingsButtons")
        self.settings_buttons.setProperty("uiRole", "dialogButtonRow")
        self.settings_buttons.button(QDialogButtonBox.Ok).setText(tr("保存设置"))
        self.settings_buttons.button(QDialogButtonBox.Ok).setProperty("kind", "convert")
        self.settings_buttons.button(QDialogButtonBox.Cancel).setText(tr("取消"))
        self.settings_buttons.accepted.connect(self.accept)
        self.settings_buttons.rejected.connect(self.reject)
        self.settings_footer = QFrame()
        self.settings_footer.setObjectName("SettingsFooter")
        self.settings_footer.setProperty("uiRole", "dialogFooter")
        settings_footer_layout = QHBoxLayout(self.settings_footer)
        settings_footer_layout.setContentsMargins(24, 10, 24, 10)
        settings_footer_layout.setSpacing(0)
        settings_footer_layout.addWidget(self.settings_buttons)
        layout.addWidget(self.settings_footer)
        self._sync_velocity_controls()

    @staticmethod
    def _settings_page(
        scroll_name: str,
        page_name: str,
    ) -> tuple[QScrollArea, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setObjectName(scroll_name)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        page = QWidget()
        page.setObjectName(page_name)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(22, 6, 24, 24)
        page_layout.setSpacing(0)
        page_layout.setAlignment(Qt.AlignTop)
        scroll.setWidget(page)
        return scroll, page_layout

    @staticmethod
    def _section(title_text: str, description: str) -> tuple[QFrame, QVBoxLayout]:
        section = QFrame()
        section.setObjectName("SettingsSection")
        section.setProperty("uiRole", "settingsSection")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 16, 0, 20)
        layout.setSpacing(8)
        # Grid rows take the height of their taller neighbour; keep each
        # section's own controls anchored directly below its description.
        layout.setAlignment(Qt.AlignTop)
        title = QLabel(tr(title_text))
        title.setObjectName("SettingsSectionTitle")
        title.setProperty("uiRole", "sectionTitle")
        detail = QLabel(tr(description))
        detail.setObjectName("Muted")
        detail.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(detail)
        return section, layout

    @staticmethod
    def _form_layout() -> QFormLayout:
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignTop)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(9)
        return form

    @staticmethod
    def _labeled_row(label_text: str, row: QHBoxLayout) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        label = QLabel(tr(label_text))
        label.setObjectName("SettingsFieldLabel")
        label.setMinimumWidth(84)
        label.setMaximumWidth(180)
        label.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Preferred,
        )
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(label)
        layout.addLayout(row, stretch=1)
        return layout

    def selected_velocity_mode(self) -> str:
        for mode, radio in self.vel_radios.items():
            if radio.isChecked():
                return mode
        return "layered"

    def _browse_output_folder(self) -> None:
        current = self.output_dir.text().strip()
        start = current if current and Path(current).is_dir() else ""
        selected = QFileDialog.getExistingDirectory(
            self,
            tr("选择输出目录"),
            start,
        )
        if selected:
            self.output_dir.setText(selected)

    def _open_output_folder(self) -> None:
        directory = Path(self.output_dir.text().strip() or DEFAULT_OUTDIR)
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(
                self,
                tr("输出目录不可用"),
                str(exc),
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory.resolve())))

    def _browse_game_music_folder(self) -> None:
        current = self.game_music_dir.text().strip()
        start = current if current and Path(current).is_dir() else ""
        selected = QFileDialog.getExistingDirectory(
            self,
            tr("选择游戏曲谱目录"),
            start,
        )
        if selected:
            self.game_music_dir.setText(selected)

    def _open_game_music_folder(self) -> None:
        directory = Path(
            self.game_music_dir.text().strip() or default_game_music_dir()
        ).expanduser()
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(
                self,
                tr("游戏曲谱目录不可用"),
                str(exc),
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory.resolve())))

    def _browse_sample_pack(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self, tr("选择本地音源包"), self.audio_source.text(), f"BDO Sample Pack (*{PACK_SUFFIX})"
        )
        if selected:
            self.audio_source.setText(selected)

    def _browse_audio_folder(self) -> None:
        current = self.audio_source.text().strip()
        start = current if current and Path(current).is_dir() else ""
        selected = QFileDialog.getExistingDirectory(
            self,
            tr("选择本地音源目录"),
            start,
        )
        if selected:
            self.audio_source.setText(selected)

    def _browse_instrument_art_folder(self) -> None:
        current = self.instrument_art_dir.text().strip()
        start = current if current and Path(current).is_dir() else ""
        selected = QFileDialog.getExistingDirectory(
            self,
            tr("选择乐器背景目录"),
            start,
        )
        if selected:
            self.instrument_art_dir.setText(selected)

    def _import_game_art(self) -> None:
        if self.game_art_worker is not None:
            return
        current = self.selected_paz_root.strip()
        start = current if current and Path(current).is_dir() else ""
        selected = QFileDialog.getExistingDirectory(
            self,
            tr("选择游戏 PAZ 目录"),
            start,
        )
        if not selected:
            return
        self._game_art_pending_paz_root = selected
        worker = GameArtImportWorker(
            selected,
            GAME_ART_CACHE_DIR,
            self,
        )
        self.game_art_worker = worker
        self.game_art_button.setEnabled(False)
        self.game_art_button.setText(tr("解密中…"))
        for role in (QDialogButtonBox.Ok, QDialogButtonBox.Cancel):
            button = self.settings_buttons.button(role)
            if button is not None:
                button.setEnabled(False)
        worker.succeeded.connect(self._game_art_import_succeeded)
        worker.failed.connect(self._game_art_import_failed)
        worker.finished.connect(self._game_art_import_finished)
        worker.start()

    def _game_art_import_succeeded(self, report: object) -> None:
        output_dir = str(getattr(report, "output_dir", "") or "")
        image_count = int(getattr(report, "image_count", 0) or 0)
        if output_dir:
            self.instrument_art_dir.setText(output_dir)
            self.selected_paz_root = self._game_art_pending_paz_root
        show_global_toast(
            self,
            trf("已解密 {count} 张游戏乐器图", count=image_count),
            kind="success",
        )

    def _game_art_import_failed(self, detail: str) -> None:
        QMessageBox.warning(
            self,
            tr("游戏图不可用"),
            trf("无法读取游戏乐器图：{detail}", detail=detail),
        )

    def _game_art_import_finished(self) -> None:
        worker = self.game_art_worker
        self.game_art_worker = None
        self._game_art_pending_paz_root = ""
        self.game_art_button.setText(tr("游戏图"))
        self.game_art_button.setEnabled(True)
        for role in (QDialogButtonBox.Ok, QDialogButtonBox.Cancel):
            button = self.settings_buttons.button(role)
            if button is not None:
                button.setEnabled(True)
        if worker is not None:
            worker.deleteLater()

    def reject(self) -> None:
        if self.game_art_worker is not None:
            show_global_toast(self, tr("正在解密游戏图"))
            return
        super().reject()

    def accept(self) -> None:
        """Keep the dialog open until all local path fields are usable."""

        if self.game_art_worker is not None:
            show_global_toast(self, tr("正在解密游戏图"))
            return
        output_dir = Path(
            self.output_dir.text().strip() or DEFAULT_OUTDIR
        ).expanduser()
        if output_dir.exists() and not output_dir.is_dir():
            self.settings_nav.setCurrentRow(0)
            self.output_dir.setFocus()
            QMessageBox.warning(
                self,
                tr("输出目录不可用"),
                tr("请选择有效的输出目录。"),
            )
            return
        game_music_dir = Path(
            self.game_music_dir.text().strip() or default_game_music_dir()
        ).expanduser()
        if game_music_dir.exists() and not game_music_dir.is_dir():
            self.settings_nav.setCurrentRow(0)
            self.game_music_dir.setFocus()
            QMessageBox.warning(
                self,
                tr("游戏曲谱目录不可用"),
                tr("请选择有效的游戏曲谱目录。"),
            )
            return
        art_value = self.instrument_art_dir.text().strip()
        if art_value and not Path(art_value).is_dir():
            self.settings_nav.setCurrentRow(2)
            self.instrument_art_dir.setFocus()
            QMessageBox.warning(
                self,
                tr("背景目录不可用"),
                tr("请选择有效的本地乐器图片目录。"),
            )
            return
        try:
            classify_audio_source(self.audio_source.text().strip())
        except ValueError:
            self.settings_nav.setCurrentRow(2)
            self.audio_source.setFocus()
            QMessageBox.warning(
                self,
                tr("音源不可用"),
                tr("请选择 .bdosamples 音源包或本地音源文件夹。"),
            )
            return
        super().accept()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.game_art_worker is not None:
            event.ignore()
            show_global_toast(self, tr("正在解密游戏图"))
            return
        super().closeEvent(event)

    def _refresh_owner_status(self, error: str = "") -> None:
        if error:
            self.owner_status.setText(error)
            self.owner_status.setProperty("ownerError", True)
        elif self.owner_id:
            self.owner_status.setText(trf("已读取 Owner ID：0x{owner_id:08x}", owner_id=self.owner_id))
            self.owner_status.setProperty("ownerError", False)
        else:
            self.owner_status.setText(
                tr("未读取 Owner ID；导出的曲谱无法在游戏内编辑。")
            )
            self.owner_status.setProperty("ownerError", False)
        self.owner_status.style().unpolish(self.owner_status)
        self.owner_status.style().polish(self.owner_status)

    def _load_owner_id(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("选择游戏内保存的曲谱文件"),
            self.game_music_dir.text().strip() or str(default_game_music_dir()),
            tr("黑色沙漠曲谱文件 (*);;所有文件 (*.*)"),
        )
        if not path:
            return
        try:
            snapshot = read_bdo_score(Path(path), allow_trailing_data=True)
            owner_id = int(snapshot.owner_id)
            char_name = snapshot.character_name_1 or snapshot.character_name_2
            if owner_id == 0:
                self._refresh_owner_status(
                    tr("未读取到有效 Owner ID，请选择游戏内保存的曲谱。")
                )
                return
        except ValueError:
            self._refresh_owner_status(
                tr("文件无法读取；请使用游戏内保存的曲谱。")
            )
            return
        except Exception as exc:
            self._refresh_owner_status(trf("读取失败：{error}", error=exc))
            return
        self.owner_id = owner_id
        if char_name:
            self.char_name.setText(char_name)
        self._refresh_owner_status()

    def _sync_velocity_controls(self) -> None:
        mode = self.selected_velocity_mode()
        step_enabled = mode == "stepped"
        range_enabled = mode == "rescale"
        floor_enabled = mode in {"floor", "stepped"}
        for widget in (self.vel_step_base, self.vel_step):
            widget.setEnabled(step_enabled)
        for widget in (self.vel_min, self.vel_max):
            widget.setEnabled(range_enabled)
        self.vel_floor.setEnabled(floor_enabled)
        self.vel_step_row.setVisible(step_enabled)
        self.vel_range_row.setVisible(range_enabled)
        self.vel_floor_row.setVisible(floor_enabled)
