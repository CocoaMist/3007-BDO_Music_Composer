"""Canonical stylesheet mixin for the main BDO composer window."""

from __future__ import annotations

from PySide6.QtGui import QFont

from .fluent_theme import build_fluent_stylesheet, refresh_fluent_icons


class MainWindowStyleMixin:
    def _apply_style(self) -> None:
        self.setFont(QFont("Microsoft YaHei UI", 9))
        style_sheet = """
            QWidget#Root { background: #151515; color: #f3f1ea; }
            QDialog QLabel { color: #ddd7cf; }
            QDialog#SettingsDialog, QDialog#MasterEffectsDialog,
            QDialog#ThanksDialog, QDialog#ReleaseNotesDialog,
            QDialog#MidiNoteEditorDialog {
                background: #151515;
                color: #f3f1ea;
            }
            QFrame[uiRole="dialogHeader"] {
                background: #191919;
                border: 0;
                border-bottom: 1px solid #4a3b27;
                border-radius: 0;
            }
            QWidget#SettingsContent {
                background: #151515;
                border: 0;
            }
            QWidget#MasterEffectsContent {
                background: #151515;
                border: 0;
            }
            QStackedWidget#SettingsPages {
                background: #151515;
                border: 0;
            }
            QListWidget#SettingsNav {
                background: #181818;
                border: 0;
                border-right: 1px solid #302f2d;
                outline: 0;
                padding: 0;
                show-decoration-selected: 1;
            }
            QListWidget#SettingsNav::item {
                background: #181818;
                color: #aaa39a;
                border: 0;
                padding-left: 20px;
                font-weight: 700;
            }
            QListWidget#SettingsNav::item:hover {
                background: #202020;
                color: #e5dfd6;
            }
            QListWidget#SettingsNav::item:selected {
                background: #25211b;
                color: #f0c66f;
                border: 0;
                border-left: 3px solid #f5a524;
                padding-left: 17px;
            }
            QWidget#SettingsGeneralPage, QWidget#SettingsMidiPage,
            QWidget#SettingsAudioPage {
                background: #151515;
            }
            QScrollArea#SettingsScroll, QScrollArea#SettingsMidiScroll,
            QScrollArea#SettingsAudioScroll {
                border: 0;
                background: #151515;
            }
            QScrollArea#SettingsScroll > QWidget > QWidget,
            QScrollArea#SettingsMidiScroll > QWidget > QWidget,
            QScrollArea#SettingsAudioScroll > QWidget > QWidget {
                background: #151515;
            }
            QDialog#SettingsDialog QLabel { color: #ddd7cf; }
            QLabel[uiRole="dialogTitle"] {
                color: #f3f1ea;
                font-size: 22px;
                font-weight: 900;
            }
            QLabel[uiRole="dialogSubtitle"] {
                color: #aaa39a;
                font-size: 11px;
            }
            QFrame#SettingsSection {
                background: transparent;
                border: 0;
                border-bottom: 1px solid #302f2d;
                border-radius: 0;
            }
            QFrame#EffectScopeNotice {
                background: #211e19;
                border: 1px solid #5a4528;
                border-radius: 0;
            }
            QLabel#EffectScopeTitle {
                color: #f0c66f;
                font-weight: 800;
            }
            QLabel#EffectPreviewNote {
                color: #b9a078;
            }
            QLabel[uiRole="sectionTitle"] {
                color: #f0c66f;
                font-size: 14px;
                font-weight: 900;
            }
            QLabel#SettingsFieldLabel { color: #c7c0b8; }
            QLabel#OwnerStatus { color: #bdb6ad; }
            QLabel#OwnerStatus[ownerError="true"] { color: #e06c62; }
            QFrame#SettingsModeRow {
                background: #1a1a1a;
                border: 0;
                border-left: 2px solid #5a4528;
                border-radius: 0;
                padding: 7px 9px;
            }
            QDialog#SettingsDialog QSpinBox,
            QDialog#MasterEffectsDialog QSpinBox {
                min-height: 27px;
                padding: 2px 7px;
            }
            QDialog#SettingsDialog QRadioButton { color: #ddd7cf; spacing: 7px; }
            QDialog#SettingsDialog QRadioButton::indicator {
                width: 14px;
                height: 14px;
                border-radius: 7px;
                border: 1px solid #6a6259;
                background: #1b1b1b;
            }
            QDialog#SettingsDialog QRadioButton::indicator:checked {
                background: #f5a524;
                border: 1px solid #f5a524;
            }
            QFrame[uiRole="dialogFooter"],
            QDialog#MasterEffectsDialog QDialogButtonBox {
                background: #1b1b1b;
                border: 0;
                border-top: 1px solid #34322f;
            }
            QDialogButtonBox[uiRole="dialogButtonRow"] {
                background: transparent;
                border: 0;
                padding: 0;
            }
            QFrame#Panel {
                background: #222222;
                border: 1px solid #343434;
                border-radius: 4px;
            }
            QStackedWidget#MainPages, QWidget#WorkspacePage, QWidget#HomePage {
                background: #1c1c1e;
                border: 0;
            }
            QFrame#HomeShell, QStackedWidget#HomeLibraryStack {
                background: transparent;
                border: 0;
            }
            QFrame#HomeOverlay {
                background: transparent;
                border: 0;
                border-radius: 0;
            }
            QPushButton#HomeOwnerIdButton {
                background: transparent;
                border: 0;
                border-radius: 6px;
                padding: 0;
            }
            QPushButton#HomeNavButton {
                min-height: 34px;
                background: transparent;
                border: 0;
                border-bottom: 1px solid transparent;
                border-radius: 0;
                color: #9b978f;
                padding: 0 8px;
                font-weight: 700;
            }
            QPushButton#HomeNavButton:hover {
                color: #e8e1d6;
                background: rgba(28, 30, 29, 52);
            }
            QPushButton#HomeNavButton:checked {
                color: #e8dfcf;
                background: transparent;
                border-bottom-color: #9f7939;
            }
            QPushButton#HomeNavButton:focus {
                color: #eee6d9;
            }
            QLabel#HomeLocalBadge {
                color: #9a958c;
                background: transparent;
                border: 0;
                border-radius: 0;
                padding: 2px 0 0 0;
                font-size: 11px;
            }
            QWidget#HomeFooter {
                background: transparent;
                border: 0;
            }
            QPushButton#HomeReleaseNotesButton {
                min-height: 20px;
                background: transparent;
                border: 0;
                color: #817d76;
                padding: 2px 0 0 8px;
                font-size: 10px;
            }
            QPushButton#HomeReleaseNotesButton:hover,
            QPushButton#HomeReleaseNotesButton:focus {
                background: transparent;
                border: 0;
                color: #c8b184;
                text-decoration: underline;
            }
            QWidget#HomeHero {
                background: transparent;
                border: 0;
            }
            QLabel#HomeEyebrow {
                color: #e3b653;
                font-size: 10px;
                font-weight: 800;
                letter-spacing: 2px;
            }
            QLabel#HomeTitle {
                color: #eee7db;
                font-size: 24px;
                font-weight: 900;
            }
            QLabel#HomeSubtitle {
                color: #9b958b;
                font-size: 12px;
            }
            QFrame#HomeCommandDeck {
                background: transparent;
                border: 0;
            }
            QPushButton#HomeQuickAction {
                min-height: 42px;
                background: rgba(20, 22, 22, 72);
                border: 1px solid rgba(151, 132, 98, 58);
                border-radius: 0;
                color: #b9b4ac;
                padding: 4px 9px;
                font-weight: 700;
            }
            QPushButton#HomeQuickAction:hover {
                background: rgba(58, 53, 43, 112);
                border-color: rgba(202, 169, 105, 118);
                color: #eee7da;
            }
            QPushButton#HomeQuickAction:focus {
                border-color: #b88a3c;
                color: #f2e9da;
            }
            QPushButton#HomeQuickAction[actionTone="accent"] {
                background: rgba(102, 76, 36, 148);
                border: 1px solid rgba(190, 142, 62, 126);
                color: #f0e7d5;
            }
            QPushButton#HomeQuickAction[actionTone="accent"]:hover {
                background: rgba(118, 88, 40, 184);
            }
            QFrame#HomeLibraryBar {
                background: transparent;
                border: 0;
            }
            QLineEdit#HomeSearch {
                min-height: 34px;
                background: rgba(9, 11, 12, 84);
                border: 1px solid rgba(151, 143, 128, 54);
                border-radius: 0;
                color: #dfd7ca;
                padding: 0 8px;
                selection-background-color: #665129;
            }
            QLineEdit#HomeSearch:focus {
                background: rgba(22, 22, 20, 118);
                border-color: #9f7939;
            }
            QFrame#HomeLibraryBar QPushButton[homeAction="true"] {
                min-height: 34px;
                background: transparent;
                border: 0;
                padding: 0 7px;
            }
            QFrame#HomeCard {
                background: transparent;
                border: 0;
                border-radius: 0;
            }
            QFrame#HomeCard[density="primary"] {
                background: transparent;
                border: 0;
            }
            QLabel#HomeCardTitle {
                color: #ded5c6;
                font-size: 13px;
                font-weight: 900;
            }
            QFrame#HomeCard[density="primary"] QLabel#HomeCardTitle {
                color: #c8b686;
            }
            QLabel#HomeCardSubtitle {
                color: #a89f8e;
                font-size: 11px;
            }
            QLabel#HomeCount {
                min-width: 16px;
                color: #a89872;
                background: transparent;
                border: 0;
                border-radius: 0;
                padding: 0 2px;
                font-size: 11px;
                font-weight: 700;
            }
            QFrame#HomeCard QPushButton[homeAction="true"] {
                min-height: 28px;
                background: transparent;
                border: 0;
                color: #9f9685;
                padding: 0 5px;
            }
            QFrame#HomeCard QPushButton[homeAction="true"]:hover {
                color: #ddd3c1;
                background: rgba(35, 36, 32, 54);
            }
            QListWidget#HomeList {
                background: transparent;
                border: 0;
                border-radius: 0;
                padding: 0;
                outline: 0;
            }
            QListWidget#HomeList:focus {
                border: 0;
                padding: 0;
            }
            QListWidget#HomeList::item {
                color: #ddd8cf;
                background: rgba(16, 18, 19, 38);
                border: 0;
                border-bottom: 1px solid rgba(152, 139, 111, 26);
                border-radius: 0;
                padding: 0;
            }
            QListWidget#HomeList::item:hover {
                background: rgba(49, 48, 42, 72);
            }
            QListWidget#HomeList::item:selected {
                background: rgba(108, 87, 45, 34);
                border: 0;
                border-left: 2px solid #9f7939;
                color: #f1e9dc;
            }
            QFrame#EditorQuantizeQuick {
                background: transparent;
                border: 0;
            }
            QLabel#QuantizeQuickLabel {
                color: #e4c17c;
                font-weight: 800;
            }
            QWidget#HomePage QPushButton[homeAction="true"] {
                border-radius: 0;
            }
            QListWidget#HomeList QScrollBar:vertical {
                width: 8px;
                background: transparent;
                margin: 2px 0;
            }
            QListWidget#HomeList QScrollBar::handle:vertical {
                min-height: 28px;
                background: #6b665b;
                border-radius: 0;
            }
            QListWidget#HomeList QScrollBar::add-line:vertical,
            QListWidget#HomeList QScrollBar::sub-line:vertical {
                height: 0;
            }
            QFrame#Toolbar {
                background: #191919;
                border: 0;
                border-bottom: 1px solid #5a4727;
                border-radius: 0;
            }
            QFrame#Toolbar QFrame#CommandGroup {
                background: transparent;
                border: 0;
                border-radius: 0;
            }
            QFrame#Toolbar QFrame#ToolbarCommandCluster {
                background: transparent;
                border: 0;
            }
            QFrame#Toolbar QPushButton, QFrame#Toolbar QLineEdit {
                border-radius: 0;
                min-height: 29px;
                padding: 3px 10px;
            }
            QFrame#Toolbar QPushButton#EnsembleCapacityBadge {
                min-width: 36px;
                max-width: 36px;
                min-height: 36px;
                max-height: 36px;
                padding: 0;
                background: transparent;
                border: 0;
            }
            QFrame#Toolbar QPushButton[kind="secondary"],
            QFrame#Toolbar QPushButton[kind="primary"] {
                background: transparent;
                border: 0;
                border-bottom: 2px solid transparent;
                color: #c9c1b5;
            }
            QFrame#Toolbar QPushButton[kind="secondary"]:hover,
            QFrame#Toolbar QPushButton[kind="primary"]:hover {
                background: #292722;
                border-bottom-color: #806533;
                color: #fff0cf;
            }
            QFrame#Toolbar QPushButton[kind="primary"] {
                color: #e8c373;
            }
            QFrame#Toolbar QLineEdit {
                background: transparent;
                border: 0;
                border-bottom: 1px solid #5d513c;
                color: #f1e7d6;
            }
            QFrame#Toolbar QLineEdit:focus {
                border-bottom-color: #d6a743;
            }
            QFrame#Toolbar QPushButton[kind="convert"]:disabled {
                background: #292722;
                border-color: #3e392f;
                color: #716a5e;
            }
            QFrame#Toolbar QLabel#ToolbarText {
                padding: 0 6px;
                color: #bdb4a7;
            }
            QFrame#Toolbar QPushButton#ToolbarBadge {
                background: transparent;
                border: 0;
                border-radius: 0;
                padding: 5px 6px;
                color: #d8c7a7;
            }
            QFrame#Toolbar QPushButton#ToolbarBadge:hover,
            QFrame#Toolbar QPushButton#ToolbarBadge:focus {
                background: #26231e;
                color: #f0d99e;
            }
            QFrame#ToolbarSeparator {
                color: #4d4539;
                background: #4d4539;
                min-width: 1px;
                max-width: 1px;
                margin: 7px 3px;
            }
            QFrame#Inspector {
                background: #202020;
                border: 0;
                border-top: 1px solid #393735;
                border-radius: 0;
            }
            QWidget#TimelineWorkspace, QWidget#TimelineCanvas {
                background: #1c1c1e;
                border: 0;
            }
            QFrame#TimelineControlBar {
                background: #2c2c30;
                border: 0;
                border-bottom: 1px solid #735b2d;
                border-radius: 0;
            }
            QFrame#TimelineControlBar QPushButton {
                min-height: 25px;
                padding: 2px 9px;
            }
            QLabel#TimelineMeta {
                color: #c9b798;
                padding: 0 5px;
            }
            QLabel#TimelineControlLabel {
                color: #a78e6a;
                font-size: 10px;
            }
            QFrame#PerformanceStrip {
                background: #1c1c1e;
                border: 0;
                border-top: 1px solid #40351f;
                border-radius: 0;
            }
            QLabel#PerformanceCaption {
                color: #7f7971;
                font-size: 9px;
                font-weight: 700;
            }
            QLabel#PerformanceMetric {
                color: #c9b798;
                font-size: 10px;
                font-family: Consolas, monospace;
            }
            QLabel#EnsembleMetric {
                color: #a9c477;
                font-size: 10px;
                font-weight: 800;
            }
            QLabel#EnsembleMetric[ensembleState="over"] {
                color: #ef8178;
            }
            QFrame#TimelineSeparator {
                color: #413d38;
                max-width: 1px;
                margin: 4px 3px;
            }
            QFrame#TranscriptionToolsSlot {
                background: transparent;
                border: 0;
            }
            QWidget#TranscriptionEditorPanel,
            QWidget#TranscriptionWaveformLane {
                background: #111313;
                border: 0;
            }
            QFrame#TranscriptionAnalysisBar, QFrame#TranscriptionReviewBar,
            QFrame#TranscriptionReviewMoreBar {
                background: #1d1f1f;
                border: 0;
                border-bottom: 1px solid #383733;
                border-radius: 0;
            }
            QFrame#TranscriptionAdvancedPanel {
                background: #151717;
                border: 0;
                border-bottom: 1px solid #383733;
                border-radius: 0;
            }
            QFrame#TranscriptionTuningToolsBar,
            QFrame#TranscriptionCandidateToolsBar,
            QFrame#TranscriptionGuideToolsBar,
            QFrame#TranscriptionAlignmentToolsBar,
            QFrame#TranscriptionDiagnosticLayersBar {
                background: #1a1c1c;
                border: 1px solid #2d302f;
                border-radius: 4px;
            }
            QFrame#TranscriptionDiagnosticLayersBar {
                background: transparent;
                border: 0;
                border-top: 1px solid #30312f;
                border-radius: 0;
            }
            QFrame#TranscriptionReviewBar {
                background: #171919;
                border-top: 1px solid #383733;
                border-bottom: 0;
            }
            QFrame#TranscriptionReviewDisplayGroup,
            QFrame#TranscriptionReviewActionGroup,
            QFrame#TranscriptionReviewCommitGroup {
                background: #1d2020;
                border: 1px solid #303432;
                border-radius: 6px;
            }
            QFrame#TranscriptionReviewMoreBar {
                background: #181a1a;
                border-top: 0;
                border-bottom: 1px solid #383733;
            }
            QLabel#TranscriptionWorkspaceTitle {
                background: transparent;
                border: 0;
                border-right: 1px solid #4d4639;
                border-radius: 0;
                color: #d8c298;
                font-weight: 700;
                padding: 2px 12px 2px 4px;
            }
            QLabel#TranscriptionReviewContext {
                background: #24231f;
                border: 1px solid #4a4438;
                border-radius: 6px;
                color: #e0c996;
                font-weight: 700;
                padding: 5px 9px;
            }
            QFrame#TranscriptionReviewBar QLabel#Muted {
                color: #a5aaa5;
                padding: 2px 6px;
            }
            QLabel#TranscriptionGroupLabel {
                background: transparent;
                border: 0;
                border-right: 1px solid #4d4639;
                border-radius: 0;
                color: #bda97f;
                font-size: 10px;
                font-weight: 700;
                padding: 1px 8px 1px 2px;
            }
            QFrame#TranscriptionAnalysisBar QPushButton,
            QFrame#TranscriptionAdvancedPanel QPushButton,
            QFrame#TranscriptionAdvancedPanel QToolButton,
            QFrame#TranscriptionReviewBar QPushButton,
            QFrame#TranscriptionReviewBar QToolButton,
            QFrame#TranscriptionReviewMoreBar QPushButton,
            QFrame#TranscriptionReviewMoreBar QToolButton {
                min-height: 27px;
                padding: 2px 9px;
                border-radius: 3px;
            }
            QFrame#TranscriptionReviewBar QComboBox {
                min-height: 27px;
                padding: 1px 7px;
                border-radius: 3px;
            }
            QToolButton#TranscriptionCandidateLayerButton:checked {
                background: #263332;
                border-color: #c9963b;
                color: #dcebe7;
            }
            QToolButton#TranscriptionCandidateLayerButton:!checked {
                color: #8f938f;
            }
            QToolButton#TranscriptionPitchGuideButton:checked,
            QToolButton#TranscriptionPitchOnlyButton:checked {
                background: #203447;
                border-color: #529dda;
                color: #d9efff;
            }
            QToolButton#TranscriptionPitchGuideButton:!checked,
            QToolButton#TranscriptionPitchOnlyButton:!checked {
                color: #9aabb7;
            }
            QFrame#EditorToolbar {
                background: #191919;
                border: 0;
                border-bottom: 1px solid #4a3b27;
                border-radius: 0;
            }
            QFrame#EditorToolbar QPushButton {
                min-height: 22px;
                padding: 3px 8px;
            }
            QLabel#EditorTrackTitle {
                color: #ffedd4;
                font-size: 15px;
                font-weight: 900;
            }
            QLabel#EditorTrackMeta {
                color: #b8a487;
                font-size: 10px;
                font-family: Consolas, "Microsoft YaHei UI";
            }
            QLabel#EditorLayerLegend {
                background: transparent;
                border: 0;
                color: #8f8b84;
                font-size: 9px;
                padding-left: 4px;
            }
            QFrame#EditorTransport {
                background: #202022;
                border: 0;
                border-radius: 0;
            }
            QFrame#EditorWorkspace {
                background: #1c1c1e;
                border: 0;
                border-radius: 0;
            }
            QFrame#EditorShortcutHud {
                background: rgba(11, 12, 14, 88);
                border: 1px solid rgba(206, 188, 157, 36);
                border-radius: 5px;
            }
            QLabel#ShortcutHudMode {
                background: transparent;
                border: 0;
                border-bottom: 1px solid rgba(206, 188, 157, 38);
                border-radius: 0;
                color: rgba(220, 196, 151, 180);
                font-size: 9px;
                font-weight: 700;
                padding: 0 0 4px 1px;
            }
            QFrame#EditorShortcutHud[hudMode="draw"] QLabel#ShortcutHudMode {
                color: rgba(185, 205, 153, 185);
            }
            QFrame#ShortcutHudRow {
                background: transparent;
                border: 0;
            }
            QLabel#ShortcutHudKey {
                background: rgba(206, 188, 157, 18);
                border: 1px solid rgba(206, 188, 157, 32);
                border-radius: 3px;
                color: rgba(228, 210, 178, 188);
                font-family: "Microsoft YaHei UI", "Segoe UI";
                font-size: 9px;
                font-weight: 600;
                padding: 1px 5px;
            }
            QLabel#ShortcutHudAction {
                background: transparent;
                border: 0;
                color: rgba(216, 210, 201, 174);
                font-family: "Microsoft YaHei UI", "Segoe UI";
                font-size: 9px;
            }
            QFrame#EditorShortcutHud[shortcutActive="false"] {
                background: rgba(11, 12, 14, 54);
                border-color: rgba(160, 151, 136, 24);
            }
            QFrame#EditorShortcutHud[shortcutActive="false"] QLabel#ShortcutHudMode,
            QFrame#EditorShortcutHud[shortcutActive="false"] QLabel#ShortcutHudAction {
                color: rgba(174, 169, 160, 118);
            }
            QFrame#EditorShortcutHud[shortcutActive="false"] QLabel#ShortcutHudKey {
                background: rgba(150, 145, 136, 10);
                border-color: rgba(150, 145, 136, 20);
                color: rgba(190, 183, 171, 126);
            }
            QDialog#EditorShortcutHelpDialog {
                background: #18191b;
            }
            QLabel#ShortcutHelpTitle {
                color: #f1dfc2;
                font-size: 18px;
                font-weight: 800;
            }
            QLabel#ShortcutHelpScopeNote {
                color: #b8ad9c;
                padding: 0 0 4px 0;
            }
            QScrollArea#ShortcutHelpScroll,
            QWidget#ShortcutHelpContent {
                background: transparent;
                border: 0;
            }
            QFrame#ShortcutHelpGroup {
                background: #202124;
                border: 1px solid #36332e;
                border-radius: 5px;
            }
            QLabel#ShortcutHelpGroupTitle {
                color: #d9b978;
                font-size: 12px;
                font-weight: 800;
                padding-bottom: 3px;
            }
            QLabel#ShortcutHelpKey {
                min-width: 155px;
                color: #ead9bd;
                font-family: "Microsoft YaHei UI", "Segoe UI";
                font-weight: 700;
            }
            QLabel#ShortcutHelpAction {
                color: #d2cec7;
            }
            QPushButton#ShortcutHelpClose {
                min-width: 84px;
            }
            QFrame#VelocityHeader {
                background: #202124;
                border: 0;
                border-top: 1px solid #735b2d;
                border-bottom: 1px solid #34353a;
                border-radius: 0;
                min-height: 32px;
                max-height: 32px;
            }
            QFrame#VelocityPanel {
                background: #1a1b1e;
                border: 0;
            }
            QLabel#VelocityTitle {
                color: #d4c7ad;
                font-weight: 700;
                padding-right: 4px;
            }
            QPushButton#VelocityModeButton {
                min-height: 20px;
                max-height: 20px;
                min-width: 48px;
                padding: 2px 8px;
            }
            QPushButton#VelocityModeButton:checked {
                background: #5c4a28;
                border-color: #caa24f;
                color: #ffedd4;
                font-weight: 800;
            }
            QComboBox#VelocityRadiusCombo, QComboBox#VelocityScopeCombo {
                min-height: 22px;
                max-height: 22px;
                min-width: 104px;
                padding: 1px 24px 1px 7px;
            }
            QFrame#NoteInspectorTop {
                background: #1c1c1e;
                border: 0;
                border-bottom: 1px solid #34322f;
                border-radius: 0;
            }
            QFrame#NoteInspectorTop QPushButton {
                min-height: 18px;
                max-height: 18px;
                padding: 4px 8px;
            }
            QPushButton#InspectorMode:checked {
                background: #5c4a28;
                border-color: #caa24f;
                color: #ffedd4;
                font-weight: 800;
            }
            QPushButton#DrawMode:checked {
                background: #435c31;
                border-color: #83a543;
                color: #f1f4df;
                font-weight: 800;
            }
            QPushButton#VelocityToggle:checked {
                background: #435c31;
                border-color: #83a543;
                color: #f1f4df;
                font-weight: 800;
            }
            QToolButton#TrackReferenceToggle {
                min-height: 24px;
                max-height: 24px;
                padding: 0 7px;
            }
            QToolButton#TrackReferenceToggle:checked {
                background: #314a49;
                border-color: #69aaa4;
                color: #e3f5f2;
                font-weight: 800;
            }
            QLabel#InspectorSelection {
                background: transparent;
                border: 0;
                border-radius: 0;
                color: #e1d4c1;
                padding: 3px 6px;
            }
            QFrame#NoteInspectorTop QLineEdit,
            QFrame#NoteInspectorTop QComboBox {
                min-height: 20px;
                padding: 3px 6px;
            }
            QComboBox#ArticulationCombo {
                border-color: #625337;
                color: #cbbd9f;
                font-weight: 700;
                min-height: 19px;
                max-height: 19px;
            }
            QPushButton#ArticulationPreview {
                background: #262628;
                border: 1px solid #4b4437;
                border-radius: 0;
                min-height: 26px;
                max-height: 26px;
                padding: 0;
            }
            QPushButton#ArticulationPreview:hover {
                background: #34312b;
                border-color: #8d7548;
            }
            QPushButton#ArticulationPreview:disabled {
                background: #202022;
                border-color: #373532;
            }
            QPushButton#ArticulationChip {
                background: #2c2c30;
                border: 1px solid #4b4437;
                border-radius: 0;
                color: #e1d4c1;
                min-height: 24px;
                padding: 1px 6px;
            }
            QPushButton#ArticulationChip:hover { border-color: #8d7548; color: #d8cab0; }
            QPushButton#ArticulationChip:checked {
                background: #463c29;
                border-color: #917744;
                color: #ddd2bd;
                font-weight: 800;
            }
            QLabel#EditorTime {
                color: #e4c17c;
                font-family: Consolas, "Microsoft YaHei UI";
            }
            QFrame#EditorFooter {
                background: #191919;
                border: 0;
                border-top: 1px solid #34322f;
                border-radius: 0;
                max-height: 31px;
            }
            QWidget#EditorToolbarInset,
            QWidget#EditorInspectorInset,
            QWidget#EditorFooterInset {
                background: #151515;
                border: 0;
            }
            QDialog#MidiNoteEditorDialog QFrame#EditorToolbar,
            QDialog#MidiNoteEditorDialog QFrame#EditorTransport,
            QDialog#MidiNoteEditorDialog QFrame#EditorWorkspace,
            QDialog#MidiNoteEditorDialog QFrame#NoteInspectorTop,
            QDialog#MidiNoteEditorDialog QFrame#EditorFooter,
            QDialog#MidiNoteEditorDialog QLabel#InspectorSelection,
            QDialog#MidiNoteEditorDialog QPushButton,
            QDialog#MidiNoteEditorDialog QLineEdit,
            QDialog#MidiNoteEditorDialog QComboBox {
                border-radius: 0;
            }
            QDialog#MidiNoteEditorDialog QComboBox#QuantizeGridCombo {
                background: #262628;
                border: 1px solid #4b4437;
                border-radius: 5px;
                color: #d8d0c4;
                font-weight: 800;
                min-height: 26px;
                max-height: 26px;
                padding: 0 24px 0 9px;
            }
            QDialog#MidiNoteEditorDialog QComboBox#QuantizeGridCombo:hover,
            QDialog#MidiNoteEditorDialog QComboBox#QuantizeGridCombo:focus {
                background: #34312b;
                border-color: #8d7548;
            }
            QDialog#MidiNoteEditorDialog QComboBox#QuantizeGridCombo::drop-down {
                background: #2c2c30;
                border: 0;
                border-left: 1px solid #4b4437;
                border-top-right-radius: 4px;
                border-bottom-right-radius: 4px;
                width: 20px;
            }
            QDialog#MidiNoteEditorDialog QScrollBar::handle {
                border-radius: 0;
            }
            QLabel#PanelTitle {
                color: #f3f1ea;
                font-size: 15px;
                font-weight: 800;
            }
            QLabel#SectionLabel {
                color: #e4c17c;
                font-size: 12px;
                font-weight: 800;
                padding-top: 2px;
            }
            QFrame#OptimizerHeader, QFrame#OptimizerOptions, QTextEdit#OptimizerReport {
                background: #201f1c;
                border: 1px solid #3d3932;
                border-radius: 9px;
            }
            QLabel#OptimizerTitle {
                color: #f5a524;
                font-size: 19px;
                font-weight: 900;
            }
            QLabel#OptimizerSummary {
                color: #d6b675;
                font-size: 12px;
                font-weight: 800;
                padding: 1px 2px;
            }
            QLabel#OptimizerScopeSummary {
                color: #f0d49a;
                font-size: 12px;
                font-weight: 800;
                padding: 2px 0;
            }
            QFrame#OptimizerOptions QCheckBox {
                color: #e5dfd6;
                min-width: 150px;
            }
            QTextEdit#OptimizerReport {
                padding: 7px;
                color: #d6d1c9;
                font-family: Consolas, "Microsoft YaHei UI";
                font-size: 11px;
            }
            QLabel#ToolbarText { color: #c7c0b8; }
            QLabel#Muted { color: #a8a29e; }
            QFrame#ThanksTextPanel {
                background: #151515;
                border: 0;
                border-radius: 0;
            }
            QLabel#ThanksMutedNote {
                color: #aaa39a;
                font-size: 11px;
                line-height: 135%;
            }
            QTextEdit#ThanksText, QTextBrowser#ThanksText {
                background: #151515;
                border: 0;
                border-radius: 0;
                color: #d8d3cc;
                padding: 0;
            }
            QFrame#ReleaseNotesBody {
                background: #151515;
                border: 0;
            }
            QComboBox#ReleaseVersionSelector {
                min-height: 26px;
                padding: 2px 8px;
            }
            QFrame#UpdateStatusCard {
                background: transparent;
                border: 0;
                border-bottom: 1px solid #3d3932;
            }
            QLabel#UpdateStatusTitle {
                color: #aaa39a;
                font-weight: 700;
            }
            QLabel#UpdateStatusTitle[updateState="available"] {
                color: #f0c66f;
            }
            QLabel#UpdateStatusTitle[updateState="ok"] {
                color: #bcd5b5;
            }
            QLabel#UpdateStatusTitle[updateState="error"] {
                color: #ddd7cf;
            }
            QLabel#ReleaseVersionTitle {
                color: #f0c66f;
                font-size: 17px;
                font-weight: 900;
            }
            QLabel#ReleaseDate, QLabel#ReleaseSummary {
                color: #aaa39a;
            }
            QTextBrowser#ReleaseHighlights {
                background: transparent;
                border: 0;
                border-radius: 0;
                color: #d8d3cc;
                padding: 4px 0 0 0;
            }
            QLabel#ToolbarBadge, QPushButton#ToolbarBadge {
                background: #1f1f1f;
                border: 1px solid #313131;
                border-radius: 3px;
                padding: 5px 9px;
                color: #e5dfd6;
            }
            QLabel#CheckCard {
                background: #202020;
                border: 1px solid #3f3a33;
                border-radius: 4px;
                color: #f3f1ea;
                padding: 8px 10px;
                font-weight: 800;
            }
            QLineEdit, QComboBox, QTextEdit {
                background: #1e1e1e;
                border: 1px solid #3a3a3a;
                border-radius: 3px;
                color: #f3f1ea;
                padding: 6px 8px;
                selection-background-color: #8f6b2e;
            }
            QListWidget {
                background: #191919;
                border: 1px solid #3a3834;
                border-radius: 4px;
                color: #ddd7cf;
                outline: 0;
                padding: 4px;
            }
            QListWidget::item {
                border-bottom: 1px solid #2c2b29;
                padding: 8px 7px;
            }
            QListWidget::item:selected {
                background: #4a391f;
                color: #fff3d6;
            }
            QLineEdit:focus, QComboBox:focus, QTextEdit:focus {
                border-color: #d9a441;
            }
            QPushButton {
                background: #2b2b2b;
                border: 1px solid #404040;
                border-radius: 3px;
                color: #f3f1ea;
                padding: 6px 10px;
            }
            QPushButton:hover { background: #343434; border-color: #55504a; }
            QPushButton:checked {
                background: #5d451e;
                border-color: #d9a441;
            }
            QPushButton[kind="primary"] {
                background: #302a20;
                border-color: #7a5a22;
            }
            QPushButton[kind="convert"] {
                background: #f5a524;
                color: #1b1305;
                border-color: #f5a524;
                font-weight: 900;
                min-width: 96px;
            }
            QPushButton[kind="ghost"] {
                background: transparent;
                border-color: #3a3a3a;
                color: #c9c2ba;
            }
            QDialog#SettingsDialog QLineEdit,
            QDialog#SettingsDialog QComboBox,
            QDialog#SettingsDialog QSpinBox,
            QDialog#SettingsDialog QPushButton,
            QDialog#ThanksDialog QPushButton,
            QDialog#ThanksDialog QTextEdit,
            QDialog#ThanksDialog QTextBrowser,
            QDialog#ReleaseNotesDialog QPushButton,
            QDialog#ReleaseNotesDialog QComboBox,
            QDialog#ReleaseNotesDialog QTextBrowser {
                border-radius: 0;
            }
            QDialog#MidiNoteEditorDialog QPushButton[kind="ghost"] {
                background: transparent;
                border-color: transparent;
            }
            QDialog#MidiNoteEditorDialog QPushButton[kind="ghost"]:hover {
                background: #282725;
                border-color: #4a443a;
            }
            QPushButton:disabled {
                color: #8d8780;
                background: #232323;
                border-color: #34322f;
            }
            QCheckBox { color: #d8d3cc; spacing: 7px; }
            QCheckBox::indicator {
                width: 15px;
                height: 15px;
                border-radius: 2px;
                border: 1px solid #56504a;
                background: #1f1f1f;
            }
            QCheckBox::indicator:checked {
                background: #f5a524;
                border-color: #f7c36c;
            }
            QScrollArea {
                border: 0;
                background: transparent;
            }
            QWidget#PianoScrollCorner {
                background: #171918;
            }
            QScrollBar:vertical {
                background: #1b1b1b;
                width: 12px;
                margin: 1px;
                border: 0;
                border-left: 1px solid #2c2b29;
            }
            QScrollBar:horizontal {
                background: #1b1b1b;
                height: 12px;
                margin: 1px;
                border: 0;
                border-top: 1px solid #2c2b29;
            }
            QScrollBar::handle:vertical {
                background: #4a4640;
                min-height: 32px;
                border-radius: 4px;
                margin: 2px 1px;
            }
            QScrollBar::handle:horizontal {
                background: #4a4640;
                min-width: 32px;
                border-radius: 4px;
                margin: 1px 2px;
            }
            QScrollBar::handle:vertical:hover,
            QScrollBar::handle:horizontal:hover {
                background: #766b5e;
            }
            QScrollBar::handle:vertical:pressed,
            QScrollBar::handle:horizontal:pressed {
                background: #b27b25;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
                subcontrol-origin: margin;
                background: transparent;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
                subcontrol-origin: margin;
                background: transparent;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: transparent;
            }
            QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical,
            QScrollBar::left-arrow:horizontal, QScrollBar::right-arrow:horizontal {
                width: 0px;
                height: 0px;
                background: transparent;
            }
            QAbstractScrollArea::corner { background: #1b1b1b; }
            QScrollBar#TimelineScroll:vertical,
            QScrollBar#PianoPitchScroll:vertical {
                background: #171918;
                border-left-color: #292c2a;
            }
            QScrollBar#PianoTimeScroll:horizontal {
                background: #171918;
                border-top-color: #292c2a;
            }
            QScrollBar#TimelineScroll::handle:vertical,
            QScrollBar#PianoPitchScroll::handle:vertical,
            QScrollBar#PianoTimeScroll::handle:horizontal {
                background: #626660;
            }
            QScrollBar#TimelineScroll::handle:vertical:hover,
            QScrollBar#PianoPitchScroll::handle:vertical:hover,
            QScrollBar#PianoTimeScroll::handle:horizontal:hover {
                background: #8b806f;
            }
            QScrollBar#TimelineScroll::handle:vertical:pressed,
            QScrollBar#PianoPitchScroll::handle:vertical:pressed,
            QScrollBar#PianoTimeScroll::handle:horizontal:pressed {
                background: #c58a2d;
            }
            QSlider::groove:horizontal {
                height: 5px;
                background: #3a3a3a;
                border-radius: 0px;
            }
            QSlider::handle:horizontal {
                width: 12px;
                height: 16px;
                margin: -6px 0;
                border-radius: 2px;
                background: #f5a524;
            }
            """
        dark = self._system_uses_dark_theme()
        self.setStyleSheet(build_fluent_stylesheet(style_sheet, dark))
        refresh_fluent_icons(self, dark)
