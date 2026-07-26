"""Lightweight runtime localization for the PySide desktop interface."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
import logging
from weakref import WeakKeyDictionary

from PySide6.QtCore import QEvent, QLocale, QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QSpinBox,
    QTabWidget,
    QWidget,
)

from bdo_midi.instruments import GM_PROGRAM_NAMES
from gm_program_translations import GM_PROGRAM_TRANSLATIONS


_LOGGER = logging.getLogger(__name__)


LANGUAGES = (
    ("zh_CN", "简体中文"),
    ("en_US", "English"),
    ("ja_JP", "日本語"),
    ("ko_KR", "한국어"),
)
AUTO_LANGUAGE = ("auto", "自动（跟随系统）")
LANGUAGE_CHOICES = (AUTO_LANGUAGE, *LANGUAGES)


@dataclass(frozen=True, slots=True)
class TranslatableValue:
    """A fixed nested token that follows the active locale inside ``trf``.

    Ordinary ``trf`` values are opaque project/runtime data.  Callers must use
    this wrapper explicitly for host-owned enum labels embedded in a larger
    formatted message; the wrapper is retained in the live-switch registry and
    therefore renders again in the newly selected language.
    """

    source: str

    def __str__(self) -> str:
        return tr(self.source)

    def __format__(self, format_spec: str) -> str:
        return format(tr(self.source), format_spec)


@dataclass(frozen=True, slots=True)
class TranslatableFormatValue:
    """A nested fixed template whose runtime values stay opaque."""

    template: str
    values: tuple[tuple[str, object], ...]

    def _render(self) -> str:
        return tr(self.template).format(**dict(self.values))

    def __str__(self) -> str:
        return self._render()

    def __format__(self, format_spec: str) -> str:
        return format(self._render(), format_spec)


@dataclass(frozen=True, slots=True)
class TranslatableJoinedValue:
    """A locale-aware list with either fixed or opaque item values."""

    values: tuple[object, ...]
    separator_source: str = "、"
    translate_values: bool = False

    def _render(self) -> str:
        values = (
            tuple(tr(str(value)) for value in self.values)
            if self.translate_values
            else tuple(str(value) for value in self.values)
        )
        return tr(self.separator_source).join(values)

    def __str__(self) -> str:
        return self._render()

    def __format__(self, format_spec: str) -> str:
        return format(self._render(), format_spec)


def detect_language_from_timezone(
    timezone_name: str | None = None,
    utc_offset_minutes: int | None = None,
) -> str:
    """Map the local system timezone to the closest supported UI language."""
    if timezone_name is None and utc_offset_minutes is None:
        # Locale is a better signal than UTC offset for international users in
        # Singapore, Malaysia, the Philippines, and other UTC+8 regions.
        system_locale = str(QLocale.system().name() or "").casefold()
        if system_locale.startswith("zh"):
            return "zh_CN"
        if system_locale.startswith("ja"):
            return "ja_JP"
        if system_locale.startswith("ko"):
            return "ko_KR"
        return "en_US"
    if timezone_name is None or utc_offset_minutes is None:
        local_now = datetime.now().astimezone()
        timezone_name = timezone_name or str(local_now.tzinfo or local_now.tzname() or "")
        offset = local_now.utcoffset()
        if utc_offset_minutes is None:
            utc_offset_minutes = round(offset.total_seconds() / 60) if offset else 0
    normalized = timezone_name.casefold().replace("_", "/")
    if any(token in normalized for token in ("asia/shanghai", "asia/chongqing", "asia/hong/kong", "asia/taipei", "china standard", "cst-china")):
        return "zh_CN"
    if any(token in normalized for token in ("asia/tokyo", "tokyo standard", "japan standard", "jst")):
        return "ja_JP"
    if any(token in normalized for token in ("asia/seoul", "korea standard", "kst")):
        return "ko_KR"
    return "en_US"


def resolve_language(language: str) -> str:
    return detect_language_from_timezone() if language == "auto" else language


EN = {
    "双击打开游戏曲谱；主页扫描不读取身份信息": "Double-click to open a game score; the home scan does not read identity data",
    "打开游戏曲谱失败": "Unable to Open Game Score", "无法读取游戏曲谱：{error}": "Unable to read game score: {error}",
    "游戏曲谱已打开": "Game score opened",
    "已打开游戏曲谱：{file} · {tracks} 轨 · {notes} 音符": "Opened game score: {file} · {tracks} tracks · {notes} notes",
    "项目": "Projects", "本地工程与最近打开的 MIDI": "Local projects and recently opened MIDI files",
    "暂无项目": "No projects yet",
    "主页": "Home", "曲谱主页": "Score Home", "刷新": "Refresh", "打开目录": "Open Folder",
    "游戏曲谱": "Game Scores", "本地项目": "Local Projects", "最近使用": "Recent",
    "从游戏曲谱、本地工程或最近使用中快速开始": "Start from game scores, local projects, or recent files",
    "仅列出本地文件，不读取曲谱中的身份信息": "Lists local files only; identity data inside scores is not read",
    "双击项目即可继续编辑": "Double-click a project to continue editing",
    "双击 MIDI 或工程即可打开": "Double-click a MIDI file or project to open it",
    "未找到游戏曲谱": "No game scores found", "未找到本地项目": "No local projects found",
    "暂无最近记录": "No recent items",
    "设置": "Settings", "致谢": "Credits", "转换": "Export", "时间轴": "Timeline",
    "导入 MIDI": "Import MIDI", "打开工程": "Open Project", "新建项目": "New Project", "全局优化": "Optimize All",
    "项目名称": "Project name", "未命名项目": "Untitled Project",
    "{project} · 空白项目": "{project} · Blank Project", "空白项目已创建": "Blank project created",
    "空白项目已创建；双击轨道即可添加音符。": "Blank project created; double-click the track to add notes.",
    "新建轨道 1": "New Track 1", "新建轨道 1 · {instrument}": "New Track 1 · {instrument}",
    "新建轨道 {track_id}": "New Track {track_id}",
    "播放": "Play", "暂停": "Pause", "继续": "Resume", "停止": "Stop",
    "新建轨道": "New Track", "删除轨道": "Delete Track", "清除 Solo": "Clear Solo",
    "取消静音": "Unmute All", "等待 MIDI": "Waiting for MIDI", "未导入 MIDI": "No MIDI imported",
    "曲谱名": "Score name", "就绪": "Ready", "音符属性": "Note Properties",
    "音高": "Pitch", "开始 ms": "Start ms", "时值 ms": "Duration ms", "力度": "Velocity",
    "奏法": "Musical Technique", "色板": "Palette", "吸附": "Snap", "量化": "Quantize",
    "缩放": "Zoom", "撤销": "Undo", "重做": "Redo", "删除": "Delete",
    "位置": "Position", "输出": "Output", "打开": "Open", "输出目录": "Output folder",
    "显示全部时间轴": "Fit the full timeline", "时间轴缩放": "Timeline zoom",
    "时间轴位置": "Timeline position",
    "拖动曲线点调整力度；越近的时间点影响越大。滚轮调整影响范围。": "Drag a curve point to change velocity; nearby time points receive more influence. Use the wheel to adjust the range.",
    "影响 {beats:.1f} 拍": "Influence {beats:.1f} beats",
    "力度曲线影响范围：前后 {beats:.1f} 拍": "Velocity curve influence: ±{beats:.1f} beats",
    "优化此轨": "Optimize Track", "应用": "Apply", "确定": "OK", "取消": "Cancel",
    "关闭": "Close", "普通": "Normal", "延音": "Sustain", "弱音": "Mute",
    "泛音": "Harmonic", "滑音": "Glissando", "三连音": "Triplet",
    "向上滑动": "Slide Up", "滑弦下降": "Slide Down", "滑音上升": "Rising Glissando",
    "剪切": "Cut", "标签": "Accent Tag", "颤音小调": "Minor Trill",
    "大调和弦": "Major Chord", "和弦小调": "Minor Chord", "拍弦": "Slap",
    "基础导出": "Basic Export", "通用与导出": "General & Export",
    "MIDI 与力度": "MIDI & Velocity", "音源与效果": "Audio & Effects",
    "写入角色名": "Character Name", "使用 MIDI": "Use MIDI",
    "BPM 覆盖": "BPM Override", "移调": "Transpose", " 半音": " semitones",
    "游戏编辑权限": "In-game Edit Permission", "从游戏曲谱读取": "Load from Game Score",
    "MIDI 解析": "MIDI Parsing", "读取并展开 MIDI sustain 踏板": "Read and expand MIDI sustain pedal",
    "忽略中途 tempo 变化，按主 BPM 拉平": "Ignore tempo changes and flatten to the main BPM",
    "力度处理": "Velocity Processing", "分层": "Layered", "阶梯": "Stepped",
    "重映射": "Rescale", "抬底": "Raise Floor", "禁用": "Off",
    "底": "Base", "步长": "Step", "阶梯参数": "Step Parameters", "最小": "Minimum",
    "最大": "Maximum", "重映射范围": "Rescale Range", "抬底值": "Floor Value",
    "MIDI 效果": "MIDI Effects", "混响": "Reverb", "延迟": "Delay",
    "游戏主效果": "Effector", "混响时间": "Reverb Time",
    "延迟反馈": "Delay Feedback", "混响发送": "Reverb Send",
    "延迟发送": "Delay Send", "合唱发送": "Chorus Send",
    "合唱反馈": "Chorus Feedback", "LFO 深度": "LFO Depth",
    "LFO 频率": "LFO Frequency", "音源模式": "Source Mode",
    "Basic 默认；其他模式待验证": "Basic by default; other modes need verification",
    "游戏参数 · 本地试听不模拟 FX": "Game parameters · FX is not simulated locally",
    "每轨发送在轨道 FX；本地试听不模拟。": "Per-track sends are under AuxSend; local preview does not simulate them.",
    "导入原值 {value}；修改后按 0–100 写入。": "Imported value {value}; edits use 0–100.",
    "深度": "Depth", "频率": "Frequency",
    "保存设置": "Save Settings", "界面语言": "Interface Language",
    "仅用于本机近似试听，不会写入曲谱，也不会上传。": "Used only for approximate local preview; it is never written to scores or uploaded.",
    "优化等级": "Optimization Level", "曲风": "Style", "歌词表达": "Lyric Expression",
    "游戏安全优化": "Game-safe Optimization", "自动识别曲风": "Auto-detect Style",
    "分析奏法": "Analyze Musical Techniques", "轻微自然化": "Light Humanization",
    "声音效果": "Sound Effects", "修复音块": "Repair Notes", "平衡力度": "Balance Velocity",
    "乐理分析（保守）": "Music Theory (Conservative)", "柔性对齐": "Soft Quantize",
    "应用游戏安全优化": "Apply Game-safe Optimization", "详细说明 ▸": "Details ▸",
    "详细说明 ▾": "Details ▾", "单轨优化": "Track Optimization", "全局 MIDI 优化": "Global MIDI Optimization",
    "转换检查": "Export Check", "复制报告": "Copy Report", "轨道 FX": "AuxSend",
    "默认": "Default", "玛勒尼斯音源": "Marnian Timbre", "单声道（Basic）": "Mono (Basic)",
    "双声（Stereo）": "Stereo", "增强（Super）": "Super", "超级增强（Super Octave）": "Super Octave",
    "感谢，让音乐工具成为可能": "Thanks for Making This Music Tool Possible",
    "项目组成": "Project Makeup", "协作地图": "Collaboration Map",
    "项目由格式研究、开源依赖与玩家验证共同完成。": "Built through format research, open-source dependencies, and player validation.",
    "这里记录实际依赖与贡献，不用于衡量代码所有权或工作量。": "This records real dependencies and contributions, not code ownership or workload.",
    "游戏采样映射": "Game Sample Mapping", "自主 MIDI 导入": "Independent MIDI Import",
    "BDO v9 编解码": "BDO v9 Codec", "社区与协作": "Community & Collaboration",
    "试听与验证": "Preview & Validation", "解析与转换": "Parsing & Conversion",
    "格式与导出": "Format & Export", "MIDI 基础": "MIDI Foundation",
    "桌面界面": "Desktop UI", "测试与反馈": "Testing & Feedback",
    "致谢名单": "Credits", "复制致谢名单": "Copy Credits",
    "OPEN SOURCE  ·  COMMUNITY": "OPEN SOURCE  ·  COMMUNITY",
    "选择新轨道的 BDO 乐器": "Choose a BDO instrument",
    "更换乐器": "Change Instrument", "编辑音符…": "Edit Notes…", "优化此轨道": "Optimize This Track",
    "所有文件 (*.*)": "All Files (*.*)", "MIDI 文件 (*.mid *.midi)": "MIDI Files (*.mid *.midi)",
}


JA = {
    "双击打开游戏曲谱；主页扫描不读取身份信息": "ダブルクリックでゲーム楽譜を開きます。ホームのスキャンでは個人情報を読み取りません",
    "打开游戏曲谱失败": "ゲーム楽譜を開けません", "无法读取游戏曲谱：{error}": "ゲーム楽譜を読み取れません: {error}",
    "游戏曲谱已打开": "ゲーム楽譜を開きました",
    "已打开游戏曲谱：{file} · {tracks} 轨 · {notes} 音符": "ゲーム楽譜を開きました: {file} · {tracks} トラック · {notes} 音符",
    "项目": "プロジェクト", "本地工程与最近打开的 MIDI": "ローカルプロジェクトと最近開いた MIDI",
    "暂无项目": "プロジェクトはありません",
    "主页": "ホーム", "曲谱主页": "楽譜ホーム", "刷新": "更新", "打开目录": "フォルダーを開く",
    "游戏曲谱": "ゲーム楽譜", "本地项目": "ローカルプロジェクト", "最近使用": "最近使用",
    "从游戏曲谱、本地工程或最近使用中快速开始": "ゲーム楽譜、ローカルプロジェクト、最近のファイルから開始",
    "仅列出本地文件，不读取曲谱中的身份信息": "ローカルファイルのみ表示し、楽譜内の個人情報は読み取りません",
    "双击项目即可继续编辑": "プロジェクトをダブルクリックして編集を再開",
    "双击 MIDI 或工程即可打开": "MIDI またはプロジェクトをダブルクリックして開く",
    "未找到游戏曲谱": "ゲーム楽譜が見つかりません", "未找到本地项目": "ローカルプロジェクトが見つかりません",
    "暂无最近记录": "最近の項目はありません",
    "设置": "設定", "致谢": "クレジット", "转换": "書き出し", "时间轴": "タイムライン",
    "导入 MIDI": "MIDIを読み込む", "打开工程": "プロジェクトを開く", "新建项目": "新規プロジェクト", "全局优化": "全体を最適化",
    "项目名称": "プロジェクト名", "未命名项目": "名称未設定プロジェクト",
    "{project} · 空白项目": "{project} · 空のプロジェクト", "空白项目已创建": "空のプロジェクトを作成しました",
    "空白项目已创建；双击轨道即可添加音符。": "空のプロジェクトを作成しました。トラックをダブルクリックしてノートを追加できます。",
    "新建轨道 1": "新規トラック 1", "新建轨道 1 · {instrument}": "新規トラック 1 · {instrument}",
    "新建轨道 {track_id}": "新規トラック {track_id}",
    "播放": "再生", "暂停": "一時停止", "继续": "再開", "停止": "停止",
    "新建轨道": "トラックを追加", "删除轨道": "トラックを削除", "清除 Solo": "Soloを解除",
    "取消静音": "ミュートを解除", "等待 MIDI": "MIDIを待機中", "未导入 MIDI": "MIDI未読み込み",
    "曲谱名": "楽譜名", "就绪": "準備完了", "音符属性": "ノート属性",
    "音高": "音高", "开始 ms": "開始 ms", "时值 ms": "長さ ms", "力度": "強度",
    "奏法": "奏法", "色板": "パレット", "吸附": "スナップ", "量化": "クオンタイズ",
    "缩放": "ズーム", "撤销": "元に戻す", "重做": "やり直す", "删除": "削除",
    "位置": "位置", "输出": "出力", "打开": "開く", "输出目录": "出力フォルダー",
    "显示全部时间轴": "タイムライン全体を表示", "时间轴缩放": "タイムラインのズーム",
    "时间轴位置": "タイムラインの位置",
    "拖动曲线点调整力度；越近的时间点影响越大。滚轮调整影响范围。": "カーブ点をドラッグしてベロシティを変更します。近い時間点ほど強く影響します。ホイールで範囲を調整できます。",
    "影响 {beats:.1f} 拍": "影響 {beats:.1f} 拍",
    "力度曲线影响范围：前后 {beats:.1f} 拍": "ベロシティカーブの影響範囲：前後 {beats:.1f} 拍",
    "优化此轨": "このトラックを最適化", "应用": "適用", "确定": "OK", "取消": "キャンセル",
    "关闭": "閉じる", "普通": "通常", "延音": "サステイン", "弱音": "ミュート",
    "泛音": "ハーモニクス", "滑音": "グリッサンド", "三连音": "三連符",
    "向上滑动": "スライドアップ", "滑弦下降": "スライドダウン", "滑音上升": "上昇グリッサンド",
    "剪切": "カット", "标签": "アクセント", "颤音小调": "短2度トリル",
    "大调和弦": "メジャーコード", "和弦小调": "マイナーコード", "拍弦": "スラップ",
    "基础导出": "基本書き出し", "通用与导出": "一般と書き出し",
    "MIDI 与力度": "MIDIとベロシティ", "音源与效果": "音源とエフェクト",
    "写入角色名": "キャラクター名", "使用 MIDI": "MIDIを使用",
    "BPM 覆盖": "BPM上書き", "移调": "トランスポーズ", " 半音": " 半音",
    "游戏编辑权限": "ゲーム内編集権限", "从游戏曲谱读取": "ゲーム楽譜から読み込む",
    "MIDI 解析": "MIDI解析", "读取并展开 MIDI sustain 踏板": "MIDIサステインペダルを読み込んで展開",
    "忽略中途 tempo 变化，按主 BPM 拉平": "途中のテンポ変更を無視して主BPMに統一",
    "力度处理": "ベロシティ処理", "分层": "レイヤー", "阶梯": "ステップ",
    "重映射": "再マッピング", "抬底": "下限を上げる", "禁用": "オフ",
    "底": "基準", "步长": "刻み", "阶梯参数": "ステップ設定", "最小": "最小",
    "最大": "最大", "重映射范围": "再マッピング範囲", "抬底值": "下限値",
    "MIDI 效果": "MIDIエフェクト", "混响": "リバーブ", "延迟": "ディレイ",
    "游戏主效果": "エフェクター", "混响时间": "リバーブ時間",
    "延迟反馈": "ディレイ・フィードバック", "混响发送": "リバーブ送信",
    "延迟发送": "ディレイ送信", "合唱发送": "コーラス送信",
    "合唱反馈": "コーラス・フィードバック", "LFO 深度": "LFO深度",
    "LFO 频率": "LFO周波数", "音源模式": "音源モード",
    "Basic 默认；其他模式待验证": "Basicが既定。その他のモードは要検証",
    "游戏参数 · 本地试听不模拟 FX": "ゲーム設定 · ローカル試聴ではFXを再現しません",
    "每轨发送在轨道 FX；本地试听不模拟。": "トラックごとの送信量はAuxSendで設定します。ローカル試聴では再現しません。",
    "导入原值 {value}；修改后按 0–100 写入。": "読み込み値 {value}。編集後は0～100で保存します。",
    "深度": "深さ", "频率": "周波数",
    "保存设置": "設定を保存", "界面语言": "表示言語",
    "仅用于本机近似试听，不会写入曲谱，也不会上传。": "ローカルでの近似試聴だけに使用し、楽譜への書き込みやアップロードは行いません。",
    "优化等级": "最適化レベル", "曲风": "スタイル", "歌词表达": "歌詞表現",
    "游戏安全优化": "ゲーム安全最適化", "自动识别曲风": "スタイルを自動判定",
    "分析奏法": "奏法を分析", "轻微自然化": "軽いヒューマナイズ", "声音效果": "サウンドエフェクト",
    "修复音块": "ノートを修復", "平衡力度": "ベロシティを調整", "乐理分析（保守）": "楽理分析（保守的）",
    "柔性对齐": "ソフトクオンタイズ", "应用游戏安全优化": "ゲーム安全最適化を適用",
    "详细说明 ▸": "詳細 ▸", "详细说明 ▾": "詳細 ▾", "单轨优化": "トラック最適化",
    "全局 MIDI 优化": "MIDI全体最適化", "转换检查": "書き出しチェック", "复制报告": "レポートをコピー",
    "轨道 FX": "AuxSend", "默认": "デフォルト", "玛勒尼斯音源": "マルニアン音色",
    "单声道（Basic）": "モノ（Basic）", "双声（Stereo）": "ステレオ", "增强（Super）": "Super",
    "超级增强（Super Octave）": "Super Octave", "感谢，让音乐工具成为可能": "この音楽ツールを支えてくださった皆様へ",
    "项目组成": "プロジェクト構成", "协作地图": "協力マップ",
    "项目由格式研究、开源依赖与玩家验证共同完成。": "フォーマット研究、オープンソース依存関係、プレイヤー検証によって作られています。",
    "这里记录实际依赖与贡献，不用于衡量代码所有权或工作量。": "実際の依存関係と貢献を記録するもので、コード所有権や作業量を測るものではありません。",
    "游戏采样映射": "ゲームサンプルマッピング", "自主 MIDI 导入": "独自MIDIインポート",
    "BDO v9 编解码": "BDO v9コーデック", "社区与协作": "コミュニティと協力",
    "试听与验证": "試聴と検証", "解析与转换": "解析と変換",
    "格式与导出": "形式と書き出し", "MIDI 基础": "MIDI基盤",
    "桌面界面": "デスクトップUI", "测试与反馈": "テストとフィードバック",
    "致谢名单": "クレジット", "复制致谢名单": "クレジットをコピー",
    "选择新轨道的 BDO 乐器": "BDO楽器を選択", "更换乐器": "楽器を変更",
    "编辑音符…": "ノートを編集…", "优化此轨道": "このトラックを最適化",
}


KO = {
    "双击打开游戏曲谱；主页扫描不读取身份信息": "두 번 클릭하여 게임 악보를 엽니다. 홈 스캔에서는 신원 정보를 읽지 않습니다",
    "打开游戏曲谱失败": "게임 악보를 열 수 없음", "无法读取游戏曲谱：{error}": "게임 악보를 읽을 수 없음: {error}",
    "游戏曲谱已打开": "게임 악보를 열었습니다",
    "已打开游戏曲谱：{file} · {tracks} 轨 · {notes} 音符": "게임 악보 열림: {file} · {tracks} 트랙 · {notes} 음표",
    "项目": "프로젝트", "本地工程与最近打开的 MIDI": "로컬 프로젝트 및 최근에 연 MIDI",
    "暂无项目": "프로젝트가 없습니다",
    "主页": "홈", "曲谱主页": "악보 홈", "刷新": "새로 고침", "打开目录": "폴더 열기",
    "游戏曲谱": "게임 악보", "本地项目": "로컬 프로젝트", "最近使用": "최근 사용",
    "从游戏曲谱、本地工程或最近使用中快速开始": "게임 악보, 로컬 프로젝트 또는 최근 파일에서 시작",
    "仅列出本地文件，不读取曲谱中的身份信息": "로컬 파일만 표시하며 악보 내부의 신원 정보는 읽지 않습니다",
    "双击项目即可继续编辑": "프로젝트를 두 번 클릭하여 편집 계속",
    "双击 MIDI 或工程即可打开": "MIDI 또는 프로젝트를 두 번 클릭하여 열기",
    "未找到游戏曲谱": "게임 악보를 찾을 수 없습니다", "未找到本地项目": "로컬 프로젝트를 찾을 수 없습니다",
    "暂无最近记录": "최근 항목이 없습니다",
    "设置": "설정", "致谢": "크레딧", "转换": "내보내기", "时间轴": "타임라인",
    "导入 MIDI": "MIDI 가져오기", "打开工程": "프로젝트 열기", "新建项目": "새 프로젝트", "全局优化": "전체 최적화",
    "项目名称": "프로젝트 이름", "未命名项目": "제목 없는 프로젝트",
    "{project} · 空白项目": "{project} · 빈 프로젝트", "空白项目已创建": "빈 프로젝트를 만들었습니다",
    "空白项目已创建；双击轨道即可添加音符。": "빈 프로젝트를 만들었습니다. 트랙을 두 번 클릭해 음표를 추가하세요.",
    "新建轨道 1": "새 트랙 1", "新建轨道 1 · {instrument}": "새 트랙 1 · {instrument}",
    "新建轨道 {track_id}": "새 트랙 {track_id}",
    "播放": "재생", "暂停": "일시정지", "继续": "계속", "停止": "정지",
    "新建轨道": "트랙 추가", "删除轨道": "트랙 삭제", "清除 Solo": "Solo 해제",
    "取消静音": "음소거 해제", "等待 MIDI": "MIDI 대기 중", "未导入 MIDI": "MIDI 없음",
    "曲谱名": "악보 이름", "就绪": "준비", "音符属性": "노트 속성",
    "音高": "음높이", "开始 ms": "시작 ms", "时值 ms": "길이 ms", "力度": "세기",
    "奏法": "주법", "色板": "팔레트", "吸附": "스냅", "量化": "퀀타이즈",
    "缩放": "확대/축소", "撤销": "실행 취소", "重做": "다시 실행", "删除": "삭제",
    "位置": "위치", "输出": "출력", "打开": "열기", "输出目录": "출력 폴더",
    "显示全部时间轴": "전체 타임라인 표시", "时间轴缩放": "타임라인 확대/축소",
    "时间轴位置": "타임라인 위치",
    "拖动曲线点调整力度；越近的时间点影响越大。滚轮调整影响范围。": "커브 포인트를 드래그해 벨로시티를 조정합니다. 가까운 시간 포인트일수록 더 크게 영향을 받습니다. 휠로 범위를 조정할 수 있습니다.",
    "影响 {beats:.1f} 拍": "영향 {beats:.1f}박",
    "力度曲线影响范围：前后 {beats:.1f} 拍": "벨로시티 커브 영향 범위: 앞뒤 {beats:.1f}박",
    "优化此轨": "이 트랙 최적화", "应用": "적용", "确定": "확인", "取消": "취소",
    "关闭": "닫기", "普通": "일반", "延音": "서스테인", "弱音": "뮤트",
    "泛音": "하모닉스", "滑音": "글리산도", "三连音": "셋잇단음표",
    "向上滑动": "슬라이드 업", "滑弦下降": "슬라이드 다운", "滑音上升": "상승 글리산도",
    "剪切": "컷", "标签": "악센트", "颤音小调": "단2도 트릴",
    "大调和弦": "메이저 코드", "和弦小调": "마이너 코드", "拍弦": "슬랩",
    "基础导出": "기본 내보내기", "通用与导出": "일반 및 내보내기",
    "MIDI 与力度": "MIDI 및 벨로시티", "音源与效果": "음원 및 효과",
    "写入角色名": "캐릭터 이름", "使用 MIDI": "MIDI 사용",
    "BPM 覆盖": "BPM 덮어쓰기", "移调": "조옮김", " 半音": " 반음",
    "游戏编辑权限": "게임 편집 권한", "从游戏曲谱读取": "게임 악보에서 읽기",
    "MIDI 解析": "MIDI 분석", "读取并展开 MIDI sustain 踏板": "MIDI 서스테인 페달 읽기 및 펼치기",
    "忽略中途 tempo 变化，按主 BPM 拉平": "중간 템포 변경을 무시하고 주 BPM으로 통일",
    "力度处理": "벨로시티 처리", "分层": "레이어", "阶梯": "스텝",
    "重映射": "재매핑", "抬底": "하한 올리기", "禁用": "끔",
    "底": "기준", "步长": "간격", "阶梯参数": "스텝 설정", "最小": "최소",
    "最大": "최대", "重映射范围": "재매핑 범위", "抬底值": "하한값",
    "MIDI 效果": "MIDI 효과", "混响": "리버브", "延迟": "딜레이",
    "游戏主效果": "이펙터", "混响时间": "리버브 시간",
    "延迟反馈": "딜레이 피드백", "混响发送": "리버브 센드",
    "延迟发送": "딜레이 센드", "合唱发送": "코러스 센드",
    "合唱反馈": "코러스 피드백", "LFO 深度": "LFO 깊이",
    "LFO 频率": "LFO 주파수", "音源模式": "음원 모드",
    "Basic 默认；其他模式待验证": "기본값은 Basic, 다른 모드는 검증 필요",
    "游戏参数 · 本地试听不模拟 FX": "게임 설정 · 로컬 미리듣기는 FX를 재현하지 않음",
    "每轨发送在轨道 FX；本地试听不模拟。": "트랙별 전송량은 AuxSend에서 설정하며 로컬 미리듣기에서는 재현하지 않습니다.",
    "导入原值 {value}；修改后按 0–100 写入。": "가져온 값 {value}; 수정 후에는 0~100으로 저장합니다.",
    "深度": "깊이", "频率": "주파수",
    "保存设置": "설정 저장", "界面语言": "인터페이스 언어",
    "仅用于本机近似试听，不会写入曲谱，也不会上传。": "로컬 근사 미리듣기에만 사용하며 악보에 기록하거나 업로드하지 않습니다.",
    "优化等级": "최적화 수준", "曲风": "스타일", "歌词表达": "가사 표현",
    "游戏安全优化": "게임 안전 최적화", "自动识别曲风": "스타일 자동 감지",
    "分析奏法": "주법 분석", "轻微自然化": "가벼운 휴머니즈", "声音效果": "사운드 효과",
    "修复音块": "노트 복구", "平衡力度": "벨로시티 균형", "乐理分析（保守）": "음악 이론 분석(보수적)",
    "柔性对齐": "소프트 퀀타이즈", "应用游戏安全优化": "게임 안전 최적화 적용",
    "详细说明 ▸": "상세 ▸", "详细说明 ▾": "상세 ▾", "单轨优化": "트랙 최적화",
    "全局 MIDI 优化": "전체 MIDI 최적화", "转换检查": "내보내기 검사", "复制报告": "보고서 복사",
    "轨道 FX": "AuxSend", "默认": "기본값", "玛勒尼斯音源": "마르니언 음색",
    "单声道（Basic）": "모노(Basic)", "双声（Stereo）": "스테레오", "增强（Super）": "Super",
    "超级增强（Super Octave）": "Super Octave", "感谢，让音乐工具成为可能": "이 음악 도구를 가능하게 해주신 분들께",
    "项目组成": "프로젝트 구성", "协作地图": "협업 지도",
    "项目由格式研究、开源依赖与玩家验证共同完成。": "포맷 연구, 오픈 소스 의존성과 플레이어 검증으로 만들어졌습니다.",
    "这里记录实际依赖与贡献，不用于衡量代码所有权或工作量。": "실제 의존성과 기여를 기록하며 코드 소유권이나 작업량을 측정하지 않습니다.",
    "游戏采样映射": "게임 샘플 매핑", "自主 MIDI 导入": "독립 MIDI 가져오기",
    "BDO v9 编解码": "BDO v9 코덱", "社区与协作": "커뮤니티 및 협업",
    "试听与验证": "미리듣기 및 검증", "解析与转换": "분석 및 변환",
    "格式与导出": "형식 및 내보내기", "MIDI 基础": "MIDI 기반",
    "桌面界面": "데스크톱 UI", "测试与反馈": "테스트 및 피드백",
    "致谢名单": "크레딧", "复制致谢名单": "크레딧 복사",
    "选择新轨道的 BDO 乐器": "BDO 악기 선택", "更换乐器": "악기 변경",
    "编辑音符…": "노트 편집…", "优化此轨道": "이 트랙 최적화",
}

EN.update({
    "未知来源": "Unknown source",
    "示例 · 来源：{source}": "Example · Source: {source}",
    "{role} · {time:.1f}s": "{role} · {time:.1f}s",
    "自动（跟随系统）": "Auto (System)",
    "自动（根据时区）": "Automatic (by Time Zone)",
    "选择目录": "Choose Folder", "本地音源目录": "Local Audio Folder", "选择音源包": "Choose Sample Pack",
    "本地音源包": "Local Sample Pack", "选择本地音源目录": "Choose Local Audio Folder",
    "选择本地音源包": "Choose Local Sample Pack", "音源包不可用": "Sample Pack Unavailable",
    "准备本地音源包": "Prepare Local Sample Pack",
    "正在校验并准备本地音源包…": "Validating and preparing the local sample pack…",
    "本地音源": "Local Audio Source", "音源路径不可用": "Audio Source Path Unavailable",
    "导出规则、MIDI 解析、力度策略与游戏效果。设置只在下次导出时生效。": "Export rules, MIDI parsing, velocity strategy, and in-game effects. Changes apply to the next export.",
    "角色名会写入乐谱；BPM 与移调会在导出时应用。": "The character name is stored in the score; BPM and transpose are applied during export.",
    "选择一份游戏内保存的曲谱，读取角色名和 Owner ID。": "Choose a score saved in game to read its character name and Score Owner ID.",
    "这两项会影响 MIDI 读入方式；修改后会重新载入当前文件。": "These options affect MIDI parsing; changing them reloads the current file.",
    "选择一种输出力度策略；下方仅显示当前策略需要的参数。": "Choose an output velocity strategy; only its relevant parameters are shown.",
    "数值范围为 0–127；设为 0 即不写入对应效果。": "Values range from 0–127; zero disables the corresponding effect.",
    "轨道 FX 中的奏法会写入支持的 BDO 乐器。": "Musical Techniques selected under AuxSend are written to supported BDO instruments.",
    "选择轨道查看详情。右键可修复和优化轨道或更换乐器；FX 可设置支持乐器的 BDO 奏法。": "Select a track for details. Right-click to optimize or change its instrument; AuxSend configures supported BDO Musical Techniques.",
    "导入 MIDI 后显示轨道与音符时间轴": "Import a MIDI file to display tracks and notes",
    "打开输出目录": "Open Output Folder", "无法原声试听": "Preview Unavailable",
    "参考音频": "Reference Audio", "未载入参考音频": "No reference audio loaded",
    "参考音频播放": "Reference audio playback",
    "载入 MP3/WAV": "Load MP3/WAV", "参考音频音量": "Reference audio volume",
    "载入": "Load", "卸载": "Unload", "正在分析波形…": "Analyzing waveform…",
    "音乐音量": "Music volume", "调整参考音频音量": "Adjust reference audio volume",
    "扒谱模式": "Transcription mode",
    "开启参考音频分析与候选音符审阅": "Enable reference-audio analysis and candidate-note review",
    "识别结果仅作为候选，不会自动写入当前轨道": "Recognition results are candidates only and are not written to the current track automatically",
    "尚未分析": "Not analyzed", "分析参考音频": "Analyze Reference Audio",
    "写入草稿": "Write to Draft", "清除候选": "Clear Candidates",
    "请先在主时间轴最下方载入 MP3/WAV 参考音频": "First load an MP3/WAV reference at the bottom of the main timeline",
    "无法开始扒谱": "Cannot Start Transcription",
    "当前轨道不适合自动扒谱": "Current Track Is Unsuitable for Automatic Transcription",
    "Basic Pitch 不识别游戏鼓件映射；请在旋律乐器轨道中审阅候选": "Basic Pitch does not recognize the game's percussion mapping; review candidates on a melodic-instrument track",
    "扒谱组件未安装": "Transcription Component Not Installed",
    "正在分析参考音频；为保证播放稳定，分析期间已停止试听": "Analyzing reference audio; playback was stopped to keep analysis stable",
    "取消分析": "Cancel Analysis", "正在取消…": "Cancelling…",
    "{count} 个候选": "{count} candidates", "缓存结果已载入": "Cached result loaded",
    "分析完成；候选仍需手动写入草稿": "Analysis complete; candidates still require explicit insertion into the draft",
    "分析失败": "Analysis failed", "扒谱分析未改变任何正式音符": "Transcription did not change any committed notes",
    "扒谱分析失败": "Transcription Failed", "已取消": "Cancelled",
    "没有可写入候选 · 重复 {duplicates} · 越界 {invalid}": "Nothing to write · {duplicates} duplicates · {invalid} out of range",
    "已写入草稿 {accepted} 个 · 跳过重复 {duplicates} · 越界 {invalid}": "Wrote {accepted} to draft · skipped {duplicates} duplicates · {invalid} out of range",
    "仅播放参考音频": "Reference audio only",
    "载入 MP3/WAV 后显示波形": "Load an MP3/WAV to display its waveform",
    "选择参考音频": "Choose Reference Audio",
    "音频文件 (*.mp3 *.wav);;所有文件 (*.*)": "Audio Files (*.mp3 *.wav);;All Files (*.*)",
    "参考音频无法播放：{error}": "Reference audio could not be played: {error}",
    "游戏轨道下拉框的默认值为 Basic。当前工程会保存此选择，非 Basic 的 BDO 序列化位置仍待游戏存档差分确认。": "The game track selector defaults to Basic. This project saves the selected mode; non-Basic BDO serialization positions still await confirmation from game-save diffs.",
    "读取全曲乐理与配器上下文，但只写入当前轨道。": "Analyze full-song theory and orchestration context, but modify only the current track.",
    "分析全部轨道；静音和独奏不改变作用域，可在下方选择允许写入的轨道。": "Analyze every track; Mute and Solo do not change scope. Select writable tracks below.",
})
EN.update({
    "优化算法": "Optimization Algorithm", "算法包目录": "Algorithm Packages",
    "优化强度": "Optimization Intensity", "保守": "Conservative", "均衡": "Balanced", "深入": "Deep",
    "选择算法和强度，然后分析优化。": "Choose an algorithm and intensity, then analyze.",
    "分析优化": "Analyze Optimization", "详细信息 ▸": "Details ▸", "详细信息 ▾": "Details ▾",
    "允许写入的轨道": "Writable Tracks", "应用预览": "Apply Preview",
    "设置已变化，请重新分析优化。": "Settings changed. Analyze again.",
    "设置已更新，点击分析优化刷新预览。": "Settings updated. Analyze to refresh the preview.",
    "没有可用的优化算法。": "No optimization algorithm is available.",
    "请至少选择一条允许写入的轨道。": "Select at least one writable track.",
    "正在分析优化…": "Analyzing optimization…",
    "安全优化未应用任何修改。请先运行转换检查；处理阻断项后再试。": "Safe optimization made no changes. Run Export Check and resolve blocking issues before trying again.",
    "算法未应用任何修改。请检查算法包，或切换到 BDO 游戏安全优化。": "The algorithm made no changes. Check its package or switch to BDO Safe Optimization.",
    "作用轨道：Track {track_id}": "Scope: Track {track_id}",
    "作用轨道：{selected} / {total}": "Scope: {selected} / {total}",
})

JA.update({
    "未知来源": "出典不明",
    "示例 · 来源：{source}": "サンプル · 出典：{source}",
    "{role} · {time:.1f}s": "{role} · {time:.1f}秒",
    "自动（跟随系统）": "自動（システム）",
    "自动（根据时区）": "自動（タイムゾーン）",
    "选择目录": "フォルダーを選択", "本地音源目录": "ローカル音源フォルダー", "选择音源包": "音源パックを選択",
    "本地音源包": "ローカル音源パック", "选择本地音源目录": "ローカル音源フォルダーを選択",
    "选择本地音源包": "ローカル音源パックを選択", "音源包不可用": "音源パックを使用できません",
    "准备本地音源包": "ローカル音源パックを準備",
    "正在校验并准备本地音源包…": "ローカル音源パックを検証して準備しています…",
    "本地音源": "ローカル音源", "音源路径不可用": "音源パスを使用できません",
    "OPEN SOURCE  ·  COMMUNITY": "OPEN SOURCE  ·  COMMUNITY",
    "所有文件 (*.*)": "すべてのファイル (*.*)", "MIDI 文件 (*.mid *.midi)": "MIDIファイル (*.mid *.midi)",
    "导出规则、MIDI 解析、力度策略与游戏效果。设置只在下次导出时生效。": "書き出し規則、MIDI解析、ベロシティ処理、ゲーム内エフェクトを設定します。次回の書き出しから反映されます。",
    "角色名会写入乐谱；BPM 与移调会在导出时应用。": "キャラクター名を楽譜に保存し、BPMとトランスポーズを書き出し時に適用します。",
    "选择一份游戏内保存的曲谱，读取角色名和 Owner ID。": "ゲーム内で保存した楽譜からキャラクター名と楽譜所有者IDを読み込みます。",
    "这两项会影响 MIDI 读入方式；修改后会重新载入当前文件。": "MIDIの読み込み方法に影響します。変更すると現在のファイルを再読み込みします。",
    "选择一种输出力度策略；下方仅显示当前策略需要的参数。": "ベロシティの出力方式を選択します。必要な設定だけが表示されます。",
    "数值范围为 0–127；设为 0 即不写入对应效果。": "値は0～127です。0にすると対応するエフェクトを書き込みません。",
    "轨道 FX 中的奏法会写入支持的 BDO 乐器。": "トラックFXの奏法は対応するBDO楽器へ書き込まれます。",
    "选择轨道查看详情。右键可修复和优化轨道或更换乐器；FX 可设置支持乐器的 BDO 奏法。": "トラックを選択すると詳細を表示します。右クリックで最適化や楽器変更、FXで奏法を設定できます。",
    "导入 MIDI 后显示轨道与音符时间轴": "MIDIを読み込むとトラックとノートを表示します",
    "打开输出目录": "出力フォルダーを開く", "无法原声试听": "プレビューできません",
    "参考音频": "参照オーディオ", "未载入参考音频": "参照オーディオ未読込",
    "参考音频播放": "参照オーディオ再生",
    "载入 MP3/WAV": "MP3/WAVを読み込む", "参考音频音量": "参照オーディオ音量",
    "载入": "読込", "卸载": "解除", "正在分析波形…": "波形を解析中…",
    "音乐音量": "音楽音量", "调整参考音频音量": "参照オーディオの音量を調整",
    "扒谱模式": "採譜モード",
    "开启参考音频分析与候选音符审阅": "参照オーディオ解析と候補ノートの確認を有効にする",
    "识别结果仅作为候选，不会自动写入当前轨道": "認識結果は候補としてのみ表示され、現在のトラックには自動で書き込まれません",
    "尚未分析": "未解析", "分析参考音频": "参照オーディオを解析",
    "写入草稿": "下書きに書き込む", "清除候选": "候補を消去",
    "请先在主时间轴最下方载入 MP3/WAV 参考音频": "先にメインタイムライン最下部でMP3/WAV参照オーディオを読み込んでください",
    "无法开始扒谱": "採譜を開始できません",
    "当前轨道不适合自动扒谱": "現在のトラックは自動採譜に適していません",
    "Basic Pitch 不识别游戏鼓件映射；请在旋律乐器轨道中审阅候选": "Basic Pitchはゲームの打楽器マッピングを認識しません。旋律楽器トラックで候補を確認してください",
    "扒谱组件未安装": "採譜コンポーネントがインストールされていません",
    "正在分析参考音频；为保证播放稳定，分析期间已停止试听": "参照オーディオを解析中です。安定性を保つため、解析中は再生を停止しています",
    "取消分析": "解析をキャンセル", "正在取消…": "キャンセル中…",
    "{count} 个候选": "候補 {count} 件", "缓存结果已载入": "キャッシュ済みの結果を読み込みました",
    "分析完成；候选仍需手动写入草稿": "解析が完了しました。候補は明示的に下書きへ書き込む必要があります",
    "分析失败": "解析に失敗しました", "扒谱分析未改变任何正式音符": "採譜解析では確定済みノートを変更していません",
    "扒谱分析失败": "採譜解析に失敗しました", "已取消": "キャンセルしました",
    "没有可写入候选 · 重复 {duplicates} · 越界 {invalid}": "書き込み可能な候補なし · 重複 {duplicates} · 範囲外 {invalid}",
    "已写入草稿 {accepted} 个 · 跳过重复 {duplicates} · 越界 {invalid}": "下書きへ {accepted} 件を書き込み · 重複 {duplicates} 件をスキップ · 範囲外 {invalid}",
    "仅播放参考音频": "参照オーディオのみ再生",
    "载入 MP3/WAV 后显示波形": "MP3/WAVを読み込むと波形を表示します",
    "选择参考音频": "参照オーディオを選択",
    "音频文件 (*.mp3 *.wav);;所有文件 (*.*)": "オーディオファイル (*.mp3 *.wav);;すべてのファイル (*.*)",
    "参考音频无法播放：{error}": "参照オーディオを再生できません：{error}",
    "游戏轨道下拉框的默认值为 Basic。当前工程会保存此选择，非 Basic 的 BDO 序列化位置仍待游戏存档差分确认。": "ゲーム内トラックの既定値はBasicです。このプロジェクトは選択したモードを保存しますが、Basic以外のBDOシリアライズ位置はゲーム保存データの差分確認待ちです。",
    "读取全曲乐理与配器上下文，但只写入当前轨道。": "曲全体の楽理と編成を分析し、現在のトラックだけを変更します。",
    "分析全部轨道；静音和独奏不改变作用域，可在下方选择允许写入的轨道。": "全トラックを分析します。Mute/Soloは範囲に影響せず、変更可能なトラックを下で選択できます。",
})
JA.update({
    "优化算法": "最適化アルゴリズム", "算法包目录": "アルゴリズムパッケージ",
    "优化强度": "最適化の強度", "保守": "保守的", "均衡": "バランス", "深入": "詳細",
    "选择算法和强度，然后分析优化。": "アルゴリズムと強度を選択して解析してください。",
    "分析优化": "最適化を解析", "详细信息 ▸": "詳細 ▸", "详细信息 ▾": "詳細 ▾",
    "允许写入的轨道": "書き込み可能なトラック", "应用预览": "プレビューを適用",
    "设置已变化，请重新分析优化。": "設定が変更されました。再解析してください。",
    "设置已更新，点击分析优化刷新预览。": "設定を更新しました。解析してプレビューを更新してください。",
    "没有可用的优化算法。": "利用可能な最適化アルゴリズムがありません。",
    "请至少选择一条允许写入的轨道。": "書き込み可能なトラックを1つ以上選択してください。",
    "正在分析优化…": "最適化を解析中…",
    "安全优化未应用任何修改。请先运行转换检查；处理阻断项后再试。": "安全最適化は変更を適用しませんでした。書き出しチェックの阻止項目を解決してから再試行してください。",
    "算法未应用任何修改。请检查算法包，或切换到 BDO 游戏安全优化。": "アルゴリズムは変更を適用しませんでした。パッケージを確認するか、BDO安全最適化へ切り替えてください。",
    "作用轨道：Track {track_id}": "対象：Track {track_id}",
    "作用轨道：{selected} / {total}": "対象：{selected} / {total}",
})

KO.update({
    "未知来源": "출처 불명",
    "示例 · 来源：{source}": "예제 · 출처: {source}",
    "{role} · {time:.1f}s": "{role} · {time:.1f}초",
    "自动（跟随系统）": "자동(시스템)",
    "自动（根据时区）": "자동(시간대 기준)",
    "选择目录": "폴더 선택", "本地音源目录": "로컬 음원 폴더", "选择音源包": "음원 팩 선택",
    "本地音源包": "로컬 음원 팩", "选择本地音源目录": "로컬 음원 폴더 선택",
    "选择本地音源包": "로컬 음원 팩 선택", "音源包不可用": "음원 팩을 사용할 수 없음",
    "准备本地音源包": "로컬 음원 팩 준비",
    "正在校验并准备本地音源包…": "로컬 음원 팩을 검증하고 준비하는 중…",
    "本地音源": "로컬 음원", "音源路径不可用": "음원 경로를 사용할 수 없음",
    "OPEN SOURCE  ·  COMMUNITY": "OPEN SOURCE  ·  COMMUNITY",
    "所有文件 (*.*)": "모든 파일 (*.*)", "MIDI 文件 (*.mid *.midi)": "MIDI 파일 (*.mid *.midi)",
    "导出规则、MIDI 解析、力度策略与游戏效果。设置只在下次导出时生效。": "내보내기 규칙, MIDI 분석, 벨로시티 전략과 게임 효과를 설정합니다. 다음 내보내기부터 적용됩니다.",
    "角色名会写入乐谱；BPM 与移调会在导出时应用。": "캐릭터 이름은 악보에 저장되고 BPM과 조옮김은 내보낼 때 적용됩니다.",
    "选择一份游戏内保存的曲谱，读取角色名和 Owner ID。": "게임에서 저장한 악보를 선택해 캐릭터 이름과 악보 소유자 ID를 읽습니다.",
    "这两项会影响 MIDI 读入方式；修改后会重新载入当前文件。": "MIDI 읽기 방식에 영향을 주며 변경하면 현재 파일을 다시 불러옵니다.",
    "选择一种输出力度策略；下方仅显示当前策略需要的参数。": "벨로시티 출력 전략을 선택합니다. 필요한 설정만 아래에 표시됩니다.",
    "数值范围为 0–127；设为 0 即不写入对应效果。": "값 범위는 0–127이며 0이면 해당 효과를 기록하지 않습니다.",
    "轨道 FX 中的奏法会写入支持的 BDO 乐器。": "트랙 FX의 주법은 지원되는 BDO 악기에 기록됩니다.",
    "选择轨道查看详情。右键可修复和优化轨道或更换乐器；FX 可设置支持乐器的 BDO 奏法。": "트랙을 선택하면 세부 정보를 봅니다. 우클릭으로 최적화하거나 악기를 바꾸고 FX에서 주법을 설정합니다.",
    "导入 MIDI 后显示轨道与音符时间轴": "MIDI를 가져오면 트랙과 노트를 표시합니다",
    "打开输出目录": "출력 폴더 열기", "无法原声试听": "미리듣기 불가",
    "参考音频": "참조 오디오", "未载入参考音频": "참조 오디오를 불러오지 않음",
    "参考音频播放": "참조 오디오 재생",
    "载入 MP3/WAV": "MP3/WAV 불러오기", "参考音频音量": "참조 오디오 음량",
    "载入": "불러오기", "卸载": "해제", "正在分析波形…": "파형 분석 중…",
    "音乐音量": "음악 음량", "调整参考音频音量": "참조 오디오 음량 조절",
    "扒谱模式": "채보 모드",
    "开启参考音频分析与候选音符审阅": "참조 오디오 분석 및 후보 음표 검토 사용",
    "识别结果仅作为候选，不会自动写入当前轨道": "인식 결과는 후보로만 표시되며 현재 트랙에 자동으로 기록되지 않습니다",
    "尚未分析": "분석 전", "分析参考音频": "참조 오디오 분석",
    "写入草稿": "초안에 기록", "清除候选": "후보 지우기",
    "请先在主时间轴最下方载入 MP3/WAV 参考音频": "먼저 메인 타임라인 맨 아래에서 MP3/WAV 참조 오디오를 불러오세요",
    "无法开始扒谱": "채보를 시작할 수 없음",
    "当前轨道不适合自动扒谱": "현재 트랙은 자동 채보에 적합하지 않음",
    "Basic Pitch 不识别游戏鼓件映射；请在旋律乐器轨道中审阅候选": "Basic Pitch는 게임 타악기 매핑을 인식하지 못합니다. 선율 악기 트랙에서 후보를 검토하세요",
    "扒谱组件未安装": "채보 구성 요소가 설치되지 않음",
    "正在分析参考音频；为保证播放稳定，分析期间已停止试听": "참조 오디오 분석 중입니다. 안정적인 분석을 위해 재생을 중지했습니다",
    "取消分析": "분석 취소", "正在取消…": "취소 중…",
    "{count} 个候选": "후보 {count}개", "缓存结果已载入": "캐시된 결과를 불러옴",
    "分析完成；候选仍需手动写入草稿": "분석이 끝났습니다. 후보는 명시적으로 초안에 기록해야 합니다",
    "分析失败": "분석 실패", "扒谱分析未改变任何正式音符": "채보 분석은 확정된 음표를 변경하지 않았습니다",
    "扒谱分析失败": "채보 분석 실패", "已取消": "취소됨",
    "没有可写入候选 · 重复 {duplicates} · 越界 {invalid}": "기록할 후보 없음 · 중복 {duplicates} · 범위 초과 {invalid}",
    "已写入草稿 {accepted} 个 · 跳过重复 {duplicates} · 越界 {invalid}": "초안에 {accepted}개 기록 · 중복 {duplicates}개 건너뜀 · 범위 초과 {invalid}",
    "仅播放参考音频": "참조 오디오만 재생",
    "载入 MP3/WAV 后显示波形": "MP3/WAV를 불러오면 파형을 표시합니다",
    "选择参考音频": "참조 오디오 선택",
    "音频文件 (*.mp3 *.wav);;所有文件 (*.*)": "오디오 파일 (*.mp3 *.wav);;모든 파일 (*.*)",
    "参考音频无法播放：{error}": "참조 오디오를 재생할 수 없습니다: {error}",
    "游戏轨道下拉框的默认值为 Basic。当前工程会保存此选择，非 Basic 的 BDO 序列化位置仍待游戏存档差分确认。": "게임 트랙 선택기의 기본값은 Basic입니다. 이 프로젝트는 선택한 모드를 저장하지만 Basic 이외 BDO 직렬화 위치는 게임 저장본 비교 확인이 필요합니다.",
    "读取全曲乐理与配器上下文，但只写入当前轨道。": "전체 곡의 음악 이론과 편성 맥락을 분석하지만 현재 트랙만 변경합니다.",
    "分析全部轨道；静音和独奏不改变作用域，可在下方选择允许写入的轨道。": "모든 트랙을 분석합니다. 음소거와 Solo는 범위를 바꾸지 않으며 아래에서 변경할 트랙을 선택합니다.",
})
KO.update({
    "优化算法": "최적화 알고리즘", "算法包目录": "알고리즘 패키지",
    "优化强度": "최적화 강도", "保守": "보수적", "均衡": "균형", "深入": "심층",
    "选择算法和强度，然后分析优化。": "알고리즘과 강도를 선택한 뒤 분석하세요.",
    "分析优化": "최적화 분석", "详细信息 ▸": "세부 정보 ▸", "详细信息 ▾": "세부 정보 ▾",
    "允许写入的轨道": "쓰기 허용 트랙", "应用预览": "미리보기 적용",
    "设置已变化，请重新分析优化。": "설정이 변경되었습니다. 다시 분석하세요.",
    "设置已更新，点击分析优化刷新预览。": "설정이 업데이트되었습니다. 분석하여 미리보기를 새로 고치세요.",
    "没有可用的优化算法。": "사용 가능한 최적화 알고리즘이 없습니다.",
    "请至少选择一条允许写入的轨道。": "쓰기 가능한 트랙을 하나 이상 선택하세요.",
    "正在分析优化…": "최적화 분석 중…",
    "安全优化未应用任何修改。请先运行转换检查；处理阻断项后再试。": "안전 최적화가 변경 사항을 적용하지 않았습니다. 내보내기 검사의 차단 항목을 해결한 뒤 다시 시도하세요.",
    "算法未应用任何修改。请检查算法包，或切换到 BDO 游戏安全优化。": "알고리즘이 변경 사항을 적용하지 않았습니다. 패키지를 확인하거나 BDO 안전 최적화로 전환하세요.",
    "作用轨道：Track {track_id}": "대상: Track {track_id}",
    "作用轨道：{selected} / {total}": "대상: {selected} / {total}",
})

# Text used by secondary dialogs and their initial dynamic summaries.  Keep
# these in the runtime catalog as well as the main-window vocabulary so a
# language switch translates every already-open dialog consistently.
EN.update({
    "中性": "Neutral", "古典 / 管弦": "Classical / Orchestral", "摇滚": "Rock",
    "放克": "Funk", "氛围": "Ambient", "爵士 / Swing": "Jazz / Swing",
    "电子": "Electronic", "自动判断": "Auto", "节奏念唱 / Rap": "Rhythmic / Rap",
    "花腔延展（Melisma）": "Melismatic", "连续连唱（Legato）": "Continuous Legato",
    "逐音节（清晰咬字）": "Syllabic (Clear Diction)", "问答分句（先建议）": "Call and Response (Suggest First)",
    "允许写入的轨道（所有轨道始终参与只读上下文分析）": "Writable tracks (all tracks always participate in read-only context analysis)",
    "只在游戏支持范围内调整奏法、力度、轻微时序和全局声音效果。不会增删音符、改音高、换乐器或新增轨道；未通过游戏 A/B 的奏法不会写入。": "Adjust Musical Techniques, velocity, subtle timing, and global effects only within game-supported limits. Notes, pitches, instruments, and tracks are preserved; Musical Techniques without in-game A/B validation are not written.",
    "复制到游戏目录": "Copy to Game Folder", "修复可自动处理项": "Apply Automatic Fixes",
    "未读取 Owner ID；导出的曲谱无法在游戏内编辑。": "No Score Owner ID loaded; exported scores cannot be edited in game.",
    "当前乐器暂未收录奏法。": "No Musical Techniques are currently cataloged for this instrument.",
    "未指定奏法，导出时保留普通音符。 此设置会把该轨导出为同一种 BDO 奏法。": "No Musical Technique selected; export keeps normal notes. This setting applies one BDO Musical Technique to the entire track.",
    "延音踏板": "Sustain Pedal", "延音 (type 0)": "Sustain (type 0)",
    "延音踏板 (type 11)": "Sustain Pedal (type 11)", "无法原声还原": "Original Preview Unavailable",
    "状态\n可转换": "Status\nReady", "问题\n0": "Issues\n0", "人工确认\n0": "Review\n0",
    "可自动修复\n0 项": "Auto-fixable\n0 items", "已选 0 · 共 0 音符": "Selected 0 · 0 notes total",
    "奏法 0 处 · 轻微自然化 0 个音符\n效果：混响 0→0 · 延迟 0→0 · 合唱 (0, 0, 0)→(0, 0, 0)": "Musical Techniques 0 · Humanized 0 notes\nEffects: Reverb 0→0 · Delay 0→0 · Chorus (0, 0, 0)→(0, 0, 0)",
    "已选 {selected} · 共 {total} 音符{position}{warning}": "Selected {selected} · {total} notes total{position}{warning}",
    "状态\n{status}": "Status\n{status}", "问题\n{count}": "Issues\n{count}",
    "人工确认\n{count}": "Review\n{count}", "可自动修复\n{count} 项": "Auto-fixable\n{count} items",
    "已读取 Owner ID：0x{owner_id:08x}": "Score Owner ID loaded: 0x{owner_id:08x}",
    "可转换": "Ready", "不可转换": "Blocked",
    " · 移调 {transpose:+d}": " · Transpose {transpose:+d}",
    " · 越界 {count}": " · Out of range {count}",
    "从 MIDI 解析、游戏曲谱研究到原声试听，每一份开源代码、文档和测试都很重要。": "From MIDI parsing and game-score research to original-sample preview, every piece of open-source code, documentation, and testing matters.",
    "以当前代码中实际承担的功能作粗略估算": "A rough estimate based on responsibilities in the current code",
    "占比仅用于表达感谢，不代表代码所有权或精确工作量。Python 与 Qt 作为运行基础未计入图表。": "These proportions express appreciation, not code ownership or exact effort. Python and Qt are runtime foundations and are not included.",
    "6 项核心依赖与贡献": "6 Core Dependencies and Contributions",
    "7 项核心依赖与贡献": "7 Core Dependencies and Contributions",
    "这不是一份排名，而是一张合作地图。谢谢每一个把工具、文档和经验分享出来的人。": "This is not a ranking, but a map of collaboration. Thank you to everyone who shared tools, documentation, and experience.",
    "复制为纯文本，便于放入项目说明或发布页面": "Copy as plain text for project documentation or release pages",
    "01 · MIDI 与游戏采样试听": "01 · MIDI and Game-sample Preview", "把 MIDI 音符一颗颗读出来、写回去。": "Reads and writes MIDI notes one by one.",
    "BDO 原始采样映射": "BDO Original-sample Mapping", "试听只使用从游戏提取并验证过的键位映射。": "Preview uses only key mappings extracted from and verified against the game.",
    "02 · GitHub 开源项目": "02 · GitHub Open-source Projects",
    "感谢早期公开的 MIDI→BDO 格式探索与实现，为本项目初期研究提供参照；当前版本已采用独立实现，不包含或调用其运行时代码。": "Thanks for the early public exploration and implementation of the MIDI-to-BDO format, which informed this project's initial research. The current version uses an independent implementation and neither contains nor calls its runtime code.",
    "感谢黑色沙漠音乐文件研究与解码相关资料作者，帮助理解外部曲谱制作方向。": "Thanks to the authors of Black Desert music-file research and decoding resources that helped guide external score creation.",
    "感谢 bdo-data-extractor 作者公开清晰的 PAZ、ICE 与 LZ 只读实现，帮助完善本地音源制作工具。": "Thanks to the bdo-data-extractor author for sharing a clear, read-only PAZ, ICE, and LZ implementation that helped improve the local sample-pack tool.",
    "03 · 开发协作": "03 · Development Collaboration", "在旁边递思路、改文案、一起收拾代码。": "Contributed ideas, refined copy, and helped organize the code.",
    "04 · 还有大家": "04 · Everyone Else", "谢谢开源维护者、文档作者、issue 讨论者、测试者，以及每一个愿意分享经验的人。": "Thanks to open-source maintainers, documentation authors, issue participants, testers, and everyone willing to share experience.",
    "感谢 CN 服务器 Rainbow Club 彩虹乐队玩家的支持、测试与音乐交流。": "Thanks to the players of Rainbow Club on the CN server for their support, testing, and musical exchange.",
    "载入失败": "Load Failed", "MIDI 已载入": "MIDI Loaded", "MIDI 载入失败：{error}": "MIDI load failed: {error}",
    "已新建 Track {track_id} · {instrument}": "Created Track {track_id} · {instrument}", "空轨道已创建；双击轨道可进入音符编辑器添加音符。": "Empty track created; double-click it to add notes in the note editor.",
    "已删除 {track}": "Deleted {track}", "轨道已删除。请选择其他轨道，或新建一条空轨道。": "Track deleted. Select another track or create an empty track.",
    "无可用音频设备": "No Audio Device", "等待预取": "Waiting for Preload", "原声已验证": "Original Audio Verified", "原声近似": "Approximate Original Audio", "原声近似（待 A/B 验证）": "Approximate Original Audio (A/B Validation Pending)",
    "正在准备游戏音源…": "Preparing Game Audio…", "试听播放": "Preview Playing", "试听暂停": "Preview Paused", "BDO 实时原声试听": "BDO Real-time Original Preview",
    "BDO 实时试听（{count} 项待验证）": "BDO Real-time Preview ({count} items pending validation)", "实时音频引擎已停止": "Real-time audio engine stopped",
    "BDO 实时试听缓冲不足 {count} 次 · 混音 P95 {p95:.1f} ms": "BDO preview underruns {count} · Mix P95 {p95:.1f} ms", "音频输出停止：{error}": "Audio output stopped: {error}",
    "正在转换...": "Exporting...", "转换完成": "Export Complete", "转换失败": "Export Failed",
    "游戏映射：检测中": "Game Mapping: Detecting", "轨道": "Tracks", "导入 MIDI 后显示轨道": "Tracks appear after importing MIDI",
    "发现自动保存工程": "Autosave Found", "发现自动保存工程：{project} · 可点打开工程恢复": "Autosave found: {project} · Click Open Project to restore",
    "建议转换检查": "Export Check Recommended", "MIDI 已载入。建议先点“转换检查”，确认音域、FX 和打击乐映射后再导出。": "MIDI loaded. Run Export Check to verify pitch ranges, FX, and percussion mapping before exporting.",
    "工程已恢复": "Project Restored", "已恢复自动保存工程：{project}": "Restored autosave project: {project}", "自动保存失败：{error}": "Autosave failed: {error}",
    "已更新 {track} · {count} 音符": "Updated {track} · {count} notes", "音符编辑已写回；转换前建议运行一次转换检查。": "Note edits were applied. Run Export Check before exporting.",
    "{scope} 已优化": "{scope} optimized", "已应用 {scope} 优化{effects}：建议再运行一次转换检查后导出。": "Applied {scope} optimization{effects}. Run Export Check again before exporting.",
    "全局 MIDI": "Global MIDI", "，并应用游戏声音效果建议": ", including suggested game audio effects", "转换检查已修复": "Export Check Fixes Applied",
    "轨": "tracks", "当前": "active", "块": "blocks",
    "{track} · {count} 音符 · {pitch_range} · BDO: {instrument} · FX: {articulation} · 右键轨道更换乐器": "{track} · {count} notes · {pitch_range} · BDO: {instrument} · FX: {articulation} · Right-click the track to change instrument",
    "{file} · {tracks} 轨 · {notes} 音符 · {minutes}m {seconds:02d}s · {pitch}": "{file} · {tracks} tracks · {notes} notes · {minutes}m {seconds:02d}s · {pitch}",
    " · 已复制到游戏目录": " · Copied to game folder", "已保存 {file} · {bytes} bytes · {instruments} 乐器 · {tracks} 轨 · {notes} 音符{extra}": "Saved {file} · {bytes} bytes · {instruments} instruments · {tracks} tracks · {notes} notes{extra}",
})

JA.update({
    "中性": "ニュートラル", "古典 / 管弦": "クラシック / オーケストラ", "摇滚": "ロック",
    "放克": "ファンク", "氛围": "アンビエント", "爵士 / Swing": "ジャズ / スウィング",
    "电子": "エレクトロニック", "自动判断": "自動判定", "节奏念唱 / Rap": "リズミック / ラップ",
    "花腔延展（Melisma）": "メリスマ", "连续连唱（Legato）": "連続レガート",
    "逐音节（清晰咬字）": "シラビック（明瞭な発音）", "问答分句（先建议）": "コール＆レスポンス（提案のみ）",
    "允许写入的轨道（所有轨道始终参与只读上下文分析）": "書き込み可能なトラック（全トラックを読み取り専用の文脈分析に使用）",
    "只在游戏支持范围内调整奏法、力度、轻微时序和全局声音效果。不会增删音符、改音高、换乐器或新增轨道；未通过游戏 A/B 的奏法不会写入。": "ゲーム対応範囲内で奏法、ベロシティ、微細なタイミング、全体エフェクトのみを調整します。ノート、音高、楽器、トラックは変更せず、ゲーム内A/B検証済みでない奏法は書き込みません。",
    "复制到游戏目录": "ゲームフォルダーへコピー", "修复可自动处理项": "自動修正を適用",
    "未读取 Owner ID；导出的曲谱无法在游戏内编辑。": "楽譜所有者IDが読み込まれていないため、書き出した楽譜はゲーム内で編集できません。",
    "当前乐器暂未收录奏法。": "この楽器の奏法はまだ登録されていません。",
    "未指定奏法，导出时保留普通音符。 此设置会把该轨导出为同一种 BDO 奏法。": "奏法未指定のため通常ノートのまま書き出します。この設定はトラック全体に同じBDO奏法を適用します。",
    "延音踏板": "サステインペダル", "延音 (type 0)": "サステイン (type 0)",
    "延音踏板 (type 11)": "サステインペダル (type 11)", "无法原声还原": "原音プレビュー不可",
    "状态\n可转换": "状態\n書き出し可能", "问题\n0": "問題\n0", "人工确认\n0": "要確認\n0",
    "可自动修复\n0 项": "自動修正可能\n0件", "已选 0 · 共 0 音符": "選択 0・全 0 ノート",
    "奏法 0 处 · 轻微自然化 0 个音符\n效果：混响 0→0 · 延迟 0→0 · 合唱 (0, 0, 0)→(0, 0, 0)": "奏法 0・ヒューマナイズ 0ノート\nエフェクト：リバーブ 0→0・ディレイ 0→0・コーラス (0, 0, 0)→(0, 0, 0)",
    "已选 {selected} · 共 {total} 音符{position}{warning}": "選択 {selected}・全 {total} ノート{position}{warning}",
    "状态\n{status}": "状態\n{status}", "问题\n{count}": "問題\n{count}",
    "人工确认\n{count}": "要確認\n{count}", "可自动修复\n{count} 项": "自動修正可能\n{count}件",
    "已读取 Owner ID：0x{owner_id:08x}": "楽譜所有者ID読み込み済み：0x{owner_id:08x}",
    "可转换": "書き出し可能", "不可转换": "書き出し不可",
    " · 移调 {transpose:+d}": " · トランスポーズ {transpose:+d}",
    " · 越界 {count}": " · 範囲外 {count}",
    "从 MIDI 解析、游戏曲谱研究到原声试听，每一份开源代码、文档和测试都很重要。": "MIDI解析、ゲーム楽譜研究、原音プレビューまで、すべてのオープンソースコード、文書、テストが重要です。",
    "以当前代码中实际承担的功能作粗略估算": "現在のコードで担う機能に基づく概算", "占比仅用于表达感谢，不代表代码所有权或精确工作量。Python 与 Qt 作为运行基础未计入图表。": "割合は感謝を表すためのもので、コード所有権や正確な作業量を示しません。基盤のPythonとQtは含みません。",
    "6 项核心依赖与贡献": "6つの主要な依存関係と貢献", "7 项核心依赖与贡献": "7つの主要な依存関係と貢献", "这不是一份排名，而是一张合作地图。谢谢每一个把工具、文档和经验分享出来的人。": "これは順位ではなく協力の地図です。ツール、文書、経験を共有してくださった皆様に感謝します。",
    "复制为纯文本，便于放入项目说明或发布页面": "プロジェクト説明やリリースページ用にプレーンテキストでコピー",
    "01 · MIDI 与游戏采样试听": "01 · MIDIとゲームサンプル試聴", "把 MIDI 音符一颗颗读出来、写回去。": "MIDIノートを一音ずつ読み書きします。", "BDO 原始采样映射": "BDO原音サンプルマッピング", "试听只使用从游戏提取并验证过的键位映射。": "ゲームから抽出・検証したキーマッピングのみを試聴に使用します。",
    "02 · GitHub 开源项目": "02 · GitHubオープンソースプロジェクト", "感谢早期公开的 MIDI→BDO 格式探索与实现，为本项目初期研究提供参照；当前版本已采用独立实现，不包含或调用其运行时代码。": "初期研究の参考となった、MIDI→BDO形式の早期の公開調査と実装に感謝します。現行版は独立実装を採用し、そのランタイムコードを含まず、呼び出しもしません。", "感谢黑色沙漠音乐文件研究与解码相关资料作者，帮助理解外部曲谱制作方向。": "外部楽譜制作の理解を助けた黒い砂漠の音楽ファイル研究・解析資料の作者に感謝します。",
    "感谢 bdo-data-extractor 作者公开清晰的 PAZ、ICE 与 LZ 只读实现，帮助完善本地音源制作工具。": "明確で読み取り専用のPAZ、ICE、LZ実装を公開し、ローカル音源パック作成ツールの改善に貢献したbdo-data-extractor作者に感謝します。",
    "03 · 开发协作": "03 · 開発協力", "在旁边递思路、改文案、一起收拾代码。": "アイデア、文面の改善、コード整理に協力しました。", "04 · 还有大家": "04 · そして皆様", "谢谢开源维护者、文档作者、issue 讨论者、测试者，以及每一个愿意分享经验的人。": "オープンソース保守者、文書作者、issue参加者、テスター、経験を共有してくださる皆様に感謝します。",
    "感谢 CN 服务器 Rainbow Club 彩虹乐队玩家的支持、测试与音乐交流。": "CNサーバーのRainbow Club（彩虹楽団）プレイヤーの皆様による支援、テスト、音楽交流に感謝します。",
    "载入失败": "読み込み失敗", "MIDI 已载入": "MIDI読み込み完了", "MIDI 载入失败：{error}": "MIDIの読み込みに失敗：{error}",
    "已新建 Track {track_id} · {instrument}": "Track {track_id}を作成 · {instrument}", "空轨道已创建；双击轨道可进入音符编辑器添加音符。": "空のトラックを作成しました。ダブルクリックしてノートを追加できます。", "已删除 {track}": "{track}を削除", "轨道已删除。请选择其他轨道，或新建一条空轨道。": "トラックを削除しました。別のトラックを選択するか空のトラックを作成してください。",
    "无可用音频设备": "利用可能なオーディオデバイスなし", "等待预取": "プリロード待機中", "原声已验证": "原音検証済み", "原声近似": "原音近似", "原声近似（待 A/B 验证）": "原音近似（A/B検証待ち）",
    "正在准备游戏音源…": "ゲーム音源を準備中…", "试听播放": "プレビュー再生中", "试听暂停": "プレビュー一時停止", "BDO 实时原声试听": "BDOリアルタイム原音プレビュー", "BDO 实时试听（{count} 项待验证）": "BDOリアルタイムプレビュー（{count}項目検証待ち）", "实时音频引擎已停止": "リアルタイム音声エンジン停止",
    "BDO 实时试听缓冲不足 {count} 次 · 混音 P95 {p95:.1f} ms": "BDOプレビューのバッファ不足 {count}回・ミックスP95 {p95:.1f} ms", "音频输出停止：{error}": "音声出力停止：{error}", "正在转换...": "書き出し中...", "转换完成": "書き出し完了", "转换失败": "書き出し失敗",
    "游戏映射：检测中": "ゲームマッピング：検出中", "轨道": "トラック", "导入 MIDI 后显示轨道": "MIDI読み込み後にトラックを表示", "发现自动保存工程": "自動保存プロジェクトを検出", "发现自动保存工程：{project} · 可点打开工程恢复": "自動保存を検出：{project}・［プロジェクトを開く］で復元できます", "建议转换检查": "書き出しチェック推奨", "MIDI 已载入。建议先点“转换检查”，确认音域、FX 和打击乐映射后再导出。": "MIDIを読み込みました。書き出し前に音域、FX、打楽器マッピングを確認してください。", "工程已恢复": "プロジェクト復元完了", "已恢复自动保存工程：{project}": "自動保存プロジェクトを復元：{project}", "自动保存失败：{error}": "自動保存失敗：{error}", "已更新 {track} · {count} 音符": "{track}を更新・{count}ノート", "音符编辑已写回；转换前建议运行一次转换检查。": "ノート編集を反映しました。書き出し前にチェックを実行してください。", "{scope} 已优化": "{scope}を最適化", "已应用 {scope} 优化{effects}：建议再运行一次转换检查后导出。": "{scope}の最適化{effects}を適用しました。再度チェックしてから書き出してください。", "全局 MIDI": "MIDI全体", "，并应用游戏声音效果建议": "、ゲーム音響効果の提案も適用", "转换检查已修复": "書き出しチェックの修正を適用",
    "轨": "トラック", "当前": "有効", "块": "ブロック", "{track} · {count} 音符 · {pitch_range} · BDO: {instrument} · FX: {articulation} · 右键轨道更换乐器": "{track}・{count}ノート・{pitch_range}・BDO: {instrument}・FX: {articulation}・右クリックで楽器を変更", "{file} · {tracks} 轨 · {notes} 音符 · {minutes}m {seconds:02d}s · {pitch}": "{file}・{tracks}トラック・{notes}ノート・{minutes}m {seconds:02d}s・{pitch}", " · 已复制到游戏目录": "・ゲームフォルダーへコピー済み", "已保存 {file} · {bytes} bytes · {instruments} 乐器 · {tracks} 轨 · {notes} 音符{extra}": "{file}を保存・{bytes} bytes・{instruments}楽器・{tracks}トラック・{notes}ノート{extra}",
})

KO.update({
    "中性": "중립", "古典 / 管弦": "클래식 / 오케스트라", "摇滚": "록",
    "放克": "펑크", "氛围": "앰비언트", "爵士 / Swing": "재즈 / 스윙",
    "电子": "일렉트로닉", "自动判断": "자동 판단", "节奏念唱 / Rap": "리드미컬 / 랩",
    "花腔延展（Melisma）": "멜리스마", "连续连唱（Legato）": "연속 레가토",
    "逐音节（清晰咬字）": "음절식(명확한 발음)", "问答分句（先建议）": "콜 앤 리스폰스(제안 우선)",
    "允许写入的轨道（所有轨道始终参与只读上下文分析）": "쓰기 허용 트랙(모든 트랙은 읽기 전용 문맥 분석에 항상 참여)",
    "只在游戏支持范围内调整奏法、力度、轻微时序和全局声音效果。不会增删音符、改音高、换乐器或新增轨道；未通过游戏 A/B 的奏法不会写入。": "게임 지원 범위에서 주법, 벨로시티, 미세 타이밍과 전체 효과만 조정합니다. 음표, 음높이, 악기와 트랙은 유지하며 게임 A/B 검증이 끝나지 않은 주법은 기록하지 않습니다.",
    "复制到游戏目录": "게임 폴더로 복사", "修复可自动处理项": "자동 수정 적용",
    "未读取 Owner ID；导出的曲谱无法在游戏内编辑。": "악보 소유자 ID를 읽지 않아 내보낸 악보를 게임에서 편집할 수 없습니다.",
    "当前乐器暂未收录奏法。": "이 악기의 주법은 아직 등록되지 않았습니다.",
    "未指定奏法，导出时保留普通音符。 此设置会把该轨导出为同一种 BDO 奏法。": "주법을 지정하지 않아 일반 음표로 내보냅니다. 이 설정은 트랙 전체에 같은 BDO 주법을 적용합니다.",
    "延音踏板": "서스테인 페달", "延音 (type 0)": "서스테인 (type 0)",
    "延音踏板 (type 11)": "서스테인 페달 (type 11)", "无法原声还原": "원음 미리듣기 불가",
    "状态\n可转换": "상태\n내보내기 가능", "问题\n0": "문제\n0", "人工确认\n0": "검토 필요\n0",
    "可自动修复\n0 项": "자동 수정 가능\n0개", "已选 0 · 共 0 音符": "선택 0 · 전체 0개 음표",
    "奏法 0 处 · 轻微自然化 0 个音符\n效果：混响 0→0 · 延迟 0→0 · 合唱 (0, 0, 0)→(0, 0, 0)": "주법 0 · 휴머니즈 0개 음표\n효과: 리버브 0→0 · 딜레이 0→0 · 코러스 (0, 0, 0)→(0, 0, 0)",
    "已选 {selected} · 共 {total} 音符{position}{warning}": "선택 {selected} · 전체 {total}개 음표{position}{warning}",
    "状态\n{status}": "상태\n{status}", "问题\n{count}": "문제\n{count}",
    "人工确认\n{count}": "검토 필요\n{count}", "可自动修复\n{count} 项": "자동 수정 가능\n{count}개",
    "已读取 Owner ID：0x{owner_id:08x}": "악보 소유자 ID 읽음: 0x{owner_id:08x}",
    "可转换": "내보내기 가능", "不可转换": "내보내기 불가",
    " · 移调 {transpose:+d}": " · 조옮김 {transpose:+d}",
    " · 越界 {count}": " · 범위 초과 {count}",
    "从 MIDI 解析、游戏曲谱研究到原声试听，每一份开源代码、文档和测试都很重要。": "MIDI 분석과 게임 악보 연구부터 원음 미리듣기까지 모든 오픈 소스 코드, 문서와 테스트가 중요합니다.",
    "以当前代码中实际承担的功能作粗略估算": "현재 코드에서 담당하는 기능을 기준으로 한 대략적인 추정", "占比仅用于表达感谢，不代表代码所有权或精确工作量。Python 与 Qt 作为运行基础未计入图表。": "비율은 감사를 표현하기 위한 것이며 코드 소유권이나 정확한 작업량을 뜻하지 않습니다. 기반인 Python과 Qt는 포함하지 않았습니다.",
    "6 项核心依赖与贡献": "6개 핵심 의존성과 기여", "7 项核心依赖与贡献": "7개 핵심 의존성과 기여", "这不是一份排名，而是一张合作地图。谢谢每一个把工具、文档和经验分享出来的人。": "순위가 아니라 협업 지도입니다. 도구, 문서와 경험을 공유한 모든 분께 감사드립니다.", "复制为纯文本，便于放入项目说明或发布页面": "프로젝트 설명이나 릴리스 페이지용 일반 텍스트로 복사",
    "01 · MIDI 与游戏采样试听": "01 · MIDI와 게임 샘플 미리듣기", "把 MIDI 音符一颗颗读出来、写回去。": "MIDI 음표를 하나씩 읽고 씁니다.", "BDO 原始采样映射": "BDO 원본 샘플 매핑", "试听只使用从游戏提取并验证过的键位映射。": "게임에서 추출하고 검증한 키 매핑만 미리듣기에 사용합니다.",
    "02 · GitHub 开源项目": "02 · GitHub 오픈 소스 프로젝트", "感谢早期公开的 MIDI→BDO 格式探索与实现，为本项目初期研究提供参照；当前版本已采用独立实现，不包含或调用其运行时代码。": "프로젝트 초기 연구에 참고가 된 MIDI→BDO 형식의 초기 공개 탐구와 구현에 감사드립니다. 현재 버전은 독립 구현을 사용하며 해당 런타임 코드를 포함하거나 호출하지 않습니다.", "感谢黑色沙漠音乐文件研究与解码相关资料作者，帮助理解外部曲谱制作方向。": "외부 악보 제작 방향을 이해하도록 도운 검은사막 음악 파일 연구 및 디코딩 자료 작성자에게 감사드립니다.",
    "感谢 bdo-data-extractor 作者公开清晰的 PAZ、ICE 与 LZ 只读实现，帮助完善本地音源制作工具。": "명확한 읽기 전용 PAZ, ICE 및 LZ 구현을 공개하여 로컬 음원 팩 제작 도구 개선에 도움을 준 bdo-data-extractor 작성자에게 감사드립니다.",
    "03 · 开发协作": "03 · 개발 협업", "在旁边递思路、改文案、一起收拾代码。": "아이디어 제안, 문구 개선과 코드 정리를 함께했습니다.", "04 · 还有大家": "04 · 그리고 모두", "谢谢开源维护者、文档作者、issue 讨论者、测试者，以及每一个愿意分享经验的人。": "오픈 소스 관리자, 문서 작성자, 이슈 참여자, 테스터와 경험을 공유한 모든 분께 감사드립니다.",
    "感谢 CN 服务器 Rainbow Club 彩虹乐队玩家的支持、测试与音乐交流。": "CN 서버 Rainbow Club(彩虹乐队) 플레이어 여러분의 지원과 테스트, 음악 교류에 감사드립니다.",
    "载入失败": "불러오기 실패", "MIDI 已载入": "MIDI 불러옴", "MIDI 载入失败：{error}": "MIDI 불러오기 실패: {error}", "已新建 Track {track_id} · {instrument}": "Track {track_id} 생성 · {instrument}", "空轨道已创建；双击轨道可进入音符编辑器添加音符。": "빈 트랙을 만들었습니다. 더블 클릭해 음표 편집기에서 음표를 추가하세요.", "已删除 {track}": "{track} 삭제", "轨道已删除。请选择其他轨道，或新建一条空轨道。": "트랙을 삭제했습니다. 다른 트랙을 선택하거나 빈 트랙을 만드세요.",
    "无可用音频设备": "사용 가능한 오디오 장치 없음", "等待预取": "프리로드 대기", "原声已验证": "원음 검증됨", "原声近似": "원음 근사", "原声近似（待 A/B 验证）": "원음 근사(A/B 검증 대기)", "正在准备游戏音源…": "게임 음원 준비 중…", "试听播放": "미리듣기 재생", "试听暂停": "미리듣기 일시정지", "BDO 实时原声试听": "BDO 실시간 원음 미리듣기", "BDO 实时试听（{count} 项待验证）": "BDO 실시간 미리듣기(검증 대기 {count}개)", "实时音频引擎已停止": "실시간 오디오 엔진 중지",
    "BDO 实时试听缓冲不足 {count} 次 · 混音 P95 {p95:.1f} ms": "BDO 미리듣기 버퍼 부족 {count}회 · 믹싱 P95 {p95:.1f} ms", "音频输出停止：{error}": "오디오 출력 중지: {error}", "正在转换...": "내보내는 중...", "转换完成": "내보내기 완료", "转换失败": "내보내기 실패",
    "游戏映射：检测中": "게임 매핑: 감지 중", "轨道": "트랙", "导入 MIDI 后显示轨道": "MIDI를 가져오면 트랙 표시", "发现自动保存工程": "자동 저장 프로젝트 발견", "发现自动保存工程：{project} · 可点打开工程恢复": "자동 저장 발견: {project} · 프로젝트 열기로 복원 가능", "建议转换检查": "내보내기 검사 권장", "MIDI 已载入。建议先点“转换检查”，确认音域、FX 和打击乐映射后再导出。": "MIDI를 불러왔습니다. 내보내기 전에 음역, FX와 타악기 매핑을 확인하세요.", "工程已恢复": "프로젝트 복원됨", "已恢复自动保存工程：{project}": "자동 저장 프로젝트 복원: {project}", "自动保存失败：{error}": "자동 저장 실패: {error}", "已更新 {track} · {count} 音符": "{track} 업데이트 · 음표 {count}개", "音符编辑已写回；转换前建议运行一次转换检查。": "음표 편집을 적용했습니다. 내보내기 전에 검사를 실행하세요.", "{scope} 已优化": "{scope} 최적화됨", "已应用 {scope} 优化{effects}：建议再运行一次转换检查后导出。": "{scope} 최적화{effects}를 적용했습니다. 다시 검사한 뒤 내보내세요.", "全局 MIDI": "전체 MIDI", "，并应用游戏声音效果建议": ", 게임 사운드 효과 제안도 적용", "转换检查已修复": "내보내기 검사 수정 적용",
    "轨": "트랙", "当前": "활성", "块": "블록", "{track} · {count} 音符 · {pitch_range} · BDO: {instrument} · FX: {articulation} · 右键轨道更换乐器": "{track} · 음표 {count}개 · {pitch_range} · BDO: {instrument} · FX: {articulation} · 우클릭으로 악기 변경", "{file} · {tracks} 轨 · {notes} 音符 · {minutes}m {seconds:02d}s · {pitch}": "{file} · 트랙 {tracks}개 · 음표 {notes}개 · {minutes}m {seconds:02d}s · {pitch}", " · 已复制到游戏目录": " · 게임 폴더에 복사됨", "已保存 {file} · {bytes} bytes · {instruments} 乐器 · {tracks} 轨 · {notes} 音符{extra}": "{file} 저장 · {bytes} bytes · 악기 {instruments}개 · 트랙 {tracks}개 · 음표 {notes}개{extra}",
})


EN.update({
    "启用 Marnian Muse 深度优化": "Enable Marnian Muse Deep Optimization",
    "乐谱修复": "Score Repair", "旋律修复": "Melody Repair", "和弦修复": "Chord Repair",
    "伴奏生成": "Accompaniment", "乐器交接": "Instrument Handoff", "情绪表达": "Emotion Expression",
    "演奏表达": "Performance Expression", "应用所选优化": "Apply Selected Optimization",
    "深度候选会在游戏安全优化之后分析；只有勾选的类别才会增删音符、修改音高或创建建议轨。":
        "Deep candidates are analyzed after game-safe optimization. Only selected categories may add/delete notes, change pitch, or create suggestion tracks.",
})
JA.update({
    "启用 Marnian Muse 深度优化": "Marnian Muse 深層最適化を有効化",
    "乐谱修复": "スコア修復", "旋律修复": "メロディ修復", "和弦修复": "コード修復",
    "伴奏生成": "伴奏生成", "乐器交接": "楽器の受け渡し", "情绪表达": "感情表現",
    "演奏表达": "演奏表現", "应用所选优化": "選択した最適化を適用",
    "深度候选会在游戏安全优化之后分析；只有勾选的类别才会增删音符、修改音高或创建建议轨。":
        "深層候補はゲーム安全最適化の後に解析されます。選択したカテゴリだけが音符の追加・削除、音高変更、提案トラック作成を行います。",
})
KO.update({
    "启用 Marnian Muse 深度优化": "Marnian Muse 심층 최적화 사용",
    "乐谱修复": "악보 복구", "旋律修复": "멜로디 복구", "和弦修复": "화음 복구",
    "伴奏生成": "반주 생성", "乐器交接": "악기 전환", "情绪表达": "감정 표현",
    "演奏表达": "연주 표현", "应用所选优化": "선택한 최적화 적용",
    "深度候选会在游戏安全优化之后分析；只有勾选的类别才会增删音符、修改音高或创建建议轨。":
        "심층 후보는 게임 안전 최적화 후 분석됩니다. 선택한 범주만 음표 추가·삭제, 음높이 변경 또는 제안 트랙 생성을 수행합니다.",
})

EN.update({
    "比较 BDO 乐谱": "Compare BDO Scores",
    "样本覆盖": "Sample Coverage",
    "其他轨道参考": "Other Track Reference",
    "循环": "Loop",
    "双击问题可定位到对应轨道和音符": "Double-click an issue to locate its track and notes.",
    "BDO 谱面对比": "BDO Score Comparison",
    "已撤销工程修改": "Project change undone",
    "已重做工程修改": "Project change redone",
})
JA.update({
    "比较 BDO 乐谱": "BDOスコアを比較",
    "样本覆盖": "サンプル範囲",
    "其他轨道参考": "他トラックを参照",
    "循环": "ループ",
    "双击问题可定位到对应轨道和音符": "問題をダブルクリックするとトラックと音符を表示します。",
    "BDO 谱面对比": "BDOスコア比較",
    "已撤销工程修改": "プロジェクトの変更を元に戻しました",
    "已重做工程修改": "プロジェクトの変更をやり直しました",
})
KO.update({
    "比较 BDO 乐谱": "BDO 악보 비교",
    "样本覆盖": "샘플 범위",
    "其他轨道参考": "다른 트랙 참조",
    "循环": "반복",
    "双击问题可定位到对应轨道和音符": "문제를 두 번 클릭하면 해당 트랙과 음표로 이동합니다.",
    "BDO 谱面对比": "BDO 악보 비교",
    "已撤销工程修改": "프로젝트 변경을 실행 취소했습니다",
    "已重做工程修改": "프로젝트 변경을 다시 실행했습니다",
})

EN.update({
    "拖动编辑 · 双击新建 · Space 播放": "Drag to edit · Double-click to add · Space to play",
    "先处理阻断项，再逐条确认预期变化；双击问题可定位。": "Resolve blockers first, then review expected changes. Double-click an issue to locate it.",
    "导出摘要": "Export Summary",
    "问题与预期变化": "Issues and Expected Changes",
    "严重问题优先显示": "Critical issues are shown first",
    "未发现阻断项或待确认变化": "No blockers or changes awaiting confirmation",
    "轨道音量": "Track Volume", "游戏轨道音量": "In-game Track Volume",
    "显示力度编辑 ▸": "Show Velocity Editor ▸", "隐藏力度编辑 ▾": "Hide Velocity Editor ▾",
    "显示或隐藏力度编辑": "Show or hide the velocity editor",
    "拖动柱形可直接调整所选音符力度": "Drag bars to adjust note velocity",
    "拖动手柄 · 横向拖绘渐变 · 多选后整体调整 · Ctrl+↑↓ 微调": "Drag handles · Paint ramps horizontally · Adjust selections together · Ctrl+↑↓ to fine-tune",
    "音符检查器": "Note Inspector", "未选择音符": "No note selected",
    "音块编辑器": "Piano Roll Editor",
    "双击空白处，写下第一个音符": "Double-click the grid to write your first note",
    "按 B 进入绘制模式 · Space 播放": "Press B for draw mode · Space to play",
    "未选择音符 · 双击网格新建": "No note selected · Double-click the grid to add one",
    "在网格空白处单击即可新建": "Click an empty grid cell to add a note",
    "音符": "Note", "网格": "Grid",
    "绘制 B": "Draw B", "点击试听": "Audition",
    "绘制模式：拖动可同时设置音符长度与力度（B）": "Draw mode: drag to set note length and velocity (B)",
    "绘制模式：拖动设置长度，上下调整力度，Alt 取消吸附": "Draw mode: drag for length, move vertically for velocity, Alt bypasses snap",
    "选择模式：双击新建，拖动空白框选，Ctrl+拖动复制": "Select mode: double-click to add, drag empty space to select, Ctrl-drag to clone",
    "选择音符后应用奏法": "Select notes, then apply a Musical Technique",
    "常用奏法": "Common Musical Techniques", "网格与参考": "Grid and Reference", "水平缩放": "Horizontal Zoom",
    "右键删除音符 · Ctrl 拖选追加 · 拖动音符两端调整时值": "Right-click to delete · Ctrl-drag to add selection · Drag note edges to resize",
    "右键删除 · Ctrl 拖选追加 · 拖动两端调整时值": "Right-click to delete · Ctrl-drag to add selection · Drag edges to resize",
    "双击新建 · Ctrl+拖动复制 · Alt 临时取消吸附 · Ctrl+D 复制": "Double-click to add · Ctrl-drag to clone · Alt bypasses snap · Ctrl+D duplicates",
    "已选择 1 个音符 · {note} · {start} ms": "1 note selected · {note} · {start} ms",
    "已选择 {count} 个音符 · 可批量修改共同属性": "{count} notes selected · Shared properties can be edited together",
    "准备中…": "Preparing…", "正在准备游戏音源… {loaded}/{total}": "Preparing game audio… {loaded}/{total}",
    "游戏音源已缓存 · 开始试听": "Game audio cached · Starting preview",
    "当前音符没有可用的游戏音源": "No game-audio sample is available for this note",
    "正在准备音符试听… {note}": "Preparing note preview… {note}",
    "试听 {note}": "Previewing {note}",
    "音符试听不可用：{message}": "Note preview unavailable: {message}",
})
JA.update({
    "拖动编辑 · 双击新建 · Space 播放": "ドラッグで編集・ダブルクリックで追加・Spaceで再生",
    "先处理阻断项，再逐条确认预期变化；双击问题可定位。": "まず阻害項目を解決し、想定される変更を確認します。ダブルクリックで場所を表示できます。",
    "导出摘要": "書き出し概要",
    "问题与预期变化": "問題と想定される変更",
    "严重问题优先显示": "重大な問題を優先表示",
    "未发现阻断项或待确认变化": "阻害項目や確認待ちの変更はありません",
    "轨道音量": "トラック音量", "游戏轨道音量": "ゲーム内トラック音量",
    "显示力度编辑 ▸": "ベロシティ編集を表示 ▸", "隐藏力度编辑 ▾": "ベロシティ編集を隠す ▾",
    "显示或隐藏力度编辑": "ベロシティエディタの表示を切り替え",
    "拖动柱形可直接调整所选音符力度": "バーをドラッグしてベロシティを調整",
    "拖动手柄 · 横向拖绘渐变 · 多选后整体调整 · Ctrl+↑↓ 微调": "ハンドルをドラッグ・横方向にランプを描画・複数選択を一括調整・Ctrl+↑↓で微調整",
    "音符检查器": "ノートインスペクタ", "未选择音符": "ノート未選択",
    "音块编辑器": "ピアノロールエディタ",
    "双击空白处，写下第一个音符": "空白をダブルクリックして最初のノートを書きましょう",
    "按 B 进入绘制模式 · Space 播放": "Bで描画モード・Spaceで再生",
    "未选择音符 · 双击网格新建": "ノート未選択・グリッドをダブルクリックして追加",
    "在网格空白处单击即可新建": "空のグリッドをクリックしてノートを追加",
    "音符": "ノート", "网格": "グリッド",
    "绘制 B": "描画 B", "点击试听": "試聴",
    "绘制模式：拖动可同时设置音符长度与力度（B）": "描画モード：ドラッグでノート長とベロシティを設定（B）",
    "绘制模式：拖动设置长度，上下调整力度，Alt 取消吸附": "描画モード：ドラッグで長さ、上下でベロシティ、Altでスナップ解除",
    "选择模式：双击新建，拖动空白框选，Ctrl+拖动复制": "選択モード：ダブルクリックで追加、空白ドラッグで範囲選択、Ctrlドラッグで複製",
    "选择音符后应用奏法": "ノートを選択して奏法を適用",
    "常用奏法": "よく使う奏法", "网格与参考": "グリッドと参照", "水平缩放": "横方向ズーム",
    "右键删除音符 · Ctrl 拖选追加 · 拖动音符两端调整时值": "右クリックで削除・Ctrlドラッグで選択追加・端をドラッグして長さを調整",
    "右键删除 · Ctrl 拖选追加 · 拖动两端调整时值": "右クリックで削除・Ctrlドラッグで選択追加・端をドラッグして長さを調整",
    "双击新建 · Ctrl+拖动复制 · Alt 临时取消吸附 · Ctrl+D 复制": "ダブルクリックで追加・Ctrlドラッグで複製・Altでスナップ解除・Ctrl+Dで複製",
    "已选择 1 个音符 · {note} · {start} ms": "1ノート選択・{note}・{start} ms",
    "已选择 {count} 个音符 · 可批量修改共同属性": "{count}ノート選択・共通属性を一括編集できます",
    "准备中…": "準備中…", "正在准备游戏音源… {loaded}/{total}": "ゲーム音源を準備中… {loaded}/{total}",
    "游戏音源已缓存 · 开始试听": "ゲーム音源をキャッシュしました・プレビューを開始",
    "当前音符没有可用的游戏音源": "このノートに使用できるゲーム音源がありません",
    "正在准备音符试听… {note}": "ノートプレビューを準備中… {note}",
    "试听 {note}": "{note} をプレビュー中",
    "音符试听不可用：{message}": "ノートプレビューを利用できません：{message}",
})
KO.update({
    "拖动编辑 · 双击新建 · Space 播放": "드래그로 편집 · 더블 클릭으로 추가 · Space로 재생",
    "先处理阻断项，再逐条确认预期变化；双击问题可定位。": "차단 문제를 먼저 해결한 뒤 예상 변경을 확인하세요. 더블 클릭하면 위치로 이동합니다.",
    "导出摘要": "내보내기 요약",
    "问题与预期变化": "문제 및 예상 변경",
    "严重问题优先显示": "심각한 문제 우선 표시",
    "未发现阻断项或待确认变化": "차단 문제나 확인 대기 중인 변경이 없습니다",
    "轨道音量": "트랙 볼륨", "游戏轨道音量": "게임 내 트랙 볼륨",
    "显示力度编辑 ▸": "벨로시티 편집 표시 ▸", "隐藏力度编辑 ▾": "벨로시티 편집 숨기기 ▾",
    "显示或隐藏力度编辑": "벨로시티 편집기 표시 또는 숨기기",
    "拖动柱形可直接调整所选音符力度": "막대를 드래그하여 음표 벨로시티 조정",
    "拖动手柄 · 横向拖绘渐变 · 多选后整体调整 · Ctrl+↑↓ 微调": "핸들 드래그 · 가로로 램프 그리기 · 다중 선택 함께 조정 · Ctrl+↑↓ 미세 조정",
    "音符检查器": "음표 검사기", "未选择音符": "선택한 음표 없음",
    "音块编辑器": "피아노 롤 편집기",
    "双击空白处，写下第一个音符": "빈 공간을 두 번 클릭해 첫 음표를 작성하세요",
    "按 B 进入绘制模式 · Space 播放": "B로 그리기 모드 · Space로 재생",
    "未选择音符 · 双击网格新建": "선택한 음표 없음 · 그리드를 두 번 클릭하여 추가",
    "在网格空白处单击即可新建": "빈 그리드를 클릭하여 음표 추가",
    "音符": "음표", "网格": "그리드",
    "绘制 B": "그리기 B", "点击试听": "미리듣기",
    "绘制模式：拖动可同时设置音符长度与力度（B）": "그리기 모드: 드래그하여 음표 길이와 벨로시티 설정(B)",
    "绘制模式：拖动设置长度，上下调整力度，Alt 取消吸附": "그리기 모드: 드래그로 길이, 위아래로 벨로시티, Alt로 스냅 해제",
    "选择模式：双击新建，拖动空白框选，Ctrl+拖动复制": "선택 모드: 두 번 클릭해 추가, 빈 공간을 드래그해 선택, Ctrl+드래그로 복제",
    "选择音符后应用奏法": "음표를 선택한 뒤 주법 적용",
    "常用奏法": "자주 쓰는 주법", "网格与参考": "그리드 및 참조", "水平缩放": "가로 확대/축소",
    "右键删除音符 · Ctrl 拖选追加 · 拖动音符两端调整时值": "우클릭으로 삭제 · Ctrl 드래그로 선택 추가 · 음표 가장자리를 드래그하여 길이 조절",
    "右键删除 · Ctrl 拖选追加 · 拖动两端调整时值": "우클릭으로 삭제 · Ctrl 드래그로 선택 추가 · 가장자리를 드래그하여 길이 조절",
    "双击新建 · Ctrl+拖动复制 · Alt 临时取消吸附 · Ctrl+D 复制": "두 번 클릭해 추가 · Ctrl+드래그로 복제 · Alt로 스냅 해제 · Ctrl+D로 복제",
    "已选择 1 个音符 · {note} · {start} ms": "음표 1개 선택 · {note} · {start} ms",
    "已选择 {count} 个音符 · 可批量修改共同属性": "음표 {count}개 선택 · 공통 속성을 함께 편집할 수 있습니다",
    "准备中…": "준비 중…", "正在准备游戏音源… {loaded}/{total}": "게임 음원 준비 중… {loaded}/{total}",
    "游戏音源已缓存 · 开始试听": "게임 음원 캐시 완료 · 미리듣기 시작",
    "当前音符没有可用的游戏音源": "이 음표에 사용할 수 있는 게임 음원이 없습니다",
    "正在准备音符试听… {note}": "음표 미리듣기 준비 중… {note}",
    "试听 {note}": "{note} 미리듣기",
    "音符试听不可用：{message}": "음표 미리듣기를 사용할 수 없음: {message}",
})

EN.update({
    "全局曲线": "Global Curve",
    "按时间为整轨力度应用渐强或渐弱曲线": "Apply a crescendo or decrescendo curve over the track timeline",
    "全局力度曲线": "Global Velocity Curve",
    "按音符所在时间逐渐缩放力度；原有强弱关系会被保留。": "Scale velocity over note time while preserving the existing dynamics.",
    "当前轨道全部音符": "All notes in this track",
    "已选音符（{count}）": "Selected notes ({count})",
    "线性": "Linear",
    "平滑 S 曲线": "Smooth S-curve",
    "缓慢进入": "Slow start",
    "快速进入": "Fast start",
    "作用范围": "Scope",
    "起始力度": "Start velocity",
    "结束力度": "End velocity",
    "曲线形状": "Curve shape",
    "应用曲线": "Apply Curve",
    "已应用全局力度曲线 · {count} 个音符": "Global velocity curve applied · {count} notes",
    "本地工程与最近打开的 MIDI · 同名项目自动合并": "Local projects and recent MIDI · Same-title items are grouped",
    "{time} · {count} 个版本": "{time} · {count} versions",
    "\n已合并 {count} 个版本，双击打开最新工程": "\n{count} versions grouped; double-click to open the latest project",
})
JA.update({
    "全局曲线": "全体カーブ",
    "按时间为整轨力度应用渐强或渐弱曲线": "トラック全体に時間ベースのクレッシェンド／デクレッシェンドを適用",
    "全局力度曲线": "全体ベロシティカーブ",
    "按音符所在时间逐渐缩放力度；原有强弱关系会被保留。": "ノート位置に沿ってベロシティを変化させ、元の強弱関係を保持します。",
    "当前轨道全部音符": "現在のトラックの全ノート",
    "已选音符（{count}）": "選択ノート（{count}）",
    "线性": "リニア",
    "平滑 S 曲线": "滑らかなSカーブ",
    "缓慢进入": "ゆっくり開始",
    "快速进入": "素早く開始",
    "作用范围": "適用範囲",
    "起始力度": "開始ベロシティ",
    "结束力度": "終了ベロシティ",
    "曲线形状": "カーブ形状",
    "应用曲线": "カーブを適用",
    "已应用全局力度曲线 · {count} 个音符": "全体ベロシティカーブを適用 · {count}ノート",
    "本地工程与最近打开的 MIDI · 同名项目自动合并": "ローカルプロジェクトと最近のMIDI · 同名項目を自動統合",
    "{time} · {count} 个版本": "{time} · {count}バージョン",
    "\n已合并 {count} 个版本，双击打开最新工程": "\n{count}バージョンを統合・ダブルクリックで最新プロジェクトを開く",
})
KO.update({
    "全局曲线": "전체 커브",
    "按时间为整轨力度应用渐强或渐弱曲线": "트랙 시간축에 크레셴도 또는 디크레셴도 커브 적용",
    "全局力度曲线": "전체 벨로시티 커브",
    "按音符所在时间逐渐缩放力度；原有强弱关系会被保留。": "음표 위치에 따라 벨로시티를 조절하며 기존 강약 관계를 유지합니다.",
    "当前轨道全部音符": "현재 트랙의 모든 음표",
    "已选音符（{count}）": "선택한 음표({count})",
    "线性": "선형",
    "平滑 S 曲线": "부드러운 S 커브",
    "缓慢进入": "느리게 시작",
    "快速进入": "빠르게 시작",
    "作用范围": "적용 범위",
    "起始力度": "시작 벨로시티",
    "结束力度": "끝 벨로시티",
    "曲线形状": "커브 형태",
    "应用曲线": "커브 적용",
    "已应用全局力度曲线 · {count} 个音符": "전체 벨로시티 커브 적용 · {count}개 음표",
    "本地工程与最近打开的 MIDI · 同名项目自动合并": "로컬 프로젝트 및 최근 MIDI · 같은 이름은 자동으로 묶음",
    "{time} · {count} 个版本": "{time} · {count}개 버전",
    "\n已合并 {count} 个版本，双击打开最新工程": "\n{count}개 버전을 묶음 · 더블 클릭하여 최신 프로젝트 열기",
})

TRANSLATIONS = {"en_US": EN, "ja_JP": JA, "ko_KR": KO}
EN.update({
    "感谢以下项目、作者与社区。": "Thanks to the following projects, authors, and communities.",
    "项目、作者与社区": "Projects, Authors, and Communities",
    "格式研究与早期启发": "Format Research and Early Inspiration",
    "开源基础": "Open-source Foundations",
    "采样、验证与协作": "Sampling, Validation, and Collaboration",
    "开源维护者、文档作者、测试者与社区玩家": "Open-source maintainers, documentation authors, testers, and community players",
    "正在打开曲谱工作台": "Opening the Score Workspace",
    "正在启动音乐工作台…": "Starting the music workspace…",
    "本地项目和游戏曲谱只在这台电脑上读取": "Local projects and game scores are read only on this computer",
    "正在检查扩展组件…": "Checking extensions…",
    "正在载入界面与本地项目…": "Loading the interface and local projects…",
    "准备完成": "Ready",
    "双击曲谱或项目即可打开；主页扫描不会读取曲谱中的身份信息。": "Double-click a score or project to open it; the home scan does not read identity data from scores.",
    "双击网格新建音符；按 B 切换绘制模式。": "Double-click the grid to add a note; press B to toggle draw mode.",
    "选择音符后即可批量应用奏法。": "Select notes to apply an articulation in a batch.",
    "{track} · {count} 音符 · {pitch_range} · BDO: {instrument} · FX: {articulation}": "{track} · {count} notes · {pitch_range} · BDO: {instrument} · FX: {articulation}",
})

JA.update({
    "感谢以下项目、作者与社区。": "以下のプロジェクト、作者、コミュニティに感謝します。",
    "项目、作者与社区": "プロジェクト・作者・コミュニティ",
    "格式研究与早期启发": "フォーマット研究と初期の着想",
    "开源基础": "オープンソース基盤",
    "采样、验证与协作": "サンプリング・検証・協力",
    "开源维护者、文档作者、测试者与社区玩家": "オープンソース保守者、文書作者、テスター、コミュニティの皆様",
    "正在打开曲谱工作台": "楽譜ワークスペースを開いています",
    "正在启动音乐工作台…": "音楽ワークスペースを起動しています…",
    "本地项目和游戏曲谱只在这台电脑上读取": "ローカルプロジェクトとゲーム楽譜はこのPC上でのみ読み取ります",
    "正在检查扩展组件…": "拡張機能を確認しています…",
    "正在载入界面与本地项目…": "画面とローカルプロジェクトを読み込んでいます…",
    "准备完成": "準備完了",
    "双击曲谱或项目即可打开；主页扫描不会读取曲谱中的身份信息。": "楽譜またはプロジェクトをダブルクリックして開きます。ホーム画面のスキャンでは楽譜内の個人情報を読み取りません。",
    "双击网格新建音符；按 B 切换绘制模式。": "グリッドをダブルクリックして音符を追加し、Bキーで描画モードを切り替えます。",
    "选择音符后即可批量应用奏法。": "音符を選択すると奏法をまとめて適用できます。",
    "{track} · {count} 音符 · {pitch_range} · BDO: {instrument} · FX: {articulation}": "{track} · {count}音符 · {pitch_range} · BDO: {instrument} · FX: {articulation}",
})

KO.update({
    "感谢以下项目、作者与社区。": "다음 프로젝트, 작성자와 커뮤니티에 감사드립니다.",
    "项目、作者与社区": "프로젝트·작성자·커뮤니티",
    "格式研究与早期启发": "형식 연구와 초기 영감",
    "开源基础": "오픈 소스 기반",
    "采样、验证与协作": "샘플링·검증·협업",
    "开源维护者、文档作者、测试者与社区玩家": "오픈 소스 유지관리자, 문서 작성자, 테스터와 커뮤니티 플레이어",
    "正在打开曲谱工作台": "악보 작업 공간을 여는 중",
    "正在启动音乐工作台…": "음악 작업 공간을 시작하는 중…",
    "本地项目和游戏曲谱只在这台电脑上读取": "로컬 프로젝트와 게임 악보는 이 컴퓨터에서만 읽습니다",
    "正在检查扩展组件…": "확장 구성 요소를 확인하는 중…",
    "正在载入界面与本地项目…": "화면과 로컬 프로젝트를 불러오는 중…",
    "准备完成": "준비 완료",
    "双击曲谱或项目即可打开；主页扫描不会读取曲谱中的身份信息。": "악보 또는 프로젝트를 두 번 클릭해 엽니다. 홈 스캔은 악보의 신원 정보를 읽지 않습니다.",
    "双击网格新建音符；按 B 切换绘制模式。": "그리드를 두 번 클릭해 음표를 추가하고 B 키로 그리기 모드를 전환합니다.",
    "选择音符后即可批量应用奏法。": "음표를 선택하면 주법을 일괄 적용할 수 있습니다.",
    "{track} · {count} 音符 · {pitch_range} · BDO: {instrument} · FX: {articulation}": "{track} · {count}개 음표 · {pitch_range} · BDO: {instrument} · FX: {articulation}",
})

EN.update({
    "扒谱": "Transcription",
    "标准/独奏": "Standard / Solo",
    "混音增强": "Mix Enhanced",
    "识别模式已更改；请重新分析整首。": "Recognition mode changed; analyze the full song again.",
    "载入参考音频": "Load Reference Audio",
    "卸载参考音频": "Unload Reference Audio",
    "分析整首": "Analyze Full Song",
    "重新分析区间": "Re-analyze Range",
    "置信度": "Confidence",
    "仅已拒绝": "Rejected Only",
    "证据轮廓": "Evidence Contour",
    "清除 A–B": "Clear A–B",
    "默认关闭细粒度音高轮廓证据": "Fine-grained pitch-contour evidence is off by default",
    "载入参考音频后可开始整首分析": "Load reference audio to analyze the full song",
    "载入参考音频后显示对齐波形": "Load reference audio to show the aligned waveform",
    "目标 BDO 乐器轨": "Target BDO Instrument Track",
    "候选默认只路由到当前轨；打击乐轨不会出现在此处。": "Candidates route only to the current track by default; percussion tracks are not listed.",
    "音频位置对齐播放头": "Align Audio Position to Playhead",
    "将播放头设为第一拍": "Set Playhead as First Beat",
    "审阅撤销": "Undo Review",
    "审阅重做": "Redo Review",
    "拒绝": "Reject",
    "恢复": "Restore",
    "写入当前轨草稿": "Write to Current Track Draft",
    "显式复制到…": "Explicit Copy to…",
    "复制到其他轨": "Copy to Other Track",
    "清除本次暂存": "Clear This Staging",
    "清除暂存": "Clear Staging",
    "未暂存候选": "No Staged Candidates",
    "已暂存 {count} 个候选": "{count} Candidates Staged",
    "存在未提交候选草稿": "Uncommitted Candidate Draft",
    "请先应用、撤销或清除本次暂存，再更换音频或重新分析。": "Apply, undo, or clear this staging before changing audio or analyzing again.",
    "请先应用、撤销或清除本次暂存，再修改音频对齐。": "Apply, undo, or clear this staging before changing audio alignment.",
    "请从“显式复制到…”选择目标轨": "Choose a destination from “Explicit Copy to…”.",
    "无法应用音符编辑": "Cannot Apply Note Edit",
    "目标轨道已经失效，或草稿包含无效音符。": "The target track is no longer valid, or the draft contains an invalid note.",
    "音符编辑已作为一个工程操作写入；可整批撤销。": "The note edit was written as one project operation and can be undone as a batch.",
    "在当前乐器轨的音符编辑器中打开完整扒谱模式": "Open full transcription mode in the current instrument track’s note editor",
    "在当前音符编辑器中显示分析证据、候选和参考波形": "Show analysis evidence, candidates, and the reference waveform in this note editor",
    "当前工程没有可用于扒谱的旋律乐器轨，请先新建乐器轨。": "This project has no melodic instrument track available for transcription. Create an instrument track first.",
    "请选择要打开的旋律乐器轨：": "Choose the melodic instrument track to open:",
    "请先选择候选或设置 A–B 区间": "Select candidates or set an A–B range first",
    "{count} 个候选；识别结果仍需人工审阅": "{count} candidates; recognition results still require manual review",
    "目标轨道不可用": "The target track is unavailable",
    "没有可复制的候选": "No candidates are available to copy",
    "已清除本次暂存；草稿音符保留为手工编辑": "This staging was cleared; its draft notes remain as manual edits",
    "部分候选未提交 · 失效 {invalid} · 孤立 {orphaned}": "Some candidates were not committed · {invalid} invalid · {orphaned} orphaned",
    "未知 BDO 乐器": "Unknown BDO instrument",
    " · BDO v9 结构回读通过": " · BDO v9 structure read-back passed",
    " · 回读检查失败：{error}": " · Read-back check failed: {error}",
    "转换完成（回读检查失败）": "Conversion completed (read-back check failed)",
    "当前仍有未提交候选草稿。请先应用，或撤销/清除本次暂存后再更换音频、调整偏移或重新分析。": "There is an uncommitted candidate draft. Apply it first, or undo/clear this staging before changing audio, adjusting the offset, or analyzing again.",
    "选择扒谱目标轨": "Choose Transcription Target Track",
    "请选择一条旋律乐器轨后进入扒谱模式。": "Choose a melodic-instrument track before entering transcription mode.",
    "当前没有可用的旋律乐器轨，请先新建乐器轨。": "No melodic-instrument track is available. Create an instrument track first.",
    "已清除本次暂存": "This staging was cleared",
    "路由到当前轨": "Route to Current Track",
    "复制到当前轨": "Copy to Current Track",
    "应用到工程": "Apply to Project",
    "应用到工程 · {apply_count}": "Apply to Project · {apply_count}",
    "应用到工程 · ": "Apply to Project · ",
    "正在分析参考音频 · ": "Analyzing reference audio · ",
    "轨道 ": "Track ",
    " 音符": " notes",
    "平衡": "Balanced",
    "敏感": "Sensitive",
    "循环区间": "Loop Range",
    "循环播放 A–B 时间区间": "Loop the A–B time range",
    "请选择一条非打击乐 BDO 乐器轨。": "Select a non-percussion BDO instrument track.",
    "请先载入参考音频。": "Load reference audio first.",
    "请先载入 MP3/WAV 参考音频": "Load an MP3/WAV reference first",
    "请先载入 MP3/WAV 参考音频。": "Load an MP3/WAV reference first.",
    "请先在音符编辑器选择候选或设置 A–B 区间": "Select candidates or set an A–B range in the note editor first",
    "更换参考音频": "Change Reference Audio",
    "当前仍有尚未应用的扒谱路由。更换或卸载音频会丢弃这些审阅路由；已应用的正式音符不受影响。是否继续？": "There are unapplied transcription routes. Changing or unloading the audio will discard those review routes; applied formal notes are unaffected. Continue?",
    "当前音频位置已对齐到播放头。": "The current audio position is aligned to the playhead.",
    "第一拍锚点已更新；正式音符位置未移动。": "The first-beat anchor was updated; formal notes were not moved.",
    "主窗口扒谱会话不可用": "The main-window transcription session is unavailable",
    "正在使用主窗口扒谱会话分析；正式音符不会自动改变": "Analyzing with the main-window transcription session; formal notes will not change automatically",
    "候选来自主窗口会话；写入草稿后仍需应用或确定": "Candidates come from the main-window session; after writing to the draft, Apply or OK is still required",
    "准备分析…": "Preparing analysis…",
    "正在分析…": "Analyzing…",
    "正在分析参考音频…": "Analyzing reference audio…",
    "正在分析参考音频 · {progress}%": "Analyzing reference audio · {progress}%",
    "区间重解码失败：{error}": "Range re-decoding failed: {error}",
    "区间重解码失败。": "Range re-decoding failed.",
    "本地扒谱引擎未能加载，当前程序安装可能不完整。请重新构建或安装完整程序后再试。": "The local transcription engine could not be loaded; this installation may be incomplete. Rebuild or reinstall the complete application and try again.",
    "扒谱组件尚未安装或不可用。请在程序目录运行：\npowershell -ExecutionPolicy Bypass -File scripts\\install_transcription.ps1": "The transcription component is not installed or unavailable. Run this from the project directory:\npowershell -ExecutionPolicy Bypass -File scripts\\install_transcription.ps1",
    "扒谱组件检查失败。详细原因已写入日志。": "The transcription component check failed. Details were written to the log.",
    "扒谱引擎加载失败（缺少运行模块）。详细原因已写入日志。": "The transcription engine could not load because a runtime module is missing. Details were written to the log.",
    "正在从缓存证据重新解码 A–B；不会再次运行模型。": "Re-decoding A–B from cached evidence; the model will not run again.",
    "正在校验并恢复扒谱缓存…": "Validating and restoring the transcription cache…",
    "扒谱缓存不存在或校验失败；请重新分析整首。": "The transcription cache is missing or invalid; analyze the full song again.",
    "参考音频已变化；旧审阅状态已隔离，请重新分析整首。": "The reference audio changed; the old review state was isolated. Analyze the full song again.",
    "缓存无法恢复；请重新分析整首。": "The cache could not be restored; analyze the full song again.",
    "碎音处理切换失败；已恢复原档位。": "Fragment-cleanup switching failed; the previous profile was restored.",
    "碎音处理切换已取消；已恢复原档位。": "Fragment-cleanup switching was cancelled; the previous profile was restored.",
    "扒谱分析失败。": "Transcription analysis failed.",
    "扒谱分析已取消。": "Transcription analysis was cancelled.",
    "已路由 {count} 个 · 越界 {invalid} · 已满足 {duplicates}": "Routed {count} · {invalid} out of range · {duplicates} already satisfied",
    "已拒绝 {count} 个候选": "Rejected {count} candidates",
    "已恢复 {count} 个候选": "Restored {count} candidates",
    "区间重解码完成 · 新增 {added} · 替换 {removed} · 保护 {protected}": "Range re-decoded · {added} added · {removed} replaced · {protected} protected",
    "{prefix}{count} 个候选；识别结果仍需人工审阅": "{prefix}{count} candidates; recognition results still require manual review",
    "已恢复缓存 · ": "Cache restored · ",
    "分析完成 · ": "Analysis complete · ",
    "没有可应用路由 · 失效 {invalid} · 孤立 {orphaned}": "No applicable routes · {invalid} invalid · {orphaned} orphaned",
    "已应用 {created} 个音符 · 已满足 {satisfied} · 保留失效 {invalid} · 孤立 {orphaned}": "Applied {created} notes · {satisfied} already satisfied · {invalid} invalid retained · {orphaned} orphaned",
    "扒谱候选已作为一个工程操作写入；可整批撤销。": "Transcription candidates were written as one project operation and can be undone together.",
})

JA.update({
    "扒谱": "採譜",
    "标准/独奏": "標準／ソロ",
    "混音增强": "ミックス強化",
    "识别模式已更改；请重新分析整首。": "認識モードを変更しました。全曲を再解析してください。",
    "载入参考音频": "参照オーディオを読み込む",
    "卸载参考音频": "参照オーディオを解除",
    "分析整首": "全曲を解析",
    "重新分析区间": "区間を再解析",
    "置信度": "信頼度",
    "仅已拒绝": "拒否済みのみ",
    "证据轮廓": "証拠輪郭",
    "清除 A–B": "A–Bをクリア",
    "默认关闭细粒度音高轮廓证据": "細粒度の音高輪郭証拠は既定でオフです",
    "载入参考音频后可开始整首分析": "参照オーディオを読み込むと全曲解析を開始できます",
    "载入参考音频后显示对齐波形": "参照オーディオを読み込むと整列した波形を表示します",
    "目标 BDO 乐器轨": "対象BDO楽器トラック",
    "候选默认只路由到当前轨；打击乐轨不会出现在此处。": "候補は既定で現在のトラックだけに割り当てます。打楽器トラックは表示されません。",
    "音频位置对齐播放头": "オーディオ位置を再生ヘッドに合わせる",
    "将播放头设为第一拍": "再生ヘッドを第1拍に設定",
    "审阅撤销": "確認を元に戻す",
    "审阅重做": "確認をやり直す",
    "拒绝": "拒否",
    "恢复": "復元",
    "写入当前轨草稿": "現在のトラックの下書きに書き込む",
    "显式复制到…": "明示的にコピー…",
    "复制到其他轨": "他のトラックへコピー",
    "清除本次暂存": "今回の一時保存をクリア",
    "清除暂存": "一時保存をクリア",
    "未暂存候选": "一時候補なし",
    "已暂存 {count} 个候选": "{count}件の候補を一時保存",
    "存在未提交候选草稿": "未確定の候補下書きがあります",
    "请先应用、撤销或清除本次暂存，再更换音频或重新分析。": "オーディオ変更や再解析の前に、今回の一時保存を適用、元に戻す、またはクリアしてください。",
    "请先应用、撤销或清除本次暂存，再修改音频对齐。": "オーディオ位置を変更する前に、今回の一時保存を適用、元に戻す、またはクリアしてください。",
    "请从“显式复制到…”选择目标轨": "「明示的にコピー…」からコピー先を選択してください。",
    "无法应用音符编辑": "音符編集を適用できません",
    "目标轨道已经失效，或草稿包含无效音符。": "対象トラックが無効になったか、下書きに無効な音符が含まれています。",
    "音符编辑已作为一个工程操作写入；可整批撤销。": "音符編集を1つのプロジェクト操作として反映しました。一括で元に戻せます。",
    "在当前乐器轨的音符编辑器中打开完整扒谱模式": "現在の楽器トラックの音符エディターで完全な採譜モードを開く",
    "在当前音符编辑器中显示分析证据、候选和参考波形": "この音符エディターに解析証拠、候補、参照波形を表示する",
    "当前工程没有可用于扒谱的旋律乐器轨，请先新建乐器轨。": "このプロジェクトには採譜に使える旋律楽器トラックがありません。先に楽器トラックを作成してください。",
    "请选择要打开的旋律乐器轨：": "開く旋律楽器トラックを選択してください：",
    "请先选择候选或设置 A–B 区间": "候補を選択するか、A–B区間を設定してください",
    "{count} 个候选；识别结果仍需人工审阅": "候補{count}件。認識結果は手動確認が必要です",
    "目标轨道不可用": "対象トラックを使用できません",
    "没有可复制的候选": "コピーできる候補がありません",
    "已清除本次暂存；草稿音符保留为手工编辑": "今回の一時保存をクリアしました。下書き音符は手動編集として残ります",
    "部分候选未提交 · 失效 {invalid} · 孤立 {orphaned}": "一部の候補を反映できませんでした · 無効{invalid}件 · 孤立{orphaned}件",
    "未知 BDO 乐器": "不明なBDO楽器",
    " · BDO v9 结构回读通过": " · BDO v9構造の読み戻しに成功",
    " · 回读检查失败：{error}": " · 読み戻し確認に失敗：{error}",
    "转换完成（回读检查失败）": "変換完了（読み戻し確認失敗）",
    "当前仍有未提交候选草稿。请先应用，或撤销/清除本次暂存后再更换音频、调整偏移或重新分析。": "未確定の候補下書きがあります。適用するか、今回の一時保存を元に戻す／クリアしてから、オーディオ変更、オフセット調整、再解析を行ってください。",
    "选择扒谱目标轨": "採譜対象トラックを選択",
    "请选择一条旋律乐器轨后进入扒谱模式。": "メロディ楽器トラックを選択してから採譜モードに入ってください。",
    "当前没有可用的旋律乐器轨，请先新建乐器轨。": "使用できるメロディ楽器トラックがありません。先に楽器トラックを作成してください。",
    "已清除本次暂存": "今回の一時保存をクリアしました",
    "路由到当前轨": "現在のトラックへ割り当て",
    "复制到当前轨": "現在のトラックへコピー",
    "应用到工程": "プロジェクトに適用",
    "应用到工程 · {apply_count}": "プロジェクトに適用 · {apply_count}",
    "应用到工程 · ": "プロジェクトに適用 · ",
    "正在分析参考音频 · ": "参照オーディオを解析中 · ",
    "轨道 ": "トラック ",
    " 音符": " ノート",
    "平衡": "バランス",
    "敏感": "高感度",
    "循环区间": "区間ループ",
    "循环播放 A–B 时间区间": "A–B時間範囲をループ再生",
    "请选择一条非打击乐 BDO 乐器轨。": "打楽器以外のBDO楽器トラックを選択してください。",
    "请先载入参考音频。": "先に参照オーディオを読み込んでください。",
    "请先载入 MP3/WAV 参考音频": "先にMP3/WAV参照オーディオを読み込んでください",
    "请先载入 MP3/WAV 参考音频。": "先にMP3/WAV参照オーディオを読み込んでください。",
    "请先在音符编辑器选择候选或设置 A–B 区间": "先にノートエディターで候補を選択するかA–B区間を設定してください",
    "更换参考音频": "参照オーディオを変更",
    "当前仍有尚未应用的扒谱路由。更换或卸载音频会丢弃这些审阅路由；已应用的正式音符不受影响。是否继续？": "未適用の採譜ルートがあります。オーディオを変更または解除すると確認ルートは破棄されます。適用済みの確定ノートには影響しません。続行しますか？",
    "当前音频位置已对齐到播放头。": "現在のオーディオ位置を再生ヘッドに合わせました。",
    "第一拍锚点已更新；正式音符位置未移动。": "第1拍アンカーを更新しました。確定ノートの位置は移動していません。",
    "主窗口扒谱会话不可用": "メインウィンドウの採譜セッションを利用できません",
    "正在使用主窗口扒谱会话分析；正式音符不会自动改变": "メインウィンドウの採譜セッションで解析中です。確定ノートは自動変更されません",
    "候选来自主窗口会话；写入草稿后仍需应用或确定": "候補はメインウィンドウのセッション由来です。下書きへの書き込み後も適用またはOKが必要です",
    "准备分析…": "解析を準備中…",
    "正在分析…": "解析中…",
    "正在分析参考音频…": "参照オーディオを解析中…",
    "正在分析参考音频 · {progress}%": "参照オーディオを解析中 · {progress}%",
    "区间重解码失败：{error}": "区間の再デコードに失敗しました：{error}",
    "区间重解码失败。": "区間の再デコードに失敗しました。",
    "本地扒谱引擎未能加载，当前程序安装可能不完整。请重新构建或安装完整程序后再试。": "ローカル採譜エンジンを読み込めませんでした。現在のインストールが不完全な可能性があります。完全なアプリケーションを再ビルドまたは再インストールして、もう一度お試しください。",
    "扒谱组件尚未安装或不可用。请在程序目录运行：\npowershell -ExecutionPolicy Bypass -File scripts\\install_transcription.ps1": "採譜コンポーネントが未インストールか利用できません。プロジェクトフォルダーで次を実行してください：\npowershell -ExecutionPolicy Bypass -File scripts\\install_transcription.ps1",
    "扒谱组件检查失败。详细原因已写入日志。": "採譜コンポーネントの確認に失敗しました。詳細はログに記録されています。",
    "扒谱引擎加载失败（缺少运行模块）。详细原因已写入日志。": "実行時モジュールが不足しているため、採譜エンジンを読み込めませんでした。詳細はログに記録されています。",
    "正在从缓存证据重新解码 A–B；不会再次运行模型。": "キャッシュ済み証拠からA–Bを再デコード中です。モデルは再実行しません。",
    "正在校验并恢复扒谱缓存…": "採譜キャッシュを検証して復元中…",
    "扒谱缓存不存在或校验失败；请重新分析整首。": "採譜キャッシュがないか検証に失敗しました。全曲を再解析してください。",
    "参考音频已变化；旧审阅状态已隔离，请重新分析整首。": "参照オーディオが変更されたため、以前の確認状態を分離しました。全曲を再解析してください。",
    "缓存无法恢复；请重新分析整首。": "キャッシュを復元できません。全曲を再解析してください。",
    "碎音处理切换失败；已恢复原档位。": "断片音処理の切り替えに失敗したため、以前のプロファイルに戻しました。",
    "碎音处理切换已取消；已恢复原档位。": "断片音処理の切り替えをキャンセルし、以前のプロファイルに戻しました。",
    "扒谱分析失败。": "採譜解析に失敗しました。",
    "扒谱分析已取消。": "採譜解析をキャンセルしました。",
    "已路由 {count} 个 · 越界 {invalid} · 已满足 {duplicates}": "{count}件を割り当て · 範囲外{invalid}件 · 適用済み{duplicates}件",
    "已拒绝 {count} 个候选": "候補を{count}件拒否しました",
    "已恢复 {count} 个候选": "候補を{count}件復元しました",
    "区间重解码完成 · 新增 {added} · 替换 {removed} · 保护 {protected}": "区間再デコード完了 · 追加{added}件 · 置換{removed}件 · 保護{protected}件",
    "{prefix}{count} 个候选；识别结果仍需人工审阅": "{prefix}候補{count}件。認識結果は手動確認が必要です",
    "已恢复缓存 · ": "キャッシュを復元 · ",
    "分析完成 · ": "解析完了 · ",
    "没有可应用路由 · 失效 {invalid} · 孤立 {orphaned}": "適用可能なルートなし · 無効{invalid}件 · 孤立{orphaned}件",
    "已应用 {created} 个音符 · 已满足 {satisfied} · 保留失效 {invalid} · 孤立 {orphaned}": "{created}音符を適用 · 適用済み{satisfied}件 · 無効{invalid}件を保持 · 孤立{orphaned}件",
    "扒谱候选已作为一个工程操作写入；可整批撤销。": "採譜候補を1回のプロジェクト操作として書き込みました。まとめて元に戻せます。",
})

KO.update({
    "扒谱": "채보",
    "标准/独奏": "표준/솔로",
    "混音增强": "믹스 향상",
    "识别模式已更改；请重新分析整首。": "인식 모드가 변경되었습니다. 전체 곡을 다시 분석하세요.",
    "载入参考音频": "참조 오디오 불러오기",
    "卸载参考音频": "참조 오디오 해제",
    "分析整首": "전체 곡 분석",
    "重新分析区间": "구간 다시 분석",
    "置信度": "신뢰도",
    "仅已拒绝": "거부된 항목만",
    "证据轮廓": "증거 윤곽",
    "清除 A–B": "A–B 지우기",
    "默认关闭细粒度音高轮廓证据": "세밀한 음높이 윤곽 증거는 기본적으로 꺼져 있습니다",
    "载入参考音频后可开始整首分析": "참조 오디오를 불러오면 전체 곡 분석을 시작할 수 있습니다",
    "载入参考音频后显示对齐波形": "참조 오디오를 불러오면 정렬된 파형을 표시합니다",
    "目标 BDO 乐器轨": "대상 BDO 악기 트랙",
    "候选默认只路由到当前轨；打击乐轨不会出现在此处。": "후보는 기본적으로 현재 트랙에만 배정되며 타악기 트랙은 표시되지 않습니다.",
    "音频位置对齐播放头": "오디오 위치를 재생 헤드에 맞추기",
    "将播放头设为第一拍": "재생 헤드를 첫 박으로 설정",
    "审阅撤销": "검토 실행 취소",
    "审阅重做": "검토 다시 실행",
    "拒绝": "거부",
    "恢复": "복원",
    "写入当前轨草稿": "현재 트랙 초안에 기록",
    "显式复制到…": "명시적으로 복사…",
    "复制到其他轨": "다른 트랙으로 복사",
    "清除本次暂存": "이번 임시 저장 지우기",
    "清除暂存": "임시 저장 지우기",
    "未暂存候选": "임시 후보 없음",
    "已暂存 {count} 个候选": "후보 {count}개 임시 저장",
    "存在未提交候选草稿": "커밋되지 않은 후보 초안",
    "请先应用、撤销或清除本次暂存，再更换音频或重新分析。": "오디오 변경이나 재분석 전에 이번 임시 저장을 적용, 실행 취소 또는 지우세요.",
    "请先应用、撤销或清除本次暂存，再修改音频对齐。": "오디오 정렬을 변경하기 전에 이번 임시 저장을 적용, 실행 취소 또는 지우세요.",
    "请从“显式复制到…”选择目标轨": "‘명시적으로 복사…’에서 대상 트랙을 선택하세요.",
    "无法应用音符编辑": "음표 편집을 적용할 수 없음",
    "目标轨道已经失效，或草稿包含无效音符。": "대상 트랙이 더 이상 유효하지 않거나 초안에 잘못된 음표가 있습니다.",
    "音符编辑已作为一个工程操作写入；可整批撤销。": "음표 편집을 하나의 프로젝트 작업으로 기록했으며 일괄 실행 취소할 수 있습니다.",
    "在当前乐器轨的音符编辑器中打开完整扒谱模式": "현재 악기 트랙의 음표 편집기에서 전체 채보 모드 열기",
    "在当前音符编辑器中显示分析证据、候选和参考波形": "현재 음표 편집기에 분석 증거, 후보 및 참조 파형 표시",
    "当前工程没有可用于扒谱的旋律乐器轨，请先新建乐器轨。": "이 프로젝트에는 채보에 사용할 멜로디 악기 트랙이 없습니다. 먼저 악기 트랙을 만드세요.",
    "请选择要打开的旋律乐器轨：": "열 멜로디 악기 트랙을 선택하세요:",
    "请先选择候选或设置 A–B 区间": "후보를 선택하거나 A–B 구간을 설정하세요",
    "{count} 个候选；识别结果仍需人工审阅": "후보 {count}개; 인식 결과는 수동 검토가 필요합니다",
    "目标轨道不可用": "대상 트랙을 사용할 수 없습니다",
    "没有可复制的候选": "복사할 수 있는 후보가 없습니다",
    "已清除本次暂存；草稿音符保留为手工编辑": "이번 임시 저장을 지웠습니다. 초안 음표는 수동 편집으로 유지됩니다",
    "部分候选未提交 · 失效 {invalid} · 孤立 {orphaned}": "일부 후보 미반영 · 잘못됨 {invalid}개 · 고립됨 {orphaned}개",
    "未知 BDO 乐器": "알 수 없는 BDO 악기",
    " · BDO v9 结构回读通过": " · BDO v9 구조 읽기 검증 통과",
    " · 回读检查失败：{error}": " · 읽기 검증 실패: {error}",
    "转换完成（回读检查失败）": "변환 완료(읽기 검증 실패)",
    "当前仍有未提交候选草稿。请先应用，或撤销/清除本次暂存后再更换音频、调整偏移或重新分析。": "커밋되지 않은 후보 초안이 있습니다. 먼저 적용하거나 이번 임시 저장을 실행 취소/지운 뒤 오디오 변경, 오프셋 조정 또는 재분석을 진행하세요.",
    "选择扒谱目标轨": "채보 대상 트랙 선택",
    "请选择一条旋律乐器轨后进入扒谱模式。": "멜로디 악기 트랙을 선택한 뒤 채보 모드로 들어가세요.",
    "当前没有可用的旋律乐器轨，请先新建乐器轨。": "사용 가능한 멜로디 악기 트랙이 없습니다. 먼저 악기 트랙을 만드세요.",
    "已清除本次暂存": "이번 임시 저장을 지웠습니다",
    "路由到当前轨": "현재 트랙으로 배정",
    "复制到当前轨": "현재 트랙으로 복사",
    "应用到工程": "프로젝트에 적용",
    "应用到工程 · {apply_count}": "프로젝트에 적용 · {apply_count}",
    "应用到工程 · ": "프로젝트에 적용 · ",
    "正在分析参考音频 · ": "참조 오디오 분석 중 · ",
    "轨道 ": "트랙 ",
    " 音符": "개 음표",
    "平衡": "균형",
    "敏感": "민감",
    "循环区间": "구간 반복",
    "循环播放 A–B 时间区间": "A–B 시간 구간 반복 재생",
    "请选择一条非打击乐 BDO 乐器轨。": "타악기가 아닌 BDO 악기 트랙을 선택하세요.",
    "请先载入参考音频。": "먼저 참조 오디오를 불러오세요.",
    "请先载入 MP3/WAV 参考音频": "먼저 MP3/WAV 참조 오디오를 불러오세요",
    "请先载入 MP3/WAV 参考音频。": "먼저 MP3/WAV 참조 오디오를 불러오세요.",
    "请先在音符编辑器选择候选或设置 A–B 区间": "먼저 노트 편집기에서 후보를 선택하거나 A–B 구간을 설정하세요",
    "更换参考音频": "참조 오디오 변경",
    "当前仍有尚未应用的扒谱路由。更换或卸载音频会丢弃这些审阅路由；已应用的正式音符不受影响。是否继续？": "아직 적용하지 않은 채보 경로가 있습니다. 오디오를 변경하거나 해제하면 검토 경로가 삭제되며 이미 적용한 확정 음표에는 영향이 없습니다. 계속할까요?",
    "当前音频位置已对齐到播放头。": "현재 오디오 위치를 재생 헤드에 맞췄습니다.",
    "第一拍锚点已更新；正式音符位置未移动。": "첫 박 기준점을 업데이트했으며 확정 음표 위치는 이동하지 않았습니다.",
    "主窗口扒谱会话不可用": "메인 창 채보 세션을 사용할 수 없습니다",
    "正在使用主窗口扒谱会话分析；正式音符不会自动改变": "메인 창 채보 세션으로 분석 중이며 확정 음표는 자동으로 변경되지 않습니다",
    "候选来自主窗口会话；写入草稿后仍需应用或确定": "후보는 메인 창 세션에서 가져오며 초안에 기록한 뒤에도 적용 또는 확인이 필요합니다",
    "准备分析…": "분석 준비 중…",
    "正在分析…": "분석 중…",
    "正在分析参考音频…": "참조 오디오 분석 중…",
    "正在分析参考音频 · {progress}%": "참조 오디오 분석 중 · {progress}%",
    "区间重解码失败：{error}": "구간 다시 디코딩 실패: {error}",
    "区间重解码失败。": "구간 다시 디코딩에 실패했습니다.",
    "本地扒谱引擎未能加载，当前程序安装可能不完整。请重新构建或安装完整程序后再试。": "로컬 채보 엔진을 불러오지 못했습니다. 현재 프로그램 설치가 불완전할 수 있습니다. 전체 프로그램을 다시 빌드하거나 설치한 후 다시 시도하세요.",
    "扒谱组件尚未安装或不可用。请在程序目录运行：\npowershell -ExecutionPolicy Bypass -File scripts\\install_transcription.ps1": "채보 구성 요소가 설치되지 않았거나 사용할 수 없습니다. 프로젝트 폴더에서 다음 명령을 실행하세요:\npowershell -ExecutionPolicy Bypass -File scripts\\install_transcription.ps1",
    "扒谱组件检查失败。详细原因已写入日志。": "채보 구성 요소 확인에 실패했습니다. 자세한 원인은 로그에 기록되었습니다.",
    "扒谱引擎加载失败（缺少运行模块）。详细原因已写入日志。": "런타임 모듈이 누락되어 채보 엔진을 불러오지 못했습니다. 자세한 원인은 로그에 기록되었습니다.",
    "正在从缓存证据重新解码 A–B；不会再次运行模型。": "캐시된 증거에서 A–B를 다시 디코딩하며 모델은 다시 실행하지 않습니다.",
    "正在校验并恢复扒谱缓存…": "채보 캐시를 검증하고 복원하는 중…",
    "扒谱缓存不存在或校验失败；请重新分析整首。": "채보 캐시가 없거나 검증에 실패했습니다. 전체 곡을 다시 분석하세요.",
    "参考音频已变化；旧审阅状态已隔离，请重新分析整首。": "참조 오디오가 변경되어 이전 검토 상태를 격리했습니다. 전체 곡을 다시 분석하세요.",
    "缓存无法恢复；请重新分析整首。": "캐시를 복원할 수 없습니다. 전체 곡을 다시 분석하세요.",
    "碎音处理切换失败；已恢复原档位。": "조각음 처리 전환에 실패하여 이전 프로필로 복원했습니다.",
    "碎音处理切换已取消；已恢复原档位。": "조각음 처리 전환을 취소하고 이전 프로필로 복원했습니다.",
    "扒谱分析失败。": "채보 분석에 실패했습니다.",
    "扒谱分析已取消。": "채보 분석이 취소되었습니다.",
    "已路由 {count} 个 · 越界 {invalid} · 已满足 {duplicates}": "{count}개 배정 · 범위 초과 {invalid}개 · 이미 충족 {duplicates}개",
    "已拒绝 {count} 个候选": "후보 {count}개 거부",
    "已恢复 {count} 个候选": "후보 {count}개 복원",
    "区间重解码完成 · 新增 {added} · 替换 {removed} · 保护 {protected}": "구간 다시 디코딩 완료 · 추가 {added}개 · 교체 {removed}개 · 보호 {protected}개",
    "{prefix}{count} 个候选；识别结果仍需人工审阅": "{prefix}후보 {count}개, 인식 결과는 수동 검토가 필요합니다",
    "已恢复缓存 · ": "캐시 복원 · ",
    "分析完成 · ": "분석 완료 · ",
    "没有可应用路由 · 失效 {invalid} · 孤立 {orphaned}": "적용 가능한 경로 없음 · 무효 {invalid}개 · 고립 {orphaned}개",
    "已应用 {created} 个音符 · 已满足 {satisfied} · 保留失效 {invalid} · 孤立 {orphaned}": "음표 {created}개 적용 · 이미 충족 {satisfied}개 · 무효 {invalid}개 유지 · 고립 {orphaned}개",
    "扒谱候选已作为一个工程操作写入；可整批撤销。": "채보 후보를 하나의 프로젝트 작업으로 기록했으며 한 번에 실행 취소할 수 있습니다.",
})

# Semantic transcription review, harmony, phrase, and BDO instrument-matching
# vocabulary.  These exact Chinese source strings are shared by the embedded
# editor panel and the piano-roll review interactions.
EN.update({
    "BDO 乐器 {instrument_id}": "BDO Instrument {instrument_id}",
    "拆分": "Split",
    "合并下一段": "Merge Next",
    "合并和弦段": "Merge Chord Segments",
    "保留当前段 · {chord}": "Keep Current · {chord}",
    "保留下一段 · {chord}": "Keep Next · {chord}",
    "选择合并后保留的和弦；不会自动改动音符：": "Choose the chord to retain after merging; notes will not be changed:",
    "请先将播放头放在所选和弦段内部。": "Place the playhead inside the selected chord segment first.",
    "只能合并相邻的和弦段。": "Only adjacent chord segments can be merged.",
    "主旋律": "Lead Melody",
    "第二旋律": "Secondary Melody",
    "和声": "Harmony",
    "低音": "Bass",
    "节奏": "Rhythm",
    "打击乐": "Percussion",
    "铺底": "Pad",
    "装饰": "Ornament",
    "效果": "FX",
    "声部": "Voice",
    "{count} 个冲突": "{count} conflicts",
    "{role} · {count} 音": "{role} · {count} notes",
    "上一乐句": "Previous Phrase",
    "下一乐句": "Next Phrase",
    "与相邻声部合并": "Merge with Adjacent Voice",
    "主调": "Key",
    "乐句 {current}/{total}": "Phrase {current}/{total}",
    "乐器匹配待确认 · {role}": "Instrument Match Needs Review · {role}",
    "仅支持 major 或 minor。": "Only major or minor is supported.",
    "原音": "Original Audio",
    "工程 + 原音": "Project + Original",
    "和声不确定 · {chord}": "Harmony Uncertain · {chord}",
    "和声与乐器建议": "Harmony and Instrument Suggestions",
    "和弦段": "Chord Segment",
    "在播放头处分割声部": "Split Voice at Playhead",
    "声部 {group_id} · {role}": "Voice {group_id} · {role}",
    "声部已失效": "Voice Is No Longer Valid",
    "声部颜色": "Voice Color",
    "备选：": "Alternatives:",
    "尚无乐句": "No Phrases Yet",
    "已暂存新轨 · {instrument} · {count} 个候选": "New Track Staged · {instrument} · {count} candidates",
    "已确认声部的 BDO 乐器建议：{instrument}": "Confirmed BDO instrument suggestion for voice: {instrument}",
    "当前声部没有可试听的该候选": "This candidate cannot be auditioned for the current voice",
    "当前没有待审项目。": "There are no review items.",
    "待审 0": "Review 0",
    "待审 {count}": "Review {count}",
    "待审队列": "Review Queue",
    "循环当前乐句": "Loop Current Phrase",
    "扒谱：{instrument}": "Transcription: {instrument}",
    "按音域、角色和奏法排序": "Ranked by range, role, and articulation",
    "播放头两侧必须都包含候选，才能分割声部。": "Candidates must exist on both sides of the playhead to split the voice.",
    "新建乐器轨": "Create Instrument Track",
    "新建该乐器轨": "Create This Instrument Track",
    "无冲突": "No Conflicts",
    "无本地音色证据": "No Local Timbre Evidence",
    "无法识别主调": "Unable to Identify Key",
    "暂存到现有轨": "Stage to Existing Track",
    "未选择声部组": "No Voice Group Selected",
    "本地音色相似 {score}%": "Local timbre similarity {score}%",
    "正在播放参考原音": "Playing original reference audio",
    "没有匹配的现有轨": "No Matching Existing Track",
    "游戏候选 A": "Game Candidate A",
    "游戏候选 B": "Game Candidate B",
    "游戏候选音源不可用；没有回退播放原音。": "The game-candidate source is unavailable; original audio was not substituted.",
    "确认匹配": "Confirm Match",
    "等待匹配理由": "Waiting for match rationale",
    "编辑": "Edit",
    "编辑主调": "Edit Key",
    "编辑和弦段": "Edit Chord Segment",
    "编辑段": "Edit Segment",
    "角色适配 {score}%": "Role fit {score}%",
    "诊断证据": "Diagnostic Evidence",
    "试听源": "Audition Source",
    "试听源：{source}；继续使用上方唯一播放控制。": "Audition source: {source}; continue using the single transport above.",
    "该乐器音域内没有可暂存候选": "No candidates can be staged within this instrument's range",
    "该声部会在 Apply 时与音符一起原子新建轨道。": "This voice and its notes will create a new track atomically on Apply.",
    "请使用“新建该乐器轨”，或先在主时间轴新建对应乐器。": "Use “Create This Instrument Track”, or first create the matching instrument on the main timeline.",
    "请输入例如 C major 或 A minor。": "Enter a key such as C major or A minor.",
    "越界候选 · {note}": "Out-of-range Candidate · {note}",
    "选择低音": "Choose Bass Note",
    "选择后只定位并设置 A–B，不会自动选择或写入音符：": "Choosing an item only locates it and sets A–B; it does not select or write notes:",
    "选择和弦；不会自动改动音符：": "Choose a chord; notes will not be changed automatically:",
    "选择或输入主调：": "Choose or enter a key:",
    "选择目标轨；Apply 前不会修改工程：": "Choose a target track; the project is unchanged until Apply:",
    "选择转位低音：": "Choose inversion bass:",
    "重叠或重复 · {note}": "Overlap or Duplicate · {note}",
    "锁定": "Lock",
    "音域覆盖 {coverage}%": "Range coverage {coverage}%",
})

JA.update({
    "BDO 乐器 {instrument_id}": "BDO楽器 {instrument_id}",
    "拆分": "分割",
    "合并下一段": "次の区間と結合",
    "合并和弦段": "コード区間を結合",
    "保留当前段 · {chord}": "現在の区間を保持 · {chord}",
    "保留下一段 · {chord}": "次の区間を保持 · {chord}",
    "选择合并后保留的和弦；不会自动改动音符：": "結合後に保持するコードを選択してください。音符は自動変更されません：",
    "请先将播放头放在所选和弦段内部。": "再生ヘッドを選択中のコード区間内に置いてください。",
    "只能合并相邻的和弦段。": "隣接するコード区間だけを結合できます。",
    "主旋律": "主旋律",
    "第二旋律": "第2旋律",
    "和声": "和声",
    "低音": "低音",
    "节奏": "リズム",
    "打击乐": "打楽器",
    "铺底": "パッド",
    "装饰": "装飾",
    "效果": "FX",
    "声部": "声部",
    "{count} 个冲突": "競合 {count}件",
    "{role} · {count} 音": "{role} · {count}音",
    "上一乐句": "前のフレーズ",
    "下一乐句": "次のフレーズ",
    "与相邻声部合并": "隣接する声部と結合",
    "主调": "主調",
    "乐句 {current}/{total}": "フレーズ {current}/{total}",
    "乐器匹配待确认 · {role}": "楽器候補の確認が必要 · {role}",
    "仅支持 major 或 minor。": "major または minor のみ対応しています。",
    "原音": "原音",
    "工程 + 原音": "プロジェクト + 原音",
    "和声不确定 · {chord}": "和声が不確定 · {chord}",
    "和声与乐器建议": "和声と楽器の候補",
    "和弦段": "コード区間",
    "在播放头处分割声部": "再生ヘッド位置で声部を分割",
    "声部 {group_id} · {role}": "声部 {group_id} · {role}",
    "声部已失效": "声部が無効になりました",
    "声部颜色": "声部の色",
    "备选：": "別候補：",
    "尚无乐句": "フレーズはまだありません",
    "已暂存新轨 · {instrument} · {count} 个候选": "新規トラックを一時保存 · {instrument} · 候補{count}件",
    "已确认声部的 BDO 乐器建议：{instrument}": "声部のBDO楽器候補を確定：{instrument}",
    "当前声部没有可试听的该候选": "現在の声部ではこの候補を試聴できません",
    "当前没有待审项目。": "確認待ちの項目はありません。",
    "待审 0": "確認待ち 0",
    "待审 {count}": "確認待ち {count}",
    "待审队列": "確認待ちキュー",
    "循环当前乐句": "現在のフレーズをループ",
    "扒谱：{instrument}": "採譜：{instrument}",
    "按音域、角色和奏法排序": "音域、役割、奏法で順位付け",
    "播放头两侧必须都包含候选，才能分割声部。": "声部を分割するには、再生ヘッドの両側に候補が必要です。",
    "新建乐器轨": "楽器トラックを作成",
    "新建该乐器轨": "この楽器トラックを作成",
    "无冲突": "競合なし",
    "无本地音色证据": "ローカル音色証拠なし",
    "无法识别主调": "主調を識別できません",
    "暂存到现有轨": "既存トラックへ一時保存",
    "未选择声部组": "声部グループ未選択",
    "本地音色相似 {score}%": "ローカル音色の類似度 {score}%",
    "正在播放参考原音": "参照原音を再生中",
    "没有匹配的现有轨": "一致する既存トラックがありません",
    "游戏候选 A": "ゲーム候補 A",
    "游戏候选 B": "ゲーム候補 B",
    "游戏候选音源不可用；没有回退播放原音。": "ゲーム候補の音源を利用できません。原音への自動切り替えは行いませんでした。",
    "确认匹配": "候補を確定",
    "等待匹配理由": "候補理由を待機中",
    "编辑": "編集",
    "编辑主调": "主調を編集",
    "编辑和弦段": "コード区間を編集",
    "编辑段": "区間を編集",
    "角色适配 {score}%": "役割適合度 {score}%",
    "诊断证据": "診断証拠",
    "试听源": "試聴ソース",
    "试听源：{source}；继续使用上方唯一播放控制。": "試聴ソース：{source}。上部の共通再生コントロールを使用します。",
    "该乐器音域内没有可暂存候选": "この楽器の音域内に一時保存できる候補がありません",
    "该声部会在 Apply 时与音符一起原子新建轨道。": "Apply時に、この声部と音符を含む新規トラックを一括作成します。",
    "请使用“新建该乐器轨”，或先在主时间轴新建对应乐器。": "「この楽器トラックを作成」を使うか、メインタイムラインで対応する楽器を先に作成してください。",
    "请输入例如 C major 或 A minor。": "C major や A minor のように入力してください。",
    "越界候选 · {note}": "音域外候補 · {note}",
    "选择低音": "ベース音を選択",
    "选择后只定位并设置 A–B，不会自动选择或写入音符：": "選択すると位置を表示してA–Bを設定するだけで、音符の選択や書き込みは行いません：",
    "选择和弦；不会自动改动音符：": "コードを選択してください。音符は自動変更されません：",
    "选择或输入主调：": "主調を選択または入力：",
    "选择目标轨；Apply 前不会修改工程：": "対象トラックを選択してください。Applyまではプロジェクトを変更しません：",
    "选择转位低音：": "転回形のベース音を選択：",
    "重叠或重复 · {note}": "重複またはオーバーラップ · {note}",
    "锁定": "ロック",
    "音域覆盖 {coverage}%": "音域カバー率 {coverage}%",
})

KO.update({
    "BDO 乐器 {instrument_id}": "BDO 악기 {instrument_id}",
    "拆分": "분할",
    "合并下一段": "다음 구간 병합",
    "合并和弦段": "코드 구간 병합",
    "保留当前段 · {chord}": "현재 구간 유지 · {chord}",
    "保留下一段 · {chord}": "다음 구간 유지 · {chord}",
    "选择合并后保留的和弦；不会自动改动音符：": "병합 후 유지할 코드를 선택하세요. 음표는 자동으로 변경되지 않습니다:",
    "请先将播放头放在所选和弦段内部。": "재생 헤드를 선택한 코드 구간 안에 놓으세요.",
    "只能合并相邻的和弦段。": "인접한 코드 구간만 병합할 수 있습니다.",
    "主旋律": "주선율",
    "第二旋律": "보조 선율",
    "和声": "화성",
    "低音": "베이스",
    "节奏": "리듬",
    "打击乐": "타악기",
    "铺底": "패드",
    "装饰": "장식",
    "效果": "FX",
    "声部": "성부",
    "{count} 个冲突": "충돌 {count}개",
    "{role} · {count} 音": "{role} · {count}음",
    "上一乐句": "이전 프레이즈",
    "下一乐句": "다음 프레이즈",
    "与相邻声部合并": "인접 성부와 병합",
    "主调": "조성",
    "乐句 {current}/{total}": "프레이즈 {current}/{total}",
    "乐器匹配待确认 · {role}": "악기 매칭 확인 필요 · {role}",
    "仅支持 major 或 minor。": "major 또는 minor만 지원합니다.",
    "原音": "원음",
    "工程 + 原音": "프로젝트 + 원음",
    "和声不确定 · {chord}": "화성 불확실 · {chord}",
    "和声与乐器建议": "화성 및 악기 제안",
    "和弦段": "코드 구간",
    "在播放头处分割声部": "재생 헤드에서 성부 분할",
    "声部 {group_id} · {role}": "성부 {group_id} · {role}",
    "声部已失效": "성부가 유효하지 않음",
    "声部颜色": "성부 색상",
    "备选：": "대안:",
    "尚无乐句": "프레이즈 없음",
    "已暂存新轨 · {instrument} · {count} 个候选": "새 트랙 임시 저장 · {instrument} · 후보 {count}개",
    "已确认声部的 BDO 乐器建议：{instrument}": "성부의 BDO 악기 제안 확인: {instrument}",
    "当前声部没有可试听的该候选": "현재 성부에서 이 후보를 미리 들을 수 없습니다",
    "当前没有待审项目。": "현재 검토할 항목이 없습니다.",
    "待审 0": "검토 0",
    "待审 {count}": "검토 {count}",
    "待审队列": "검토 대기열",
    "循环当前乐句": "현재 프레이즈 반복",
    "扒谱：{instrument}": "채보: {instrument}",
    "按音域、角色和奏法排序": "음역, 역할 및 주법으로 정렬",
    "播放头两侧必须都包含候选，才能分割声部。": "성부를 분할하려면 재생 헤드 양쪽에 후보가 있어야 합니다.",
    "新建乐器轨": "악기 트랙 만들기",
    "新建该乐器轨": "이 악기 트랙 만들기",
    "无冲突": "충돌 없음",
    "无本地音色证据": "로컬 음색 증거 없음",
    "无法识别主调": "조성을 식별할 수 없음",
    "暂存到现有轨": "기존 트랙에 임시 저장",
    "未选择声部组": "성부 그룹을 선택하지 않음",
    "本地音色相似 {score}%": "로컬 음색 유사도 {score}%",
    "正在播放参考原音": "참조 원음 재생 중",
    "没有匹配的现有轨": "일치하는 기존 트랙 없음",
    "游戏候选 A": "게임 후보 A",
    "游戏候选 B": "게임 후보 B",
    "游戏候选音源不可用；没有回退播放原音。": "게임 후보 음원을 사용할 수 없어 원음으로 자동 대체하지 않았습니다.",
    "确认匹配": "매칭 확인",
    "等待匹配理由": "매칭 근거 대기 중",
    "编辑": "편집",
    "编辑主调": "조성 편집",
    "编辑和弦段": "코드 구간 편집",
    "编辑段": "구간 편집",
    "角色适配 {score}%": "역할 적합도 {score}%",
    "诊断证据": "진단 증거",
    "试听源": "미리듣기 소스",
    "试听源：{source}；继续使用上方唯一播放控制。": "미리듣기 소스: {source}; 위의 단일 재생 컨트롤을 계속 사용합니다.",
    "该乐器音域内没有可暂存候选": "이 악기의 음역 안에 임시 저장할 후보가 없습니다",
    "该声部会在 Apply 时与音符一起原子新建轨道。": "Apply 시 이 성부와 음표를 포함한 새 트랙을 원자적으로 만듭니다.",
    "请使用“新建该乐器轨”，或先在主时间轴新建对应乐器。": "‘이 악기 트랙 만들기’를 사용하거나 메인 타임라인에 해당 악기를 먼저 만드세요.",
    "请输入例如 C major 或 A minor。": "C major 또는 A minor처럼 입력하세요.",
    "越界候选 · {note}": "음역 밖 후보 · {note}",
    "选择低音": "베이스 음 선택",
    "选择后只定位并设置 A–B，不会自动选择或写入音符：": "항목을 선택하면 위치를 찾고 A–B만 설정하며 음표를 자동 선택하거나 기록하지 않습니다:",
    "选择和弦；不会自动改动音符：": "코드를 선택하세요. 음표는 자동으로 변경되지 않습니다:",
    "选择或输入主调：": "조성 선택 또는 입력:",
    "选择目标轨；Apply 前不会修改工程：": "대상 트랙을 선택하세요. Apply 전에는 프로젝트를 변경하지 않습니다:",
    "选择转位低音：": "전위 베이스 음 선택:",
    "重叠或重复 · {note}": "겹침 또는 중복 · {note}",
    "锁定": "잠금",
    "音域覆盖 {coverage}%": "음역 커버리지 {coverage}%",
})


EN.update({
    "修改声部角色": "Change Voice Role",
    "已确认匹配": "Match Confirmed",
    "{state} · 轨道 {track_id}": "{state} · Track {track_id}",
    "孤立路由": "Orphaned Route",
    "失效路由": "Invalid Route",
    " · 已确认 0x{instrument_id:02X}（不在当前 Top-3）": " · Confirmed 0x{instrument_id:02X} (outside current Top 3)",
    "可能不适合：{reason}": "May not fit: {reason}",
    "未发现明显硬性冲突": "No obvious hard conflict",
    "有 {percent}% 的候选超出该乐器可用音域": "{percent}% of candidates are outside this instrument's range",
    "该乐器与当前声部角色适配较弱": "This instrument is a weak fit for the current voice role",
    "该乐器不在当前声部的 Top-3 建议中。": "This instrument is not in the current voice's Top-3 suggestions.",
    "低置信可见度": "Low-confidence Visibility",
    "只调整低置信候选的透明度，不隐藏或禁用候选。": "Adjusts only the opacity of low-confidence candidates; candidates remain visible and usable.",
})

JA.update({
    "修改声部角色": "声部役割を変更",
    "已确认匹配": "確認済み",
    "{state} · 轨道 {track_id}": "{state} · トラック {track_id}",
    "孤立路由": "孤立ルート",
    "失效路由": "無効なルート",
    " · 已确认 0x{instrument_id:02X}（不在当前 Top-3）": " · 確認済み 0x{instrument_id:02X}（現在のTop 3外）",
    "可能不适合：{reason}": "不向きの可能性：{reason}",
    "未发现明显硬性冲突": "明確な必須条件の衝突なし",
    "有 {percent}% 的候选超出该乐器可用音域": "候補の{percent}%がこの楽器の音域外です",
    "该乐器与当前声部角色适配较弱": "この楽器は現在の声部役割との適合度が低めです",
    "该乐器不在当前声部的 Top-3 建议中。": "この楽器は現在の声部のTop 3候補にありません。",
    "低置信可见度": "低信頼候補の表示",
    "只调整低置信候选的透明度，不隐藏或禁用候选。": "低信頼候補の透明度だけを調整し、非表示や無効化はしません。",
})

KO.update({
    "修改声部角色": "성부 역할 변경",
    "已确认匹配": "매칭 확인됨",
    "{state} · 轨道 {track_id}": "{state} · 트랙 {track_id}",
    "孤立路由": "고립된 라우트",
    "失效路由": "유효하지 않은 라우트",
    " · 已确认 0x{instrument_id:02X}（不在当前 Top-3）": " · 확인됨 0x{instrument_id:02X} (현재 Top 3 밖)",
    "可能不适合：{reason}": "맞지 않을 수 있음: {reason}",
    "未发现明显硬性冲突": "명확한 필수 조건 충돌 없음",
    "有 {percent}% 的候选超出该乐器可用音域": "후보의 {percent}%가 이 악기의 음역 밖입니다",
    "该乐器与当前声部角色适配较弱": "이 악기는 현재 성부 역할과의 적합도가 낮습니다",
    "该乐器不在当前声部的 Top-3 建议中。": "이 악기는 현재 성부의 Top 3 제안에 없습니다.",
    "低置信可见度": "낮은 신뢰도 표시",
    "只调整低置信候选的透明度，不隐藏或禁用候选。": "낮은 신뢰도 후보의 투명도만 조절하며 숨기거나 비활성화하지 않습니다.",
})

EN.update({
    "工程已恢复；参考音频未随工程保存，请重新载入。": (
        "Project restored; reference audio is not stored with the project. "
        "Load it again to relink it."
    ),
})

JA.update({
    "工程已恢复；参考音频未随工程保存，请重新载入。": (
        "プロジェクトを復元しました。参照オーディオはプロジェクトに保存されないため、"
        "再度読み込んで関連付けてください。"
    ),
})

KO.update({
    "工程已恢复；参考音频未随工程保存，请重新载入。": (
        "프로젝트를 복원했습니다. 참조 오디오는 프로젝트에 저장되지 않으므로 "
        "다시 불러와 연결하세요."
    ),
})

EN.update({
    "待审项目较多，当前只显示优先级最高的 {count} 项。": (
        "Many review items remain; showing only the top {count} by priority."
    ),
    "游戏候选含移调后不可用的音高，已停止试听。": (
        "The game candidate contains pitches unavailable after transposition; "
        "audition stopped."
    ),
})

JA.update({
    "待审项目较多，当前只显示优先级最高的 {count} 项。": (
        "確認待ち項目が多いため、優先度の高い {count} 件のみ表示します。"
    ),
    "游戏候选含移调后不可用的音高，已停止试听。": (
        "ゲーム候補に移調後は使用できない音高が含まれるため、試聴を停止しました。"
    ),
})

KO.update({
    "待审项目较多，当前只显示优先级最高的 {count} 项。": (
        "검토 항목이 많아 우선순위가 높은 {count}개만 표시합니다."
    ),
    "游戏候选含移调后不可用的音高，已停止试听。": (
        "게임 후보에 조옮김 후 사용할 수 없는 음높이가 있어 미리 듣기를 중지했습니다."
    ),
})

EN.update({
    "保留碎音": "Preserve Fragments",
    "平衡整理": "Balanced Cleanup",
    "干净整理": "Clean Cleanup",
    "独立于灵敏度。当前自动合并与隐藏尚未通过留出集发布门槛；平衡/干净档仅增加可疑碎音标记。": (
        "Independent of sensitivity. Automatic merging and hiding have not "
        "passed the holdout release gates; Balanced and Clean currently add "
        "suspected-fragment flags only."
    ),
    "显示已隐藏碎音": "Show Hidden Fragments",
    "干净档隐藏项仅用于审计；切换到平衡或保留可恢复。": (
        "Items hidden by Clean remain available for audit; switch to Balanced "
        "or Preserve to restore them."
    ),
    "选择疑似碎音": "Select Suspected Fragments",
    "已选择 {count} 个疑似碎音候选": "Selected {count} suspected fragment candidates",
    "疑似碎音 · {note}": "Suspected fragment · {note}",
    "{count} 个候选 · 自动合并 {merged} · 疑似碎音 {suspected} · 已隐藏 {suppressed}": (
        "{count} candidates · {merged} auto-merged · {suspected} suspected "
        "fragments · {suppressed} hidden"
    ),
    "{prefix}{count} 个候选 · 自动合并 {merged} · 疑似碎音 {suspected} · 已隐藏 {suppressed}": (
        "{prefix}{count} candidates · {merged} auto-merged · {suspected} "
        "suspected fragments · {suppressed} hidden"
    ),
    "区间重解码完成 · 新增 {added} · 替换 {removed} · 保护 {protected} · 自动合并 {merged} · 疑似碎音 {suspected}": (
        "Range re-decoded · {added} added · {removed} replaced · {protected} "
        "protected · {merged} auto-merged · {suspected} suspected fragments"
    ),
})

JA.update({
    "保留碎音": "断片を保持",
    "平衡整理": "バランス整理",
    "干净整理": "クリーン整理",
    "独立于灵敏度。当前自动合并与隐藏尚未通过留出集发布门槛；平衡/干净档仅增加可疑碎音标记。": (
        "感度とは独立しています。自動結合と非表示はホールドアウトの公開基準を"
        "まだ満たしていないため、現在のバランス／クリーン整理は疑わしい断片に"
        "印を付けるだけです。"
    ),
    "显示已隐藏碎音": "非表示の断片を表示",
    "干净档隐藏项仅用于审计；切换到平衡或保留可恢复。": (
        "クリーン整理で非表示になった項目は監査用に保持され、バランス整理または"
        "保持へ切り替えると復元できます。"
    ),
    "选择疑似碎音": "疑わしい断片を選択",
    "已选择 {count} 个疑似碎音候选": "疑わしい断片候補を{count}件選択しました",
    "疑似碎音 · {note}": "疑わしい断片 · {note}",
    "{count} 个候选 · 自动合并 {merged} · 疑似碎音 {suspected} · 已隐藏 {suppressed}": (
        "候補{count}件 · 自動結合{merged}件 · 疑わしい断片{suspected}件 · "
        "非表示{suppressed}件"
    ),
    "{prefix}{count} 个候选 · 自动合并 {merged} · 疑似碎音 {suspected} · 已隐藏 {suppressed}": (
        "{prefix}候補{count}件 · 自動結合{merged}件 · 疑わしい断片{suspected}件 · "
        "非表示{suppressed}件"
    ),
    "区间重解码完成 · 新增 {added} · 替换 {removed} · 保护 {protected} · 自动合并 {merged} · 疑似碎音 {suspected}": (
        "区間再デコード完了 · 追加{added}件 · 置換{removed}件 · 保護{protected}件 · "
        "自動結合{merged}件 · 疑わしい断片{suspected}件"
    ),
})

KO.update({
    "保留碎音": "조각음 유지",
    "平衡整理": "균형 정리",
    "干净整理": "깔끔하게 정리",
    "独立于灵敏度。当前自动合并与隐藏尚未通过留出集发布门槛；平衡/干净档仅增加可疑碎音标记。": (
        "민감도와 별개입니다. 자동 병합과 숨김이 홀드아웃 출시 기준을 아직 "
        "통과하지 못해 현재 균형/깔끔 정리는 의심 조각음 표시만 추가합니다."
    ),
    "显示已隐藏碎音": "숨긴 조각음 표시",
    "干净档隐藏项仅用于审计；切换到平衡或保留可恢复。": (
        "깔끔하게 정리에서 숨긴 항목은 검토용으로 유지되며 균형 정리 또는 유지로 "
        "전환하면 복원됩니다."
    ),
    "选择疑似碎音": "의심 조각음 선택",
    "已选择 {count} 个疑似碎音候选": "의심 조각음 후보 {count}개를 선택했습니다",
    "疑似碎音 · {note}": "의심 조각음 · {note}",
    "{count} 个候选 · 自动合并 {merged} · 疑似碎音 {suspected} · 已隐藏 {suppressed}": (
        "후보 {count}개 · 자동 병합 {merged}개 · 의심 조각음 {suspected}개 · "
        "숨김 {suppressed}개"
    ),
    "{prefix}{count} 个候选 · 自动合并 {merged} · 疑似碎音 {suspected} · 已隐藏 {suppressed}": (
        "{prefix}후보 {count}개 · 자동 병합 {merged}개 · 의심 조각음 "
        "{suspected}개 · 숨김 {suppressed}개"
    ),
    "区间重解码完成 · 新增 {added} · 替换 {removed} · 保护 {protected} · 自动合并 {merged} · 疑似碎音 {suspected}": (
        "구간 다시 디코딩 완료 · 추가 {added}개 · 교체 {removed}개 · 보호 "
        "{protected}개 · 자동 병합 {merged}개 · 의심 조각음 {suspected}개"
    ),
})


EN.update({
    "保留（安全默认）": "Preserve (Safe Default)",
    "平衡（实验）": "Balanced (Experimental)",
    "干净（实验）": "Clean (Experimental)",
    "安全默认": "Safe default",
    "实验性自动整理，未通过留出集验证": (
        "Experimental automatic cleanup; not validated on the holdout set"
    ),
    "实验性档位，等待缓存重解码": (
        "Experimental profile; waiting for cached evidence to be re-decoded"
    ),
    "安全默认：保留碎音，仅排序并清除完全重复候选。": (
        "Safe default: preserve fragments; only sort and remove exact duplicate "
        "candidates."
    ),
    "实验性：自动合并明确的同音伪分裂；尚未通过留出集验证。": (
        "Experimental: automatically merge clear false same-pitch splits; "
        "not yet validated on the holdout set."
    ),
    "实验性：在平衡档基础上隐藏高疑似误检；尚未通过留出集验证，可用“显示已隐藏碎音”审阅。": (
        "Experimental: in addition to Balanced cleanup, hide highly suspected "
        "false detections. This has not passed holdout validation; use Show "
        "Hidden Fragments to review them."
    ),
    "独立于灵敏度。已有分析时，切换档位只从缓存证据重新解码，不再次运行模型。平衡/干净必须由用户显式启用，且尚未通过留出集验证；请审阅后再应用。": (
        "Independent of sensitivity. When evidence is already cached, changing "
        "the profile re-decodes that evidence without running the model again. "
        "Balanced and Clean require explicit opt-in and have not passed "
        "holdout validation; review the result before applying it."
    ),
    "显示干净档自动隐藏的候选供审阅；切换到平衡或保留可恢复全部隐藏项，隐藏项不会写入正式轨道。": (
        "Show candidates automatically hidden by Clean for review. Switch to "
        "Balanced or Preserve to restore every hidden item; hidden items are "
        "never written to the formal track."
    ),
    "正在按“{profile}”从缓存证据重新解码；不会再次运行模型。": (
        "Re-decoding cached evidence with “{profile}”; the model will not run "
        "again."
    ),
    "已选择“{profile}”；下次分析将使用该档位。": (
        "Selected “{profile}”; the next analysis will use this profile."
    ),
    "{profile} · {profile_state} · {count} 个候选 · 自动合并 {merged} · 疑似碎音 {suspected} · 已隐藏 {suppressed}": (
        "{profile} · {profile_state} · {count} candidates · {merged} "
        "auto-merged · {suspected} suspected fragments · {suppressed} hidden"
    ),
    "{prefix}{profile} · {profile_state} · {count} 个候选 · 自动合并 {merged} · 疑似碎音 {suspected} · 已隐藏 {suppressed}": (
        "{prefix}{profile} · {profile_state} · {count} candidates · {merged} "
        "auto-merged · {suspected} suspected fragments · {suppressed} hidden"
    ),
    "区间重解码完成 · {profile} · {profile_state} · 新增 {added} · 替换 {removed} · 保护 {protected} · 自动合并 {merged} · 疑似碎音 {suspected} · 已隐藏 {suppressed}": (
        "Range re-decoded · {profile} · {profile_state} · {added} added · "
        "{removed} replaced · {protected} protected · {merged} auto-merged · "
        "{suspected} suspected fragments · {suppressed} hidden"
    ),
})

JA.update({
    "保留（安全默认）": "保持（安全な既定）",
    "平衡（实验）": "バランス（実験）",
    "干净（实验）": "クリーン（実験）",
    "安全默认": "安全な既定",
    "实验性自动整理，未通过留出集验证": (
        "実験的な自動整理（ホールドアウト未検証）"
    ),
    "实验性档位，等待缓存重解码": (
        "実験プロファイル：キャッシュ再デコード待ち"
    ),
    "安全默认：保留碎音，仅排序并清除完全重复候选。": (
        "安全な既定：断片音を保持し、並べ替えと完全重複候補の削除のみを行います。"
    ),
    "实验性：自动合并明确的同音伪分裂；尚未通过留出集验证。": (
        "実験機能：明確な同音の誤分割を自動結合します。ホールドアウトでは未検証です。"
    ),
    "实验性：在平衡档基础上隐藏高疑似误检；尚未通过留出集验证，可用“显示已隐藏碎音”审阅。": (
        "実験機能：バランス処理に加えて誤検出の疑いが強い候補を非表示にします。"
        "ホールドアウトでは未検証です。「非表示の断片を表示」で確認できます。"
    ),
    "独立于灵敏度。已有分析时，切换档位只从缓存证据重新解码，不再次运行模型。平衡/干净必须由用户显式启用，且尚未通过留出集验证；请审阅后再应用。": (
        "感度とは独立しています。解析済みの場合、プロファイル変更はキャッシュ済み証拠を"
        "再デコードし、モデルは再実行しません。バランス／クリーンは明示的な有効化が必要で、"
        "ホールドアウトでは未検証です。適用前に確認してください。"
    ),
    "显示干净档自动隐藏的候选供审阅；切换到平衡或保留可恢复全部隐藏项，隐藏项不会写入正式轨道。": (
        "クリーンで自動的に非表示にした候補を確認用に表示します。バランスまたは保持へ"
        "切り替えると全項目を復元できます。非表示項目は正式トラックへ書き込まれません。"
    ),
    "正在按“{profile}”从缓存证据重新解码；不会再次运行模型。": (
        "「{profile}」でキャッシュ済み証拠を再デコード中です。モデルは再実行しません。"
    ),
    "已选择“{profile}”；下次分析将使用该档位。": (
        "「{profile}」を選択しました。次回の解析でこのプロファイルを使用します。"
    ),
    "{profile} · {profile_state} · {count} 个候选 · 自动合并 {merged} · 疑似碎音 {suspected} · 已隐藏 {suppressed}": (
        "{profile} · {profile_state} · 候補{count}件 · 自動結合{merged}件 · "
        "疑わしい断片{suspected}件 · 非表示{suppressed}件"
    ),
    "{prefix}{profile} · {profile_state} · {count} 个候选 · 自动合并 {merged} · 疑似碎音 {suspected} · 已隐藏 {suppressed}": (
        "{prefix}{profile} · {profile_state} · 候補{count}件 · 自動結合{merged}件 · "
        "疑わしい断片{suspected}件 · 非表示{suppressed}件"
    ),
    "区间重解码完成 · {profile} · {profile_state} · 新增 {added} · 替换 {removed} · 保护 {protected} · 自动合并 {merged} · 疑似碎音 {suspected} · 已隐藏 {suppressed}": (
        "区間再デコード完了 · {profile} · {profile_state} · 追加{added}件 · "
        "置換{removed}件 · 保護{protected}件 · 自動結合{merged}件 · "
        "疑わしい断片{suspected}件 · 非表示{suppressed}件"
    ),
})

KO.update({
    "保留（安全默认）": "보존(안전 기본값)",
    "平衡（实验）": "균형(실험)",
    "干净（实验）": "정리(실험)",
    "安全默认": "안전 기본값",
    "实验性自动整理，未通过留出集验证": (
        "실험적 자동 정리, 홀드아웃 검증 미통과"
    ),
    "实验性档位，等待缓存重解码": (
        "실험 프로필, 캐시 재디코딩 대기 중"
    ),
    "安全默认：保留碎音，仅排序并清除完全重复候选。": (
        "안전 기본값: 조각음을 보존하고 정렬 및 완전히 중복된 후보만 제거합니다."
    ),
    "实验性：自动合并明确的同音伪分裂；尚未通过留出集验证。": (
        "실험 기능: 명확한 동일 음높이 오분할을 자동 병합합니다. "
        "홀드아웃 검증은 아직 통과하지 못했습니다."
    ),
    "实验性：在平衡档基础上隐藏高疑似误检；尚未通过留出集验证，可用“显示已隐藏碎音”审阅。": (
        "실험 기능: 균형 정리에 더해 오검출 가능성이 높은 후보를 숨깁니다. "
        "홀드아웃 검증은 아직 통과하지 못했으며 ‘숨긴 조각음 표시’로 검토할 수 있습니다."
    ),
    "独立于灵敏度。已有分析时，切换档位只从缓存证据重新解码，不再次运行模型。平衡/干净必须由用户显式启用，且尚未通过留出集验证；请审阅后再应用。": (
        "민감도와 독립적입니다. 분석 증거가 캐시되어 있으면 프로필 변경 시 모델을 다시 "
        "실행하지 않고 해당 증거만 재디코딩합니다. 균형/정리는 사용자가 명시적으로 "
        "활성화해야 하며 홀드아웃 검증을 통과하지 못했으므로 적용 전에 검토하십시오."
    ),
    "显示干净档自动隐藏的候选供审阅；切换到平衡或保留可恢复全部隐藏项，隐藏项不会写入正式轨道。": (
        "정리 프로필에서 자동으로 숨긴 후보를 검토용으로 표시합니다. 균형 또는 보존으로 "
        "전환하면 숨긴 항목을 모두 복원할 수 있으며 정식 트랙에는 기록되지 않습니다."
    ),
    "正在按“{profile}”从缓存证据重新解码；不会再次运行模型。": (
        "‘{profile}’로 캐시된 증거를 재디코딩하는 중입니다. 모델은 다시 실행하지 않습니다."
    ),
    "已选择“{profile}”；下次分析将使用该档位。": (
        "‘{profile}’를 선택했습니다. 다음 분석에서 이 프로필을 사용합니다."
    ),
    "{profile} · {profile_state} · {count} 个候选 · 自动合并 {merged} · 疑似碎音 {suspected} · 已隐藏 {suppressed}": (
        "{profile} · {profile_state} · 후보 {count}개 · 자동 병합 {merged}개 · "
        "의심 조각음 {suspected}개 · 숨김 {suppressed}개"
    ),
    "{prefix}{profile} · {profile_state} · {count} 个候选 · 自动合并 {merged} · 疑似碎音 {suspected} · 已隐藏 {suppressed}": (
        "{prefix}{profile} · {profile_state} · 후보 {count}개 · 자동 병합 {merged}개 · "
        "의심 조각음 {suspected}개 · 숨김 {suppressed}개"
    ),
    "区间重解码完成 · {profile} · {profile_state} · 新增 {added} · 替换 {removed} · 保护 {protected} · 自动合并 {merged} · 疑似碎音 {suspected} · 已隐藏 {suppressed}": (
        "구간 재디코딩 완료 · {profile} · {profile_state} · 추가 {added}개 · "
        "교체 {removed}개 · 보호 {protected}개 · 자동 병합 {merged}개 · "
        "의심 조각음 {suspected}개 · 숨김 {suppressed}개"
    ),
})

# Compact transcription command-strip labels.  Detailed explanations remain
# available through translated tooltips and accessible names.
EN.update({
    "全曲": "Full",
    "保留": "Keep",
    "平衡 β": "Balance β",
    "干净 β": "Clean β",
    "碎音": "Fragments",
    "弱显": "Low",
    "证据": "Evidence",
    "拒绝项": "Rejected",
    "隐藏项": "Hidden",
    "对齐": "Align",
    "定拍": "Beat",
    "和声/配器": "Harmony/Voices",
    "暂存 {count}": "Staged {count}",
    "清空": "Clear",
    "写入本轨": "Write Here",
    "复制到…": "Copy to…",
    "碎音 {count}": "Fragments {count}",
})

JA.update({
    "全曲": "全曲",
    "保留": "保持",
    "平衡 β": "バランス β",
    "干净 β": "クリーン β",
    "碎音": "断片",
    "弱显": "弱表示",
    "证据": "証拠",
    "拒绝项": "拒否",
    "隐藏项": "非表示",
    "对齐": "整列",
    "定拍": "拍設定",
    "和声/配器": "和声/編成",
    "暂存 {count}": "一時 {count}",
    "清空": "クリア",
    "写入本轨": "ここへ書込",
    "复制到…": "コピー先…",
    "碎音 {count}": "断片 {count}",
})

KO.update({
    "全曲": "전체",
    "保留": "유지",
    "平衡 β": "균형 β",
    "干净 β": "정리 β",
    "碎音": "조각음",
    "弱显": "약음",
    "证据": "증거",
    "拒绝项": "거부",
    "隐藏项": "숨김",
    "对齐": "정렬",
    "定拍": "박 설정",
    "和声/配器": "화성/편성",
    "暂存 {count}": "임시 {count}",
    "清空": "지우기",
    "写入本轨": "현재 트랙",
    "复制到…": "복사…",
    "碎音 {count}": "조각음 {count}",
})

EN.update({
    "频谱": "Spectrogram",
    "简化声谱图": "Simplified spectrogram",
    "旋律线": "Melody lines",
    "旋律线辅助": "Melody-line guide",
    "分析后显示旋律线": "Analyze to show melody lines",
    "主旋律 · 低音 · 和弦；线粗表示置信度": (
        "Lead · bass · chords; thickness shows confidence"
    ),
    "主旋律 · 低音 · 和弦；线粗表示置信度；点击线定位候选": (
        "Lead · bass · chords; thickness shows confidence; click a line to select evidence"
    ),
    "和声/和弦": "Harmony/chords",
    "分支": "Branch",
    "点击定位候选": "Click to select evidence",
    "声谱": "Spectrum",
    "原始声谱图": "Raw spectrogram",
    "原始声谱图（诊断）": "Raw spectrogram (diagnostic)",
})
JA.update({
    "频谱": "スペクトログラム",
    "简化声谱图": "簡易スペクトログラム",
    "旋律线": "メロディライン",
    "旋律线辅助": "メロディライン補助",
    "分析后显示旋律线": "解析後にメロディラインを表示",
    "主旋律 · 低音 · 和弦；线粗表示置信度": (
        "主旋律・低音・コード；線の太さは信頼度"
    ),
    "主旋律 · 低音 · 和弦；线粗表示置信度；点击线定位候选": (
        "主旋律・低音・コード；線の太さは信頼度；クリックで候補を選択"
    ),
    "和声/和弦": "和声/コード",
    "分支": "分岐",
    "点击定位候选": "クリックで候補を選択",
    "声谱": "スペクトル",
    "原始声谱图": "元スペクトログラム",
    "原始声谱图（诊断）": "元スペクトログラム（診断）",
})
KO.update({
    "频谱": "스펙트로그램",
    "简化声谱图": "간이 스펙트로그램",
    "旋律线": "멜로디 라인",
    "旋律线辅助": "멜로디 라인 가이드",
    "分析后显示旋律线": "분석 후 멜로디 라인 표시",
    "主旋律 · 低音 · 和弦；线粗表示置信度": (
        "주선율 · 저음 · 화음; 선 굵기는 신뢰도"
    ),
    "主旋律 · 低音 · 和弦；线粗表示置信度；点击线定位候选": (
        "주선율 · 저음 · 화음; 선 굵기는 신뢰도; 클릭해 후보 선택"
    ),
    "和声/和弦": "화성/코드",
    "分支": "분기",
    "点击定位候选": "클릭해 후보 선택",
    "声谱": "스펙트럼",
    "原始声谱图": "원본 스펙트로그램",
    "原始声谱图（诊断）": "원본 스펙트로그램(진단)",
})

EN.update({
    "幽灵": "Ghost",
    "幽灵音块透明度": "Ghost-note opacity",
    "背景": "Ref",
    "旋律线、Frame、Onset、Contour 与声谱透明度": (
        "Melody-line, Frame, Onset, Contour, and spectrogram opacity"
    ),
})
JA.update({
    "幽灵": "ゴースト",
    "幽灵音块透明度": "ゴーストノートの透明度",
    "背景": "参照",
    "旋律线、Frame、Onset、Contour 与声谱透明度": (
        "メロディライン、Frame、Onset、Contour、スペクトルの透明度"
    ),
})
KO.update({
    "幽灵": "고스트",
    "幽灵音块透明度": "고스트 노트 투명도",
    "背景": "참조",
    "旋律线、Frame、Onset、Contour 与声谱透明度": (
        "멜로디 라인, Frame, Onset, Contour 및 스펙트럼 투명도"
    ),
})

# Local-only preview sources and optional lane artwork. The packaged defaults
# are original app artwork; configured game images remain private local data.
EN.update({
    "未选择": "Not selected",
    "音源包": "Sample pack",
    "文件夹": "Folder",
    "清除": "Clear",
    "音源不可用": "Audio source unavailable",
    "请选择 .bdosamples 音源包或本地音源文件夹。": (
        "Choose a .bdosamples pack or a local sample folder."
    ),
    "选择 .bdosamples 音源包": "Choose a .bdosamples pack",
    "选择已准备好的本地 BDO 音源目录": (
        "Choose a prepared local BDO sample folder"
    ),
    "内置线稿": "Built-in line art",
    "内置原创图标": "Built-in original icons",
    "轨道背景": "Lane art",
    "选择本地乐器图片目录；未设置时使用内置线稿": (
        "Choose a local instrument-art folder; built-in line art is used otherwise"
    ),
    "选择本地乐器图片目录；未设置时使用内置原创图标": (
        "Choose a local instrument-art folder; built-in original icons are used otherwise"
    ),
    "选择乐器背景目录": "Choose Instrument Art Folder",
    "背景目录不可用": "Artwork Folder Unavailable",
    "请选择有效的本地乐器图片目录。": (
        "Choose a valid local instrument-art folder."
    ),
    "已载入 {count} 张轨道背景": "Loaded {count} lane images",
})
JA.update({
    "未选择": "未選択",
    "音源包": "音源パック",
    "文件夹": "フォルダー",
    "清除": "クリア",
    "音源不可用": "音源を使用できません",
    "请选择 .bdosamples 音源包或本地音源文件夹。": (
        ".bdosamples 音源パックまたはローカル音源フォルダーを選択してください。"
    ),
    "选择 .bdosamples 音源包": ".bdosamples 音源パックを選択",
    "选择已准备好的本地 BDO 音源目录": (
        "準備済みのローカル BDO 音源フォルダーを選択"
    ),
    "内置线稿": "内蔵ラインアート",
    "内置原创图标": "内蔵オリジナルアイコン",
    "轨道背景": "トラック背景",
    "选择本地乐器图片目录；未设置时使用内置线稿": (
        "ローカル楽器画像フォルダーを選択；未設定時は内蔵ラインアート"
    ),
    "选择本地乐器图片目录；未设置时使用内置原创图标": (
        "ローカル楽器画像フォルダーを選択；未設定時は内蔵オリジナルアイコン"
    ),
    "选择乐器背景目录": "楽器背景フォルダーを選択",
    "背景目录不可用": "背景フォルダーを使用できません",
    "请选择有效的本地乐器图片目录。": (
        "有効なローカル楽器画像フォルダーを選択してください。"
    ),
    "已载入 {count} 张轨道背景": "トラック背景を {count} 枚読み込みました",
})
KO.update({
    "未选择": "선택 안 함",
    "音源包": "음원 팩",
    "文件夹": "폴더",
    "清除": "지우기",
    "音源不可用": "음원을 사용할 수 없음",
    "请选择 .bdosamples 音源包或本地音源文件夹。": (
        ".bdosamples 음원 팩 또는 로컬 음원 폴더를 선택하세요."
    ),
    "选择 .bdosamples 音源包": ".bdosamples 음원 팩 선택",
    "选择已准备好的本地 BDO 音源目录": (
        "준비된 로컬 BDO 음원 폴더 선택"
    ),
    "内置线稿": "내장 선화",
    "内置原创图标": "내장 오리지널 아이콘",
    "轨道背景": "트랙 배경",
    "选择本地乐器图片目录；未设置时使用内置线稿": (
        "로컬 악기 이미지 폴더 선택; 미설정 시 내장 선화 사용"
    ),
    "选择本地乐器图片目录；未设置时使用内置原创图标": (
        "로컬 악기 이미지 폴더 선택; 미설정 시 내장 오리지널 아이콘 사용"
    ),
    "选择乐器背景目录": "악기 배경 폴더 선택",
    "背景目录不可用": "배경 폴더를 사용할 수 없음",
    "请选择有效的本地乐器图片目录。": (
        "유효한 로컬 악기 이미지 폴더를 선택하세요."
    ),
    "已载入 {count} 张轨道背景": "트랙 배경 {count}개 로드됨",
})

EN.update({
    "本程序": "This app",
    "音频 --": "Audio --",
    "声部 --": "Voices --",
    "当前 BDO Music Composer 进程；每秒低开销采样一次": (
        "Current BDO Music Composer process; sampled once per second"
    ),
    "音频 {load:.0f}% · XRUN {count}": "Audio {load:.0f}% · XRUN {count}",
    "声部 {count}": "Voices {count}",
})
JA.update({
    "本程序": "このアプリ",
    "音频 --": "オーディオ --",
    "声部 --": "ボイス --",
    "当前 BDO Music Composer 进程；每秒低开销采样一次": (
        "現在の BDO Music Composer プロセスを毎秒低負荷で測定"
    ),
    "音频 {load:.0f}% · XRUN {count}": "オーディオ {load:.0f}% · XRUN {count}",
    "声部 {count}": "ボイス {count}",
})
KO.update({
    "本程序": "이 앱",
    "音频 --": "오디오 --",
    "声部 --": "보이스 --",
    "当前 BDO Music Composer 进程；每秒低开销采样一次": (
        "현재 BDO Music Composer 프로세스를 1초마다 저부하로 측정"
    ),
    "音频 {load:.0f}% · XRUN {count}": "오디오 {load:.0f}% · XRUN {count}",
    "声部 {count}": "보이스 {count}",
})


EN.update({
    "游戏图": "Game art",
    "从本机游戏 PAZ 解密乐器图；只写入本地缓存": (
        "Decrypt instrument art from local game PAZ files; local cache only"
    ),
    "选择游戏 PAZ 目录": "Choose Game PAZ Folder",
    "解密中…": "Decrypting…",
    "已解密 {count} 张游戏乐器图": "Decrypted {count} game instrument images",
    "游戏图不可用": "Game Art Unavailable",
    "无法读取游戏乐器图：{detail}": "Could not read game instrument art: {detail}",
    "正在解密游戏图": "Decrypting game art",
})
JA.update({
    "游戏图": "ゲーム画像",
    "从本机游戏 PAZ 解密乐器图；只写入本地缓存": (
        "ローカルのゲーム PAZ から楽器画像を復号し、ローカルキャッシュにのみ保存"
    ),
    "选择游戏 PAZ 目录": "ゲーム PAZ フォルダーを選択",
    "解密中…": "復号中…",
    "已解密 {count} 张游戏乐器图": "ゲーム楽器画像を {count} 枚復号しました",
    "游戏图不可用": "ゲーム画像を使用できません",
    "无法读取游戏乐器图：{detail}": "ゲーム楽器画像を読み込めません：{detail}",
    "正在解密游戏图": "ゲーム画像を復号中",
})
KO.update({
    "游戏图": "게임 이미지",
    "从本机游戏 PAZ 解密乐器图；只写入本地缓存": (
        "로컬 게임 PAZ에서 악기 이미지를 복호화하고 로컬 캐시에만 저장"
    ),
    "选择游戏 PAZ 目录": "게임 PAZ 폴더 선택",
    "解密中…": "복호화 중…",
    "已解密 {count} 张游戏乐器图": "게임 악기 이미지 {count}개 복호화 완료",
    "游戏图不可用": "게임 이미지를 사용할 수 없음",
    "无法读取游戏乐器图：{detail}": "게임 악기 이미지를 읽을 수 없음: {detail}",
    "正在解密游戏图": "게임 이미지 복호화 중",
})

EN.update({
    "音量": "Volume",
    "转换文件保存位置。": "Folder for exported scores.",
    "选择": "Choose",
    "选择输出目录": "Choose Output Folder",
    "输出目录不可用": "Output Folder Unavailable",
    "请选择有效的输出目录。": "Choose a valid output folder.",
})
JA.update({
    "音量": "音量",
    "转换文件保存位置。": "書き出した楽譜の保存先です。",
    "选择": "選択",
    "选择输出目录": "出力フォルダーを選択",
    "输出目录不可用": "出力フォルダーを使用できません",
    "请选择有效的输出目录。": "有効な出力フォルダーを選択してください。",
})
KO.update({
    "音量": "음량",
    "转换文件保存位置。": "내보낸 악보를 저장할 폴더입니다.",
    "选择": "선택",
    "选择输出目录": "출력 폴더 선택",
    "输出目录不可用": "출력 폴더를 사용할 수 없음",
    "请选择有效的输出目录。": "유효한 출력 폴더를 선택하세요.",
})


EN.update({
    "MIDI 优化": "MIDI Optimization",
    "参数错误": "Invalid Parameters",
    "定位失败": "Seek Failed",
    "导出已阻止": "Export Blocked",
    "工程里的源文件和自动保存副本都不存在。": (
        "Neither the project's source file nor its autosave copy exists."
    ),
    "建议先做一次转换检查，确认音域、FX 和打击乐映射": (
        "Run Export Check first to verify pitch ranges, FX, and percussion mapping"
    ),
    "当前没有可试听轨道，请取消静音或 Solo。": (
        "No tracks are available for preview. Unmute a track or clear Solo."
    ),
    "打开工程失败": "Unable to Open Project",
    "无法试听": "Cannot Preview",
    "显示力度曲线；拖动时间点会按距离影响周边点": (
        "Show the velocity curve; dragging a point affects nearby points by distance"
    ),
    "样本覆盖检查失败": "Sample Coverage Check Failed",
    "检查音域、FX 和打击乐映射": "Check pitch ranges, FX, and percussion mapping",
    "没有可试听轨道": "No Previewable Tracks",
    "确认导出变化": "Confirm Export Changes",
    "程序错误": "Application Error",
    "试听不可用": "Preview Unavailable",
    "试听失败": "Preview Failed",
    "请先在时间轴中选择要删除的轨道。": (
        "Select a track on the timeline before deleting it."
    ),
    "请先导入 MIDI 或打开一个工程。": "Import a MIDI file or open a project first.",
    "请先导入 MIDI。": "Import a MIDI file first.",
    "谱面对比失败": "Score Comparison Failed",
    "其他": "Other",
    "BDO 游戏安全优化": "BDO Game-Safe Optimization",
    "保持音符数量、音高集合、乐器映射和手动奏法的确定性安全优化。": (
        "Deterministic safe optimization that preserves note count, pitch set, "
        "instrument mapping, and manual Musical Techniques."
    ),
    "效果器": "Effector",
    "辅助发送": "AuxSend",
    "玛尔尼音色": "Marnian Timbre",
    "基本": "Basic",
    "颤音": "Trill",
    "颤音 2": "Trill 2",
    "颤音 3": "Trill 3",
    "颤音 4": "Trill 4",
    "颤音大调": "Major Trill",
    "大调颤音": "Major Trill (Alt.)",
    "颤音小调 2": "Minor Trill 2",
    "维持滤波器": "Sustain Filter",
    "滤波铜管": "Filter Brass",
    "X-音符": "X-Note",
    "FX(C2~G2)": "FX (C2–G2)",
    "SusPiano": "Sustain (Piano)",
    "SusMezzoForte": "Sustain (Mezzo-forte)",
    "SusForte": "Sustain (Forte)",
    "默认延音。适合旋律线、长音、和声铺底；不确定时优先保留。": (
        "Default sustain. Suitable for melody lines, long notes, and harmonic beds; "
        "keep it when uncertain."
    ),
    "强调或游戏内标记型奏法。实际音色仍需验证，建议只在人工确认后使用。": (
        "An accent or in-game marker technique. Its exact timbre still requires "
        "verification; use it only after manual review."
    ),
    "短促断奏。适合短音、明显断开的节奏型或跳音。": (
        "Short staccato. Suitable for short notes, clearly separated rhythms, or "
        "detached notes."
    ),
    "向上滑入。适合后接更高音、间隔 1-4 半音且连接较紧的音。": (
        "Slide upward into a higher following note, typically one to four semitones "
        "away with a close connection."
    ),
    "半音邻音颤动。适合长音或邻音来回装饰。": (
        "Semitone-neighbor trill for long notes or alternating-neighbor ornaments."
    ),
    "全音邻音颤动。适合长音或全音邻音装饰。": (
        "Whole-tone-neighbor trill for long notes or whole-tone ornaments."
    ),
    "颤音/抖音。适合长音、快速同音重复或需要持续变化的音色。": (
        "Trill or tremolo for long notes, rapid repeated notes, or a continuously "
        "changing timbre."
    ),
    "颤音变体。具体 BDO 音色需继续验证，建议先作为人工候选。": (
        "A trill variant whose exact BDO timbre still needs verification; keep it "
        "as a manual candidate."
    ),
    "大调颤音变体。适合全音邻音装饰，具体音色需验证。": (
        "A major-trill variant for whole-tone-neighbor ornaments; its exact timbre "
        "still needs verification."
    ),
    "大调和弦。适合明确的大三和弦竖琴块，不适合单音旋律。": (
        "Major chord for clear harp major-triad blocks, not single-note melodies."
    ),
    "小调和弦。适合明确的小三和弦竖琴块，不适合单音旋律。": (
        "Minor chord for clear harp minor-triad blocks, not single-note melodies."
    ),
    "钢琴延音踏板。适合 MIDI CC64、和声保持、同和弦重叠延续。": (
        "Piano sustain pedal for MIDI CC64, harmonic sustain, and overlapping notes "
        "within the same chord."
    ),
    "向下滑弦。适合后接更低音、间隔 1-4 半音的吉他/贝斯收尾。": (
        "Downward slide into a lower following note, typically one to four semitones "
        "away, for guitar or bass endings."
    ),
    "弱音。适合吉他/贝斯短促伴奏、切分节奏、低到中等力度重复音。": (
        "Muted technique for short guitar or bass accompaniment, syncopation, and "
        "low-to-medium-velocity repeated notes."
    ),
    "泛音。适合高音区稀疏点缀或空灵音色，不适合整轨密集套用。": (
        "Harmonics for sparse high-register accents or an airy timbre; avoid applying "
        "them densely across an entire track."
    ),
    "三连音。适合一拍内三等分的局部节奏或三连音装饰。": (
        "Triplet for local rhythms divided into three equal parts per beat or for "
        "triplet ornaments."
    ),
    "滑音。适合竖琴扫弦、贝斯滑奏或快速连续跨音程装饰。": (
        "Glissando for harp sweeps, bass slides, or fast continuous interval ornaments."
    ),
    "大调颤音。适合全音邻音装饰或明亮颤动长音。": (
        "Major trill for whole-tone-neighbor ornaments or bright, trilling long notes."
    ),
    "维持滤波器。适合玛勒尼恩合成铺底、长音和持续纹理，需人工验证。": (
        "Sustain Filter for Marnian synth beds, long notes, and continuous textures; "
        "manual verification is required."
    ),
    "滤波铜管。适合明亮、高力度或铜管感合成长音，需人工验证。": (
        "Filter Brass for bright, high-velocity, brass-like synth sustains; manual "
        "verification is required."
    ),
    "拍弦。适合贝斯高力度短音、funk 节奏或八度跳进。": (
        "Slap for high-velocity short bass notes, funk rhythms, or octave leaps."
    ),
    "滑音上升。适合贝斯/低音提琴上行滑入目标音。": (
        "Rising glissando for sliding upward into a target note on bass or contrabass."
    ),
    "X-音符。适合贝斯极短鬼音、死音或节奏填充，不保证明确音高。": (
        "X-Note for very short bass ghost notes, dead notes, or rhythmic fills; a "
        "definite pitch is not guaranteed."
    ),
    "电吉他 FX 触发。只适合 C2-G2 特效触发音，不应自动套到普通旋律。": (
        "Electric-guitar FX trigger for C2–G2 effect notes only; do not apply it "
        "automatically to ordinary melodies."
    ),
    "弱力度持续音。适合单簧管/圆号长音，建议 velocity < 70。": (
        "Soft sustain for clarinet or horn long notes; recommended velocity below 70."
    ),
    "中力度持续音。适合单簧管/圆号长音，建议 velocity 70-99。": (
        "Medium sustain for clarinet or horn long notes; recommended velocity 70–99."
    ),
    "强力度持续音。适合单簧管/圆号长音，建议 velocity >= 100。": (
        "Strong sustain for clarinet or horn long notes; recommended velocity 100 or "
        "higher."
    ),
})

JA.update({
    "MIDI 优化": "MIDI最適化",
    "参数错误": "パラメーターエラー",
    "定位失败": "位置の変更に失敗しました",
    "导出已阻止": "書き出しがブロックされました",
    "工程里的源文件和自动保存副本都不存在。": (
        "プロジェクトの元ファイルも自動保存コピーも見つかりません。"
    ),
    "建议先做一次转换检查，确认音域、FX 和打击乐映射": (
        "先に書き出しチェックを実行し、音域、FX、打楽器マッピングを確認してください"
    ),
    "当前没有可试听轨道，请取消静音或 Solo。": (
        "試聴できるトラックがありません。ミュートまたはSoloを解除してください。"
    ),
    "打开工程失败": "プロジェクトを開けません",
    "无法试听": "試聴できません",
    "显示力度曲线；拖动时间点会按距离影响周边点": (
        "ベロシティカーブを表示します。時間点をドラッグすると距離に応じて周辺へ影響します"
    ),
    "样本覆盖检查失败": "サンプル範囲の確認に失敗しました",
    "检查音域、FX 和打击乐映射": "音域、FX、打楽器マッピングを確認",
    "没有可试听轨道": "試聴可能なトラックがありません",
    "确认导出变化": "書き出し時の変更を確認",
    "程序错误": "アプリケーションエラー",
    "试听不可用": "試聴を利用できません",
    "试听失败": "試聴に失敗しました",
    "请先在时间轴中选择要删除的轨道。": (
        "削除するトラックを先にタイムラインで選択してください。"
    ),
    "请先导入 MIDI 或打开一个工程。": (
        "先にMIDIを読み込むか、プロジェクトを開いてください。"
    ),
    "请先导入 MIDI。": "先にMIDIを読み込んでください。",
    "谱面对比失败": "楽譜の比較に失敗しました",
    "其他": "その他",
    "BDO 游戏安全优化": "BDOゲーム安全最適化",
    "保持音符数量、音高集合、乐器映射和手动奏法的确定性安全优化。": (
        "ノート数、音高集合、楽器マッピング、手動の奏法を維持する決定論的なゲーム安全最適化です。"
    ),
    "效果器": "エフェクター",
    "辅助发送": "AuxSend",
    "玛尔尼音色": "マルニアン音色",
    "基本": "基本",
    "颤音": "トリル",
    "颤音 2": "トリル 2",
    "颤音 3": "トリル 3",
    "颤音 4": "トリル 4",
    "颤音大调": "メジャートリル",
    "大调颤音": "メジャートリル（別）",
    "颤音小调 2": "マイナートリル 2",
    "维持滤波器": "サステインフィルター",
    "滤波铜管": "フィルターブラス",
    "X-音符": "Xノート",
    "FX(C2~G2)": "FX（C2～G2）",
    "SusPiano": "サステイン（ピアノ）",
    "SusMezzoForte": "サステイン（メゾフォルテ）",
    "SusForte": "サステイン（フォルテ）",
    "默认延音。适合旋律线、长音、和声铺底；不确定时优先保留。": (
        "標準のサステインです。旋律線、長音、和声の土台に適し、判断できない場合は優先して保持します。"
    ),
    "强调或游戏内标记型奏法。实际音色仍需验证，建议只在人工确认后使用。": (
        "アクセントまたはゲーム内マーカー型の奏法です。実際の音色は未検証のため、手動確認後のみ使用してください。"
    ),
    "短促断奏。适合短音、明显断开的节奏型或跳音。": (
        "短いスタッカートです。短音、明確に分離したリズム、跳ねるような音に適します。"
    ),
    "向上滑入。适合后接更高音、间隔 1-4 半音且连接较紧的音。": (
        "1～4半音上の後続音へ密接につなぐ上向きスライドです。"
    ),
    "半音邻音颤动。适合长音或邻音来回装饰。": (
        "長音や隣接音を往復する装飾に適した半音トリルです。"
    ),
    "全音邻音颤动。适合长音或全音邻音装饰。": (
        "長音や全音隣接音の装飾に適した全音トリルです。"
    ),
    "颤音/抖音。适合长音、快速同音重复或需要持续变化的音色。": (
        "長音、速い同音反復、継続的に変化する音色に適したトリル／トレモロです。"
    ),
    "颤音变体。具体 BDO 音色需继续验证，建议先作为人工候选。": (
        "トリルの派生です。BDOでの正確な音色は未検証のため、手動候補として扱ってください。"
    ),
    "大调颤音变体。适合全音邻音装饰，具体音色需验证。": (
        "全音隣接音の装飾に適したメジャートリルの派生です。正確な音色は要検証です。"
    ),
    "大调和弦。适合明确的大三和弦竖琴块，不适合单音旋律。": (
        "明確な長三和音のハープブロック向けです。単音旋律には適しません。"
    ),
    "小调和弦。适合明确的小三和弦竖琴块，不适合单音旋律。": (
        "明確な短三和音のハープブロック向けです。単音旋律には適しません。"
    ),
    "钢琴延音踏板。适合 MIDI CC64、和声保持、同和弦重叠延续。": (
        "MIDI CC64、和声の保持、同一コード内の重なりに適したピアノのサステインペダルです。"
    ),
    "向下滑弦。适合后接更低音、间隔 1-4 半音的吉他/贝斯收尾。": (
        "1～4半音下の後続音へつなぐ、ギター／ベースの終止向け下向きスライドです。"
    ),
    "弱音。适合吉他/贝斯短促伴奏、切分节奏、低到中等力度重复音。": (
        "ギター／ベースの短い伴奏、シンコペーション、弱～中ベロシティの反復音向けミュートです。"
    ),
    "泛音。适合高音区稀疏点缀或空灵音色，不适合整轨密集套用。": (
        "高音域の疎らな装飾や透明感のある音色向けです。トラック全体への密な適用は避けてください。"
    ),
    "三连音。适合一拍内三等分的局部节奏或三连音装饰。": (
        "1拍を3等分する局所リズムや三連符装飾に適します。"
    ),
    "滑音。适合竖琴扫弦、贝斯滑奏或快速连续跨音程装饰。": (
        "ハープのスイープ、ベースのスライド、速い連続音程装飾に適したグリッサンドです。"
    ),
    "大调颤音。适合全音邻音装饰或明亮颤动长音。": (
        "全音隣接音の装飾や、明るく揺れる長音に適したメジャートリルです。"
    ),
    "维持滤波器。适合玛勒尼恩合成铺底、长音和持续纹理，需人工验证。": (
        "マルニアンのシンセパッド、長音、持続テクスチャ向けのサステインフィルターです。手動確認が必要です。"
    ),
    "滤波铜管。适合明亮、高力度或铜管感合成长音，需人工验证。": (
        "明るく強い、ブラス風のシンセ長音向けフィルターブラスです。手動確認が必要です。"
    ),
    "拍弦。适合贝斯高力度短音、funk 节奏或八度跳进。": (
        "強いベース短音、ファンクのリズム、オクターブ跳躍に適したスラップです。"
    ),
    "滑音上升。适合贝斯/低音提琴上行滑入目标音。": (
        "ベース／コントラバスで目標音へ上向きに滑り込むグリッサンドです。"
    ),
    "X-音符。适合贝斯极短鬼音、死音或节奏填充，不保证明确音高。": (
        "ベースの非常に短いゴーストノート、デッドノート、リズムフィル向けです。明確な音高は保証されません。"
    ),
    "电吉他 FX 触发。只适合 C2-G2 特效触发音，不应自动套到普通旋律。": (
        "C2～G2のエフェクト音専用のエレキギターFXトリガーです。通常の旋律へ自動適用しないでください。"
    ),
    "弱力度持续音。适合单簧管/圆号长音，建议 velocity < 70。": (
        "クラリネット／ホルンの長音向け弱サステインです。推奨ベロシティは70未満です。"
    ),
    "中力度持续音。适合单簧管/圆号长音，建议 velocity 70-99。": (
        "クラリネット／ホルンの長音向け中サステインです。推奨ベロシティは70～99です。"
    ),
    "强力度持续音。适合单簧管/圆号长音，建议 velocity >= 100。": (
        "クラリネット／ホルンの長音向け強サステインです。推奨ベロシティは100以上です。"
    ),
})

KO.update({
    "MIDI 优化": "MIDI 최적화",
    "参数错误": "매개변수 오류",
    "定位失败": "위치 이동 실패",
    "导出已阻止": "내보내기 차단됨",
    "工程里的源文件和自动保存副本都不存在。": (
        "프로젝트 원본 파일과 자동 저장 사본이 모두 없습니다."
    ),
    "建议先做一次转换检查，确认音域、FX 和打击乐映射": (
        "먼저 내보내기 검사를 실행하여 음역, FX 및 타악기 매핑을 확인하세요"
    ),
    "当前没有可试听轨道，请取消静音或 Solo。": (
        "미리 들을 수 있는 트랙이 없습니다. 음소거 또는 Solo를 해제하세요."
    ),
    "打开工程失败": "프로젝트를 열 수 없음",
    "无法试听": "미리들을 수 없음",
    "显示力度曲线；拖动时间点会按距离影响周边点": (
        "벨로시티 커브를 표시합니다. 시간 지점을 드래그하면 거리에 따라 주변 지점에 영향을 줍니다"
    ),
    "样本覆盖检查失败": "샘플 범위 검사 실패",
    "检查音域、FX 和打击乐映射": "음역, FX 및 타악기 매핑 검사",
    "没有可试听轨道": "미리들을 수 있는 트랙 없음",
    "确认导出变化": "내보내기 변경 확인",
    "程序错误": "프로그램 오류",
    "试听不可用": "미리듣기 사용 불가",
    "试听失败": "미리듣기 실패",
    "请先在时间轴中选择要删除的轨道。": (
        "삭제할 트랙을 먼저 타임라인에서 선택하세요."
    ),
    "请先导入 MIDI 或打开一个工程。": (
        "먼저 MIDI를 가져오거나 프로젝트를 여세요."
    ),
    "请先导入 MIDI。": "먼저 MIDI를 가져오세요.",
    "谱面对比失败": "악보 비교 실패",
    "其他": "기타",
    "BDO 游戏安全优化": "BDO 게임 안전 최적화",
    "保持音符数量、音高集合、乐器映射和手动奏法的确定性安全优化。": (
        "음표 수, 음높이 집합, 악기 매핑 및 수동 주법을 보존하는 결정적 게임 안전 최적화입니다."
    ),
    "效果器": "이펙터",
    "辅助发送": "AuxSend",
    "玛尔尼音色": "마르니언 음색",
    "基本": "기본",
    "颤音": "트릴",
    "颤音 2": "트릴 2",
    "颤音 3": "트릴 3",
    "颤音 4": "트릴 4",
    "颤音大调": "메이저 트릴",
    "大调颤音": "메이저 트릴(변형)",
    "颤音小调 2": "마이너 트릴 2",
    "维持滤波器": "서스테인 필터",
    "滤波铜管": "필터 브라스",
    "X-音符": "X-노트",
    "FX(C2~G2)": "FX(C2~G2)",
    "SusPiano": "서스테인(피아노)",
    "SusMezzoForte": "서스테인(메조포르테)",
    "SusForte": "서스테인(포르테)",
    "默认延音。适合旋律线、长音、和声铺底；不确定时优先保留。": (
        "기본 서스테인입니다. 선율선, 긴 음표와 화성 패드에 적합하며 확실하지 않으면 우선 유지하세요."
    ),
    "强调或游戏内标记型奏法。实际音色仍需验证，建议只在人工确认后使用。": (
        "강조 또는 게임 내 표식형 주법입니다. 실제 음색은 검증이 필요하므로 수동 확인 후에만 사용하세요."
    ),
    "短促断奏。适合短音、明显断开的节奏型或跳音。": (
        "짧은 스타카토입니다. 짧은 음표, 뚜렷하게 끊긴 리듬 또는 도약음에 적합합니다."
    ),
    "向上滑入。适合后接更高音、间隔 1-4 半音且连接较紧的音。": (
        "1~4반음 위의 다음 음으로 촘촘히 연결되는 상향 슬라이드입니다."
    ),
    "半音邻音颤动。适合长音或邻音来回装饰。": (
        "긴 음표나 이웃음을 오가는 장식에 적합한 반음 트릴입니다."
    ),
    "全音邻音颤动。适合长音或全音邻音装饰。": (
        "긴 음표나 온음 이웃음 장식에 적합한 온음 트릴입니다."
    ),
    "颤音/抖音。适合长音、快速同音重复或需要持续变化的音色。": (
        "긴 음표, 빠른 동음 반복 또는 계속 변화하는 음색에 적합한 트릴/트레몰로입니다."
    ),
    "颤音变体。具体 BDO 音色需继续验证，建议先作为人工候选。": (
        "트릴 변형입니다. 정확한 BDO 음색은 추가 검증이 필요하므로 수동 후보로 두세요."
    ),
    "大调颤音变体。适合全音邻音装饰，具体音色需验证。": (
        "온음 이웃음 장식에 적합한 메이저 트릴 변형이며 정확한 음색은 검증이 필요합니다."
    ),
    "大调和弦。适合明确的大三和弦竖琴块，不适合单音旋律。": (
        "명확한 장3화음 하프 블록에 적합하며 단선율에는 적합하지 않습니다."
    ),
    "小调和弦。适合明确的小三和弦竖琴块，不适合单音旋律。": (
        "명확한 단3화음 하프 블록에 적합하며 단선율에는 적합하지 않습니다."
    ),
    "钢琴延音踏板。适合 MIDI CC64、和声保持、同和弦重叠延续。": (
        "MIDI CC64, 화성 유지 및 같은 화음 안의 겹친 음표에 적합한 피아노 서스테인 페달입니다."
    ),
    "向下滑弦。适合后接更低音、间隔 1-4 半音的吉他/贝斯收尾。": (
        "1~4반음 아래의 다음 음으로 연결되는 기타/베이스 마무리용 하향 슬라이드입니다."
    ),
    "弱音。适合吉他/贝斯短促伴奏、切分节奏、低到中等力度重复音。": (
        "기타/베이스의 짧은 반주, 싱코페이션 및 낮거나 중간 벨로시티의 반복음에 적합한 뮤트입니다."
    ),
    "泛音。适合高音区稀疏点缀或空灵音色，不适合整轨密集套用。": (
        "고음역의 드문 장식이나 맑은 음색에 적합하며 트랙 전체에 빽빽하게 적용하지 마세요."
    ),
    "三连音。适合一拍内三等分的局部节奏或三连音装饰。": (
        "한 박을 3등분한 부분 리듬이나 셋잇단음표 장식에 적합합니다."
    ),
    "滑音。适合竖琴扫弦、贝斯滑奏或快速连续跨音程装饰。": (
        "하프 스윕, 베이스 슬라이드 또는 빠르게 이어지는 음정 장식에 적합한 글리산도입니다."
    ),
    "大调颤音。适合全音邻音装饰或明亮颤动长音。": (
        "온음 이웃음 장식이나 밝게 떨리는 긴 음표에 적합한 메이저 트릴입니다."
    ),
    "维持滤波器。适合玛勒尼恩合成铺底、长音和持续纹理，需人工验证。": (
        "마르니언 신스 패드, 긴 음표와 지속 텍스처에 적합한 서스테인 필터이며 수동 검증이 필요합니다."
    ),
    "滤波铜管。适合明亮、高力度或铜管感合成长音，需人工验证。": (
        "밝고 강한 브라스 계열 신스 롱톤에 적합한 필터 브라스이며 수동 검증이 필요합니다."
    ),
    "拍弦。适合贝斯高力度短音、funk 节奏或八度跳进。": (
        "강한 베이스 짧은 음표, 펑크 리듬 또는 옥타브 도약에 적합한 슬랩입니다."
    ),
    "滑音上升。适合贝斯/低音提琴上行滑入目标音。": (
        "베이스/콘트라베이스에서 목표음으로 올라가며 미끄러지는 글리산도입니다."
    ),
    "X-音符。适合贝斯极短鬼音、死音或节奏填充，不保证明确音高。": (
        "베이스의 매우 짧은 고스트 노트, 데드 노트 또는 리듬 필에 적합하며 뚜렷한 음높이는 보장되지 않습니다."
    ),
    "电吉他 FX 触发。只适合 C2-G2 特效触发音，不应自动套到普通旋律。": (
        "C2~G2 이펙트 음 전용 일렉 기타 FX 트리거이며 일반 선율에 자동 적용하면 안 됩니다."
    ),
    "弱力度持续音。适合单簧管/圆号长音，建议 velocity < 70。": (
        "클라리넷/호른 긴 음표용 약한 서스테인이며 권장 벨로시티는 70 미만입니다."
    ),
    "中力度持续音。适合单簧管/圆号长音，建议 velocity 70-99。": (
        "클라리넷/호른 긴 음표용 중간 서스테인이며 권장 벨로시티는 70~99입니다."
    ),
    "强力度持续音。适合单簧管/圆号长音，建议 velocity >= 100。": (
        "클라리넷/호른 긴 음표용 강한 서스테인이며 권장 벨로시티는 100 이상입니다."
    ),
})


EN.update({
    "新手专用：吉他": "Beginner Guitar",
    "新手专用：长笛": "Beginner Flute",
    "新手专用：竖笛": "Beginner Recorder",
    "新手专用：笛子": "Beginner Recorder",
    "新手专用：手鼓": "Beginner Hand Drum",
    "新手专用：钹": "Beginner Cymbals",
    "新手专用：竖琴": "Beginner Harp",
    "新手专用：钢琴": "Beginner Piano",
    "新手专用：小提琴": "Beginner Violin",
    "弗洛凯斯特拉：原声吉他": "Florchestra Acoustic Guitar",
    "弗洛凯斯特拉：长笛": "Florchestra Flute",
    "弗洛凯斯特拉：架子鼓套装": "Florchestra Drum Set",
    "玛尔尼贝斯": "Marnibass",
    "弗洛凯斯特拉：低音提琴": "Florchestra Contrabass",
    "弗洛凯斯特拉：竖琴": "Florchestra Harp",
    "弗洛凯斯特拉：钢琴": "Florchestra Piano",
    "弗洛凯斯特拉：小提琴": "Florchestra Violin",
    "弗洛凯斯特拉：手碟": "Florchestra Handpan",
    "玛勒尼斯：玛勒尼恩 - 波纹行星": "Marnian: Wavy Planet",
    "玛勒尼斯：玛勒尼恩 - 幻象树": "Marnian: Illusion Tree",
    "玛勒尼斯：玛勒尼恩 - 秘密笔记": "Marnian: Secret Note",
    "玛勒尼斯：玛勒尼恩 - 三明治": "Marnian: Sandwich",
    "玛勒尼斯：电吉他 - 银色水波": "Marni Electric Guitar: Silver Wave",
    "玛勒尼斯：电吉他 - 高速路": "Marni Electric Guitar: Highway",
    "玛勒尼斯：电吉他 - 赫克赛格莱姆": "Marni Electric Guitar: Hexe Glam",
    "弗洛凯斯特拉：单簧管": "Florchestra Clarinet",
    "弗洛凯斯特拉：圆号": "Florchestra Horn",
    # Legacy source spellings remain readable in older projects and reports.
    "弗罗凯特拉：原声吉他": "Florchestra Acoustic Guitar",
    "弗罗凯特拉：长笛": "Florchestra Flute",
    "弗罗凯特拉：架子鼓套装": "Florchestra Drum Set",
    "玛勒尼斯：贝斯": "Marnibass",
    "弗罗凯特拉：肯特拉贝斯": "Florchestra Contrabass",
    "弗罗凯特拉：竖琴": "Florchestra Harp",
    "弗罗凯特拉：钢琴": "Florchestra Piano",
    "弗罗凯特拉：小提琴": "Florchestra Violin",
    "弗罗凯特拉：手碟": "Florchestra Handpan",
    "玛勒尼斯：电吉他 - 赫赛德兰": "Marni Electric Guitar: Hexe Glam",
    "弗罗凯特拉：单簧管": "Florchestra Clarinet",
    "弗罗凯特拉：圆号": "Florchestra Horn",
})

JA.update({
    "新手专用：吉他": "初心者用ギター",
    "新手专用：长笛": "初心者用フルート",
    "新手专用：竖笛": "初心者用リコーダー",
    "新手专用：笛子": "初心者用リコーダー",
    "新手专用：手鼓": "初心者用ハンドドラム",
    "新手专用：钹": "初心者用シンバル",
    "新手专用：竖琴": "初心者用ハープ",
    "新手专用：钢琴": "初心者用ピアノ",
    "新手专用：小提琴": "初心者用バイオリン",
    "弗洛凯斯特拉：原声吉他": "フローケストラアコースティックギター",
    "弗洛凯斯特拉：长笛": "フローケストラフルート",
    "弗洛凯斯特拉：架子鼓套装": "フローケストラドラムセット",
    "玛尔尼贝斯": "マルニバス",
    "弗洛凯斯特拉：低音提琴": "フローケストラコントラバス",
    "弗洛凯斯特拉：竖琴": "フローケストラハープ",
    "弗洛凯斯特拉：钢琴": "フローケストラピアノ",
    "弗洛凯斯特拉：小提琴": "フローケストラバイオリン",
    "弗洛凯斯特拉：手碟": "フローケストラタンドラム",
    "玛勒尼斯：玛勒尼恩 - 波纹行星": "マルニアン：波の惑星",
    "玛勒尼斯：玛勒尼恩 - 幻象树": "マルニアン：幻想ツリー",
    "玛勒尼斯：玛勒尼恩 - 秘密笔记": "マルニアン：秘密のノート",
    "玛勒尼斯：玛勒尼恩 - 三明治": "マルニアン：サンドイッチ",
    "玛勒尼斯：电吉他 - 银色水波": "マルニエレキギター：銀色の波",
    "玛勒尼斯：电吉他 - 高速路": "マルニエレキギター：ハイウェイ",
    "玛勒尼斯：电吉他 - 赫克赛格莱姆": "マルニエレキギター：ヘクセグラム",
    "弗洛凯斯特拉：单簧管": "フローケストラクラリネット",
    "弗洛凯斯特拉：圆号": "フローケストラホルン",
    "弗罗凯特拉：原声吉他": "フローケストラアコースティックギター",
    "弗罗凯特拉：长笛": "フローケストラフルート",
    "弗罗凯特拉：架子鼓套装": "フローケストラドラムセット",
    "玛勒尼斯：贝斯": "マルニバス",
    "弗罗凯特拉：肯特拉贝斯": "フローケストラコントラバス",
    "弗罗凯特拉：竖琴": "フローケストラハープ",
    "弗罗凯特拉：钢琴": "フローケストラピアノ",
    "弗罗凯特拉：小提琴": "フローケストラバイオリン",
    "弗罗凯特拉：手碟": "フローケストラタンドラム",
    "玛勒尼斯：电吉他 - 赫赛德兰": "マルニエレキギター：ヘクセグラム",
    "弗罗凯特拉：单簧管": "フローケストラクラリネット",
    "弗罗凯特拉：圆号": "フローケストラホルン",
})

KO.update({
    "新手专用：吉他": "초보자용 기타",
    "新手专用：长笛": "초보자용 플룻",
    "新手专用：竖笛": "초보자용 리코더",
    "新手专用：笛子": "초보자용 리코더",
    "新手专用：手鼓": "초보자용 핸드드럼",
    "新手专用：钹": "초보자용 심벌즈",
    "新手专用：竖琴": "초보자용 하프",
    "新手专用：钢琴": "초보자용 피아노",
    "新手专用：小提琴": "초보자용 바이올린",
    "弗洛凯斯特拉：原声吉他": "플로케스트라 어쿠스틱 기타",
    "弗洛凯斯特拉：长笛": "플로케스트라 플룻",
    "弗洛凯斯特拉：架子鼓套装": "플로케스트라 드럼 세트",
    "玛尔尼贝斯": "마르니베이스",
    "弗洛凯斯特拉：低音提琴": "플로케스트라 콘트라베이스",
    "弗洛凯斯特拉：竖琴": "플로케스트라 하프",
    "弗洛凯斯特拉：钢琴": "플로케스트라 피아노",
    "弗洛凯斯特拉：小提琴": "플로케스트라 바이올린",
    "弗洛凯斯特拉：手碟": "플로케스트라 팬드럼",
    "玛勒尼斯：玛勒尼恩 - 波纹行星": "마르니언 : 물결행성",
    "玛勒尼斯：玛勒尼恩 - 幻象树": "마르니언 : 환상트리",
    "玛勒尼斯：玛勒尼恩 - 秘密笔记": "마르니언 : 비밀노트",
    "玛勒尼斯：玛勒尼恩 - 三明治": "마르니언 : 샌드위치",
    "玛勒尼斯：电吉他 - 银色水波": "마르니 일렉기타 : 은빛물결",
    "玛勒尼斯：电吉他 - 高速路": "마르니 일렉기타 : 하이웨이",
    "玛勒尼斯：电吉他 - 赫克赛格莱姆": "마르니 일렉기타 : 헥세글램",
    "弗洛凯斯特拉：单簧管": "플로케스트라 클라리넷",
    "弗洛凯斯特拉：圆号": "플로케스트라 호른",
    "弗罗凯特拉：原声吉他": "플로케스트라 어쿠스틱 기타",
    "弗罗凯特拉：长笛": "플로케스트라 플룻",
    "弗罗凯特拉：架子鼓套装": "플로케스트라 드럼 세트",
    "玛勒尼斯：贝斯": "마르니베이스",
    "弗罗凯特拉：肯特拉贝斯": "플로케스트라 콘트라베이스",
    "弗罗凯特拉：竖琴": "플로케스트라 하프",
    "弗罗凯特拉：钢琴": "플로케스트라 피아노",
    "弗罗凯特拉：小提琴": "플로케스트라 바이올린",
    "弗罗凯特拉：手碟": "플로케스트라 팬드럼",
    "玛勒尼斯：电吉他 - 赫赛德兰": "마르니 일렉기타 : 헥세글램",
    "弗罗凯特拉：单簧管": "플로케스트라 클라리넷",
    "弗罗凯特拉：圆号": "플로케스트라 호른",
})


# Export validation and score comparison can be rendered outside the widget
# tree (reports, clipboard text and CLI output), so their complete templates
# live in the same catalogs and retain the source placeholder signatures.
EN.update({
    "当前轨道因 Mute/Solo 状态不参与导出。": (
        "This track is excluded from export because of its Mute/Solo state."
    ),
    "轨道游戏音量不是有效的 v9 字节。": (
        "The track's in-game volume is not a valid v9 byte."
    ),
    "轨道音量 {volume} 超过当前游戏编辑范围 0–100；未编辑时会原样保留。": (
        "Track volume {volume} exceeds the current in-game edit range of 0–100; "
        "the imported value is preserved unless edited."
    ),
    "轨道效果设置不是有效的 8 字节 v9 数据。": (
        "The track effect settings are not valid 8-byte v9 data."
    ),
    "轨道效果发送量含超过当前游戏编辑范围 0–100 的导入值；未编辑项会原样保留。": (
        "The track effect sends contain an imported value above the current in-game "
        "edit range of 0–100; unedited values are preserved."
    ),
    "未知 BDO 乐器 ID 0x{instrument_id:02X}。": (
        "Unknown BDO instrument ID 0x{instrument_id:02X}."
    ),
    "{count} 个 GM 打击乐音符没有 BDO 映射：{pitches}。": (
        "GM percussion notes without a BDO mapping: {count}; pitches: {pitches}."
    ),
    "导出会把 {count} 个 GM 打击乐音符转换为 BDO 48–64 / ntype 99。": (
        "Export will convert {count} GM percussion notes to BDO 48–64 / ntype 99."
    ),
    "独立打击乐没有完整 GM 逐音映射，当前结果需要游戏内确认。": (
        "This percussion instrument has no complete per-note GM mapping; verify the "
        "result in game."
    ),
    "{count} 个音符超出 BDO C0–B8 范围，当前导出器会裁剪音高。": (
        "{count} notes are outside the BDO C0–B8 range; the exporter will clamp "
        "their pitches."
    ),
    "当前乐器缺少经过验证的完整游戏音域。": (
        "A complete verified in-game range is not available for this instrument."
    ),
    "{count} 个音符不在当前乐器的已知游戏音域内。": (
        "{count} notes are outside this instrument's known in-game range."
    ),
    "导出会将此轨道全部音符移调 {transpose:+d} 半音。": (
        "Export will transpose every note on this track by {transpose:+d} semitones."
    ),
    "导出会将此轨道音符时值乘以 {duration_scale:.3g}。": (
        "Export will multiply note durations on this track by {duration_scale:.3g}."
    ),
    "导出会将此轨道力度乘以 {volume_scale:.3g}。": (
        "Export will multiply note velocities on this track by {volume_scale:.3g}."
    ),
    "FX type {articulation} 不属于当前乐器。": (
        "FX type {articulation} is not available for this instrument."
    ),
    "导出会把此轨道全部音符设为 FX type {articulation}。": (
        "Export will set every note on this track to FX type {articulation}."
    ),
    "该乐器当前只有样本键位证据，完整音域仍待游戏验证。": (
        "Only sample-key evidence is available for this instrument; its complete "
        "range still requires in-game verification."
    ),
    "导出会把 {track_count} 条轨道按乐器 0x{instrument_id:02X} 合并：{track_names}。": (
        "Export will merge {track_count} tracks for instrument 0x{instrument_id:02X}: "
        "{track_names}."
    ),
    "同一游戏乐器的 {track_count} 条轨道使用了不同音量；游戏只保存一个乐器音量，请先统一。": (
        "{track_count} tracks for the same in-game instrument use different volumes; "
        "the game stores one instrument volume, so make them consistent first."
    ),
    "同一游戏乐器的 {track_count} 条轨道使用了不同效果发送量；游戏只保存一组发送量，请先统一。": (
        "{track_count} tracks for the same in-game instrument use different effect "
        "send levels; the game stores one set, so make them consistent first."
    ),
    "乐器 0x{instrument_id:02X} 合并后有 {count} 个音符，超过已验证上限 {limit}。": (
        "Instrument 0x{instrument_id:02X} has {count} notes after merging, exceeding "
        "the verified limit of {limit}."
    ),
    "乐器 0x{instrument_id:02X} 合并后有 {count} 个音符，超过工具保守审阅阈值 {limit}；"
    "导出器不会因此截断，但游戏实际 noteCount 由账号能力运行时下发，请在游戏内确认。": (
        "Instrument 0x{instrument_id:02X} has {count} notes after merging, exceeding "
        "the tool's conservative review threshold of {limit}. The exporter will not "
        "truncate them, but the game's actual noteCount is supplied at runtime for "
        "the account; verify it in game."
    ),
    "导出会使用 {velocity_mode} 力度处理模式修改活动音符。": (
        "Export will modify active notes using the {velocity_mode} velocity mode."
    ),
    "导出会写入全局效果：reverb={reverb}, delay={delay}, chorus={chorus}。": (
        "Export will write global effects: reverb={reverb}, delay={delay}, "
        "chorus={chorus}."
    ),
    "主效果包含无效的 v9 字节。": "The master effects contain an invalid v9 byte.",
    "主效果含超过当前游戏编辑范围 0–100 的导入值；未编辑项会原样保留。": (
        "The master effects contain an imported value above the current in-game edit "
        "range of 0–100; unedited values are preserved."
    ),
    "需处理": "Action required",
    "需人工确认": "Manual confirmation",
    "变化说明": "Change summary",
    "轨道 {track_id}": "Track {track_id}",
    "全局": "Global",
    "{count} 个音符": "{count} notes",
    "已验证": "Verified",
    "推断": "Inferred",
    "近似": "Approximate",
    "  证据（{status}）：{evidence}": "  Evidence ({status}): {evidence}",
    "谱面结构与音符一致（时间容差 {tolerance:g} ms）。": (
        "Score structure and notes match (time tolerance: {tolerance:g} ms)."
    ),
    "发现 {count} 项差异：": "Found {count} differences:",
    "- {path}: {message} ({expected!r} -> {actual!r})": (
        "- {path}: {message} ({expected!r} -> {actual!r})"
    ),
    "时间差超过 {tolerance:g} ms": "Time difference exceeds {tolerance:g} ms",
    "字段不同": "Field differs",
    "私有字段不同": "Private field differs",
    "轨道数量不同": "Track count differs",
    "乐器轨道顺序不同": "Instrument track order differs",
    "轨道缺失": "Track is missing",
    "轨道字段不同": "Track field differs",
    "音符数量不同": "Note count differs",
    "音符字段不同": "Note field differs",
})

JA.update({
    "当前轨道因 Mute/Solo 状态不参与导出。": (
        "現在のトラックはMute/Solo状態により書き出し対象外です。"
    ),
    "轨道游戏音量不是有效的 v9 字节。": (
        "トラックのゲーム内音量は有効なv9バイトではありません。"
    ),
    "轨道音量 {volume} 超过当前游戏编辑范围 0–100；未编辑时会原样保留。": (
        "トラック音量{volume}は現在のゲーム内編集範囲0～100を超えています。"
        "未編集の場合、読み込んだ値をそのまま保持します。"
    ),
    "轨道效果设置不是有效的 8 字节 v9 数据。": (
        "トラックのエフェクト設定は有効な8バイトのv9データではありません。"
    ),
    "轨道效果发送量含超过当前游戏编辑范围 0–100 的导入值；未编辑项会原样保留。": (
        "トラックのエフェクトセンドに現在のゲーム内編集範囲0～100を超える"
        "読み込み値があります。未編集の値はそのまま保持します。"
    ),
    "未知 BDO 乐器 ID 0x{instrument_id:02X}。": (
        "不明なBDO楽器ID 0x{instrument_id:02X}です。"
    ),
    "{count} 个 GM 打击乐音符没有 BDO 映射：{pitches}。": (
        "BDOマッピングのないGMパーカッションノートが{count}個あります：{pitches}。"
    ),
    "导出会把 {count} 个 GM 打击乐音符转换为 BDO 48–64 / ntype 99。": (
        "書き出し時に{count}個のGMパーカッションノートを"
        "BDO 48～64 / ntype 99へ変換します。"
    ),
    "独立打击乐没有完整 GM 逐音映射，当前结果需要游戏内确认。": (
        "このパーカッション楽器には完全なGMノート別マッピングがありません。"
        "結果をゲーム内で確認してください。"
    ),
    "{count} 个音符超出 BDO C0–B8 范围，当前导出器会裁剪音高。": (
        "{count}個のノートがBDOのC0～B8範囲外です。"
        "現在の書き出し処理では音高を範囲内に収めます。"
    ),
    "当前乐器缺少经过验证的完整游戏音域。": (
        "この楽器には検証済みの完全なゲーム内音域がありません。"
    ),
    "{count} 个音符不在当前乐器的已知游戏音域内。": (
        "{count}個のノートがこの楽器の既知のゲーム内音域外です。"
    ),
    "导出会将此轨道全部音符移调 {transpose:+d} 半音。": (
        "書き出し時にこのトラックの全ノートを{transpose:+d}半音移調します。"
    ),
    "导出会将此轨道音符时值乘以 {duration_scale:.3g}。": (
        "書き出し時にこのトラックのノート長を{duration_scale:.3g}倍します。"
    ),
    "导出会将此轨道力度乘以 {volume_scale:.3g}。": (
        "書き出し時にこのトラックのベロシティを{volume_scale:.3g}倍します。"
    ),
    "FX type {articulation} 不属于当前乐器。": (
        "FX type {articulation}はこの楽器では使用できません。"
    ),
    "导出会把此轨道全部音符设为 FX type {articulation}。": (
        "書き出し時にこのトラックの全ノートをFX type {articulation}に設定します。"
    ),
    "该乐器当前只有样本键位证据，完整音域仍待游戏验证。": (
        "この楽器には現在サンプルキーの証拠しかありません。"
        "完全な音域はゲーム内での検証が必要です。"
    ),
    "导出会把 {track_count} 条轨道按乐器 0x{instrument_id:02X} 合并：{track_names}。": (
        "書き出し時に楽器0x{instrument_id:02X}の{track_count}トラックを"
        "結合します：{track_names}。"
    ),
    "同一游戏乐器的 {track_count} 条轨道使用了不同音量；游戏只保存一个乐器音量，请先统一。": (
        "同じゲーム内楽器の{track_count}トラックで音量が異なります。"
        "ゲームには楽器ごとに1つの音量しか保存されないため、先に統一してください。"
    ),
    "同一游戏乐器的 {track_count} 条轨道使用了不同效果发送量；游戏只保存一组发送量，请先统一。": (
        "同じゲーム内楽器の{track_count}トラックでエフェクトセンド量が異なります。"
        "ゲームには1組のセンド量しか保存されないため、先に統一してください。"
    ),
    "乐器 0x{instrument_id:02X} 合并后有 {count} 个音符，超过已验证上限 {limit}。": (
        "楽器0x{instrument_id:02X}は結合後に{count}個のノートがあり、"
        "検証済み上限{limit}を超えています。"
    ),
    "乐器 0x{instrument_id:02X} 合并后有 {count} 个音符，超过工具保守审阅阈值 {limit}；"
    "导出器不会因此截断，但游戏实际 noteCount 由账号能力运行时下发，请在游戏内确认。": (
        "楽器0x{instrument_id:02X}は結合後に{count}個のノートがあり、ツールの"
        "保守的な確認しきい値{limit}を超えています。書き出し処理はこれを理由に"
        "切り捨てませんが、ゲームの実際のnoteCountはアカウント能力に応じて実行時に"
        "渡されます。ゲーム内で確認してください。"
    ),
    "导出会使用 {velocity_mode} 力度处理模式修改活动音符。": (
        "書き出し時に{velocity_mode}ベロシティ処理モードで有効なノートを変更します。"
    ),
    "导出会写入全局效果：reverb={reverb}, delay={delay}, chorus={chorus}。": (
        "書き出し時にグローバルエフェクトを設定します："
        "reverb={reverb}, delay={delay}, chorus={chorus}。"
    ),
    "主效果包含无效的 v9 字节。": (
        "マスターエフェクトに無効なv9バイトが含まれています。"
    ),
    "主效果含超过当前游戏编辑范围 0–100 的导入值；未编辑项会原样保留。": (
        "マスターエフェクトに現在のゲーム内編集範囲0～100を超える読み込み値が"
        "あります。未編集の値はそのまま保持します。"
    ),
    "需处理": "対応が必要",
    "需人工确认": "手動確認が必要",
    "变化说明": "変更内容",
    "轨道 {track_id}": "トラック {track_id}",
    "全局": "グローバル",
    "{count} 个音符": "{count}ノート",
    "已验证": "検証済み",
    "推断": "推定",
    "近似": "近似",
    "  证据（{status}）：{evidence}": "  証拠（{status}）：{evidence}",
    "谱面结构与音符一致（时间容差 {tolerance:g} ms）。": (
        "楽譜構造とノートは一致しています（時刻許容差{tolerance:g} ms）。"
    ),
    "发现 {count} 项差异：": "{count}件の差異が見つかりました：",
    "- {path}: {message} ({expected!r} -> {actual!r})": (
        "- {path}: {message}（{expected!r} -> {actual!r}）"
    ),
    "时间差超过 {tolerance:g} ms": "時刻差が{tolerance:g} msを超えています",
    "字段不同": "フィールドが異なります",
    "私有字段不同": "プライベートフィールドが異なります",
    "轨道数量不同": "トラック数が異なります",
    "乐器轨道顺序不同": "楽器トラックの順序が異なります",
    "轨道缺失": "トラックがありません",
    "轨道字段不同": "トラックフィールドが異なります",
    "音符数量不同": "ノート数が異なります",
    "音符字段不同": "ノートフィールドが異なります",
})

KO.update({
    "当前轨道因 Mute/Solo 状态不参与导出。": (
        "현재 트랙은 Mute/Solo 상태로 인해 내보내기 대상에서 제외됩니다."
    ),
    "轨道游戏音量不是有效的 v9 字节。": (
        "트랙의 게임 내 음량이 유효한 v9 바이트가 아닙니다."
    ),
    "轨道音量 {volume} 超过当前游戏编辑范围 0–100；未编辑时会原样保留。": (
        "트랙 음량 {volume}이(가) 현재 게임 내 편집 범위 0~100을 벗어납니다. "
        "편집하지 않으면 가져온 값을 그대로 유지합니다."
    ),
    "轨道效果设置不是有效的 8 字节 v9 数据。": (
        "트랙 이펙트 설정이 유효한 8바이트 v9 데이터가 아닙니다."
    ),
    "轨道效果发送量含超过当前游戏编辑范围 0–100 的导入值；未编辑项会原样保留。": (
        "트랙 이펙트 센드에 현재 게임 내 편집 범위 0~100을 벗어난 가져오기 값이 "
        "있습니다. 편집하지 않은 값은 그대로 유지합니다."
    ),
    "未知 BDO 乐器 ID 0x{instrument_id:02X}。": (
        "알 수 없는 BDO 악기 ID 0x{instrument_id:02X}입니다."
    ),
    "{count} 个 GM 打击乐音符没有 BDO 映射：{pitches}。": (
        "BDO 매핑이 없는 GM 타악기 노트가 {count}개 있습니다: {pitches}."
    ),
    "导出会把 {count} 个 GM 打击乐音符转换为 BDO 48–64 / ntype 99。": (
        "내보낼 때 GM 타악기 노트 {count}개를 BDO 48~64 / ntype 99로 변환합니다."
    ),
    "独立打击乐没有完整 GM 逐音映射，当前结果需要游戏内确认。": (
        "이 타악기에는 완전한 GM 음별 매핑이 없습니다. 결과를 게임에서 확인하세요."
    ),
    "{count} 个音符超出 BDO C0–B8 范围，当前导出器会裁剪音高。": (
        "노트 {count}개가 BDO C0~B8 범위를 벗어납니다. "
        "현재 내보내기에서는 음높이를 범위 안으로 제한합니다."
    ),
    "当前乐器缺少经过验证的完整游戏音域。": (
        "이 악기는 검증된 전체 게임 내 음역 정보가 없습니다."
    ),
    "{count} 个音符不在当前乐器的已知游戏音域内。": (
        "노트 {count}개가 이 악기의 알려진 게임 내 음역을 벗어납니다."
    ),
    "导出会将此轨道全部音符移调 {transpose:+d} 半音。": (
        "내보낼 때 이 트랙의 모든 노트를 {transpose:+d}반음 조옮김합니다."
    ),
    "导出会将此轨道音符时值乘以 {duration_scale:.3g}。": (
        "내보낼 때 이 트랙의 노트 길이에 {duration_scale:.3g}을(를) 곱합니다."
    ),
    "导出会将此轨道力度乘以 {volume_scale:.3g}。": (
        "내보낼 때 이 트랙의 벨로시티에 {volume_scale:.3g}을(를) 곱합니다."
    ),
    "FX type {articulation} 不属于当前乐器。": (
        "FX type {articulation}은(는) 이 악기에서 사용할 수 없습니다."
    ),
    "导出会把此轨道全部音符设为 FX type {articulation}。": (
        "내보낼 때 이 트랙의 모든 노트를 FX type {articulation}(으)로 설정합니다."
    ),
    "该乐器当前只有样本键位证据，完整音域仍待游戏验证。": (
        "현재 이 악기는 샘플 키 증거만 있습니다. 전체 음역은 게임 내 검증이 필요합니다."
    ),
    "导出会把 {track_count} 条轨道按乐器 0x{instrument_id:02X} 合并：{track_names}。": (
        "내보낼 때 악기 0x{instrument_id:02X}의 트랙 {track_count}개를 "
        "병합합니다: {track_names}."
    ),
    "同一游戏乐器的 {track_count} 条轨道使用了不同音量；游戏只保存一个乐器音量，请先统一。": (
        "같은 게임 악기의 트랙 {track_count}개가 서로 다른 음량을 사용합니다. "
        "게임에는 악기 음량 하나만 저장되므로 먼저 통일하세요."
    ),
    "同一游戏乐器的 {track_count} 条轨道使用了不同效果发送量；游戏只保存一组发送量，请先统一。": (
        "같은 게임 악기의 트랙 {track_count}개가 서로 다른 이펙트 센드 양을 사용합니다. "
        "게임에는 센드 값 한 세트만 저장되므로 먼저 통일하세요."
    ),
    "乐器 0x{instrument_id:02X} 合并后有 {count} 个音符，超过已验证上限 {limit}。": (
        "악기 0x{instrument_id:02X}은(는) 병합 후 노트가 {count}개이며 "
        "검증된 상한 {limit}을(를) 초과합니다."
    ),
    "乐器 0x{instrument_id:02X} 合并后有 {count} 个音符，超过工具保守审阅阈值 {limit}；"
    "导出器不会因此截断，但游戏实际 noteCount 由账号能力运行时下发，请在游戏内确认。": (
        "악기 0x{instrument_id:02X}은(는) 병합 후 노트가 {count}개이며 도구의 "
        "보수적 검토 임계값 {limit}을(를) 초과합니다. 내보내기 도구는 이를 이유로 "
        "잘라내지 않지만 게임의 실제 noteCount는 계정 능력에 따라 런타임에 제공됩니다. "
        "게임에서 확인하세요."
    ),
    "导出会使用 {velocity_mode} 力度处理模式修改活动音符。": (
        "내보낼 때 {velocity_mode} 벨로시티 처리 모드로 활성 노트를 변경합니다."
    ),
    "导出会写入全局效果：reverb={reverb}, delay={delay}, chorus={chorus}。": (
        "내보낼 때 전역 이펙트를 기록합니다: reverb={reverb}, "
        "delay={delay}, chorus={chorus}."
    ),
    "主效果包含无效的 v9 字节。": (
        "마스터 이펙트에 유효하지 않은 v9 바이트가 포함되어 있습니다."
    ),
    "主效果含超过当前游戏编辑范围 0–100 的导入值；未编辑项会原样保留。": (
        "마스터 이펙트에 현재 게임 내 편집 범위 0~100을 벗어난 가져오기 값이 "
        "있습니다. 편집하지 않은 값은 그대로 유지합니다."
    ),
    "需处理": "조치 필요",
    "需人工确认": "수동 확인 필요",
    "变化说明": "변경 사항",
    "轨道 {track_id}": "트랙 {track_id}",
    "全局": "전역",
    "{count} 个音符": "노트 {count}개",
    "已验证": "검증됨",
    "推断": "추론됨",
    "近似": "근사",
    "  证据（{status}）：{evidence}": "  증거({status}): {evidence}",
    "谱面结构与音符一致（时间容差 {tolerance:g} ms）。": (
        "악보 구조와 노트가 일치합니다(시간 허용 오차 {tolerance:g} ms)."
    ),
    "发现 {count} 项差异：": "차이점 {count}개를 찾았습니다:",
    "- {path}: {message} ({expected!r} -> {actual!r})": (
        "- {path}: {message} ({expected!r} -> {actual!r})"
    ),
    "时间差超过 {tolerance:g} ms": "시간 차이가 {tolerance:g} ms를 초과합니다",
    "字段不同": "필드가 다릅니다",
    "私有字段不同": "비공개 필드가 다릅니다",
    "轨道数量不同": "트랙 수가 다릅니다",
    "乐器轨道顺序不同": "악기 트랙 순서가 다릅니다",
    "轨道缺失": "트랙이 없습니다",
    "轨道字段不同": "트랙 필드가 다릅니다",
    "音符数量不同": "노트 수가 다릅니다",
    "音符字段不同": "노트 필드가 다릅니다",
})

EN.update({
    "\n\n详细错误已写入：{path}": "\n\nDetailed error written to: {path}",
    "  缺失音符索引: {indices}": "  Missing note indexes: {indices}",
    " · 先运行游戏安全预处理": " · Run game-safe preprocessing first",
    "BDO Profile: {profile} · {status}\n时间差比较容差: {tolerance} ms\n\n{report}": (
        "BDO Profile: {profile} · {status}\n"
        "Time-comparison tolerance: {tolerance} ms\n\n{report}"
    ),
    "BDO 乐谱 (*);;所有文件 (*.*)": "BDO Scores (*);;All Files (*.*)",
    "BDO 音源目录不可用：{path}": "BDO sample folder unavailable: {path}",
    "MIDI 文件 (*.mid *.midi);;所有文件 (*.*)": (
        "MIDI Files (*.mid *.midi);;All Files (*.*)"
    ),
    "{instrument} · {count} 音符 · {range}": (
        "{instrument} · {count} notes · {range}"
    ),
    "{summary} · 修改操作 {count}": "{summary} · {count} edit operations",
    "{track}\n{count} 音符 · {range}": "{track}\n{count} notes · {range}",
    "{track} 使用独立打击乐，尚无完整 GM 逐音映射": (
        "{track} uses standalone percussion; a complete per-note GM mapping is "
        "not available"
    ),
    "{track} 使用轨道奏法 type {ntype}": (
        "{track} uses track Musical Technique type {ntype}"
    ),
    "{track} 含无对应游戏音源的键位或力度": (
        "{track} contains keys or velocity layers without a corresponding game sample"
    ),
    "{track} 含音符奏法 type {ntype}": (
        "{track} contains note Musical Technique type {ntype}"
    ),
    "{track} 缺少 {mode} synth WAV": "{track} is missing the {mode} synth WAV",
    "全局移调设为 {transpose:+d}": "Global transpose set to {transpose:+d}",
    "分析失败：{message}": "Analysis failed: {message}",
    "分析完成": "Analysis complete",
    "单轨优化完成 · 当前草稿 {count} 音符 · 点击应用或确定后写回": (
        "Track optimization complete · Current draft: {count} notes · "
        "Click Apply or OK to commit"
    ),
    "回读音符数 {actual} 与导出摘要 {expected} 不一致": (
        "Read-back note count {actual} does not match export summary {expected}"
    ),
    "基准：{first}\n对比：{second}": "Baseline: {first}\nComparison: {second}",
    "存在未绑定已命名游戏 BNK 的乐器": (
        "Some instruments are not bound to a named game BNK"
    ),
    "存在未绑定游戏 BNK 的乐器": "Some instruments are not bound to a game BNK",
    "尚未读取有效 Owner ID。请在设置中选择一份游戏内保存的曲谱，否则导出文件无法在游戏内正常编辑。": (
        "No valid Score Owner ID has been loaded. In Settings, choose a score saved "
        "in game; otherwise the exported file cannot be edited correctly in game."
    ),
    "工程文件 (project.json);;JSON 文件 (*.json);;所有文件 (*.*)": (
        "Project Files (project.json);;JSON Files (*.json);;All Files (*.*)"
    ),
    "已修复：": "Repaired:",
    "当前 MIDI 拍号分母为 /{denominator}，但 BDO v9 曲谱只保存 /4 拍号。请先在 MIDI 软件中转换为等价的 /4 拍号后再导出，程序不会静默写入错误拍号。": (
        "The current MIDI time-signature denominator is /{denominator}, but BDO v9 "
        "scores only store /4 meters. Convert it to an equivalent /4 meter in your "
        "MIDI software before exporting; the app will not silently write an "
        "incorrect meter."
    ),
    "当前工程的 Wwise 键位/力度层映射覆盖（不代表 DSP 已通过游戏 A/B）：": (
        "Current-project Wwise key/velocity-layer mapping coverage "
        "(this does not mean DSP has passed an in-game A/B test):"
    ),
    "当前工程缺少可用的实时游戏音源：\n- ": (
        "The current project is missing usable real-time game samples:\n- "
    ),
    "当前轨道缺少可用的实时游戏音源：": (
        "The current track is missing usable real-time game samples:"
    ),
    "当前输入没有需要应用的修改。": "The current input has no changes to apply.",
    "打开自动保存工程": "Open Autosave Project",
    "文件无法读取；请使用游戏内保存的曲谱。": (
        "The file cannot be read; use a score saved in game."
    ),
    "无法读取工程文件：{error}": "Unable to read project file: {error}",
    "无法读取游戏采样映射：{error}": "Unable to read game sample mapping: {error}",
    "曲谱名包含 Windows 文件名非法字符，请去掉 <>:\"/\\|?*": (
        "The score name contains invalid Windows filename characters; remove "
        "<>:\"/\\|?*"
    ),
    "未知奏法 type {ntype}": "Unknown Musical Technique type {ntype}",
    "未知轨道": "Unknown track",
    "未知错误": "Unknown error",
    "未读取到有效 Owner ID，请选择游戏内保存的曲谱。": (
        "No valid Score Owner ID was found. Choose a score saved in game."
    ),
    "检查发现 {count} 项需要确认的近似结果或预期变化。\n这些项目已在转换检查中列出。确认继续导出吗？": (
        "The check found {count} approximate results or expected changes that need "
        "confirmation.\nThey are listed in Export Check. Continue exporting?"
    ),
    "没有可导出的轨道，请取消静音或 Solo 至少一条轨道": (
        "No tracks are available to export. Unmute or Solo at least one track."
    ),
    "没有可自动修复的项目。未知打击乐、样本音域和需要拆轨的情况仍需人工处理。": (
        "Nothing can be repaired automatically. Unknown percussion, sample ranges, "
        "and cases requiring track splitting still need manual review."
    ),
    "清空 {count} 条无效 FX": "Cleared {count} invalid FX settings",
    "游戏曲谱不包含乐器轨道": "The game score contains no instrument tracks",
    "版本 {version} · 能力：{capabilities} · 作用域：{scopes}": (
        "Version {version} · Capabilities: {capabilities} · Scope: {scopes}"
    ),
    "独奏": "Solo",
    "目标：Track {track_id} · {track}": "Target: Track {track_id} · {track}",
    "确定删除“{track}”及其中的 {count} 个音符吗？\n此操作可通过自动保存工程恢复。": (
        "Delete “{track}” and its {count} notes?\n"
        "This operation can be recovered from an autosaved project."
    ),
    "程序发生错误，日志已写入：\n{path}\n\n{error}": (
        "The app encountered an error. The log was written to:\n{path}\n\n{error}"
    ),
    "算法包：{item}": "Algorithm package: {item}",
    "编辑音符 · {track}": "Edit Notes · {track}",
    "缺少解包后的 BDO Wwise 映射": "Unpacked BDO Wwise mapping is missing",
    "诊断": "Diagnostics",
    "诊断：{item}": "Diagnostic: {item}",
    "请选择有效的 MIDI 文件": "Choose a valid MIDI file",
    "读取失败：{error}": "Read failed: {error}",
    "轨道 · {count}": "Tracks · {count}",
    "轨道效果（混响、延迟或合唱）尚未由离线 Wwise 渲染器复现": (
        "Track effects (reverb, delay, or chorus) are not yet reproduced by the "
        "offline Wwise renderer"
    ),
    "转换检查仍有 {count} 项必须处理的问题。请先打开转换检查定位并修复。": (
        "Export Check still has {count} required fixes. Open Export Check to locate "
        "and resolve them first."
    ),
    "转换设置：力度 {velocity} · 移调 {transpose:+d} · BPM {bpm} · 踏板 {sustain}": (
        "Export settings: Velocity {velocity} · Transpose {transpose:+d} · "
        "BPM {bpm} · Pedal {sustain}"
    ),
    "选择 MIDI 文件": "Choose MIDI File",
    "选择基准 BDO 乐谱": "Choose Baseline BDO Score",
    "选择对比 BDO 乐谱": "Choose Comparison BDO Score",
    "选择游戏内保存的曲谱文件": "Choose a Score Saved in Game",
    "静音": "Mute",
    "黑色沙漠曲谱文件 (*);;所有文件 (*.*)": (
        "Black Desert Score Files (*);;All Files (*.*)"
    ),
    "低置信候选透明度": "Low-confidence candidate opacity",
    "参考背景透明度": "Reference background opacity",
})

JA.update({
    "\n\n详细错误已写入：{path}": "\n\n詳細なエラーを次に書き込みました：{path}",
    "  缺失音符索引: {indices}": "  欠落ノートのインデックス：{indices}",
    " · 先运行游戏安全预处理": " · 先にゲームセーフ前処理を実行",
    "BDO Profile: {profile} · {status}\n时间差比较容差: {tolerance} ms\n\n{report}": (
        "BDOプロファイル：{profile} · {status}\n"
        "時刻差の比較許容値：{tolerance} ms\n\n{report}"
    ),
    "BDO 乐谱 (*);;所有文件 (*.*)": "BDO楽譜 (*);;すべてのファイル (*.*)",
    "BDO 音源目录不可用：{path}": "BDO音源フォルダーを使用できません：{path}",
    "MIDI 文件 (*.mid *.midi);;所有文件 (*.*)": (
        "MIDIファイル (*.mid *.midi);;すべてのファイル (*.*)"
    ),
    "{instrument} · {count} 音符 · {range}": (
        "{instrument} · {count}ノート · {range}"
    ),
    "{summary} · 修改操作 {count}": "{summary} · 変更操作{count}件",
    "{track}\n{count} 音符 · {range}": "{track}\n{count}ノート · {range}",
    "{track} 使用独立打击乐，尚无完整 GM 逐音映射": (
        "{track}は独立パーカッションを使用しています。完全なGMノート別"
        "マッピングはありません"
    ),
    "{track} 使用轨道奏法 type {ntype}": (
        "{track}はトラック奏法type {ntype}を使用しています"
    ),
    "{track} 含无对应游戏音源的键位或力度": (
        "{track}に対応するゲーム音源のないキーまたはベロシティレイヤーがあります"
    ),
    "{track} 含音符奏法 type {ntype}": (
        "{track}にノート奏法type {ntype}があります"
    ),
    "{track} 缺少 {mode} synth WAV": "{track}に{mode} synth WAVがありません",
    "全局移调设为 {transpose:+d}": "全体の移調を{transpose:+d}に設定",
    "分析失败：{message}": "解析に失敗しました：{message}",
    "分析完成": "解析完了",
    "单轨优化完成 · 当前草稿 {count} 音符 · 点击应用或确定后写回": (
        "トラック最適化完了 · 現在の下書きは{count}ノート · "
        "「適用」または「OK」で反映"
    ),
    "回读音符数 {actual} 与导出摘要 {expected} 不一致": (
        "読み戻したノート数{actual}が書き出し概要{expected}と一致しません"
    ),
    "基准：{first}\n对比：{second}": "基準：{first}\n比較：{second}",
    "存在未绑定已命名游戏 BNK 的乐器": (
        "名前付きゲームBNKに関連付けられていない楽器があります"
    ),
    "存在未绑定游戏 BNK 的乐器": "ゲームBNKに関連付けられていない楽器があります",
    "尚未读取有效 Owner ID。请在设置中选择一份游戏内保存的曲谱，否则导出文件无法在游戏内正常编辑。": (
        "有効な楽譜所有者IDが読み込まれていません。設定でゲーム内保存の楽譜を"
        "選択してください。選択しない場合、書き出したファイルをゲーム内で正しく"
        "編集できません。"
    ),
    "工程文件 (project.json);;JSON 文件 (*.json);;所有文件 (*.*)": (
        "プロジェクトファイル (project.json);;JSONファイル (*.json);;"
        "すべてのファイル (*.*)"
    ),
    "已修复：": "修復済み：",
    "当前 MIDI 拍号分母为 /{denominator}，但 BDO v9 曲谱只保存 /4 拍号。请先在 MIDI 软件中转换为等价的 /4 拍号后再导出，程序不会静默写入错误拍号。": (
        "現在のMIDIの拍子分母は/{denominator}ですが、BDO v9楽譜に保存できる拍子は"
        "/4のみです。MIDIソフトで等価な/4拍子に変換してから書き出してください。"
        "誤った拍子を通知せずに書き込むことはありません。"
    ),
    "当前工程的 Wwise 键位/力度层映射覆盖（不代表 DSP 已通过游戏 A/B）：": (
        "現在のプロジェクトのWwiseキー／ベロシティレイヤー対応状況"
        "（DSPのゲーム内A/B検証済みを意味しません）："
    ),
    "当前工程缺少可用的实时游戏音源：\n- ": (
        "現在のプロジェクトに使用可能なリアルタイムゲーム音源がありません：\n- "
    ),
    "当前轨道缺少可用的实时游戏音源：": (
        "現在のトラックに使用可能なリアルタイムゲーム音源がありません："
    ),
    "当前输入没有需要应用的修改。": "現在の入力に適用する変更はありません。",
    "打开自动保存工程": "自動保存プロジェクトを開く",
    "文件无法读取；请使用游戏内保存的曲谱。": (
        "ファイルを読み取れません。ゲーム内で保存した楽譜を使用してください。"
    ),
    "无法读取工程文件：{error}": "プロジェクトファイルを読み取れません：{error}",
    "无法读取游戏采样映射：{error}": "ゲームサンプルマッピングを読み取れません：{error}",
    "曲谱名包含 Windows 文件名非法字符，请去掉 <>:\"/\\|?*": (
        "楽譜名にWindowsのファイル名で使用できない文字があります。"
        "<>:\"/\\|?*を削除してください"
    ),
    "未知奏法 type {ntype}": "不明な奏法type {ntype}",
    "未知轨道": "不明なトラック",
    "未知错误": "不明なエラー",
    "未读取到有效 Owner ID，请选择游戏内保存的曲谱。": (
        "有効な楽譜所有者IDを読み取れませんでした。ゲーム内で保存した楽譜を"
        "選択してください。"
    ),
    "检查发现 {count} 项需要确认的近似结果或预期变化。\n这些项目已在转换检查中列出。确认继续导出吗？": (
        "確認が必要な近似結果または予定される変更が{count}件あります。\n"
        "「書き出しチェック」に一覧表示されています。書き出しを続行しますか？"
    ),
    "没有可导出的轨道，请取消静音或 Solo 至少一条轨道": (
        "書き出せるトラックがありません。少なくとも1トラックのミュートを解除するか"
        "Soloにしてください"
    ),
    "没有可自动修复的项目。未知打击乐、样本音域和需要拆轨的情况仍需人工处理。": (
        "自動修復できる項目はありません。不明なパーカッション、サンプル音域、"
        "トラック分割が必要なケースは手動で対応してください。"
    ),
    "清空 {count} 条无效 FX": "無効なFX設定を{count}件クリア",
    "游戏曲谱不包含乐器轨道": "ゲーム楽譜に楽器トラックがありません",
    "版本 {version} · 能力：{capabilities} · 作用域：{scopes}": (
        "バージョン{version} · 機能：{capabilities} · 対象範囲：{scopes}"
    ),
    "独奏": "Solo",
    "目标：Track {track_id} · {track}": "対象：Track {track_id} · {track}",
    "确定删除“{track}”及其中的 {count} 个音符吗？\n此操作可通过自动保存工程恢复。": (
        "「{track}」とその{count}ノートを削除しますか？\n"
        "この操作は自動保存プロジェクトから復元できます。"
    ),
    "程序发生错误，日志已写入：\n{path}\n\n{error}": (
        "アプリでエラーが発生しました。ログの保存先：\n{path}\n\n{error}"
    ),
    "算法包：{item}": "アルゴリズムパッケージ：{item}",
    "编辑音符 · {track}": "ノート編集 · {track}",
    "缺少解包后的 BDO Wwise 映射": "展開済みBDO Wwiseマッピングがありません",
    "诊断": "診断",
    "诊断：{item}": "診断：{item}",
    "请选择有效的 MIDI 文件": "有効なMIDIファイルを選択してください",
    "读取失败：{error}": "読み込みに失敗しました：{error}",
    "轨道 · {count}": "トラック · {count}",
    "轨道效果（混响、延迟或合唱）尚未由离线 Wwise 渲染器复现": (
        "トラックエフェクト（リバーブ、ディレイ、コーラス）はオフラインWwise"
        "レンダラーでまだ再現されていません"
    ),
    "转换检查仍有 {count} 项必须处理的问题。请先打开转换检查定位并修复。": (
        "書き出しチェックに対応必須の問題が{count}件残っています。"
        "先に書き出しチェックを開いて修正してください。"
    ),
    "转换设置：力度 {velocity} · 移调 {transpose:+d} · BPM {bpm} · 踏板 {sustain}": (
        "書き出し設定：強度{velocity} · 移調{transpose:+d} · "
        "BPM {bpm} · ペダル{sustain}"
    ),
    "选择 MIDI 文件": "MIDIファイルを選択",
    "选择基准 BDO 乐谱": "基準BDO楽譜を選択",
    "选择对比 BDO 乐谱": "比較BDO楽譜を選択",
    "选择游戏内保存的曲谱文件": "ゲーム内で保存した楽譜を選択",
    "静音": "ミュート",
    "黑色沙漠曲谱文件 (*);;所有文件 (*.*)": (
        "黒い砂漠の楽譜ファイル (*);;すべてのファイル (*.*)"
    ),
    "低置信候选透明度": "低信頼候補の不透明度",
    "参考背景透明度": "参照背景の不透明度",
})

KO.update({
    "\n\n详细错误已写入：{path}": "\n\n자세한 오류를 다음 위치에 기록했습니다: {path}",
    "  缺失音符索引: {indices}": "  누락된 노트 인덱스: {indices}",
    " · 先运行游戏安全预处理": " · 먼저 게임 안전 전처리 실행",
    "BDO Profile: {profile} · {status}\n时间差比较容差: {tolerance} ms\n\n{report}": (
        "BDO 프로필: {profile} · {status}\n"
        "시간 차이 비교 허용값: {tolerance} ms\n\n{report}"
    ),
    "BDO 乐谱 (*);;所有文件 (*.*)": "BDO 악보 (*);;모든 파일 (*.*)",
    "BDO 音源目录不可用：{path}": "BDO 음원 폴더를 사용할 수 없습니다: {path}",
    "MIDI 文件 (*.mid *.midi);;所有文件 (*.*)": (
        "MIDI 파일 (*.mid *.midi);;모든 파일 (*.*)"
    ),
    "{instrument} · {count} 音符 · {range}": (
        "{instrument} · 노트 {count}개 · {range}"
    ),
    "{summary} · 修改操作 {count}": "{summary} · 수정 작업 {count}개",
    "{track}\n{count} 音符 · {range}": "{track}\n노트 {count}개 · {range}",
    "{track} 使用独立打击乐，尚无完整 GM 逐音映射": (
        "{track}은(는) 독립 타악기를 사용하며 완전한 GM 음별 매핑이 없습니다"
    ),
    "{track} 使用轨道奏法 type {ntype}": (
        "{track}은(는) 트랙 주법 type {ntype}을(를) 사용합니다"
    ),
    "{track} 含无对应游戏音源的键位或力度": (
        "{track}에 대응하는 게임 음원이 없는 키 또는 벨로시티 레이어가 있습니다"
    ),
    "{track} 含音符奏法 type {ntype}": (
        "{track}에 노트 주법 type {ntype}이(가) 있습니다"
    ),
    "{track} 缺少 {mode} synth WAV": "{track}에 {mode} synth WAV가 없습니다",
    "全局移调设为 {transpose:+d}": "전체 조옮김을 {transpose:+d}(으)로 설정",
    "分析失败：{message}": "분석 실패: {message}",
    "分析完成": "분석 완료",
    "单轨优化完成 · 当前草稿 {count} 音符 · 点击应用或确定后写回": (
        "트랙 최적화 완료 · 현재 초안 노트 {count}개 · 적용 또는 확인을 눌러 반영"
    ),
    "回读音符数 {actual} 与导出摘要 {expected} 不一致": (
        "다시 읽은 노트 수 {actual}이(가) 내보내기 요약 {expected}과(와) 다릅니다"
    ),
    "基准：{first}\n对比：{second}": "기준: {first}\n비교: {second}",
    "存在未绑定已命名游戏 BNK 的乐器": (
        "이름이 있는 게임 BNK에 연결되지 않은 악기가 있습니다"
    ),
    "存在未绑定游戏 BNK 的乐器": "게임 BNK에 연결되지 않은 악기가 있습니다",
    "尚未读取有效 Owner ID。请在设置中选择一份游戏内保存的曲谱，否则导出文件无法在游戏内正常编辑。": (
        "유효한 악보 소유자 ID를 읽지 않았습니다. 설정에서 게임에 저장된 악보를 "
        "선택하세요. 선택하지 않으면 내보낸 파일을 게임에서 정상적으로 편집할 수 없습니다."
    ),
    "工程文件 (project.json);;JSON 文件 (*.json);;所有文件 (*.*)": (
        "프로젝트 파일 (project.json);;JSON 파일 (*.json);;모든 파일 (*.*)"
    ),
    "已修复：": "복구됨:",
    "当前 MIDI 拍号分母为 /{denominator}，但 BDO v9 曲谱只保存 /4 拍号。请先在 MIDI 软件中转换为等价的 /4 拍号后再导出，程序不会静默写入错误拍号。": (
        "현재 MIDI 박자표 분모는 /{denominator}이지만 BDO v9 악보에는 /4 박자표만 "
        "저장됩니다. MIDI 프로그램에서 같은 의미의 /4 박자표로 변환한 뒤 내보내세요. "
        "프로그램은 잘못된 박자표를 알림 없이 기록하지 않습니다."
    ),
    "当前工程的 Wwise 键位/力度层映射覆盖（不代表 DSP 已通过游戏 A/B）：": (
        "현재 프로젝트의 Wwise 키/벨로시티 레이어 매핑 범위"
        "(DSP가 게임 A/B 검증을 통과했다는 뜻은 아닙니다):"
    ),
    "当前工程缺少可用的实时游戏音源：\n- ": (
        "현재 프로젝트에 사용할 수 있는 실시간 게임 음원이 없습니다:\n- "
    ),
    "当前轨道缺少可用的实时游戏音源：": (
        "현재 트랙에 사용할 수 있는 실시간 게임 음원이 없습니다:"
    ),
    "当前输入没有需要应用的修改。": "현재 입력에 적용할 변경 사항이 없습니다.",
    "打开自动保存工程": "자동 저장 프로젝트 열기",
    "文件无法读取；请使用游戏内保存的曲谱。": (
        "파일을 읽을 수 없습니다. 게임에 저장된 악보를 사용하세요."
    ),
    "无法读取工程文件：{error}": "프로젝트 파일을 읽을 수 없습니다: {error}",
    "无法读取游戏采样映射：{error}": "게임 샘플 매핑을 읽을 수 없습니다: {error}",
    "曲谱名包含 Windows 文件名非法字符，请去掉 <>:\"/\\|?*": (
        "악보 이름에 Windows 파일명으로 사용할 수 없는 문자가 있습니다. "
        "<>:\"/\\|?* 문자를 제거하세요"
    ),
    "未知奏法 type {ntype}": "알 수 없는 주법 type {ntype}",
    "未知轨道": "알 수 없는 트랙",
    "未知错误": "알 수 없는 오류",
    "未读取到有效 Owner ID，请选择游戏内保存的曲谱。": (
        "유효한 악보 소유자 ID를 읽지 못했습니다. 게임에 저장된 악보를 선택하세요."
    ),
    "检查发现 {count} 项需要确认的近似结果或预期变化。\n这些项目已在转换检查中列出。确认继续导出吗？": (
        "확인이 필요한 근사 결과 또는 예상 변경 사항이 {count}개 있습니다.\n"
        "내보내기 검사에 표시되어 있습니다. 계속 내보내시겠습니까?"
    ),
    "没有可导出的轨道，请取消静音或 Solo 至少一条轨道": (
        "내보낼 트랙이 없습니다. 트랙을 하나 이상 음소거 해제하거나 Solo로 설정하세요"
    ),
    "没有可自动修复的项目。未知打击乐、样本音域和需要拆轨的情况仍需人工处理。": (
        "자동으로 복구할 항목이 없습니다. 알 수 없는 타악기, 샘플 음역, 트랙 분리가 "
        "필요한 경우는 수동으로 처리해야 합니다."
    ),
    "清空 {count} 条无效 FX": "유효하지 않은 FX 설정 {count}개 지움",
    "游戏曲谱不包含乐器轨道": "게임 악보에 악기 트랙이 없습니다",
    "版本 {version} · 能力：{capabilities} · 作用域：{scopes}": (
        "버전 {version} · 기능: {capabilities} · 범위: {scopes}"
    ),
    "独奏": "Solo",
    "目标：Track {track_id} · {track}": "대상: Track {track_id} · {track}",
    "确定删除“{track}”及其中的 {count} 个音符吗？\n此操作可通过自动保存工程恢复。": (
        "‘{track}’ 및 노트 {count}개를 삭제하시겠습니까?\n"
        "이 작업은 자동 저장 프로젝트에서 복구할 수 있습니다."
    ),
    "程序发生错误，日志已写入：\n{path}\n\n{error}": (
        "프로그램에 오류가 발생했습니다. 로그 기록 위치:\n{path}\n\n{error}"
    ),
    "算法包：{item}": "알고리즘 패키지: {item}",
    "编辑音符 · {track}": "노트 편집 · {track}",
    "缺少解包后的 BDO Wwise 映射": "압축을 푼 BDO Wwise 매핑이 없습니다",
    "诊断": "진단",
    "诊断：{item}": "진단: {item}",
    "请选择有效的 MIDI 文件": "유효한 MIDI 파일을 선택하세요",
    "读取失败：{error}": "읽기 실패: {error}",
    "轨道 · {count}": "트랙 · {count}",
    "轨道效果（混响、延迟或合唱）尚未由离线 Wwise 渲染器复现": (
        "트랙 이펙트(리버브, 딜레이 또는 코러스)는 오프라인 Wwise 렌더러에서 아직 "
        "재현되지 않습니다"
    ),
    "转换检查仍有 {count} 项必须处理的问题。请先打开转换检查定位并修复。": (
        "내보내기 검사에 반드시 처리해야 할 문제가 {count}개 남아 있습니다. "
        "먼저 내보내기 검사를 열어 찾아서 수정하세요."
    ),
    "转换设置：力度 {velocity} · 移调 {transpose:+d} · BPM {bpm} · 踏板 {sustain}": (
        "내보내기 설정: 세기 {velocity} · 조옮김 {transpose:+d} · "
        "BPM {bpm} · 페달 {sustain}"
    ),
    "选择 MIDI 文件": "MIDI 파일 선택",
    "选择基准 BDO 乐谱": "기준 BDO 악보 선택",
    "选择对比 BDO 乐谱": "비교 BDO 악보 선택",
    "选择游戏内保存的曲谱文件": "게임에 저장된 악보 파일 선택",
    "静音": "음소거",
    "黑色沙漠曲谱文件 (*);;所有文件 (*.*)": (
        "검은사막 악보 파일 (*);;모든 파일 (*.*)"
    ),
    "低置信候选透明度": "낮은 신뢰도 후보 불투명도",
    "参考背景透明度": "참조 배경 불투명도",
})

EN.update({
    "新建轨道 {number} · {instrument}": "New Track {number} · {instrument}",
    "{count} 轨 · BPM {bpm} · {meter}/4": "{count} tracks · BPM {bpm} · {meter}/4",
    "未指定奏法，导出时保留普通音符。": (
        "No Musical Technique selected; export keeps normal notes."
    ),
})

EN.update({
    "奏法 {articulations} 处 · 轻微自然化 {humanized} 个音符": (
        "Musical Techniques: {articulations} · Light humanization: {humanized} notes"
    ),
    "效果：混响 {reverb_before}→{reverb_after} · 延迟 {delay_before}→{delay_after} · "
    "合唱 {chorus_before}→{chorus_after}": (
        "Effects: Reverb {reverb_before}→{reverb_after} · Delay "
        "{delay_before}→{delay_after} · Chorus {chorus_before}→{chorus_after}"
    ),
    "注意：{message}": "Notice: {message}",
    "MIDI 优化报告": "MIDI Optimization Report",
    "总计：去重 {removed}，修重叠 {trimmed}，量化 {quantized}，力度润色 {velocity}，"
    "奏法 {articulations}，新增/拆分音 {added}": (
        "Totals: deduplicated {removed}, overlap fixes {trimmed}, quantized "
        "{quantized}, velocity edits {velocity}, Musical Techniques "
        "{articulations}, added/split notes {added}"
    ),
    "{key_root} {key_mode} {confidence}": "{key_root} {key_mode} {confidence}",
    "全曲上下文：{tonal} · 风格 {styles}": (
        "Song context: {tonal} · Style {styles}"
    ),
    "大调": "major",
    "小调": "minor",
    "调性不稳定": "Unstable tonality",
    "歌词：{tokens} 个音节/文本单元 · {alignments} 个对齐 · {mode} · 置信度 {confidence}": (
        "Lyrics: {tokens} syllable/text units · {alignments} alignments · {mode} · "
        "Confidence {confidence}"
    ),
    "连贯": "Legato",
    "歌词与主旋律起点偏差较大": "Lyrics start far from the lead melody",
    "仅作为建议，不自动改写音高": "suggestion only; pitches are not rewritten",
    "游戏安全自然化：{count} 个音符": "Game-safe humanization: {count} notes",
    "游戏效果：Reverb {reverb_before}->{reverb_after} · Delay {delay_before}->{delay_after} · "
    "Chorus {chorus_before}->{chorus_after} · 置信度 {confidence}": (
        "In-game effects: Reverb {reverb_before}->{reverb_after} · Delay "
        "{delay_before}->{delay_after} · Chorus {chorus_before}->{chorus_after} · "
        "Confidence {confidence}"
    ),
    "管弦配置使用适度空间感": "Use moderate space for orchestral instrumentation",
    "工程没有可分析音符": "The project has no notes to analyze",
    "声音效果优化已关闭": "Sound-effect optimization is disabled",
    "  - 配器建议：{message}": "  - Instrumentation: {message}",
    "{track_name} 与主旋律同节奏、同音区竞争；建议降低活动密度或错开起音": (
        "{track_name} competes with the lead melody in rhythm and register; reduce "
        "activity or offset note onsets"
    ),
    "仅建议奏法 {count}（未写入工程）": (
        "Suggested Musical Techniques: {count} (not written to the project)"
    ),
    "已优化": "Optimized",
    "无变化": "No changes",
    "修改": "Modified",
    "只读上下文": "Read-only context",
    "自动编曲新增": "Added by arrangement",
    "[{status}/{scope}] Track {track_id}: {track_name} · {before_notes}->{after_notes} notes": (
        "[{status}/{scope}] Track {track_id}: {track_name} · "
        "{before_notes}->{after_notes} notes"
    ),
    "副旋律": "Secondary Melody",
    "装饰声部": "Ornament",
    "音效": "FX",
    "旋律": "Melody",
    "和弦": "Chord",
    "低音动机": "Bass Riff",
    "  角色：{role}": "  Role: {role}",
    "  去重 {duplicates} · 重叠 {overlaps} · 短音 {short_notes} · 量化 {quantized} · "
    "力度 {velocities} · 奏法 {articulations}": (
        "  Duplicates {duplicates} · Overlaps {overlaps} · Short notes {short_notes} · "
        "Quantized {quantized} · Velocity {velocities} · Musical Techniques {articulations}"
    ),
    "  奏法分布：{counts}": "  Musical Technique distribution: {counts}",
    "  仅建议 {suggestions} · 跳过候选 {skipped}": (
        "  Suggestions {suggestions} · Skipped candidates {skipped}"
    ),
    "已加入预览": "Added to preview",
    "仅建议": "Suggestion only",
    "已验证映射": "Verified mapping",
    "长音含半音邻音往返": "A held note alternates with a semitone neighbor",
    "句尾保守降级": "Conservatively reduced at phrase end",
    "非和弦音降级": "Reduced for a non-chord tone",
    "强拍": "Strong beat",
    "弱拍": "Weak beat",
    "{mode} 调性": "{mode} key",
    "  - [{state}] {technique} · {confidence} · {evidence} · {reason}{theory}": (
        "  - [{state}] {technique} · {confidence} · {evidence} · {reason}{theory}"
    ),
    "乐理分析：{key_root} {key_mode} 调性置信度 {confidence}": (
        "Music theory: {key_root} {key_mode}, confidence {confidence}"
    ),
    "{count} 个音超出目标乐器的游戏/采样键位，未自动夹音": (
        "{count} notes are outside the target instrument's in-game/sample keys; "
        "pitches were not clamped"
    ),
    "检测到同拍多奏法": "Multiple Musical Techniques detected at one onset",
    "保留人工内容并要求导出前确认": (
        "manual content is preserved and requires confirmation before export"
    ),
    "  - 配器：{issue}": "  - Instrumentation: {issue}",
    "BDO 原生": "Native BDO",
    "MIDI 近似": "MIDI approximation",
    "揉弦/气息颤音": "Vibrato",
    "Pitch Bend 曲线反复换向": "The Pitch Bend curve repeatedly changes direction",
    "  - 技法 {technique} · {confidence} · {state} · {reason}": (
        "  - Technique {technique} · {confidence} · {state} · {reason}"
    ),
    "Track {track_id}（{role}）整体移调 {shift:+d} 半音，减少与主旋律的音区遮蔽": (
        "Track {track_id} ({role}) transposed {shift:+d} semitones to reduce register "
        "masking with the lead melody"
    ),
    "[编配] {change}": "[Arrangement] {change}",
    "输入已有 {count} 个音符超出当前乐器映射；优化仅保留，不会新增，请在转换检查中处理。": (
        "The input already has {count} notes outside the current instrument mapping. "
        "Optimization preserves but does not add them; resolve them in Conversion Check."
    ),
    "输入已有 {count} 个鼓音尚未规范为 BDO 48–64/type 99；优化仅保留，请在转换检查中处理。": (
        "The input already has {count} drum notes not normalized to BDO 48–64/type 99. "
        "Optimization preserves them; resolve them in Conversion Check."
    ),
    "输入已有 {count} 个未验证奏法；优化会保护人工值，不会复制或新增。": (
        "The input already has {count} unverified Musical Techniques. Optimization "
        "protects manual values and will not copy or add them."
    ),
    "歌词与主旋律起点偏差较大；仅作为建议，不自动改写音高": (
        "Lyrics start far from the lead melody; suggestion only, pitches are not rewritten"
    ),
    "检测到同拍多奏法；保留人工内容并要求导出前确认": (
        "Multiple Musical Techniques detected at one onset; manual content is preserved "
        "and requires confirmation before export"
    ),
    "{track_name} · 自动八度加倍": "{track_name} · Automatic octave doubling",
})

JA.update({
    "新建轨道 {number} · {instrument}": "新規トラック {number} · {instrument}",
    "{count} 轨 · BPM {bpm} · {meter}/4": "{count}トラック · BPM {bpm} · {meter}/4",
    "未指定奏法，导出时保留普通音符。": (
        "奏法未指定のため、通常ノートのまま書き出します。"
    ),
})

JA.update({
    "奏法 {articulations} 处 · 轻微自然化 {humanized} 个音符": (
        "奏法{articulations}か所 · 軽いヒューマナイズ{humanized}ノート"
    ),
    "效果：混响 {reverb_before}→{reverb_after} · 延迟 {delay_before}→{delay_after} · "
    "合唱 {chorus_before}→{chorus_after}": (
        "エフェクト：リバーブ{reverb_before}→{reverb_after} · ディレイ"
        "{delay_before}→{delay_after} · コーラス{chorus_before}→{chorus_after}"
    ),
    "注意：{message}": "注意：{message}",
    "MIDI 优化报告": "MIDI最適化レポート",
    "总计：去重 {removed}，修重叠 {trimmed}，量化 {quantized}，力度润色 {velocity}，"
    "奏法 {articulations}，新增/拆分音 {added}": (
        "合計：重複削除{removed}、重なり修正{trimmed}、クオンタイズ{quantized}、"
        "ベロシティ調整{velocity}、奏法{articulations}、追加／分割ノート{added}"
    ),
    "{key_root} {key_mode} {confidence}": "{key_root} {key_mode} {confidence}",
    "全曲上下文：{tonal} · 风格 {styles}": (
        "全曲コンテキスト：{tonal} · スタイル{styles}"
    ),
    "大调": "メジャー",
    "小调": "マイナー",
    "调性不稳定": "調性が不安定",
    "歌词：{tokens} 个音节/文本单元 · {alignments} 个对齐 · {mode} · 置信度 {confidence}": (
        "歌詞：{tokens}音節／テキスト単位 · {alignments}件の整列 · {mode} · "
        "信頼度{confidence}"
    ),
    "连贯": "レガート",
    "歌词与主旋律起点偏差较大": "歌詞と主旋律の開始位置が大きくずれています",
    "仅作为建议，不自动改写音高": "提案のみ。音高は自動変更しません",
    "游戏安全自然化：{count} 个音符": "ゲームセーフなヒューマナイズ：{count}ノート",
    "游戏效果：Reverb {reverb_before}->{reverb_after} · Delay {delay_before}->{delay_after} · "
    "Chorus {chorus_before}->{chorus_after} · 置信度 {confidence}": (
        "ゲームエフェクト：Reverb {reverb_before}->{reverb_after} · Delay "
        "{delay_before}->{delay_after} · Chorus {chorus_before}->{chorus_after} · "
        "信頼度{confidence}"
    ),
    "管弦配置使用适度空间感": "オーケストラ編成に適度な空間表現を使用",
    "工程没有可分析音符": "プロジェクトに解析できるノートがありません",
    "声音效果优化已关闭": "サウンドエフェクト最適化は無効です",
    "  - 配器建议：{message}": "  - 編成提案：{message}",
    "{track_name} 与主旋律同节奏、同音区竞争；建议降低活动密度或错开起音": (
        "{track_name}が主旋律と同じリズム／音域で競合しています。"
        "活動密度を下げるか、発音位置をずらしてください"
    ),
    "仅建议奏法 {count}（未写入工程）": (
        "奏法の提案のみ{count}件（プロジェクトには未反映）"
    ),
    "已优化": "最適化済み",
    "无变化": "変更なし",
    "修改": "変更",
    "只读上下文": "読み取り専用コンテキスト",
    "自动编曲新增": "自動編曲で追加",
    "[{status}/{scope}] Track {track_id}: {track_name} · {before_notes}->{after_notes} notes": (
        "[{status}/{scope}] Track {track_id}: {track_name} · "
        "{before_notes}->{after_notes}ノート"
    ),
    "副旋律": "サブメロディ",
    "装饰声部": "装飾声部",
    "音效": "FX",
    "旋律": "メロディ",
    "和弦": "コード",
    "低音动机": "ベースリフ",
    "  角色：{role}": "  役割：{role}",
    "  去重 {duplicates} · 重叠 {overlaps} · 短音 {short_notes} · 量化 {quantized} · "
    "力度 {velocities} · 奏法 {articulations}": (
        "  重複{duplicates} · 重なり{overlaps} · 短音{short_notes} · "
        "クオンタイズ{quantized} · 強度{velocities} · 奏法{articulations}"
    ),
    "  奏法分布：{counts}": "  奏法分布：{counts}",
    "  仅建议 {suggestions} · 跳过候选 {skipped}": (
        "  提案のみ{suggestions} · スキップ候補{skipped}"
    ),
    "已加入预览": "プレビューに追加済み",
    "仅建议": "提案のみ",
    "已验证映射": "検証済みマッピング",
    "长音含半音邻音往返": "ロングトーンが半音隣接音と交互に動いています",
    "句尾保守降级": "フレーズ終端で保守的に抑制",
    "非和弦音降级": "非和声音のため抑制",
    "强拍": "強拍",
    "弱拍": "弱拍",
    "{mode} 调性": "{mode}キー",
    "  - [{state}] {technique} · {confidence} · {evidence} · {reason}{theory}": (
        "  - [{state}] {technique} · {confidence} · {evidence} · {reason}{theory}"
    ),
    "乐理分析：{key_root} {key_mode} 调性置信度 {confidence}": (
        "楽理分析：{key_root} {key_mode}、調性信頼度{confidence}"
    ),
    "{count} 个音超出目标乐器的游戏/采样键位，未自动夹音": (
        "{count}ノートが対象楽器のゲーム／サンプルキー範囲外です。"
        "音高は自動で範囲内に収めていません"
    ),
    "检测到同拍多奏法": "同じ発音位置に複数の奏法を検出",
    "保留人工内容并要求导出前确认": (
        "手動内容を保持し、書き出し前の確認を求めます"
    ),
    "  - 配器：{issue}": "  - 編成：{issue}",
    "BDO 原生": "BDOネイティブ",
    "MIDI 近似": "MIDI近似",
    "揉弦/气息颤音": "ビブラート",
    "Pitch Bend 曲线反复换向": "Pitch Bendカーブが繰り返し方向転換しています",
    "  - 技法 {technique} · {confidence} · {state} · {reason}": (
        "  - 技法{technique} · {confidence} · {state} · {reason}"
    ),
    "Track {track_id}（{role}）整体移调 {shift:+d} 半音，减少与主旋律的音区遮蔽": (
        "Track {track_id}（{role}）を全体で{shift:+d}半音移調し、"
        "主旋律との音域マスキングを低減"
    ),
    "[编配] {change}": "[編曲] {change}",
    "输入已有 {count} 个音符超出当前乐器映射；优化仅保留，不会新增，请在转换检查中处理。": (
        "入力には現在の楽器マッピング外のノートがすでに{count}個あります。"
        "最適化では保持のみを行い、追加しません。書き出しチェックで対応してください。"
    ),
    "输入已有 {count} 个鼓音尚未规范为 BDO 48–64/type 99；优化仅保留，请在转换检查中处理。": (
        "入力にはBDO 48～64/type 99へ正規化されていないドラムノートが"
        "すでに{count}個あります。最適化では保持のみを行います。"
        "書き出しチェックで対応してください。"
    ),
    "输入已有 {count} 个未验证奏法；优化会保护人工值，不会复制或新增。": (
        "入力には未検証の奏法がすでに{count}件あります。最適化は手動値を保護し、"
        "複製や追加は行いません。"
    ),
    "歌词与主旋律起点偏差较大；仅作为建议，不自动改写音高": (
        "歌詞と主旋律の開始位置が大きくずれています。提案のみで、音高は自動変更しません"
    ),
    "检测到同拍多奏法；保留人工内容并要求导出前确认": (
        "同じ発音位置に複数の奏法を検出しました。手動内容を保持し、書き出し前の確認を求めます"
    ),
    "{track_name} · 自动八度加倍": "{track_name} · 自動オクターブ重ね",
})

KO.update({
    "新建轨道 {number} · {instrument}": "새 트랙 {number} · {instrument}",
    "{count} 轨 · BPM {bpm} · {meter}/4": "트랙 {count}개 · BPM {bpm} · {meter}/4",
    "未指定奏法，导出时保留普通音符。": (
        "주법을 지정하지 않아 일반 노트로 내보냅니다."
    ),
})

KO.update({
    "奏法 {articulations} 处 · 轻微自然化 {humanized} 个音符": (
        "주법 {articulations}곳 · 가벼운 휴머나이즈 노트 {humanized}개"
    ),
    "效果：混响 {reverb_before}→{reverb_after} · 延迟 {delay_before}→{delay_after} · "
    "合唱 {chorus_before}→{chorus_after}": (
        "이펙트: 리버브 {reverb_before}→{reverb_after} · 딜레이 "
        "{delay_before}→{delay_after} · 코러스 {chorus_before}→{chorus_after}"
    ),
    "注意：{message}": "알림: {message}",
    "MIDI 优化报告": "MIDI 최적화 보고서",
    "总计：去重 {removed}，修重叠 {trimmed}，量化 {quantized}，力度润色 {velocity}，"
    "奏法 {articulations}，新增/拆分音 {added}": (
        "합계: 중복 제거 {removed}, 겹침 수정 {trimmed}, 퀀타이즈 {quantized}, "
        "벨로시티 조정 {velocity}, 주법 {articulations}, 추가/분할 노트 {added}"
    ),
    "{key_root} {key_mode} {confidence}": "{key_root} {key_mode} {confidence}",
    "全曲上下文：{tonal} · 风格 {styles}": (
        "전체 곡 컨텍스트: {tonal} · 스타일 {styles}"
    ),
    "大调": "장조",
    "小调": "단조",
    "调性不稳定": "조성이 불안정함",
    "歌词：{tokens} 个音节/文本单元 · {alignments} 个对齐 · {mode} · 置信度 {confidence}": (
        "가사: 음절/텍스트 단위 {tokens}개 · 정렬 {alignments}개 · {mode} · "
        "신뢰도 {confidence}"
    ),
    "连贯": "레가토",
    "歌词与主旋律起点偏差较大": "가사와 주선율의 시작 위치 차이가 큽니다",
    "仅作为建议，不自动改写音高": "제안만 제공하며 음높이를 자동으로 바꾸지 않습니다",
    "游戏安全自然化：{count} 个音符": "게임 안전 휴머나이즈: 노트 {count}개",
    "游戏效果：Reverb {reverb_before}->{reverb_after} · Delay {delay_before}->{delay_after} · "
    "Chorus {chorus_before}->{chorus_after} · 置信度 {confidence}": (
        "게임 이펙트: Reverb {reverb_before}->{reverb_after} · Delay "
        "{delay_before}->{delay_after} · Chorus {chorus_before}->{chorus_after} · "
        "신뢰도 {confidence}"
    ),
    "管弦配置使用适度空间感": "관현악 편성에 적당한 공간감을 사용",
    "工程没有可分析音符": "프로젝트에 분석할 노트가 없습니다",
    "声音效果优化已关闭": "사운드 이펙트 최적화가 꺼져 있습니다",
    "  - 配器建议：{message}": "  - 편성 제안: {message}",
    "{track_name} 与主旋律同节奏、同音区竞争；建议降低活动密度或错开起音": (
        "{track_name}이(가) 주선율과 같은 리듬 및 음역에서 경쟁합니다. "
        "활동 밀도를 낮추거나 노트 시작을 엇갈리게 하세요"
    ),
    "仅建议奏法 {count}（未写入工程）": (
        "제안 주법 {count}개(프로젝트에는 기록하지 않음)"
    ),
    "已优化": "최적화됨",
    "无变化": "변경 없음",
    "修改": "수정",
    "只读上下文": "읽기 전용 컨텍스트",
    "自动编曲新增": "자동 편곡으로 추가",
    "[{status}/{scope}] Track {track_id}: {track_name} · {before_notes}->{after_notes} notes": (
        "[{status}/{scope}] Track {track_id}: {track_name} · "
        "노트 {before_notes}->{after_notes}개"
    ),
    "副旋律": "보조 선율",
    "装饰声部": "장식 성부",
    "音效": "FX",
    "旋律": "선율",
    "和弦": "화음",
    "低音动机": "베이스 리프",
    "  角色：{role}": "  역할: {role}",
    "  去重 {duplicates} · 重叠 {overlaps} · 短音 {short_notes} · 量化 {quantized} · "
    "力度 {velocities} · 奏法 {articulations}": (
        "  중복 {duplicates} · 겹침 {overlaps} · 짧은 노트 {short_notes} · "
        "퀀타이즈 {quantized} · 세기 {velocities} · 주법 {articulations}"
    ),
    "  奏法分布：{counts}": "  주법 분포: {counts}",
    "  仅建议 {suggestions} · 跳过候选 {skipped}": (
        "  제안만 {suggestions} · 건너뛴 후보 {skipped}"
    ),
    "已加入预览": "미리보기에 추가됨",
    "仅建议": "제안만",
    "已验证映射": "검증된 매핑",
    "长音含半音邻音往返": "긴 노트가 반음 이웃음과 번갈아 움직입니다",
    "句尾保守降级": "프레이즈 끝에서 보수적으로 낮춤",
    "非和弦音降级": "비화음음이므로 낮춤",
    "强拍": "강박",
    "弱拍": "약박",
    "{mode} 调性": "{mode} 조성",
    "  - [{state}] {technique} · {confidence} · {evidence} · {reason}{theory}": (
        "  - [{state}] {technique} · {confidence} · {evidence} · {reason}{theory}"
    ),
    "乐理分析：{key_root} {key_mode} 调性置信度 {confidence}": (
        "음악 이론 분석: {key_root} {key_mode}, 조성 신뢰도 {confidence}"
    ),
    "{count} 个音超出目标乐器的游戏/采样键位，未自动夹音": (
        "노트 {count}개가 대상 악기의 게임/샘플 키 범위를 벗어납니다. "
        "음높이를 자동으로 제한하지 않았습니다"
    ),
    "检测到同拍多奏法": "같은 시작 위치에 여러 주법이 감지됨",
    "保留人工内容并要求导出前确认": (
        "수동 내용을 유지하며 내보내기 전에 확인해야 합니다"
    ),
    "  - 配器：{issue}": "  - 편성: {issue}",
    "BDO 原生": "BDO 네이티브",
    "MIDI 近似": "MIDI 근사",
    "揉弦/气息颤音": "비브라토",
    "Pitch Bend 曲线反复换向": "Pitch Bend 곡선의 방향이 반복해서 바뀝니다",
    "  - 技法 {technique} · {confidence} · {state} · {reason}": (
        "  - 기법 {technique} · {confidence} · {state} · {reason}"
    ),
    "Track {track_id}（{role}）整体移调 {shift:+d} 半音，减少与主旋律的音区遮蔽": (
        "Track {track_id}({role})을(를) 전체적으로 {shift:+d}반음 조옮김하여 "
        "주선율과의 음역 마스킹을 줄임"
    ),
    "[编配] {change}": "[편곡] {change}",
    "输入已有 {count} 个音符超出当前乐器映射；优化仅保留，不会新增，请在转换检查中处理。": (
        "입력에 현재 악기 매핑을 벗어난 노트가 이미 {count}개 있습니다. "
        "최적화는 유지할 뿐 추가하지 않습니다. 내보내기 검사에서 처리하세요."
    ),
    "输入已有 {count} 个鼓音尚未规范为 BDO 48–64/type 99；优化仅保留，请在转换检查中处理。": (
        "입력에 BDO 48~64/type 99로 정규화되지 않은 드럼 노트가 이미 {count}개 "
        "있습니다. 최적화는 그대로 유지합니다. 내보내기 검사에서 처리하세요."
    ),
    "输入已有 {count} 个未验证奏法；优化会保护人工值，不会复制或新增。": (
        "입력에 검증되지 않은 주법이 이미 {count}개 있습니다. 최적화는 수동 값을 "
        "보호하며 복사하거나 추가하지 않습니다."
    ),
    "歌词与主旋律起点偏差较大；仅作为建议，不自动改写音高": (
        "가사와 주선율의 시작 위치 차이가 큽니다. 제안만 제공하며 음높이를 자동으로 바꾸지 않습니다"
    ),
    "检测到同拍多奏法；保留人工内容并要求导出前确认": (
        "같은 시작 위치에 여러 주법이 감지되었습니다. 수동 내용을 유지하며 내보내기 전에 확인해야 합니다"
    ),
    "{track_name} · 自动八度加倍": "{track_name} · 자동 옥타브 더블링",
})


EN.update({
    "备选：{alternatives}": "Alternatives: {alternatives}",
    "、": ", ",
    "全览": "Fit",
    "轨道 {track_id} · {track}": "Track {track_id} · {track}",
})
JA.update({
    "备选：{alternatives}": "候補：{alternatives}",
    "、": "、",
    "全览": "全体表示",
    "轨道 {track_id} · {track}": "トラック {track_id} · {track}",
})
KO.update({
    "备选：{alternatives}": "대안: {alternatives}",
    "、": ", ",
    "全览": "전체 보기",
    "轨道 {track_id} · {track}": "트랙 {track_id} · {track}",
})


# Built-in optimizer runtime vocabulary. These values may be nested inside a
# report, so each fixed source fragment must be translated independently while
# track names and captured numeric values remain untouched.
_OPTIMIZER_RUNTIME_TRANSLATIONS = {
    "CC11 表情曲线净变化 {delta}": (
        "CC11 expression-curve net change {delta}",
        "CC11エクスプレッションカーブの正味変化{delta}",
        "CC11 익스프레션 곡선 순변화 {delta}",
    ),
    "{count} 个电吉他 FX 音不在 C2-G2 触发区": (
        "{count} electric-guitar FX notes are outside the C2–G2 trigger range",
        "エレキギターFXノート{count}個がC2～G2のトリガー範囲外です",
        "일렉 기타 FX 노트 {count}개가 C2~G2 트리거 범위를 벗어납니다",
    ),
    "一字一音": ("Syllabic", "音節式", "음절식"),
    "一字多音": ("Melismatic", "メリスマ", "멜리스마"),
    "单轨": ("Single Track", "単一トラック", "단일 트랙"),
    "三吐": ("Triple Tonguing", "トリプルタンギング", "트리플 텅잉"),
    "上弓": ("Up Bow", "上げ弓", "올림활"),
    "上扫弦": ("Upstroke Strum", "アップストローク", "업스트로크 스트럼"),
    "上扬音/Doit": ("Doit", "ドゥイット", "두잇"),
    "下坠音/Fall": ("Fall", "フォール", "폴"),
    "下弓": ("Down Bow", "下げ弓", "내림활"),
    "下扫弦": ("Downstroke Strum", "ダウンストローク", "다운스트로크 스트럼"),
    "与 {track_name} 存在明显同度加倍，作为配器层保留": (
        "Clear unison doubling with {track_name}; retained as an orchestration layer",
        "{track_name}との明確なユニゾン重ねを編成レイヤーとして保持",
        "{track_name}과(와) 뚜렷한 유니즌 더블링이 있어 편성 레이어로 유지",
    ),
    "与 {track_name} 音区高度重叠，存在织体遮蔽风险": (
        "Heavy register overlap with {track_name}; texture-masking risk",
        "{track_name}と音域が大きく重なり、テクスチャを覆う可能性があります",
        "{track_name}과(와) 음역이 크게 겹쳐 텍스처 마스킹 위험이 있습니다",
    ),
    "与该奏法的演奏语境不完全匹配": (
        "The musical context is not a complete match for this Musical Technique",
        "この奏法の演奏コンテキストと完全には一致しません",
        "이 주법의 연주 맥락과 완전히 일치하지 않습니다",
    ),
    "两音动机重复": ("Repeated two-note motif", "2音動機の反復", "두 음 동기 반복"),
    "中力度持续音": ("Medium Sustain", "中強度サステイン", "중간 세기 서스테인"),
    "乐器资料标记为不适用于当前织体": (
        "Instrument evidence marks it unsuitable for the current texture",
        "楽器資料では現在のテクスチャに不適とされています",
        "악기 자료에서 현재 텍스처에 적합하지 않은 것으로 표시됩니다",
    ),
    "乐理分析：调性不稳定，已降级为节拍、乐句与织体规则": (
        "Music theory: unstable tonality; using beat, phrase, and texture rules instead",
        "楽理分析：調性が不安定なため、拍・フレーズ・テクスチャ規則へ切り替えました",
        "음악 이론 분석: 조성이 불안정하여 박, 프레이즈 및 텍스처 규칙으로 전환했습니다",
    ),
    "低中音区分离节奏型": (
        "Detached rhythmic pattern in the low-mid register",
        "中低音域の分離したリズム型",
        "중저음역의 분리된 리듬 패턴",
    ),
    "低音/节奏型匹配": ("Bass/rhythm pattern match", "ベース／リズム型に適合", "베이스/리듬 패턴 일치"),
    "低音与节奏密度较高，抑制混响混浊": (
        "Dense bass and rhythm; reduce reverb muddiness",
        "ベースとリズムが密なため、リバーブの濁りを抑制",
        "베이스와 리듬 밀도가 높아 리버브의 혼탁함을 억제",
    ),
    "低音区同时活跃的乐器过多；建议让非低音角色减少低区音符或短时留白": (
        "Too many instruments are active in the low register; reduce low notes in "
        "non-bass parts or leave brief gaps",
        "低音域で同時に鳴る楽器が多すぎます。ベース以外のパートは低音を減らすか、"
        "短い空白を作ってください",
        "저음역에서 동시에 연주되는 악기가 너무 많습니다. 베이스 이외 파트의 저음을 "
        "줄이거나 짧은 여백을 두세요",
    ),
    "低音平均音区高于其他旋律层，可能发生声部交叉": (
        "The bass has a higher average register than another melodic layer; voice crossing may occur",
        "ベースの平均音域が別の旋律レイヤーより高く、声部交差の可能性があります",
        "베이스 평균 음역이 다른 선율 레이어보다 높아 성부 교차가 발생할 수 있습니다",
    ),
    "使用轻合唱，避免低频与鼓组失焦": (
        "Use light chorus to keep bass and drums focused",
        "軽いコーラスを使い、低域とドラムの焦点を保ちます",
        "가벼운 코러스를 사용해 저역과 드럼의 초점을 유지합니다",
    ),
    "保持音/Tenuto": ("Tenuto", "テヌート", "테누토"),
    "全音颤音": ("Whole-tone Trill", "全音トリル", "온음 트릴"),
    "击弦": ("Hammer-on", "ハンマリング・オン", "해머온"),
    "分弓/分奏": ("Détaché", "デタシェ", "데타셰"),
    "制音/闷止": ("Damping/Choke", "ミュート／チョーク", "뮤트/초크"),
    "加弱音器": ("Con Sordino", "コン・ソルディーノ", "콘 소르디노"),
    "勾弦": ("Pull-off", "プリング・オフ", "풀오프"),
    "半踏板": ("Half Pedal", "ハーフペダル", "하프 페달"),
    "半音颤音": ("Semitone Trill", "半音トリル", "반음 트릴"),
    "双吐": ("Double Tonguing", "ダブルタンギング", "더블 텅잉"),
    "合成器或氛围织体适合中等合唱深度": (
        "Synth or ambient textures suit moderate chorus depth",
        "シンセやアンビエントのテクスチャには中程度のコーラスが適します",
        "신스 또는 앰비언트 텍스처에는 중간 코러스 깊이가 적합합니다",
    ),
    "合成长音持续纹理": (
        "Sustained synth texture",
        "シンセの持続テクスチャ",
        "신스 서스테인 텍스처",
    ),
    "合成长音的音色候选": (
        "Timbre candidate for sustained synth notes",
        "シンセのロングトーン向け音色候補",
        "신스 롱톤용 음색 후보",
    ),
    "同向快速级进的竖琴滑奏候选": (
        "Harp glissando candidate from a fast one-direction scale run",
        "同方向の速い順次進行によるハープグリッサンド候補",
        "같은 방향의 빠른 순차 진행으로 만든 하프 글리산도 후보",
    ),
    "同声部小上行紧密连接": (
        "Closely connected small ascending interval in one voice",
        "同一声部の小さな上行音程が密接に連結",
        "같은 성부의 작은 상행 음정이 촘촘히 연결됨",
    ),
    "同声部小下行紧密连接": (
        "Closely connected small descending interval in one voice",
        "同一声部の小さな下行音程が密接に連結",
        "같은 성부의 작은 하행 음정이 촘촘히 연결됨",
    ),
    "同拍和弦适合竖琴分解或琶音化": (
        "Same-onset chord suits harp voicing or arpeggiation",
        "同時発音の和音はハープの分散和音／アルペジオに適しています",
        "동시 시작 화음은 하프 분산화음 또는 아르페지오에 적합합니다",
    ),
    "同鼓件一拍内快速重复": (
        "Fast same-drum repetition within one beat",
        "同じドラム音の1拍内での高速反復",
        "같은 드럼 음을 한 박 안에서 빠르게 반복",
    ),
    "同鼓件极短双击形成 Flam": (
        "Very short same-drum double hit forms a flam",
        "同じドラム音のごく短い2打でフラムを形成",
        "같은 드럼 음의 매우 짧은 두 타격으로 플램 형성",
    ),
    "向下滑动": ("Slide Down", "スライドダウン", "슬라이드 다운"),
    "吼音/Growl": ("Growl", "グロウル", "그로울"),
    "和弦音在短窗口内按音高方向依次起音": (
        "Chord tones start sequentially by pitch direction within a short window",
        "短い時間内に和音構成音が音高方向へ順次発音",
        "짧은 구간에서 화음 구성음이 음높이 방향으로 차례로 시작됨",
    ),
    "哨音": ("Whistle Tone", "ホイッスルトーン", "휘슬 톤"),
    "小调和弦": ("Minor Chord", "マイナーコード", "단조 화음"),
    "小音程紧密连接形成方向性手势": (
        "Closely connected small intervals form a directional gesture",
        "密接した小音程が方向性のあるジェスチャーを形成",
        "촘촘히 연결된 작은 음정이 방향성 있는 제스처를 형성",
    ),
    "局部力度峰值形成明确起音强调": (
        "A local velocity peak creates a clear attack accent",
        "局所的なベロシティピークが明確なアタックアクセントを形成",
        "국소 벨로시티 피크가 뚜렷한 어택 악센트를 형성",
    ),
    "已应用过轻微自然化，本次保持不变": (
        "Light humanization was already applied; unchanged this time",
        "軽いヒューマナイズは適用済みのため、今回は変更しません",
        "가벼운 휴머나이즈가 이미 적용되어 이번에는 변경하지 않습니다",
    ),
    "已设置轨道级 FX，保留手工选择且不生成自动奏法": (
        "Track-level FX is set; preserve the manual choice and do not generate automatic Musical Techniques",
        "トラックFXが設定済みのため、手動選択を保持し自動奏法を生成しません",
        "트랙 FX가 설정되어 있어 수동 선택을 유지하고 자동 주법을 생성하지 않습니다",
    ),
    "开放音": ("Open Tone", "オープントーン", "오픈 톤"),
    "开镲": ("Open Hi-hat", "オープンハイハット", "오픈 하이햇"),
    "弯音": ("Bend", "ベンド", "벤드"),
    "弱力度持续音": ("Soft Sustain", "弱強度サステイン", "약한 세기 서스테인"),
    "强力度持续音": ("Strong Sustain", "強強度サステイン", "강한 세기 서스테인"),
    "强拍支撑": ("Strong-beat support", "強拍を支える", "강박 지지"),
    "强重音/Marcato": ("Marcato", "マルカート", "마르카토"),
    "当前配器不需要全局合唱扩宽": (
        "The current orchestration does not need global chorus widening",
        "現在の編成にはグローバルコーラスによる拡幅は不要です",
        "현재 편성에는 전역 코러스 확장이 필요하지 않습니다",
    ),
    "待游戏验证": ("Requires In-game Verification", "ゲーム内検証待ち", "게임 내 검증 필요"),
    "待验证奏法": ("Unverified Musical Technique", "未検証の奏法", "검증되지 않은 주법"),
    "快速重复起音符合多吐音型": (
        "Fast repeated attacks match a multiple-tonguing pattern",
        "高速の反復アタックが多重タンギングの型に一致",
        "빠른 반복 어택이 다중 텅잉 패턴과 일치",
    ),
    "扫拨/Rake": ("Rake", "レイク", "레이크"),
    "拨弦": ("Pizzicato", "ピチカート", "피치카토"),
    "持续音可用同音重复形成震音纹理": (
        "Repeated pitches can turn a held note into a tremolo texture",
        "同音反復で持続音をトレモロのテクスチャにできます",
        "동음 반복으로 지속음을 트레몰로 텍스처로 만들 수 있습니다",
    ),
    "指板上奏": ("Sul Tasto", "スル・タスト", "술 타스토"),
    "按键声": ("Key Click", "キークリック", "키 클릭"),
    "换气乐句": ("Breath Phrase", "ブレスフレーズ", "호흡 프레이즈"),
    "掌根闷音": ("Palm Mute", "パームミュート", "팜 뮤트"),
    "接近完整拍值并保持清晰换音": (
        "Near-full beat duration with clear note changes",
        "拍のほぼ全長を保ちながら明確に音を切り替えています",
        "거의 한 박 길이를 유지하면서 음 전환이 뚜렷합니다",
    ),
    "教程支持": ("Tutorial-supported", "チュートリアルで裏付け", "튜토리얼 근거"),
    "断奏/吐音": ("Staccato/Tonguing", "スタッカート／タンギング", "스타카토/텅잉"),
    "新增 Track {track_id}，以乐器 0x{instrument_id:02X} 对主旋律作{shift:+d}半音加倍": (
        "Add Track {track_id}, doubling the lead melody by {shift:+d} semitones with instrument 0x{instrument_id:02X}",
        "Track {track_id}を追加し、楽器0x{instrument_id:02X}で主旋律を{shift:+d}半音重ねます",
        "Track {track_id}을(를) 추가하고 악기 0x{instrument_id:02X}(으)로 주선율을 {shift:+d}반음 더블링합니다",
    ),
    "旋律折返，滑音降级": (
        "Melody reverses direction; slide reduced",
        "旋律が折り返すため、スライドを抑制",
        "선율 방향이 바뀌어 슬라이드를 낮춤",
    ),
    "旋律较稀疏，可使用少量延迟": (
        "Sparse melody permits a small amount of delay",
        "旋律が疎なため、少量のディレイを使用可能",
        "선율이 성겨 소량의 딜레이를 사용할 수 있습니다",
    ),
    "无揉弦/Non-vibrato": ("Non-vibrato", "ノンビブラート", "논 비브라토"),
    "明确的大/小三和弦块": (
        "Clear major/minor triad block",
        "明確な長三和音／短三和音ブロック",
        "명확한 장/단3화음 블록",
    ),
    "木杆击弦/Col legno": ("Col Legno", "コル・レーニョ", "콜 레뇨"),
    "极短弱力度节奏填充": (
        "Very short, soft rhythmic fill",
        "ごく短く弱いリズムフィル",
        "매우 짧고 약한 리듬 필",
    ),
    "极短弱力度贝斯填充": (
        "Very short, soft bass fill",
        "ごく短く弱いベースフィル",
        "매우 짧고 약한 베이스 필",
    ),
    "极短断奏": ("Staccatissimo", "スタッカーティッシモ", "스타카티시모"),
    "柔音踏板/Una corda": ("Una Corda", "ウナ・コルダ", "우나 코르다"),
    "检测到 CC65 Portamento 开关": (
        "CC65 Portamento switch detected",
        "CC65ポルタメントスイッチを検出",
        "CC65 포르타멘토 스위치 감지",
    ),
    "检测到 CC66 选择性延音踏板": (
        "CC66 sostenuto pedal detected",
        "CC66ソステヌートペダルを検出",
        "CC66 소스테누토 페달 감지",
    ),
    "检测到 CC67 柔音踏板": (
        "CC67 soft pedal detected",
        "CC67ソフトペダルを検出",
        "CC67 소프트 페달 감지",
    ),
    "检测到 CC74 音色/滤波曲线": (
        "CC74 timbre/filter curve detected",
        "CC74音色／フィルターカーブを検出",
        "CC74 음색/필터 곡선 감지",
    ),
    "检测到 Channel/Poly Aftertouch 压力表情": (
        "Channel/Poly Aftertouch pressure expression detected",
        "Channel/Poly Aftertouchの圧力表現を検出",
        "Channel/Poly Aftertouch 압력 표현 감지",
    ),
    "检测到原始 MIDI CC64 踏板事件": (
        "Original MIDI CC64 pedal events detected",
        "元のMIDI CC64ペダルイベントを検出",
        "원본 MIDI CC64 페달 이벤트 감지",
    ),
    "检测到已有人工微时差，跳过自动自然化": (
        "Existing manual microtiming detected; automatic humanization skipped",
        "既存の手動マイクロタイミングを検出したため、自動ヒューマナイズをスキップ",
        "기존 수동 미세 타이밍을 감지하여 자동 휴머나이즈를 건너뜁니다",
    ),
    "检测到已有力度/表情曲线，保持原力度": (
        "Existing velocity/expression curve detected; original velocity preserved",
        "既存のベロシティ／エクスプレッションカーブを検出し、元の強度を保持",
        "기존 벨로시티/익스프레션 곡선을 감지하여 원래 세기를 유지합니다",
    ),
    "检测到显著 Pitch Bend 音高手势": (
        "Prominent Pitch Bend gesture detected",
        "顕著なPitch Bendの音高ジェスチャーを検出",
        "뚜렷한 Pitch Bend 음높이 제스처 감지",
    ),
    "检测到连续 CC64 半踏板区间": (
        "Continuous CC64 half-pedal region detected",
        "連続するCC64ハーフペダル区間を検出",
        "연속 CC64 하프 페달 구간 감지",
    ),
    "横槌/Cross stick": ("Cross Stick", "クロススティック", "크로스 스틱"),
    "歌词密集处与主旋律同音区、同起点竞争；建议错开节奏、降力度或短时留白": (
        "Dense lyrics compete with the lead melody in register and onset; offset the rhythm, lower velocity, or leave brief gaps",
        "歌詞が密な箇所で主旋律と音域・発音位置が競合しています。リズムをずらす、"
        "強度を下げる、または短い空白を作ってください",
        "가사가 밀집된 구간에서 주선율과 음역 및 시작 위치가 경쟁합니다. 리듬을 엇갈리게 "
        "하거나 세기를 낮추거나 짧은 여백을 두세요",
    ),
    "歌词节奏念唱：收短 {count} 个共享音，保留旋律音高": (
        "Rhythmic spoken lyrics: shortened {count} shared notes while preserving melody pitches",
        "リズム朗唱：共有ノート{count}個を短縮し、旋律の音高を保持",
        "리듬 낭송 가사: 공유 노트 {count}개를 줄이고 선율 음높이는 유지",
    ),
    "歌词连续表达：延长 {count} 个主旋律音的衔接，未改变音高或音符数": (
        "Continuous lyric delivery: extended connections for {count} lead notes without changing pitch or note count",
        "連続する歌詞表現：主旋律{count}ノートの接続を延長し、音高とノート数は維持",
        "연속 가사 표현: 주선율 노트 {count}개의 연결을 늘리고 음높이와 노트 수는 유지",
    ),
    "止镲": ("Cymbal Choke", "シンバルチョーク", "심벌 초크"),
    "氛围和长音织体允许更宽的混响": (
        "Ambient and sustained textures allow wider reverb",
        "アンビエントと持続音のテクスチャには広めのリバーブが適します",
        "앰비언트 및 지속음 텍스처에는 더 넓은 리버브가 적합합니다",
    ),
    "渐弱": ("Diminuendo", "ディミヌエンド", "디미누엔도"),
    "渐强": ("Crescendo", "クレッシェンド", "크레셴도"),
    "游戏安全约束阻止了音符数量或音高变化，已回退本轨": (
        "Game-safe constraints blocked a note-count or pitch change; this track was reverted",
        "ゲームセーフ制約がノート数または音高の変更を阻止したため、このトラックを元に戻しました",
        "게임 안전 제약이 노트 수 또는 음높이 변경을 막아 이 트랙을 되돌렸습니다",
    ),
    "滑音/滑奏": ("Slide/Glissando", "スライド／グリッサンド", "슬라이드/글리산도"),
    "滚奏": ("Roll", "ロール", "롤"),
    "滤波持续音": ("Filter Sustain", "フィルターサステイン", "필터 서스테인"),
    "点弦/Tapping": ("Tapping", "タッピング", "태핑"),
    "琶音器": ("Arpeggiator", "アルペジエーター", "아르페지에이터"),
    "相同 BDO 乐器合并后超过工具的 10000 音符处理阈值，自动编曲不会继续加倍；该阈值不是游戏账号配额": (
        "Merged tracks for the same BDO instrument exceed the tool's 10,000-note processing threshold; automatic arrangement will not add another doubling layer. This threshold is not an in-game account quota",
        "同じBDO楽器を結合するとツールの10,000ノート処理しきい値を超えるため、自動編曲は"
        "重ねを追加しません。このしきい値はゲームアカウントの上限ではありません",
        "같은 BDO 악기 트랙을 병합하면 도구의 10,000노트 처리 임계값을 초과하여 자동 "
        "편곡이 더블링 레이어를 추가하지 않습니다. 이 임계값은 게임 계정 한도가 아닙니다",
    ),
    "相邻音无可听断点且声部连续": (
        "Adjacent notes have no audible break and the voice remains continuous",
        "隣接ノート間に聴感上の切れ目がなく、声部が連続",
        "인접 노트 사이에 들리는 끊김이 없고 성부가 연속됨",
    ),
    "短促、分离且{detail}的节奏 riff": (
        "Short, detached rhythmic riff with {detail}",
        "短く分離し、{detail}のあるリズムリフ",
        "짧고 분리되며 {detail}이(가) 있는 리듬 리프",
    ),
    "短促且有可听间隔的同声部音": (
        "Short same-voice notes with audible gaps",
        "聴感上の間隔がある短い同声部ノート",
        "들리는 간격이 있는 짧은 동일 성부 노트",
    ),
    "短促断奏": ("Short Staccato", "ショートスタッカート", "짧은 스타카토"),
    "短时值且与下一音存在可听间隔": (
        "Short duration with an audible gap before the next note",
        "短い音価で次のノートとの間に聴感上の間隔があります",
        "짧은 길이이며 다음 노트와 들리는 간격이 있습니다",
    ),
    "突强后回落/Sforzando": ("Sforzando", "スフォルツァンド", "스포르찬도"),
    "竖琴滑奏": ("Harp Glissando", "ハープグリッサンド", "하프 글리산도"),
    "竖琴琶音": ("Harp Arpeggio", "ハープアルペジオ", "하프 아르페지오"),
    "管乐长音按力度分层": (
        "Layer sustained wind notes by velocity",
        "管楽器のロングトーンを強度別にレイヤー化",
        "관악기 롱톤을 세기별로 레이어링",
    ),
    "自动": ("Automatic", "自動", "자동"),
    "节奏念唱": ("Rhythmic Spoken", "リズム朗唱", "리듬 낭송"),
    "花舌/Flutter tongue": ("Flutter Tongue", "フラッタータンギング", "플러터 텅잉"),
    "装饰击/Flam": ("Flam", "フラム", "플램"),
    "触后渐变": ("Aftertouch Swell", "アフタータッチ変化", "애프터터치 변화"),
    "贝斯高力度短音重击": (
        "Hard, high-velocity short bass attack",
        "ベースの高強度な短音アタック",
        "베이스의 강한 고세기 짧은 어택",
    ),
    "超出该奏法常用音区": (
        "Outside the usual range for this Musical Technique",
        "この奏法の通常音域外です",
        "이 주법의 일반 음역을 벗어납니다",
    ),
    "跳弓": ("Spiccato", "スピッカート", "스피카토"),
    "边击/Rim shot": ("Rim Shot", "リムショット", "림 샷"),
    "近琴码奏": ("Sul Ponticello", "スル・ポンティチェロ", "술 폰티첼로"),
    "连奏": ("Legato", "レガート", "레가토"),
    "连续同向级进形成滑奏候选": (
        "Continuous one-direction scale motion forms a glissando candidate",
        "連続する同方向の順次進行がグリッサンド候補を形成",
        "연속된 같은 방향의 순차 진행이 글리산도 후보를 형성",
    ),
    "连贯滑音/Portamento": ("Portamento", "ポルタメント", "포르타멘토"),
    "选择性延音踏板": ("Sostenuto Pedal", "ソステヌートペダル", "소스테누토 페달"),
    "重复音": ("Repeated Notes", "反復音", "반복음"),
    "重音": ("Accent", "アクセント", "악센트"),
    "钢琴延音踏板": ("Piano Sustain Pedal", "ピアノサステインペダル", "피아노 서스테인 페달"),
    "铲入音/Scoop": ("Scoop", "スクープ", "스쿱"),
    "长间隔构成自然换气边界": (
        "A long gap forms a natural breath boundary",
        "長い間隔が自然なブレス境界を形成",
        "긴 간격이 자연스러운 호흡 경계를 형성",
    ),
    "长音含全音邻音往返": (
        "A held note alternates with a whole-tone neighbor",
        "ロングトーンが全音隣接音と交互に動いています",
        "긴 노트가 온음 이웃음과 번갈아 움직입니다",
    ),
    "长音跨入后续材料，适合踏板保持": (
        "A held note extends into following material and suits pedal sustain",
        "ロングトーンが後続素材まで伸び、ペダル保持に適しています",
        "긴 노트가 다음 소재까지 이어져 페달 서스테인에 적합합니다",
    ),
    "门限短于相邻音间隔的 22%": (
        "Gate is shorter than 22% of the adjacent-note interval",
        "ゲートが隣接ノート間隔の22%未満です",
        "게이트가 인접 노트 간격의 22%보다 짧습니다",
    ),
    "门限短音": ("Gated Short Note", "ゲートショートノート", "게이트 짧은 노트"),
    "闭塞音/Stopped": ("Stopped", "ストップド", "스톱드"),
    "闭镲": ("Closed Hi-hat", "クローズドハイハット", "클로즈드 하이햇"),
    "问答": ("Call and Response", "コール＆レスポンス", "콜 앤 리스폰스"),
    "震音": ("Tremolo", "トレモロ", "트레몰로"),
    "震音/颤音": ("Tremolo/Vibrato", "トレモロ／ビブラート", "트레몰로/비브라토"),
    "非旋律角色降级": (
        "Reduced for a non-melodic role",
        "非旋律役割のため抑制",
        "비선율 역할이므로 낮춤",
    ),
    "音程颤音": ("Interval Trill", "音程トリル", "음정 트릴"),
    "音色/滤波扫频": ("Timbre/Filter Sweep", "音色／フィルタースイープ", "음색/필터 스윕"),
    "马达颤音": ("Motor Vibrato", "モータービブラート", "모터 비브라토"),
    "高力度短时值贝斯重击": (
        "High-velocity, short-duration bass attack",
        "高強度・短音価のベースアタック",
        "고세기 짧은 길이의 베이스 어택",
    ),
    "高音区稀疏点缀": (
        "Sparse high-register ornament",
        "高音域の疎な装飾",
        "고음역의 성긴 장식",
    ),
    "鬼音": ("Ghost Note", "ゴーストノート", "고스트 노트"),
    "鼓与贝斯的主要起音联系较弱；建议在段落重拍建立少量共同锚点": (
        "Drum and bass primary onsets are weakly connected; add a few shared anchors "
        "on strong section beats",
        "ドラムとベースの主要アタックの結び付きが弱いため、セクションの強拍に少数の"
        "共通アンカーを置いてください",
        "드럼과 베이스의 주요 시작 연결이 약합니다. 구간의 강박에 소수의 공통 앵커를 "
        "배치하세요",
    ),
    "鼓刷": ("Brushes", "ブラシ", "브러시"),
}

for _source, (_english, _japanese, _korean) in _OPTIMIZER_RUNTIME_TRANSLATIONS.items():
    if _source in EN or _source in JA or _source in KO:
        raise RuntimeError(f"duplicate optimizer localization source: {_source}")
    EN[_source] = _english
    JA[_source] = _japanese
    KO[_source] = _korean

del _source, _english, _japanese, _korean


# Final regional terminology pass.  Keeping these corrections in one table
# makes the NA/EU, Japan, and Korea wording directly comparable and prevents
# later feature catalogs from silently restoring older generic terms.
_REGIONAL_QUALITY_TRANSLATIONS = {
    "管乐器": ("Wind Instruments", "管楽器", "관악기"),
    "弦乐器": ("String Instruments", "弦楽器", "현악기"),
    "键盘乐器": ("Keyboard Instruments", "鍵盤楽器", "건반악기"),
    "打击乐器": ("Percussion Instruments", "打楽器", "타악기"),
    "该奏法的游戏内音色仍需人工验证。": (
        "This Musical Technique's in-game timbre still needs manual verification.",
        "この奏法のゲーム内音色は、引き続き手動確認が必要です。",
        "이 주법의 게임 내 음색은 아직 직접 확인해야 합니다.",
    ),
    "游戏音域待验证": (
        "In-game range pending verification",
        "ゲーム内音域は未検証",
        "게임 내 음역 검증 대기",
    ),
    "游戏 {low}-{high}": (
        "In-game {low}–{high}",
        "ゲーム内 {low}～{high}",
        "게임 내 {low}~{high}",
    ),
    "游戏 {low}-{high}（缺少 {gap_count} 个音）": (
        "In-game {low}–{high} ({gap_count} unavailable notes)",
        "ゲーム内 {low}～{high}（使用不可{gap_count}音）",
        "게임 내 {low}~{high}(사용 불가 음 {gap_count}개)",
    ),
    "开": ("On", "オン", "켬"),
    "关": ("Off", "オフ", "끔"),
    "鼓组 · MIDI 通道 10": (
        "Drums · MIDI Channel 10",
        "ドラム · MIDIチャンネル10",
        "드럼 · MIDI 채널 10",
    ),
    "声部 {group_id} · {role} · 已确认 0x{instrument_id:02X}（不在当前 Top-3）": (
        "Voice {group_id} · {role} · Confirmed 0x{instrument_id:02X} (outside current Top 3)",
        "声部 {group_id}・{role}・確認済み 0x{instrument_id:02X}（現在の上位3件以外）",
        "성부 {group_id} · {role} · 0x{instrument_id:02X} 확인됨(현재 상위 3개 외)",
    ),
    "证据轮廓": ("Pitch Contour", "ピッチ輪郭", "피치 윤곽"),
    "旋律线、Frame、Onset、Contour 与声谱透明度": (
        "Melody-line, Frame Activation, Onset Strength, Pitch Contour, and Spectrogram opacity",
        "メロディライン、フレーム活性度、オンセット強度、ピッチ輪郭、スペクトログラムの透明度",
        "멜로디 라인, 프레임 활성도, 온셋 강도, 피치 윤곽 및 스펙트로그램 투명도",
    ),
    "声谱": ("Spectrogram", "スペクトログラム", "스펙트로그램"),
    "普通": ("Normal", "通常", "일반"),
    # Keep terse labels reversible across live language switches. If two
    # source keys intentionally mean the same thing, their full locale vector
    # is identical; otherwise the wording is distinct in every region.
    "详细说明 ▸": ("Details ▸", "詳細 ▸", "세부 정보 ▸"),
    "详细信息 ▸": ("Details ▸", "詳細 ▸", "세부 정보 ▸"),
    "详细说明 ▾": ("Details ▾", "詳細 ▾", "세부 정보 ▾"),
    "详细信息 ▾": ("Details ▾", "詳細 ▾", "세부 정보 ▾"),
    "和弦小调": ("Minor Chord", "マイナーコード", "마이너 코드"),
    "小调和弦": ("Minor Chord", "マイナーコード", "마이너 코드"),
    "弱音": ("Mute", "ミュート", "뮤트"),
    "静音": ("Mute Audio", "消音", "음소거"),
    "装饰": ("Ornament", "装飾", "장식"),
    "装饰声部": ("Ornament Voice", "装飾声部", "장식 성부"),
    "无法原声试听": (
        "Original Preview Unavailable",
        "原音を試聴できません",
        "원음 미리듣기 불가",
    ),
    "无法原声还原": (
        "Original Preview Unavailable",
        "原音を試聴できません",
        "원음 미리듣기 불가",
    ),
    "试听不可用": (
        "Preview Unavailable",
        "試聴を利用できません",
        "미리듣기 사용 불가",
    ),
    "就绪": ("Ready", "準備完了", "준비"),
    "可转换": ("Ready to Export", "書き出し可能", "내보내기 가능"),
    "准备完成": ("Prepared", "準備済み", "준비 완료"),
    "第二旋律": ("Secondary Melody", "サブメロディ", "보조 선율"),
    "副旋律": ("Secondary Melody", "サブメロディ", "보조 선율"),
    "优化此轨": ("Optimize This Track", "このトラックを最適化", "이 트랙 최적화"),
    "优化此轨道": ("Optimize This Track", "このトラックを最適化", "이 트랙 최적화"),
    "标签": ("Accent Tag", "アクセントタグ", "악센트 태그"),
    "重音": ("Accent", "アクセント", "악센트"),
    "轨道": ("Tracks", "トラック一覧", "트랙 목록"),
    "轨": ("tracks", "トラック", "트랙"),
    "摇滚": ("Rock", "ロック", "록"),
    "锁定": ("Lock", "ロックする", "잠금"),
    "右键删除音符 · Ctrl 拖选追加 · 拖动音符两端调整时值": (
        "Right-click to delete · Ctrl-drag to add selection · Drag note edges to resize",
        "右クリックで削除・Ctrlドラッグで選択追加・端をドラッグして長さを調整",
        "우클릭으로 삭제 · Ctrl 드래그로 선택 추가 · 음표 가장자리를 드래그하여 길이 조절",
    ),
    "右键删除 · Ctrl 拖选追加 · 拖动两端调整时值": (
        "Right-click to delete · Ctrl-drag to add selection · Drag note edges to resize",
        "右クリックで削除・Ctrlドラッグで選択追加・端をドラッグして長さを調整",
        "우클릭으로 삭제 · Ctrl 드래그로 선택 추가 · 음표 가장자리를 드래그하여 길이 조절",
    ),
    "打击乐": ("Percussion", "打楽器", "타악기"),
    "打击乐器": ("Percussion Instruments", "打楽器群", "타악기류"),
    "拒绝": ("Reject", "拒否", "거부"),
    "拒绝项": ("Rejected", "拒否済み", "거부됨"),
    "比较 BDO 乐谱": ("Compare BDO Scores", "BDOスコアを比較", "BDO 악보 비교하기"),
    "BDO 谱面对比": ("BDO Score Comparison", "BDOスコア比較", "BDO 악보 비교"),
    "样本覆盖": ("Sample Coverage", "サンプルカバレッジ", "샘플 커버리지"),
    "全部覆盖": ("Fully Covered", "全ノートをカバー", "전체 커버"),
    "部分覆盖": ("Partially Covered", "一部カバー", "일부 커버"),
    "未映射": ("Unmapped", "未マッピング", "매핑 없음"),
    "轨道 {track_id} · {track}: {covered}/{total} · {status}": (
        "Track {track_id} · {track}: {covered}/{total} · {status}",
        "トラック {track_id}・{track}: {covered}/{total}・{status}",
        "트랙 {track_id} · {track}: {covered}/{total} · {status}",
    ),
    "优化器输入包含重复轨道 ID": (
        "Optimizer input contains duplicate track IDs",
        "最適化入力に重複したトラックIDがあります",
        "최적화 입력에 중복 트랙 ID가 있습니다",
    ),
    "优化目标范围引用了未知轨道": (
        "The optimization target references an unknown track",
        "最適化対象が不明なトラックを参照しています",
        "최적화 대상이 알 수 없는 트랙을 참조합니다",
    ),
    "曲目超过优化器音符上限": (
        "The song exceeds the optimizer note limit",
        "曲が最適化のノート数上限を超えています",
        "곡이 최적화 음표 수 제한을 초과했습니다",
    ),
    "曲目超过优化器节拍上限": (
        "The song exceeds the optimizer beat limit",
        "曲が最適化の拍数上限を超えています",
        "곡이 최적화 박자 수 제한을 초과했습니다",
    ),
    "分析后工程已变化；请重新分析": (
        "The project changed after analysis; analyze again",
        "解析後にプロジェクトが変更されました。再解析してください",
        "분석 후 프로젝트가 변경되었습니다. 다시 분석하세요",
    ),
    "预览算法标识与清单不一致": (
        "The preview algorithm ID does not match its manifest",
        "プレビューのアルゴリズムIDがマニフェストと一致しません",
        "미리보기 알고리즘 ID가 매니페스트와 일치하지 않습니다",
    ),
    "算法不得删除完整的源轨道": (
        "The optimizer may not remove complete source tracks",
        "最適化アルゴリズムは元のトラック全体を削除できません",
        "최적화 알고리즘은 원본 트랙 전체를 삭제할 수 없습니다",
    ),
    "音符的音高、力度或 ntype 超出协议范围": (
        "A note pitch, velocity, or ntype is outside the wire-format range",
        "ノートの音高、強度、またはntypeが通信形式の範囲外です",
        "음표의 음높이, 세기 또는 ntype이 전송 형식 범위를 벗어났습니다",
    ),
    "音符时间必须有限、非负且时值不为零": (
        "Note timing must be finite and non-negative, with a non-zero duration",
        "ノート時刻は有限かつ0以上で、長さは0以外である必要があります",
        "음표 시간은 유한한 0 이상의 값이어야 하며 길이는 0일 수 없습니다",
    ),
    "派生鼓音必须使用 BDO 音高 48..64 和 ntype=99": (
        "Derived drum notes must use BDO pitches 48..64 and ntype=99",
        "派生ドラムノートにはBDO音高48..64とntype=99が必要です",
        "파생 드럼 음표는 BDO 음높이 48..64와 ntype=99를 사용해야 합니다",
    ),
    "预览不得复制或新增不受支持的手动奏法": (
        "The preview may not duplicate or invent unsupported manual Musical Techniques",
        "プレビューは未対応の手動奏法を複製または新規設定できません",
        "미리보기는 지원하지 않는 수동 주법을 복제하거나 새로 만들 수 없습니다",
    ),
    "预览不得新增非规范鼓音高或音符类型": (
        "The preview may not add noncanonical drum pitches or note types",
        "プレビューは規定外のドラム音高やノート種別を追加できません",
        "미리보기는 비표준 드럼 음높이 또는 음표 유형을 추가할 수 없습니다",
    ),
    "鼓轨必须使用规范的 BDO 架子鼓乐器": (
        "Drum tracks must use the canonical BDO Drum Set instrument",
        "ドラムトラックには規定のBDOドラムセット楽器が必要です",
        "드럼 트랙은 표준 BDO 드럼 세트 악기를 사용해야 합니다",
    ),
    "不得混用整轨操作与按索引音符操作": (
        "Whole-track and indexed-note operations may not be mixed",
        "トラック全体の操作とインデックス指定のノート操作は併用できません",
        "전체 트랙 작업과 인덱스 기반 음표 작업을 함께 사용할 수 없습니다",
    ),
    "预览源指纹与请求不一致": (
        "The preview source fingerprint does not match its request",
        "プレビューの元データ指紋がリクエストと一致しません",
        "미리보기 원본 지문이 요청과 일치하지 않습니다",
    ),
    "预览对每个源乐器只能设置一次": (
        "A preview may set each source instrument only once",
        "プレビューで各元楽器を設定できるのは1回だけです",
        "미리보기에서는 각 원본 악기를 한 번만 설정할 수 있습니다",
    ),
    "预览最多只能包含一次全局效果修改": (
        "A preview may contain only one global effect change",
        "プレビューに含められるグローバルエフェクト変更は1件だけです",
        "미리보기에는 전역 효과 변경을 하나만 포함할 수 있습니다",
    ),
    "单轨优化不得写入全局效果": (
        "Single-track optimization may not write global effects",
        "単一トラックの最適化ではグローバルエフェクトを書き込めません",
        "단일 트랙 최적화는 전역 효과를 기록할 수 없습니다",
    ),
    "效果值必须在 [0, 127] 范围内": (
        "Effect values must be in the [0, 127] range",
        "エフェクト値は[0, 127]の範囲内である必要があります",
        "효과 값은 [0, 127] 범위여야 합니다",
    ),
    "单轨优化不得创建轨道": (
        "Single-track optimization may not create tracks",
        "単一トラックの最適化ではトラックを作成できません",
        "단일 트랙 최적화는 트랙을 만들 수 없습니다",
    ),
    "派生轨道必须至少包含一个音符": (
        "Derived tracks must contain at least one note",
        "派生トラックには1音以上が必要です",
        "파생 트랙에는 음표가 하나 이상 있어야 합니다",
    ),
    "派生轨道引用了未知源轨道": (
        "A derived track references an unknown source track",
        "派生トラックが不明な元トラックを参照しています",
        "파생 트랙이 알 수 없는 원본 트랙을 참조합니다",
    ),
    "预览超过主程序的曲目音符上限": (
        "The preview exceeds the host song-note limit",
        "プレビューがホストの曲内ノート数上限を超えています",
        "미리보기가 호스트의 곡 음표 수 제한을 초과했습니다",
    ),
    "缺少主程序 Note 原型，无法生成音符": (
        "Notes cannot be materialized without a host Note prototype",
        "ホストのNoteプロトタイプがないため、ノートを生成できません",
        "호스트 Note 원형이 없어 음표를 생성할 수 없습니다",
    ),
    "缺少源轨道，无法创建派生轨道": (
        "A derived track cannot be created without a source track",
        "元トラックがないため、派生トラックを作成できません",
        "원본 트랙이 없어 파생 트랙을 만들 수 없습니다",
    ),
    "算法包包含过多文件": (
        "The optimizer package contains too many files",
        "最適化パッケージ内のファイル数が多すぎます",
        "최적화 패키지에 파일이 너무 많습니다",
    ),
    "算法包解压后超过 16 GiB 上限": (
        "The optimizer package exceeds the 16 GiB extracted-size limit",
        "最適化パッケージの展開サイズが16 GiBの上限を超えています",
        "최적화 패키지의 압축 해제 크기가 16 GiB 제한을 초과합니다",
    ),
    "算法包缺少 manifest.json": (
        "The optimizer package is missing manifest.json",
        "最適化パッケージにmanifest.jsonがありません",
        "최적화 패키지에 manifest.json이 없습니다",
    ),
    "算法包清单根节点必须是对象": (
        "The optimizer manifest root must be an object",
        "最適化マニフェストのルートはオブジェクトである必要があります",
        "최적화 매니페스트 루트는 객체여야 합니다",
    ),
    "plugin_id 必须是稳定的小写标识符": (
        "plugin_id must be a stable lowercase identifier",
        "plugin_id は安定した小文字の識別子である必要があります",
        "plugin_id는 안정적인 소문자 식별자여야 합니다",
    ),
    "version 必须是路径安全的标识符": (
        "version must be a path-safe identifier",
        "version はパスに安全な識別子である必要があります",
        "version은 경로에 안전한 식별자여야 합니다",
    ),
    "intensities 和 scopes 必须是数组": (
        "intensities and scopes must be arrays",
        "intensities と scopes は配列である必要があります",
        "intensities와 scopes는 배열이어야 합니다",
    ),
    "capabilities 必须是数组": (
        "capabilities must be an array",
        "capabilities は配列である必要があります",
        "capabilities는 배열이어야 합니다",
    ),
    "requires_safe_prepass 必须是布尔值": (
        "requires_safe_prepass must be a Boolean value",
        "requires_safe_prepass は真偽値である必要があります",
        "requires_safe_prepass는 불리언 값이어야 합니다",
    ),
    "算法必须支持 conservative、balanced 和 deep": (
        "The optimizer must support conservative, balanced, and deep",
        "最適化アルゴリズムは conservative、balanced、deep に対応する必要があります",
        "최적화 알고리즘은 conservative, balanced 및 deep을 지원해야 합니다",
    ),
    "算法 scopes 无效": (
        "The optimizer scopes are invalid",
        "最適化アルゴリズムの scopes が無効です",
        "최적화 알고리즘의 scopes가 올바르지 않습니다",
    ),
    "entrypoint 必须使用 module:function 格式": (
        "entrypoint must use the module:function format",
        "entrypoint は module:function 形式で指定する必要があります",
        "entrypoint는 module:function 형식을 사용해야 합니다",
    ),
    "entrypoint 包含无效的 Python 标识符": (
        "entrypoint contains an invalid Python identifier",
        "entrypoint に無効な Python 識別子が含まれています",
        "entrypoint에 올바르지 않은 Python 식별자가 있습니다",
    ),
    "display_name 不能为空": (
        "display_name must not be empty",
        "display_name は空にできません",
        "display_name은 비워 둘 수 없습니다",
    ),
    "算法包缺少 payload/ 目录": (
        "The optimizer package is missing the payload/ directory",
        "最適化パッケージにpayload/ディレクトリがありません",
        "최적화 패키지에 payload/ 디렉터리가 없습니다",
    ),
    "外部算法描述缺少算法包": (
        "The external optimizer descriptor has no package",
        "外部最適化アルゴリズムの記述にパッケージがありません",
        "외부 최적화 알고리즘 설명에 패키지가 없습니다",
    ),
    "优化算法返回了不兼容的预览对象": (
        "The optimizer returned an incompatible preview object",
        "最適化アルゴリズムが互換性のないプレビューオブジェクトを返しました",
        "최적화 알고리즘이 호환되지 않는 미리보기 객체를 반환했습니다",
    ),
    "算法对象必须提供 analyse(request, environment)": (
        "The optimizer object must provide analyse(request, environment)",
        "最適化オブジェクトにはanalyse(request, environment)が必要です",
        "최적화 객체는 analyse(request, environment)를 제공해야 합니다",
    ),
    "算法 ID 重复；所有副本均已禁用": (
        "Duplicate optimizer ID; all copies were disabled",
        "最適化IDが重複しているため、すべてのコピーを無効にしました",
        "최적화 ID가 중복되어 모든 사본을 비활성화했습니다",
    ),
    "无法读取优化算法包：{value}": (
        "Could not read the optimizer package: {value}",
        "最適化パッケージを読み取れません: {value}",
        "최적화 패키지를 읽을 수 없습니다: {value}",
    ),
    "算法包包含不安全路径：{value}": (
        "The optimizer package contains an unsafe path: {value}",
        "最適化パッケージに安全でないパスが含まれています: {value}",
        "최적화 패키지에 안전하지 않은 경로가 있습니다: {value}",
    ),
    "算法包不允许符号链接：{value}": (
        "Symbolic links are not allowed in optimizer packages: {value}",
        "最適化パッケージではシンボリックリンクを使用できません: {value}",
        "최적화 패키지에는 심볼릭 링크를 사용할 수 없습니다: {value}",
    ),
    "算法包清单字段无效：{value}": (
        "The optimizer manifest fields are invalid: {value}",
        "最適化マニフェストのフィールドが無効です: {value}",
        "최적화 매니페스트 필드가 올바르지 않습니다: {value}",
    ),
    "不支持的算法包 schema：{value}": (
        "Unsupported optimizer package schema: {value}",
        "未対応の最適化パッケージ schema です: {value}",
        "지원하지 않는 최적화 패키지 schema입니다: {value}",
    ),
    "不支持的优化器 API：{value}": (
        "Unsupported optimizer API: {value}",
        "未対応の最適化 API です: {value}",
        "지원하지 않는 최적화 API입니다: {value}",
    ),
    "entrypoint 不可调用：{value}": (
        "entrypoint is not callable: {value}",
        "entrypoint を呼び出せません: {value}",
        "entrypoint를 호출할 수 없습니다: {value}",
    ),
    "未知 BDO 乐器 ID：{value}": (
        "Unknown BDO instrument ID: {value}",
        "不明なBDO楽器IDです: {value}",
        "알 수 없는 BDO 악기 ID: {value}",
    ),
    "轨道 {value} 的音符替换已过期": (
        "The note replacement for track {value} is stale",
        "トラック{value}のノート置換は期限切れです",
        "트랙 {value}의 음표 교체가 만료되었습니다",
    ),
    "插入索引超出轨道 {value} 的范围": (
        "The insert index is outside track {value}",
        "挿入インデックスがトラック{value}の範囲外です",
        "삽입 인덱스가 트랙 {value} 범위를 벗어났습니다",
    ),
    "音符索引超出轨道 {value} 的范围": (
        "The note index is outside track {value}",
        "ノートインデックスがトラック{value}の範囲外です",
        "음표 인덱스가 트랙 {value} 범위를 벗어났습니다",
    ),
    "轨道 {value} 的索引音符操作已过期": (
        "The indexed-note operation for track {value} is stale",
        "トラック{value}のインデックス指定ノート操作は期限切れです",
        "트랙 {value}의 인덱스 음표 작업이 만료되었습니다",
    ),
    "轨道 {value} 存在重复的索引音符操作": (
        "Track {value} has a duplicate indexed-note operation",
        "トラック{value}に重複するインデックス指定ノート操作があります",
        "트랙 {value}에 중복된 인덱스 음표 작업이 있습니다",
    ),
    "操作写入了目标范围外的轨道：{value}": (
        "The operation writes outside the target scope: track {value}",
        "操作が対象範囲外のトラック{value}に書き込みます",
        "작업이 대상 범위 밖의 트랙 {value}에 기록됩니다",
    ),
    "轨道 {value} 的乐器替换已过期": (
        "The instrument replacement for track {value} is stale",
        "トラック{value}の楽器置換は期限切れです",
        "트랙 {value}의 악기 교체가 만료되었습니다",
    ),
    "音高 {value} 不受 BDO 乐器 {instrument_id} 支持": (
        "Pitch {value} is unsupported for BDO instrument {instrument_id}",
        "音高{value}はBDO楽器{instrument_id}でサポートされていません",
        "음높이 {value}은(는) BDO 악기 {instrument_id}에서 지원되지 않습니다",
    ),
    "ntype {value} 不受 BDO 乐器 {instrument_id} 支持": (
        "ntype {value} is unsupported for BDO instrument {instrument_id}",
        "ntype {value}はBDO楽器{instrument_id}でサポートされていません",
        "ntype {value}은(는) BDO 악기 {instrument_id}에서 지원되지 않습니다",
    ),
    "样本覆盖检查失败": (
        "Sample Coverage Check Failed",
        "サンプルカバレッジの確認に失敗しました",
        "샘플 커버리지 검사 실패",
    ),
    "弱显": ("Low Opacity", "弱く表示", "약하게 표시"),
    "深入": ("Deep", "高度", "심층"),
    "MIDI 解析": ("MIDI Parsing", "MIDI解析", "MIDI 파싱"),
    "存在未提交候选草稿": (
        "Unapplied Candidate Draft",
        "未適用の候補下書き",
        "미적용 후보 초안",
    ),
    "该声部会在 Apply 时与音符一起原子新建轨道。": (
        "This voice and its notes will create a new track atomically on Apply.",
        "「適用」時に、この声部と音符を含む新規トラックを一括作成します。",
        "적용할 때 이 성부와 음표를 포함한 새 트랙을 한 번에 만듭니다.",
    ),
    "选择目标轨；Apply 前不会修改工程：": (
        "Choose a target track; the project is unchanged until Apply:",
        "対象トラックを選択してください。「適用」まではプロジェクトを変更しません：",
        "대상 트랙을 선택하세요. 적용 전에는 프로젝트를 변경하지 않습니다:",
    ),
    "输入已有 {count} 个音符超出当前乐器映射；优化仅保留，不会新增，请在转换检查中处理。": (
        "The input already has {count} notes outside the current instrument mapping. Optimization preserves but does not add them; resolve them in Export Check.",
        "入力には現在の楽器マッピング範囲外のノートが{count}個あります。最適化では保持のみを行い、追加しません。書き出しチェックで対応してください。",
        "입력에 현재 악기 매핑을 벗어난 음표가 {count}개 있습니다. 최적화는 이를 유지하지만 새로 추가하지 않으므로 내보내기 검사에서 처리하세요.",
    ),
    "输入已有 {count} 个鼓音尚未规范为 BDO 48–64/type 99；优化仅保留，请在转换检查中处理。": (
        "The input already has {count} drum notes not normalized to BDO 48–64/type 99. Optimization preserves them; resolve them in Export Check.",
        "入力にはBDO 48～64／type 99へ正規化されていないドラムノートが{count}個あります。最適化では保持のみを行います。書き出しチェックで対応してください。",
        "입력에 BDO 48~64/type 99로 정규화되지 않은 드럼 음표가 {count}개 있습니다. 최적화는 이를 유지하므로 내보내기 검사에서 처리하세요.",
    ),
    "轨道效果发送量含超过当前游戏编辑范围 0–100 的导入值；未编辑项会原样保留。": (
        "Track AuxSend contains an imported value above the current in-game edit range of 0–100; unedited values are preserved.",
        "トラックのAuxSendに、現在のゲーム内編集範囲0～100を超える読み込み値があります。未編集の値はそのまま保持します。",
        "트랙 AuxSend에 현재 게임 내 편집 범위 0~100을 벗어난 가져오기 값이 있습니다. 편집하지 않은 값은 그대로 유지합니다.",
    ),
    "同一游戏乐器的 {track_count} 条轨道使用了不同效果发送量；游戏只保存一组发送量，请先统一。": (
        "{track_count} tracks for the same in-game instrument use different AuxSend values; the game stores one set, so make them consistent first.",
        "同じゲーム内楽器の{track_count}トラックでAuxSend値が異なります。ゲームには1組だけ保存されるため、先に統一してください。",
        "같은 게임 악기의 트랙 {track_count}개가 서로 다른 AuxSend 값을 사용합니다. 게임에는 한 세트만 저장되므로 먼저 통일하세요.",
    ),
    "贝斯高力度短音重击": (
        "Hard, high-velocity short bass attack",
        "ベースの高強度な短音アタック",
        "베이스의 강한 고벨로시티 짧은 어택",
    ),
    "高力度短时值贝斯重击": (
        "High-velocity, short-duration bass attack",
        "高強度・短音価のベースアタック",
        "고벨로시티의 짧은 베이스 어택",
    ),
    "请先应用、撤销或清除本次暂存，再更换音频或重新分析。": (
        "Apply, undo, or clear the pending changes before changing audio or analyzing again.",
        "今回の適用待ち内容を適用、元に戻す、または消去してから、オーディオ変更や再解析を行ってください。",
        "적용 대기 내용을 적용, 실행 취소 또는 지운 뒤 오디오를 변경하거나 다시 분석하세요.",
    ),
    "请先应用、撤销或清除本次暂存，再修改音频对齐。": (
        "Apply, undo, or clear the pending changes before changing audio alignment.",
        "今回の適用待ち内容を適用、元に戻す、または消去してから、オーディオ位置を変更してください。",
        "적용 대기 내용을 적용, 실행 취소 또는 지운 뒤 오디오 정렬을 변경하세요.",
    ),
    "当前仍有未提交候选草稿。请先应用，或撤销/清除本次暂存后再更换音频、调整偏移或重新分析。": (
        "There is an unapplied candidate draft. Apply it, or undo/clear the pending changes before changing audio, adjusting the offset, or analyzing again.",
        "未適用の候補下書きがあります。適用するか、適用待ち内容を元に戻す／消去してから、オーディオ変更、オフセット調整、再解析を行ってください。",
        "미적용 후보 초안이 있습니다. 적용하거나 적용 대기 내용을 실행 취소/지운 뒤 오디오 변경, 오프셋 조정 또는 재분석을 진행하세요.",
    ),
}

for _source, (_english, _japanese, _korean) in _REGIONAL_QUALITY_TRANSLATIONS.items():
    EN[_source] = _english
    JA[_source] = _japanese
    KO[_source] = _korean

del _source, _english, _japanese, _korean


if len(GM_PROGRAM_NAMES) != 128 or len(GM_PROGRAM_TRANSLATIONS) != 128:
    raise RuntimeError("General MIDI localization table must contain 128 programs")

for _source, (_english, _japanese, _korean) in zip(
    GM_PROGRAM_NAMES,
    GM_PROGRAM_TRANSLATIONS,
    strict=True,
):
    for _catalog, _translated in (
        (EN, _english),
        (JA, _japanese),
        (KO, _korean),
    ):
        _existing = _catalog.get(_source)
        if _existing is not None and _existing != _translated:
            raise RuntimeError(
                f"General MIDI source key collides with UI catalog: {_source!r}"
            )
        _catalog.setdefault(_source, _translated)

del _source, _english, _japanese, _korean, _catalog, _translated, _existing


def _translation_reverse_maps() -> dict[str, dict[str, str]]:
    """Build translated-text mappings when every candidate is equivalent.

    Synonymous source keys sometimes deliberately share the same wording. A
    duplicate is safe to reverse only when all candidates have the same full
    translation vector; choosing either source then produces identical text in
    every supported locale. Meaningful collisions remain deliberately absent.
    """

    reverse_maps: dict[str, dict[str, str]] = {}
    for language, catalog in TRANSLATIONS.items():
        candidates: dict[str, set[str]] = {}
        for source, translated in catalog.items():
            candidates.setdefault(str(translated), set()).add(str(source))
        reverse: dict[str, str] = {}
        for translated, sources in candidates.items():
            vectors = {
                tuple(
                    catalog_by_locale.get(source, source)
                    for catalog_by_locale in TRANSLATIONS.values()
                )
                for source in sources
            }
            if len(vectors) == 1:
                reverse[translated] = sorted(sources)[0]
        reverse_maps[language] = reverse
    return reverse_maps


_TRANSLATION_SOURCES = frozenset(EN)
_REVERSE_TRANSLATIONS = _translation_reverse_maps()


class Localizer(QObject):
    _FORMATTED_SOURCE_LIMIT = 2048
    _AMBIGUOUS_FORMATTED_SOURCE = object()

    def __init__(self, app: QApplication, language: str = "auto") -> None:
        super().__init__(app)
        self.app = app
        self.requested_language = (
            language
            if language in {code for code, _ in LANGUAGE_CHOICES}
            else "auto"
        )
        self.language = resolve_language(self.requested_language)
        self.sources: WeakKeyDictionary[QObject, dict[str, object]] = WeakKeyDictionary()
        self.formatted_sources: OrderedDict[
            str,
            tuple[str, dict[str, object]] | object,
        ] = OrderedDict()
        app.installEventFilter(self)

    def translate(self, text: str) -> str:
        return TRANSLATIONS.get(self.language, {}).get(text, text)

    def register_formatted_source(
        self,
        rendered: str,
        source_template: str,
        values: dict[str, object],
    ) -> None:
        """Remember a safe path back from one formatted UI string.

        A rendered string can occasionally be produced by two templates or by
        two different value sets.  Such collisions are deliberately marked
        ambiguous instead of guessing and rewriting user-provided text.
        """

        record = (source_template, dict(values))
        existing = self.formatted_sources.get(rendered)
        if existing is None:
            self.formatted_sources[rendered] = record
        elif existing is not self._AMBIGUOUS_FORMATTED_SOURCE:
            same_record = False
            try:
                same_record = existing == record
            except (TypeError, ValueError):
                same_record = False
            if not same_record:
                self.formatted_sources[rendered] = self._AMBIGUOUS_FORMATTED_SOURCE
        self.formatted_sources.move_to_end(rendered)
        while len(self.formatted_sources) > self._FORMATTED_SOURCE_LIMIT:
            self.formatted_sources.popitem(last=False)

    def _formatted_source(
        self,
        rendered: str,
    ) -> tuple[str, dict[str, object]] | object | None:
        if rendered not in self.formatted_sources:
            return None
        record = self.formatted_sources[rendered]
        if record is self._AMBIGUOUS_FORMATTED_SOURCE:
            return self._AMBIGUOUS_FORMATTED_SOURCE
        self.formatted_sources.move_to_end(rendered)
        template, values = record
        return template, dict(values)

    def set_language(self, language: str) -> None:
        previous_language = self.language
        self.requested_language = (
            language
            if language in {code for code, _ in LANGUAGE_CHOICES}
            else "auto"
        )
        self.language = resolve_language(self.requested_language)
        callback_seen: set[int] = set()
        for widget in self.app.topLevelWidgets():
            self.translate_tree(
                widget,
                source_language=previous_language,
                _callback_seen=callback_seen,
            )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Show and isinstance(watched, QWidget):
            # Constructors render their structured dynamic state once. Show
            # events only need to translate late-created Qt properties; rerun
            # dynamic analysis/report callbacks on an actual locale change.
            self.translate_tree(watched, _invoke_dynamic_callbacks=False)
        return False

    @staticmethod
    def _catalog_sources() -> frozenset[str]:
        return _TRANSLATION_SOURCES

    def _recover_source(self, text: str, language: str) -> str:
        """Recover a source key without rewriting unknown dynamic content."""

        if text in self._catalog_sources():
            return text
        source = _REVERSE_TRANSLATIONS.get(language, {}).get(text)
        if source is not None:
            return source
        # This handles widgets constructed with tr() immediately before a new
        # Localizer is installed.  Only a source that is unambiguous across all
        # catalogs is accepted; arbitrary user/plugin text remains untouched.
        candidates = {
            reverse[text]
            for reverse in _REVERSE_TRANSLATIONS.values()
            if text in reverse
        }
        return next(iter(candidates)) if len(candidates) == 1 else text

    def _translate_property(
        self,
        owner: QObject,
        key: str,
        getter,
        setter,
        *,
        source_language: str,
    ) -> None:
        source_data = self.sources.setdefault(owner, {})
        current = str(getter())
        previous = source_data.get(key)
        opaque = False
        if (
            isinstance(previous, dict)
            and current == str(previous.get("rendered", ""))
        ):
            source = str(previous.get("source", current))
            values = previous.get("values")
            formatted_values = dict(values) if isinstance(values, dict) else None
            opaque = bool(previous.get("opaque", False))
        else:
            # A property changed after the widget was shown.  It may contain a
            # raw Chinese source key, text already produced by tr(), or unknown
            # dynamic data.  Recover only the first two forms.
            formatted = self._formatted_source(current)
            if formatted is self._AMBIGUOUS_FORMATTED_SOURCE:
                # Two templates produced the same string. Treat it as opaque;
                # reverse-looking it up could turn plugin/user data such as
                # "Play" into the fixed source key "播放".
                source = current
                formatted_values = None
                opaque = True
            elif formatted is None:
                source = self._recover_source(current, source_language)
                formatted_values = None
            else:
                source, formatted_values = formatted
        rendered = current if opaque else self.translate(source)
        if formatted_values is not None:
            try:
                rendered = rendered.format(**formatted_values)
            except (KeyError, IndexError, ValueError):
                # Keep the exact current text if a plugin supplied a malformed
                # translated format.  Formatting must never lose dynamic data.
                rendered = current
        if current != rendered:
            setter(rendered)
        source_data[key] = {
            "source": source,
            "rendered": rendered,
            "language": self.language,
        }
        if formatted_values is not None:
            source_data[key]["values"] = formatted_values
        if opaque:
            source_data[key]["opaque"] = True

    def _translate_widget_properties(
        self,
        widget: QWidget,
        *,
        source_language: str,
    ) -> None:
        for key, getter, setter, skip_property in (
            ("tooltip", widget.toolTip, widget.setToolTip, "i18nSkipToolTip"),
            ("status_tip", widget.statusTip, widget.setStatusTip, "i18nSkipStatusTip"),
            ("whats_this", widget.whatsThis, widget.setWhatsThis, "i18nSkipWhatsThis"),
            (
                "accessible_name",
                widget.accessibleName,
                widget.setAccessibleName,
                "i18nSkipAccessibleName",
            ),
            (
                "accessible_description",
                widget.accessibleDescription,
                widget.setAccessibleDescription,
                "i18nSkipAccessibleDescription",
            ),
        ):
            if bool(widget.property(skip_property)):
                continue
            self._translate_property(
                widget,
                key,
                getter,
                setter,
                source_language=source_language,
            )

    def _translate_action(
        self,
        action: QAction,
        *,
        source_language: str,
    ) -> None:
        if bool(action.property("i18nSkip")):
            return
        for key, getter, setter, skip_property in (
            ("action_text", action.text, action.setText, "i18nSkipText"),
            ("action_tooltip", action.toolTip, action.setToolTip, "i18nSkipToolTip"),
            (
                "action_status_tip",
                action.statusTip,
                action.setStatusTip,
                "i18nSkipStatusTip",
            ),
            (
                "action_whats_this",
                action.whatsThis,
                action.setWhatsThis,
                "i18nSkipWhatsThis",
            ),
        ):
            if bool(action.property(skip_property)):
                continue
            self._translate_property(
                action,
                key,
                getter,
                setter,
                source_language=source_language,
            )

    def translate_tree(
        self,
        root: QWidget,
        *,
        source_language: str | None = None,
        _callback_seen: set[int] | None = None,
        _invoke_dynamic_callbacks: bool = True,
    ) -> None:
        input_language = source_language or self.language
        widgets = [root, *root.findChildren(QWidget)]
        for widget in widgets:
            if bool(widget.property("i18nSkip")):
                continue
            skip_text = bool(widget.property("i18nSkipText"))
            if isinstance(widget, (QMainWindow,)) or widget.isWindow():
                if not skip_text:
                    self._translate_property(
                        widget,
                        "window_title",
                        widget.windowTitle,
                        widget.setWindowTitle,
                        source_language=input_language,
                    )
            if (
                isinstance(widget, (QLabel, QAbstractButton, QGroupBox))
                and not skip_text
            ):
                self._translate_property(
                    widget,
                    "text",
                    widget.text,
                    widget.setText,
                    source_language=input_language,
                )
            if isinstance(widget, QMenu) and not skip_text:
                self._translate_property(
                    widget,
                    "menu_title",
                    widget.title,
                    widget.setTitle,
                    source_language=input_language,
                )
            self._translate_widget_properties(
                widget,
                source_language=input_language,
            )
            if isinstance(widget, QLineEdit):
                self._translate_property(
                    widget,
                    "placeholder",
                    widget.placeholderText,
                    widget.setPlaceholderText,
                    source_language=input_language,
                )
            if isinstance(widget, QSpinBox):
                self._translate_property(
                    widget,
                    "special",
                    widget.specialValueText,
                    widget.setSpecialValueText,
                    source_language=input_language,
                )
                self._translate_property(
                    widget,
                    "prefix",
                    widget.prefix,
                    widget.setPrefix,
                    source_language=input_language,
                )
                self._translate_property(
                    widget,
                    "suffix",
                    widget.suffix,
                    widget.setSuffix,
                    source_language=input_language,
                )
            if isinstance(widget, QComboBox) and not widget.property("i18nSkipItems"):
                raw_skip_indexes = widget.property("i18nSkipItemIndexes") or ()
                try:
                    skip_indexes = {int(index) for index in raw_skip_indexes}
                except TypeError:
                    skip_indexes = set()
                for index in range(widget.count()):
                    if index in skip_indexes:
                        continue
                    self._translate_property(
                        widget,
                        f"combo_item:{index}",
                        lambda item=index: widget.itemText(item),
                        lambda text, item=index: widget.setItemText(item, text),
                        source_language=input_language,
                    )
            if isinstance(widget, QTabWidget):
                for index in range(widget.count()):
                    self._translate_property(
                        widget,
                        f"tab_text:{index}",
                        lambda item=index: widget.tabText(item),
                        lambda text, item=index: widget.setTabText(item, text),
                        source_language=input_language,
                    )
                    self._translate_property(
                        widget,
                        f"tab_tooltip:{index}",
                        lambda item=index: widget.tabToolTip(item),
                        lambda text, item=index: widget.setTabToolTip(item, text),
                        source_language=input_language,
                    )
                    self._translate_property(
                        widget,
                        f"tab_whats_this:{index}",
                        lambda item=index: widget.tabWhatsThis(item),
                        lambda text, item=index: widget.setTabWhatsThis(item, text),
                        source_language=input_language,
                    )
            if isinstance(widget, QListWidget) and bool(
                widget.property("i18nTranslateItems")
            ):
                for index in range(widget.count()):
                    item = widget.item(index)
                    if item is None:
                        continue
                    for property_name, getter, setter in (
                        ("text", item.text, item.setText),
                        ("tooltip", item.toolTip, item.setToolTip),
                        ("status_tip", item.statusTip, item.setStatusTip),
                        ("whats_this", item.whatsThis, item.setWhatsThis),
                    ):
                        self._translate_property(
                            widget,
                            f"list_item:{index}:{property_name}",
                            getter,
                            setter,
                            source_language=input_language,
                        )
        menu_actions = {
            widget.menuAction()
            for widget in widgets
            if isinstance(widget, QMenu)
        }
        for action in root.findChildren(QAction):
            if action not in menu_actions:
                self._translate_action(
                    action,
                    source_language=input_language,
                )
        if not _invoke_dynamic_callbacks:
            return
        for widget in widgets:
            callback = getattr(widget, "retranslate_dynamic_content", None)
            identity = id(widget)
            if not callable(callback) or (
                _callback_seen is not None and identity in _callback_seen
            ):
                continue
            if _callback_seen is not None:
                _callback_seen.add(identity)
            try:
                callback()
            except Exception:
                _LOGGER.exception(
                    "Dynamic UI retranslation failed for %s",
                    type(widget).__name__,
                )


_localizer: Localizer | None = None


def install_localizer(app: QApplication, language: str = "auto") -> Localizer:
    global _localizer
    _localizer = Localizer(app, language)
    return _localizer


def localizer() -> Localizer | None:
    return _localizer


def tr(text: str) -> str:
    return _localizer.translate(text) if _localizer else text


def trf(text: str, /, **values: object) -> str:
    """Translate a stable template before interpolating dynamic UI values."""
    rendered = tr(text).format(**values)
    if _localizer is not None:
        _localizer.register_formatted_source(rendered, text, values)
    return rendered


def trv(text: str) -> TranslatableValue:
    """Mark one host-owned formatted value as translatable on live switches."""

    return TranslatableValue(text)


def trfv(text: str, /, **values: object) -> TranslatableFormatValue:
    """Defer one nested fixed template until its enclosing ``trf`` renders."""

    return TranslatableFormatValue(text, tuple(values.items()))


def tr_joinv(
    values: Iterable[object],
    separator: str = "、",
    *,
    translate_values: bool = False,
) -> TranslatableJoinedValue:
    """Defer list punctuation and optional host-owned item localization."""

    return TranslatableJoinedValue(
        tuple(values),
        separator,
        bool(translate_values),
    )


def defer_tr(value: object) -> object:
    """Preserve a rendered fixed message for later locale changes.

    Status models often outlive the label currently showing them. This helper
    recovers the source template registered by :func:`trf`, or a known source
    key rendered by :func:`tr`, while leaving unknown runtime text opaque.
    """

    if isinstance(
        value,
        (TranslatableValue, TranslatableFormatValue, TranslatableJoinedValue),
    ):
        return value
    rendered = str(value)
    if _localizer is not None:
        formatted = _localizer._formatted_source(rendered)
        if formatted is _localizer._AMBIGUOUS_FORMATTED_SOURCE:
            return rendered
        if formatted is not None:
            template, values = formatted
            return TranslatableFormatValue(template, tuple(values.items()))
        source = _localizer._recover_source(rendered, _localizer.language)
    else:
        source = rendered
    if source in _TRANSLATION_SOURCES:
        return TranslatableValue(source)
    return rendered
