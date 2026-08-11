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
from bdo_music_composer.core.gm_program_translations import GM_PROGRAM_TRANSLATIONS


_LOGGER = logging.getLogger(__name__)


LANGUAGES = (
    ("zh_CN", "简体中文"),
    ("zh_TW", "繁體中文"),
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
            if any(
                token in system_locale
                for token in ("zh_tw", "zh_hk", "zh_mo", "zh_hant")
            ):
                return "zh_TW"
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
    if any(token in normalized for token in ("asia/taipei", "taipei standard", "asia/hong/kong", "hong kong standard")):
        return "zh_TW"
    if any(token in normalized for token in ("asia/shanghai", "asia/chongqing", "china standard", "cst-china")):
        return "zh_CN"
    if any(token in normalized for token in ("asia/tokyo", "tokyo standard", "japan standard", "jst")):
        return "ja_JP"
    if any(token in normalized for token in ("asia/seoul", "korea standard", "kst")):
        return "ko_KR"
    return "en_US"


def resolve_language(language: str) -> str:
    return detect_language_from_timezone() if language == "auto" else language


# Compact character coverage for every Han character currently used by the
# Chinese source catalog. Phrase replacements run first to resolve contextual
# forms and common Taiwan desktop terminology; no runtime conversion package
# is required in source or frozen builds.
_SIMPLIFIED_CATALOG_CHARACTERS = '\u4e0e\u4e13\u4e22\u4e24\u4e25\u4e2a\u4e34\u4e3a\u4e50\u4e89\u4e8e\u4e91\u4ec5\u4ece\u4ef7\u4f18\u4f1a\u4f20\u4f2a\u4f53\u4fa7\u5170\u5173\u5185\u5199\u51b2\u51b5\u51c0\u51c6\u51cf\u51ef\u51fb\u5219\u521b\u5220\u522b\u52a1\u52a8\u52bf\u533a\u534f\u5355\u5360\u538b\u53c2\u53cc\u53d1\u53d8\u53e0\u53f0\u53f7\u540e\u5417\u542c\u542f\u5450\u54cd\u5522\u56f4\u56fd\u56fe\u5706\u5757\u5760\u58f0\u5904\u5907\u590d\u5934\u5939\u5b66\u5b9e\u5ba1\u5bbd\u5bf9\u5bfc\u5c06\u5c14\u5c42\u5c5e\u5cf0\u5e26\u5e2e\u5e72\u5e76\u5e93\u5e94\u5f00\u5f02\u5f03\u5f20\u5f2f\u5f39\u5f3a\u5f53\u5f55\u5f84\u6001\u603b\u613f\u620f\u6237\u6269\u626b\u626c\u62a4\u62a5\u62c5\u62e8\u62e9\u6362\u636e\u6447\u6491\u6570\u65ad\u65e0\u65e7\u65f6\u663e\u6682\u673a\u6743\u6761\u6765\u6781\u6784\u67aa\u6807\u6811\u6837\u6863\u68c0\u69db\u6a2a\u6c14\u6ca1\u6d4a\u6d4b\u6d4f\u6da6\u6e10\u6e29\u6e38\u6eda\u6ee1\u6ee4\u7075\u70b9\u72b6\u72ec\u732e\u739b\u73af\u73b0\u7535\u76d6\u76d8\u7801\u7840\u786e\u79bb\u79cd\u79d8\u79f0\u7a33\u7ad6\u7ade\u7b14\u7b5d\u7b7e\u7b80\u7bab\u7c7b\u7d27\u7ea6\u7ea7\u7eaf\u7eb9\u7ebf\u7ec4\u7ec6\u7ec7\u7ec8\u7ecf\u7ed1\u7ed3\u7ed8\u7edd\u7edf\u7ee7\u7eea\u7eed\u7ef4\u7f00\u7f13\u7f16\u7f29\u7f51\u7f57\u8054\u8111\u8282\u8303\u83b1\u8428\u8854\u88c5\u89c1\u89c4\u89c8\u89e6\u8ba1\u8ba4\u8ba8\u8ba9\u8bae\u8bb0\u8bb8\u8bba\u8bbe\u8bc1\u8bc6\u8bca\u8bcd\u8bd5\u8bdd\u8be5\u8be6\u8bed\u8bef\u8bf4\u8bf7\u8bfb\u8c03\u8c22\u8c23\u8c31\u8d1d\u8d1f\u8d21\u8d25\u8d26\u8d2f\u8d44\u8d56\u8d5b\u8dc3\u8f68\u8f6c\u8f6e\u8f6f\u8f74\u8f7b\u8f7d\u8f83\u8f85\u8f91\u8f93\u8fb9\u8fbe\u8fc7\u8fd0\u8fd8\u8fd9\u8fdb\u8fde\u8fdf\u9002\u9009\u9012\u90bb\u91c7\u91cc\u949f\u94a2\u94b9\u94c3\u94db\u94dc\u94f2\u94f6\u94fa\u94fe\u9500\u9501\u9510\u9519\u951a\u952e\u952f\u9572\u957f\u95e8\u95ed\u95ee\u95f4\u95f7\u9605\u9608\u961f\u9636\u9645\u9669\u968f\u9690\u9759\u9875\u9879\u987a\u987b\u9884\u9891\u9897\u9898\u989c\u989d\u98a4\u98ce\u9970\u9988\u9a6c\u9a8c\u9c7c\u9e1f\u9e23\u9f50\u9f7f\u9f99'
_TRADITIONAL_CATALOG_CHARACTERS = '\u8207\u5c08\u4e1f\u5169\u56b4\u500b\u81e8\u7232\u6a02\u722d\u65bc\u96f2\u50c5\u5f9e\u50f9\u512a\u6703\u50b3\u50de\u9ad4\u5074\u862d\u95dc\u5167\u5beb\u885d\u6cc1\u6de8\u6e96\u6e1b\u51f1\u64ca\u5247\u5275\u522a\u5225\u52d9\u52d5\u52e2\u5340\u5354\u55ae\u4f54\u58d3\u53c3\u96d9\u767c\u8b8a\u758a\u81fa\u865f\u5f8c\u55ce\u807d\u5553\u5436\u97ff\u55e9\u570d\u570b\u5716\u5713\u584a\u589c\u8072\u8655\u5099\u5fa9\u982d\u593e\u5b78\u5be6\u5be9\u5bec\u5c0d\u5c0e\u5c07\u723e\u5c64\u5c6c\u5cef\u5e36\u5e6b\u5e79\u4e26\u5eab\u61c9\u958b\u7570\u68c4\u5f35\u5f4e\u5f48\u5f37\u7576\u9304\u5f91\u614b\u7e3d\u9858\u6232\u6236\u64f4\u6383\u63da\u8b77\u5831\u64d4\u64a5\u64c7\u63db\u64da\u6416\u6490\u6578\u65b7\u7121\u820a\u6642\u986f\u66ab\u6a5f\u6b0a\u689d\u4f86\u6975\u69cb\u69cd\u6a19\u6a39\u6a23\u6a94\u6aa2\u6abb\u6a6b\u6c23\u6c92\u6fc1\u6e2c\u700f\u6f64\u6f38\u6eab\u904a\u6efe\u6eff\u6ffe\u9748\u9ede\u72c0\u7368\u737b\u746a\u74b0\u73fe\u96fb\u84cb\u76e4\u78bc\u790e\u78ba\u96e2\u7a2e\u7955\u7a31\u7a69\u8c4e\u7af6\u7b46\u7b8f\u7c64\u7c21\u7c2b\u985e\u7dca\u7d04\u7d1a\u7d14\u7d0b\u7dda\u7d44\u7d30\u7e54\u7d42\u7d93\u7d81\u7d50\u7e6a\u7d55\u7d71\u7e7c\u7dd2\u7e8c\u7dad\u7db4\u7de9\u7de8\u7e2e\u7db2\u7f85\u806f\u8166\u7bc0\u7bc4\u840a\u85a9\u929c\u88dd\u898b\u898f\u89bd\u89f8\u8a08\u8a8d\u8a0e\u8b93\u8b70\u8a18\u8a31\u8ad6\u8a2d\u8b49\u8b58\u8a3a\u8a5e\u8a66\u8a71\u8a72\u8a73\u8a9e\u8aa4\u8aaa\u8acb\u8b80\u8abf\u8b1d\u8b20\u8b5c\u8c9d\u8ca0\u8ca2\u6557\u8cec\u8cab\u8cc7\u8cf4\u8cfd\u8e8d\u8ecc\u8f49\u8f2a\u8edf\u8ef8\u8f15\u8f09\u8f03\u8f14\u8f2f\u8f38\u908a\u9054\u904e\u904b\u9084\u9019\u9032\u9023\u9072\u9069\u9078\u905e\u9130\u63a1\u88cf\u937e\u92fc\u9238\u9234\u943a\u9285\u93df\u9280\u92ea\u93c8\u92b7\u9396\u92b3\u932f\u9328\u9375\u92f8\u9454\u9577\u9580\u9589\u554f\u9593\u60b6\u95b1\u95be\u968a\u968e\u969b\u96aa\u96a8\u96b1\u975c\u9801\u9805\u9806\u9808\u9810\u983b\u9846\u984c\u984f\u984d\u986b\u98a8\u98fe\u994b\u99ac\u9a57\u9b5a\u9ce5\u9cf4\u9f4a\u9f52\u9f8d'

_TRADITIONAL_CHARACTER_TRANSLATION = str.maketrans(
    _SIMPLIFIED_CATALOG_CHARACTERS,
    _TRADITIONAL_CATALOG_CHARACTERS,
)
_TAIWAN_UI_PHRASES = {
    "为": "為",
    "文件路径": "檔案路徑",
    "文件格式": "檔案格式",
    "源文件": "來源檔案",
    "文件夹": "資料夾",
    "文件名": "檔名",
    "文件": "檔案",
    "转换检查": "匯出檢查",
    "导入": "匯入",
    "导出": "匯出",
    "加载": "載入",
    "读取": "讀取",
    "保存": "儲存",
    "设置": "設定",
    "默认": "預設",
    "项目": "專案",
    "工程": "專案",
    "打开": "開啟",
    "新建": "新增",
    "创建": "建立",
    "应用": "套用",
    "优化": "最佳化",
    "列表": "清單",
    "菜单": "選單",
    "按钮": "按鈕",
    "搜索": "搜尋",
    "刷新": "重新整理",
    "点击": "按一下",
    "双击": "按兩下",
    "右键": "按右鍵",
    "鼠标": "滑鼠",
    "界面": "介面",
    "窗口": "視窗",
    "用户": "使用者",
    "软件": "軟體",
    "硬件": "硬體",
    "音频": "音訊",
    "视频": "影片",
    "数据": "資料",
    "缓存": "快取",
    "内存": "記憶體",
    "后台": "背景",
    "程序": "程式",
    "进程": "處理程序",
    "线程": "執行緒",
    "网络": "網路",
    "链接": "連結",
    "兼容": "相容",
    "支持": "支援",
    "反馈": "回授",
    "曲谱": "樂譜",
    "轨道": "音軌",
    "复制": "複製",
    "剪切": "剪下",
    "粘贴": "貼上",
    "撤销": "復原",
    "本地": "本機",
    "分辨率": "解析度",
    "质量": "品質",
    "复选框": "核取方塊",
    "标签": "標籤",
    "签名": "簽名",
    "干声": "乾聲",
    "干净": "乾淨",
    "干扰": "干擾",
    "回收站": "資源回收筒",
    "产生": "產生",
    "摆动": "擺動",
    "重复": "重複",
    "调制": "調變",
}


def simplified_to_traditional_ui(text: str) -> str:
    """Return deterministic Taiwan-oriented UI copy without touching data."""

    converted = str(text)
    for source, translated in sorted(
        _TAIWAN_UI_PHRASES.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        converted = converted.replace(source, translated)
    return converted.translate(_TRADITIONAL_CHARACTER_TRANSLATION)


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
    "导入 MIDI": "Import MIDI", "打开工程": "Open Project", "新建项目": "New Project",
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
    "游戏参数 · 本地 FX 试听为未校准近似": "Game parameters · local FX preview is an uncalibrated approximation",
    "当前初级乐器在游戏中不提供 Effector/AuxSend；现有曲谱字节会原样保留。": "The game does not expose Effector/AuxSend for this beginner instrument; existing score bytes will be preserved unchanged.",
    "每轨发送在轨道 FX；本地试听为未校准近似，导出值不变。": "Per-track sends are under AuxSend; local preview is uncalibrated and export values remain unchanged.",
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
    "详细说明 ▾": "Details ▾",
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
    "导入 MIDI": "MIDIを読み込む", "打开工程": "プロジェクトを開く", "新建项目": "新規プロジェクト",
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
    "游戏参数 · 本地 FX 试听为未校准近似": "ゲーム設定 · ローカルFX試聴は未校正の近似です",
    "当前初级乐器在游戏中不提供 Effector/AuxSend；现有曲谱字节会原样保留。": "この初心者用楽器ではゲームのEffector/AuxSendを使用できません。既存の楽譜バイトは変更せず保持します。",
    "每轨发送在轨道 FX；本地试听为未校准近似，导出值不变。": "トラックごとの送信量はAuxSendで設定します。ローカル試聴は未校正の近似で、書き出し値は変わりません。",
    "导入原值 {value}；修改后按 0–100 写入。": "読み込み値 {value}。編集後は0～100で保存します。",
    "深度": "深さ", "频率": "周波数",
    "保存设置": "設定を保存", "界面语言": "表示言語",
    "仅用于本机近似试听，不会写入曲谱，也不会上传。": "ローカルでの近似試聴だけに使用し、楽譜への書き込みやアップロードは行いません。",
    "优化等级": "最適化レベル", "曲风": "スタイル", "歌词表达": "歌詞表現",
    "游戏安全优化": "ゲーム安全最適化", "自动识别曲风": "スタイルを自動判定",
    "分析奏法": "奏法を分析", "轻微自然化": "軽いヒューマナイズ", "声音效果": "サウンドエフェクト",
    "修复音块": "ノートを修復", "平衡力度": "ベロシティを調整", "乐理分析（保守）": "楽理分析（保守的）",
    "柔性对齐": "ソフトクオンタイズ", "应用游戏安全优化": "ゲーム安全最適化を適用",
    "详细说明 ▸": "詳細 ▸", "详细说明 ▾": "詳細 ▾",
    "转换检查": "書き出しチェック", "复制报告": "レポートをコピー",
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
    "导入 MIDI": "MIDI 가져오기", "打开工程": "프로젝트 열기", "新建项目": "새 프로젝트",
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
    "游戏参数 · 本地 FX 试听为未校准近似": "게임 설정 · 로컬 FX 미리듣기는 보정되지 않은 근사치",
    "当前初级乐器在游戏中不提供 Effector/AuxSend；现有曲谱字节会原样保留。": "이 초보자용 악기는 게임에서 Effector/AuxSend를 제공하지 않습니다. 기존 악보 바이트는 변경 없이 보존됩니다.",
    "每轨发送在轨道 FX；本地试听为未校准近似，导出值不变。": "트랙별 전송량은 AuxSend에서 설정합니다. 로컬 미리듣기는 보정되지 않은 근사치이며 내보내기 값은 바뀌지 않습니다.",
    "导入原值 {value}；修改后按 0–100 写入。": "가져온 값 {value}; 수정 후에는 0~100으로 저장합니다.",
    "深度": "깊이", "频率": "주파수",
    "保存设置": "설정 저장", "界面语言": "인터페이스 언어",
    "仅用于本机近似试听，不会写入曲谱，也不会上传。": "로컬 근사 미리듣기에만 사용하며 악보에 기록하거나 업로드하지 않습니다.",
    "优化等级": "최적화 수준", "曲风": "스타일", "歌词表达": "가사 표현",
    "游戏安全优化": "게임 안전 최적화", "自动识别曲风": "스타일 자동 감지",
    "分析奏法": "주법 분석", "轻微自然化": "가벼운 휴머니즈", "声音效果": "사운드 효과",
    "修复音块": "노트 복구", "平衡力度": "벨로시티 균형", "乐理分析（保守）": "음악 이론 분석(보수적)",
    "柔性对齐": "소프트 퀀타이즈", "应用游戏安全优化": "게임 안전 최적화 적용",
    "详细说明 ▸": "상세 ▸", "详细说明 ▾": "상세 ▾",
    "转换检查": "내보내기 검사", "复制报告": "보고서 복사",
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
    "选择音源包…": "Choose Sample Pack…",
    "内置通用音源": "Built-in General Source",
    "配套近似音源": "Companion Approximate Source",
    "自选音源包": "Custom Sample Pack",
    "管理音源包…": "Manage Sample Packs…",
    "音源包路径": "Sample Pack Path",
    "定位配套包": "Locate Companion Pack",
    "配套近似音源不可用": "Companion Approximate Source Unavailable",
    "自选音源包不可用": "Custom Sample Pack Unavailable",
    "当前音源包无法试听：{reason}": "The current sample pack cannot preview: {reason}",
    "请先选择一个 .bdosamples 音源包。": "Select a .bdosamples sample pack first.",
    "音乐参考": "Music Reference",
    "在当前音符编辑器中显示音乐参考、分析证据、候选和参考波形": "Show music-reference evidence, candidates, and the aligned waveform in this note editor",
    "当前工程没有可用于音乐参考的旋律乐器轨，请先新建乐器轨。": "This project has no melodic instrument track for Music Reference. Create one first.",
    "选择音乐参考目标轨": "Choose Music Reference Track",
    "音乐参考已收起；草稿保持可编辑，点击“完成”后写回项目。": "Music Reference is hidden. The draft remains editable and is written back when you click Finish.",
    "节奏整理": "Rhythm Cleanup",
    "自动网格": "Auto Grid",
    "严格 1/64": "Strict 1/64",
    "自动网格优先选择能解释乐句的最粗网格；严格模式将起止点统一投影到1/64": (
        "Auto Grid chooses the coarsest grid that explains the phrase; Strict "
        "projects starts and ends to 1/64"
    ),
    "显示整理后": "Show Aligned",
    "显示节奏整理后的参考音块": "Show rhythm-aligned reference notes",
    "关闭后显示原始识别时间；不会删除节奏整理结果": (
        "Turn off to show original detected timing; the alignment is retained"
    ),
    "自动检测速度和第一拍，将参考音块投影到最合适的1/4–1/64或三连音网格；可随时切回原始识别时间": (
        "Detect tempo and first beat, then project reference notes to the best "
        "1/4–1/64 or triplet grid; original timing remains available"
    ),
    "节奏整理中…": "Aligning Rhythm…",
    "已对齐 {count}": "Aligned {count}",
    "检测 BPM {bpm} · 置信 {confidence}% · 点击重新整理；参考音块菜单可切换原始/整理后时间": (
        "Detected BPM {bpm} · Confidence {confidence}% · Click to realign; "
        "switch original/aligned timing in the reference-note menu"
    ),
    "节奏整理完成 · 对齐 {aligned} · 检测 BPM {bpm} · 置信 {confidence}% · 合并复核 {merged} · 弱音复核 {suppressed}；原始识别结果仍可恢复。": (
        "Rhythm cleanup complete · Aligned {aligned} · Detected BPM {bpm} · "
        "Confidence {confidence}% · Merge reviews {merged} · Weak-note reviews "
        "{suppressed}; original detections remain recoverable."
    ),
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
    "这两项仅用于下一次 MIDI 导入；不会重新解析或覆盖当前工程。": "These options apply only to the next MIDI import; they never reparse or overwrite the current project.",
    "选择后会写入当前音符力度；导出阶段不会再做隐藏处理。": "Choosing a mode writes it into current note velocities; export applies no hidden processing.",
    "数值范围为 0–100；设为 0 即不写入对应效果。": "Values range from 0–100; zero disables the corresponding effect.",
    "轨道 FX 设置每轨发送；此页设置共享主效果。": "Track FX sets per-track sends; this page configures the shared master effects.",
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
    "优化范围": "Optimization Scope", "整个工程": "Entire Project",
    "选择作用范围，分析预览后再应用；不会跳过游戏安全校验。": "Choose a scope, analyze the preview, then apply it; game-safety validation is never skipped.",
    "单轨 · Track {track_id} · {track}": "Single Track · Track {track_id} · {track}",
    "整个工程 · 可写轨道 {selected}/{total} · 可调整全局效果": "Entire Project · Writable Tracks {selected}/{total} · Global Effects Allowed",
    "单轨 · Track {track_id} · 读取全曲上下文 · 不修改全局效果": "Single Track · Track {track_id} · Full-Song Context · No Global Effects",
    "全局模式读取全部轨道；静音和独奏不改变作用域，可在“详细信息”中限制允许写入的轨道。": "Global mode reads every track; Mute and Solo do not change scope. Limit writable tracks under Details.",
    "范围锁定为当前草稿轨道；读取全曲上下文，但只写入该轨道。": "Scope is locked to the current draft track; full-song context is read, but only this track is modified.",
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
    "选择音源包…": "音源パックを選択…",
    "内置通用音源": "内蔵汎用音源",
    "配套近似音源": "コンパニオン近似音源",
    "自选音源包": "カスタム音源パック",
    "管理音源包…": "音源パックを管理…",
    "音源包路径": "音源パックのパス",
    "定位配套包": "コンパニオンパックを指定",
    "配套近似音源不可用": "コンパニオン近似音源を使用できません",
    "自选音源包不可用": "カスタム音源パックを使用できません",
    "当前音源包无法试听：{reason}": "現在の音源パックを試聴できません：{reason}",
    "请先选择一个 .bdosamples 音源包。": ".bdosamples 音源パックを先に選択してください。",
    "音乐参考": "音楽リファレンス",
    "在当前音符编辑器中显示音乐参考、分析证据、候选和参考波形": "このノートエディターに音楽リファレンス、解析証拠、候補、参照波形を表示します",
    "当前工程没有可用于音乐参考的旋律乐器轨，请先新建乐器轨。": "音楽リファレンスに使えるメロディ楽器トラックがありません。先に作成してください。",
    "选择音乐参考目标轨": "音楽リファレンストラックを選択",
    "音乐参考已收起；草稿保持可编辑，点击“完成”后写回项目。": "音楽リファレンスを閉じました。下書きは編集可能で、「完了」を押すとプロジェクトへ反映されます。",
    "节奏整理": "リズム整理",
    "自动网格": "自動グリッド",
    "严格 1/64": "厳密 1/64",
    "自动网格优先选择能解释乐句的最粗网格；严格模式将起止点统一投影到1/64": (
        "自動グリッドはフレーズを説明できる最も粗いグリッドを選び、厳密モードは開始・終了を1/64に揃えます"
    ),
    "显示整理后": "整理後を表示",
    "显示节奏整理后的参考音块": "リズム整理後の参照音符を表示",
    "关闭后显示原始识别时间；不会删除节奏整理结果": (
        "オフにすると元の検出タイミングを表示します。整理結果は保持されます"
    ),
    "自动检测速度和第一拍，将参考音块投影到最合适的1/4–1/64或三连音网格；可随时切回原始识别时间": (
        "テンポと第1拍を検出し、参照音符を最適な1/4～1/64または3連符グリッドに配置します"
    ),
    "节奏整理中…": "リズム整理中…",
    "已对齐 {count}": "整列済み {count}",
    "检测 BPM {bpm} · 置信 {confidence}% · 点击重新整理；参考音块菜单可切换原始/整理后时间": (
        "検出BPM {bpm}・信頼度 {confidence}%・クリックで再整理。参照音符メニューで元/整理後を切替"
    ),
    "节奏整理完成 · 对齐 {aligned} · 检测 BPM {bpm} · 置信 {confidence}% · 合并复核 {merged} · 弱音复核 {suppressed}；原始识别结果仍可恢复。": (
        "リズム整理完了・整列 {aligned}・検出BPM {bpm}・信頼度 {confidence}%・"
        "結合確認 {merged}・弱音確認 {suppressed}。元の検出結果は復元できます。"
    ),
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
    "这两项仅用于下一次 MIDI 导入；不会重新解析或覆盖当前工程。": "この2項目は次回のMIDI読み込みにのみ適用され、現在のプロジェクトを再解析または上書きしません。",
    "选择后会写入当前音符力度；导出阶段不会再做隐藏处理。": "選択した処理は現在の音符ベロシティに書き込まれ、書き出し時に隠れた処理は行いません。",
    "数值范围为 0–100；设为 0 即不写入对应效果。": "値は0～100です。0にすると対応するエフェクトを書き込みません。",
    "轨道 FX 设置每轨发送；此页设置共享主效果。": "トラックFXはトラックごとの送信量を設定し、このページでは共有マスターエフェクトを設定します。",
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
    "优化范围": "最適化範囲", "整个工程": "プロジェクト全体",
    "选择作用范围，分析预览后再应用；不会跳过游戏安全校验。": "対象範囲を選び、プレビューを解析してから適用します。ゲーム安全検証は省略されません。",
    "单轨 · Track {track_id} · {track}": "単一トラック · Track {track_id} · {track}",
    "整个工程 · 可写轨道 {selected}/{total} · 可调整全局效果": "プロジェクト全体 · 書き込み可能 {selected}/{total} · 全体エフェクト変更可",
    "单轨 · Track {track_id} · 读取全曲上下文 · 不修改全局效果": "単一トラック · Track {track_id} · 全曲コンテキスト参照 · 全体エフェクト変更なし",
    "全局模式读取全部轨道；静音和独奏不改变作用域，可在“详细信息”中限制允许写入的轨道。": "全体モードは全トラックを参照します。Mute/Soloは範囲に影響せず、［詳細］で書き込み可能トラックを制限できます。",
    "范围锁定为当前草稿轨道；读取全曲上下文，但只写入该轨道。": "範囲は現在の下書きトラックに固定されています。全曲を参照しますが、このトラックだけを変更します。",
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
    "选择音源包…": "음원 팩 선택…",
    "内置通用音源": "내장 범용 음원",
    "配套近似音源": "동반 근사 음원",
    "自选音源包": "사용자 음원 팩",
    "管理音源包…": "음원 팩 관리…",
    "音源包路径": "음원 팩 경로",
    "定位配套包": "동반 팩 찾기",
    "配套近似音源不可用": "동반 근사 음원을 사용할 수 없음",
    "自选音源包不可用": "사용자 음원 팩을 사용할 수 없음",
    "当前音源包无法试听：{reason}": "현재 음원 팩을 미리들을 수 없습니다: {reason}",
    "请先选择一个 .bdosamples 音源包。": "먼저 .bdosamples 음원 팩을 선택하세요.",
    "音乐参考": "음악 참조",
    "在当前音符编辑器中显示音乐参考、分析证据、候选和参考波形": "현재 음표 편집기에 음악 참조, 분석 근거, 후보 및 참조 파형을 표시합니다",
    "当前工程没有可用于音乐参考的旋律乐器轨，请先新建乐器轨。": "음악 참조에 사용할 멜로디 악기 트랙이 없습니다. 먼저 생성하세요.",
    "选择音乐参考目标轨": "음악 참조 트랙 선택",
    "音乐参考已收起；草稿保持可编辑，点击“完成”后写回项目。": "음악 참조를 숨겼습니다. 초안은 계속 편집할 수 있으며 '완료'를 누르면 프로젝트에 반영됩니다.",
    "节奏整理": "리듬 정리",
    "自动网格": "자동 그리드",
    "严格 1/64": "엄격 1/64",
    "自动网格优先选择能解释乐句的最粗网格；严格模式将起止点统一投影到1/64": (
        "자동 그리드는 악구를 설명하는 가장 성긴 그리드를 선택하고 엄격 모드는 시작과 끝을 1/64에 맞춥니다"
    ),
    "显示整理后": "정리 후 표시",
    "显示节奏整理后的参考音块": "리듬 정리된 참조 음표 표시",
    "关闭后显示原始识别时间；不会删除节奏整理结果": (
        "끄면 원래 감지 시간을 표시하며 정리 결과는 유지됩니다"
    ),
    "自动检测速度和第一拍，将参考音块投影到最合适的1/4–1/64或三连音网格；可随时切回原始识别时间": (
        "템포와 첫 박을 감지해 참조 음표를 최적의 1/4–1/64 또는 셋잇단음표 그리드에 맞춥니다"
    ),
    "节奏整理中…": "리듬 정리 중…",
    "已对齐 {count}": "정렬 {count}",
    "检测 BPM {bpm} · 置信 {confidence}% · 点击重新整理；参考音块菜单可切换原始/整理后时间": (
        "감지 BPM {bpm} · 신뢰도 {confidence}% · 클릭해 다시 정리; 참조 음표 메뉴에서 원본/정리 후 전환"
    ),
    "节奏整理完成 · 对齐 {aligned} · 检测 BPM {bpm} · 置信 {confidence}% · 合并复核 {merged} · 弱音复核 {suppressed}；原始识别结果仍可恢复。": (
        "리듬 정리 완료 · 정렬 {aligned} · 감지 BPM {bpm} · 신뢰도 {confidence}% · "
        "병합 검토 {merged} · 약한 음 검토 {suppressed}; 원본 감지 결과를 복원할 수 있습니다."
    ),
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
    "这两项仅用于下一次 MIDI 导入；不会重新解析或覆盖当前工程。": "이 두 옵션은 다음 MIDI 가져오기에만 적용되며 현재 프로젝트를 다시 분석하거나 덮어쓰지 않습니다.",
    "选择后会写入当前音符力度；导出阶段不会再做隐藏处理。": "선택한 처리는 현재 음표 벨로시티에 기록되며 내보낼 때 숨겨진 처리를 하지 않습니다.",
    "数值范围为 0–100；设为 0 即不写入对应效果。": "값 범위는 0–100이며 0이면 해당 효과를 기록하지 않습니다.",
    "轨道 FX 设置每轨发送；此页设置共享主效果。": "트랙 FX에서 트랙별 전송량을 설정하고 이 페이지에서 공유 마스터 이펙트를 설정합니다.",
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
    "优化范围": "최적화 범위", "整个工程": "전체 프로젝트",
    "选择作用范围，分析预览后再应用；不会跳过游戏安全校验。": "범위를 선택하고 미리보기를 분석한 뒤 적용합니다. 게임 안전 검증은 생략되지 않습니다.",
    "单轨 · Track {track_id} · {track}": "단일 트랙 · Track {track_id} · {track}",
    "整个工程 · 可写轨道 {selected}/{total} · 可调整全局效果": "전체 프로젝트 · 쓰기 가능 트랙 {selected}/{total} · 전체 효과 조정 가능",
    "单轨 · Track {track_id} · 读取全曲上下文 · 不修改全局效果": "단일 트랙 · Track {track_id} · 전체 곡 맥락 참조 · 전체 효과 변경 없음",
    "全局模式读取全部轨道；静音和独奏不改变作用域，可在“详细信息”中限制允许写入的轨道。": "전체 모드는 모든 트랙을 참조합니다. 음소거와 Solo는 범위를 바꾸지 않으며 세부 정보에서 쓰기 가능한 트랙을 제한할 수 있습니다.",
    "范围锁定为当前草稿轨道；读取全曲上下文，但只写入该轨道。": "범위가 현재 초안 트랙으로 고정됩니다. 전체 곡 맥락을 읽지만 이 트랙만 변경합니다.",
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
    "触控板双指滑动：平移；Ctrl+滚轮：时间缩放；Alt+滚轮：音块高度": "Two-finger touchpad scroll: pan; Ctrl+wheel: time zoom; Alt+wheel: note height",
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
    "触控板双指滑动：平移；Ctrl+滚轮：时间缩放；Alt+滚轮：音块高度": "タッチパッドを2本指でスクロール：移動；Ctrl+ホイール：時間ズーム；Alt+ホイール：音符の高さ",
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
    "触控板双指滑动：平移；Ctrl+滚轮：时间缩放；Alt+滚轮：音块高度": "터치패드 두 손가락 스크롤: 이동; Ctrl+휠: 시간 확대/축소; Alt+휠: 음표 높이",
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
    "以此轨统一同乐器音量和 FX": "Use this track to unify same-instrument Volume and FX",
    "无法同步游戏乐器音量：{error}": "Cannot sync game-instrument Volume: {error}",
    "已同步 {count} 条同乐器轨道的游戏音量": "Synced game Volume to {count} same-instrument tracks",
    "所选轨道的游戏混音数据无效：{error}": "The selected track has invalid game mixer data: {error}",
    "无法统一游戏乐器混音：{error}": "Cannot unify the game-instrument mixer: {error}",
    "同乐器轨道已经一致": "Same-instrument tracks are already consistent",
    "已按所选轨道统一 {count} 条同乐器轨道": "Unified {count} same-instrument tracks from the selected track",
    "目标游戏乐器存在混音冲突：{error}": "The target game instrument has mixer conflicts: {error}",
    "已采用目标游戏乐器的共享音量和 FX": "Adopted the target game instrument's shared Volume and FX",
    "无法新建同乐器轨道：{error}": "Cannot create a same-instrument track: {error}",
    "无法同步游戏乐器 FX：{error}": "Cannot sync game-instrument FX: {error}",
    "当前工程没有可导出的轨道": "The current project has no exportable tracks",
    "保持原力度": "Preserve original velocity",
    "工程轨道数据无效：{error}": "The project track data is invalid: {error}",
    "工程未保存原 MIDI 的拍号分母，且源文件已不可用；已阻止导出以避免静默写入错误拍号。": "The project did not save the original MIDI meter denominator and the source is unavailable; export was blocked to prevent writing an incorrect meter.",
})
JA.update({
    "以此轨统一同乐器音量和 FX": "このトラックで同一楽器の音量とFXを統一",
    "无法同步游戏乐器音量：{error}": "ゲーム楽器の音量を同期できません：{error}",
    "已同步 {count} 条同乐器轨道的游戏音量": "同一楽器の{count}トラックにゲーム音量を同期しました",
    "所选轨道的游戏混音数据无效：{error}": "選択トラックのゲームミキサーデータが無効です：{error}",
    "无法统一游戏乐器混音：{error}": "ゲーム楽器のミキサーを統一できません：{error}",
    "同乐器轨道已经一致": "同一楽器のトラックはすでに一致しています",
    "已按所选轨道统一 {count} 条同乐器轨道": "選択トラックを基準に同一楽器の{count}トラックを統一しました",
    "目标游戏乐器存在混音冲突：{error}": "対象ゲーム楽器のミキサーに競合があります：{error}",
    "已采用目标游戏乐器的共享音量和 FX": "対象ゲーム楽器の共有音量とFXを適用しました",
    "无法新建同乐器轨道：{error}": "同一楽器のトラックを作成できません：{error}",
    "无法同步游戏乐器 FX：{error}": "ゲーム楽器のFXを同期できません：{error}",
    "当前工程没有可导出的轨道": "現在のプロジェクトには書き出せるトラックがありません",
    "保持原力度": "元のベロシティを保持",
    "工程轨道数据无效：{error}": "プロジェクトのトラックデータが無効です：{error}",
    "工程未保存原 MIDI 的拍号分母，且源文件已不可用；已阻止导出以避免静默写入错误拍号。": "元のMIDIの拍子分母が保存されておらず、ソースも利用できないため、誤った拍子の書き込みを防ぐため書き出しを停止しました。",
})
KO.update({
    "以此轨统一同乐器音量和 FX": "이 트랙 기준으로 같은 악기의 음량과 FX 통일",
    "无法同步游戏乐器音量：{error}": "게임 악기 음량을 동기화할 수 없음: {error}",
    "已同步 {count} 条同乐器轨道的游戏音量": "같은 악기 {count}개 트랙에 게임 음량을 동기화함",
    "所选轨道的游戏混音数据无效：{error}": "선택한 트랙의 게임 믹서 데이터가 잘못됨: {error}",
    "无法统一游戏乐器混音：{error}": "게임 악기 믹서를 통일할 수 없음: {error}",
    "同乐器轨道已经一致": "같은 악기 트랙이 이미 일치함",
    "已按所选轨道统一 {count} 条同乐器轨道": "선택한 트랙 기준으로 같은 악기 {count}개 트랙을 통일함",
    "目标游戏乐器存在混音冲突：{error}": "대상 게임 악기에 믹서 충돌이 있음: {error}",
    "已采用目标游戏乐器的共享音量和 FX": "대상 게임 악기의 공유 음량과 FX를 적용함",
    "无法新建同乐器轨道：{error}": "같은 악기 트랙을 만들 수 없음: {error}",
    "无法同步游戏乐器 FX：{error}": "게임 악기 FX를 동기화할 수 없음: {error}",
    "当前工程没有可导出的轨道": "현재 프로젝트에 내보낼 트랙이 없음",
    "保持原力度": "원래 벨로시티 유지",
    "工程轨道数据无效：{error}": "프로젝트 트랙 데이터가 잘못됨: {error}",
    "工程未保存原 MIDI 的拍号分母，且源文件已不可用；已阻止导出以避免静默写入错误拍号。": "프로젝트에 원본 MIDI 박자표 분모가 저장되지 않았고 소스도 사용할 수 없어 잘못된 박자표 기록을 막기 위해 내보내기를 중단했습니다.",
})
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
    "许可证": "License",
    "自动扒谱、音频与科学计算": "Automatic Transcription, Audio, and Scientific Computing",
    "应用运行、界面与打包": "Application Runtime, UI, and Packaging",
    "格式研究、引用与开发协作": "Format Research, References, and Development Collaboration",
    "仅作引用；采用上游条款": "Reference only; upstream terms apply",
    "仅作引用；未捆绑代码": "Reference only; no code is bundled",
    "开发致谢；无运行时依赖": "Development acknowledgement; no runtime dependency",
    "Basic Pitch 代码与模型许可": "Basic Pitch Code and Model License",
    "Basic Pitch 0.4.0 的代码、随包 nmp.onnx、LICENSE 与 NOTICE 位于同一官方发行树；未发现模型目录中的单独限制性许可证。按 Apache-2.0 再分发时必须附带 LICENSE 并保留 NOTICE。": (
        "Basic Pitch 0.4.0 keeps its code, bundled nmp.onnx, LICENSE, and NOTICE "
        "in the same official release tree; no separate restrictive license was "
        "found in the model directory. Apache-2.0 redistribution must include "
        "the LICENSE and preserve the NOTICE."
    ),
    "论文引用": "Research Citation",
    "论文": "Paper",
    "社区、测试与音乐交流": "Community, Testing, and Music Exchange",
    "本程序未内置 OpenAI API 或云端模型；OpenAI 仅列为开发协作致谢。": (
        "This app does not embed the OpenAI API or any cloud model; OpenAI is "
        "acknowledged only for development collaboration."
    ),
    "完整许可清单": "Complete License Inventory",
    "这里是便于阅读的致谢；每次构建仍会生成并随 EXE 嵌入完整的依赖、许可证、NOTICE 与二进制哈希清单。": (
        "This is a readable acknowledgement list. Every build still generates "
        "and embeds in the EXE a complete dependency, license, NOTICE, and "
        "binary-hash inventory."
    ),
})

_DRUM_LANE_TRANSLATIONS = {
    "底鼓": ("Kick", "バスドラム", "베이스 드럼"),
    "原声底鼓": ("Acoustic kick", "アコースティックバスドラム", "어쿠스틱 베이스 드럼"),
    "小军鼓边击": ("Snare side hit", "スネアサイド", "스네어 사이드 히트"),
    "鼓边轻击": ("Side stick", "サイドスティック", "사이드 스틱"),
    "小军鼓": ("Snare", "スネア", "스네어"),
    "鼓边重击": ("Drum rim shot", "ドラム・リムショット", "드럼 림 샷"),
    "小军鼓复击": ("Snare flam", "スネアフラム", "스네어 플램"),
    "拍手": ("Hand clap", "ハンドクラップ", "핸드 클랩"),
    "电子小军鼓": ("Electric snare", "エレクトリックスネア", "일렉트릭 스네어"),
    "嗵鼓 1": ("Tom 1", "タム 1", "탐 1"),
    "嗵鼓 2": ("Tom 2", "タム 2", "탐 2"),
    "嗵鼓 3": ("Tom 3", "タム 3", "탐 3"),
    "嗵鼓 4": ("Tom 4", "タム 4", "탐 4"),
    "嗵鼓 5": ("Tom 5", "タム 5", "탐 5"),
    "低音落地嗵鼓": ("Low floor tom", "ロー・フロアタム", "로우 플로어 탐"),
    "高音落地嗵鼓": ("High floor tom", "ハイ・フロアタム", "하이 플로어 탐"),
    "低音嗵鼓": ("Low tom", "ロータム", "로우 탐"),
    "中低音嗵鼓": ("Low-mid tom", "ロー・ミッドタム", "로우 미드 탐"),
    "中高音嗵鼓": ("Hi-mid tom", "ハイ・ミッドタム", "하이 미드 탐"),
    "高音嗵鼓": ("High tom", "ハイタム", "하이 탐"),
    "闭合踩镲": ("Closed hi-hat", "クローズド・ハイハット", "드럼 클로즈드 하이햇"),
    "脚踩踩镲": ("Pedal hi-hat", "ペダル・ハイハット", "페달 하이햇"),
    "开放踩镲": ("Open hi-hat", "オープン・ハイハット", "드럼 오픈 하이햇"),
    "碎音镲": ("Crash cymbal", "クラッシュシンバル", "크래시 심벌"),
    "碎音镲 1": ("Crash cymbal 1", "クラッシュシンバル 1", "크래시 심벌 1"),
    "碎音镲 2": ("Crash cymbal 2", "クラッシュシンバル 2", "크래시 심벌 2"),
    "节奏镲": ("Ride cymbal", "ライドシンバル", "라이드 심벌"),
    "节奏镲 1": ("Ride cymbal 1", "ライドシンバル 1", "라이드 심벌 1"),
    "节奏镲 2": ("Ride cymbal 2", "ライドシンバル 2", "라이드 심벌 2"),
    "中国镲": ("Chinese cymbal", "チャイナシンバル", "차이나 심벌"),
    "镲帽": ("Ride bell", "ライドベル", "라이드 벨"),
    "铃鼓": ("Tambourine", "タンバリン", "탬버린"),
    "水镲": ("Splash cymbal", "スプラッシュシンバル", "스플래시 심벌"),
    "牛铃": ("Cowbell", "カウベル", "카우벨"),
    "颤音器": ("Vibra slap", "ビブラスラップ", "비브라 슬랩"),
    "高音邦戈鼓": ("High bongo", "ハイボンゴ", "하이 봉고"),
    "低音邦戈鼓": ("Low bongo", "ローボンゴ", "로우 봉고"),
    "小军鼓短滚奏": ("Short snare roll", "スネア・ショートロール", "스네어 쇼트 롤"),
    "小军鼓长滚奏": ("Long snare roll", "スネア・ロングロール", "스네어 롱 롤"),
}
for _source, (_english, _japanese, _korean) in _DRUM_LANE_TRANSLATIONS.items():
    EN[_source] = _english
    JA[_source] = _japanese
    KO[_source] = _korean
del _source, _english, _japanese, _korean

JA.update({
    "许可证": "ライセンス",
    "自动扒谱、音频与科学计算": "自動採譜・オーディオ・科学計算",
    "应用运行、界面与打包": "アプリ実行環境・UI・パッケージング",
    "格式研究、引用与开发协作": "形式研究・参考資料・開発協力",
    "仅作引用；采用上游条款": "参考のみ・上流の利用条件に従います",
    "仅作引用；未捆绑代码": "参考のみ・コードは同梱していません",
    "开发致谢；无运行时依赖": "開発協力への謝辞・実行時依存なし",
    "Basic Pitch 代码与模型许可": "Basic Pitch のコードとモデルのライセンス",
    "Basic Pitch 0.4.0 的代码、随包 nmp.onnx、LICENSE 与 NOTICE 位于同一官方发行树；未发现模型目录中的单独限制性许可证。按 Apache-2.0 再分发时必须附带 LICENSE 并保留 NOTICE。": (
        "Basic Pitch 0.4.0では、コード、同梱のnmp.onnx、LICENSE、NOTICEが同じ"
        "公式リリースツリーにあり、モデルディレクトリに別の制限的ライセンスは"
        "見当たりません。Apache-2.0で再配布する際はLICENSEを同梱し、NOTICEを"
        "保持する必要があります。"
    ),
    "论文引用": "論文の引用",
    "论文": "論文",
    "社区、测试与音乐交流": "コミュニティ・テスト・音楽交流",
    "本程序未内置 OpenAI API 或云端模型；OpenAI 仅列为开发协作致谢。": (
        "本アプリはOpenAI APIやクラウドモデルを内蔵していません。OpenAIは"
        "開発協力への謝辞としてのみ掲載しています。"
    ),
    "完整许可清单": "完全なライセンス一覧",
    "这里是便于阅读的致谢；每次构建仍会生成并随 EXE 嵌入完整的依赖、许可证、NOTICE 与二进制哈希清单。": (
        "これは読みやすさを優先した謝辞です。各ビルドでは、依存関係、ライセンス、"
        "NOTICE、バイナリハッシュの完全な一覧を生成し、EXEに同梱します。"
    ),
})

KO.update({
    "许可证": "라이선스",
    "自动扒谱、音频与科学计算": "자동 채보·오디오·과학 계산",
    "应用运行、界面与打包": "앱 런타임·UI·패키징",
    "格式研究、引用与开发协作": "형식 연구·참고 자료·개발 협업",
    "仅作引用；采用上游条款": "참고용이며 업스트림 조건을 따름",
    "仅作引用；未捆绑代码": "참고용이며 코드를 포함하지 않음",
    "开发致谢；无运行时依赖": "개발 협업 감사·런타임 의존성 없음",
    "Basic Pitch 代码与模型许可": "Basic Pitch 코드 및 모델 라이선스",
    "Basic Pitch 0.4.0 的代码、随包 nmp.onnx、LICENSE 与 NOTICE 位于同一官方发行树；未发现模型目录中的单独限制性许可证。按 Apache-2.0 再分发时必须附带 LICENSE 并保留 NOTICE。": (
        "Basic Pitch 0.4.0의 코드, 포함된 nmp.onnx, LICENSE 및 NOTICE는 동일한 "
        "공식 릴리스 트리에 있으며 모델 디렉터리에서 별도의 제한적 라이선스는 "
        "확인되지 않았습니다. Apache-2.0으로 재배포할 때는 LICENSE를 포함하고 "
        "NOTICE를 유지해야 합니다."
    ),
    "论文引用": "논문 인용",
    "论文": "논문",
    "社区、测试与音乐交流": "커뮤니티·테스트·음악 교류",
    "本程序未内置 OpenAI API 或云端模型；OpenAI 仅列为开发协作致谢。": (
        "이 앱은 OpenAI API 또는 클라우드 모델을 내장하지 않습니다. OpenAI는 "
        "개발 협업 감사 항목으로만 표시됩니다."
    ),
    "完整许可清单": "전체 라이선스 목록",
    "这里是便于阅读的致谢；每次构建仍会生成并随 EXE 嵌入完整的依赖、许可证、NOTICE 与二进制哈希清单。": (
        "이 목록은 읽기 쉬운 감사 목록입니다. 각 빌드는 전체 의존성, 라이선스, "
        "NOTICE 및 바이너리 해시 목록을 생성하여 EXE에 포함합니다."
    ),
})

EN.update({
    "扒谱": "Transcription",
    "标准/独奏": "Standard / Solo",
    "混音增强": "Mix Enhanced",
    "识别模式已更改；请重新分析整首。": "Recognition mode changed; analyze the full song again.",
    "载入参考音频": "Load Reference Audio",
    "卸载参考音频": "Unload Reference Audio",
    "分析整首": "Analyze Full Song",
    "分析 A–B": "Analyze A–B",
    "1 · 载入音频": "1 · Load Audio",
    "2 · 生成音符": "2 · Generate Notes",
    "3 · 审阅并写入": "3 · Review & Write",
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
    "分析 A–B": "A–Bを解析",
    "1 · 载入音频": "1 · 音声を読み込む",
    "2 · 生成音符": "2 · 音符を生成",
    "3 · 审阅并写入": "3 · 確認して書き込む",
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
    "分析 A–B": "A–B 분석",
    "1 · 载入音频": "1 · 오디오 불러오기",
    "2 · 生成音符": "2 · 음표 생성",
    "3 · 审阅并写入": "3 · 검토 후 기록",
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
    "音频扒谱": "Audio Transcription",
    "载入音频": "Load Audio",
    "载入或更换参考音频": "Load or Change Reference Audio",
    "更换音频": "Change Audio",
    "移除音频": "Remove Audio",
    "移除参考音频": "Remove Reference Audio",
    "分析": "Analyze",
    "显示强度": "Display intensity",
    "筛选与节奏": "Filters & rhythm",
    "乐器区分": "Instrument distinction",
    "节奏网格": "Rhythm grid",
    "识别结果": "Detected Notes",
    "忽略所选": "Ignore Selected",
    "恢复忽略": "Restore Ignored",
    "应用所选": "Apply Selected",
    "将所选识别音块加入当前轨道": (
        "Add the selected detected notes to this track"
    ),
    "载入音频，然后分析": "Load audio, then analyze",
    "识别到 {count} 个音块 · 框选后点击“应用所选”": (
        "{count} notes detected · Select an area, then click Apply Selected"
    ),
    "幽灵": "Ghost",
    "幽灵音块透明度": "Ghost-note opacity",
    "扒谱工作区": "Transcription Workspace",
    "候选审阅": "Candidate Review",
    "应用并关闭": "Apply & Close",
    "绘制": "Draw Tool",
    "完成": "Finish Editing",
    "放弃": "Discard Changes",
    "显示": "View",
    "分析设置": "Analysis Setup",
    "显示参考": "Reference View",
    "更多操作": "More Actions",
    "审阅工具": "Review Tools",
    "其他轨": "Other Tracks",
    "参照": "Refs",
    "点击开关其他轨参照；箭头可调整透明度": "Toggle other-track reference; use the arrow to adjust opacity",
    "透明度": "Opacity",
    "其他轨道参照透明度": "Other-track reference opacity",
    "已创建当前轨音符": "Created a note on this track",
    "候选音高不适用于当前轨道": "This candidate pitch is unavailable on the current track",
    "当前位置已有相同音符": "A matching note already exists here",
    "以细线显示未静音的其他轨道；只作对位参考，不可编辑": "Show unmuted tracks as thin alignment guides; reference only, not editable",
    "背景": "Ref",
    "旋律线、Frame、Onset、Contour 与声谱透明度": (
        "Melody-line, Frame, Onset, Contour, and spectrogram opacity"
    ),
})
JA.update({
    "音频扒谱": "オーディオ採譜",
    "载入音频": "音声を読み込む",
    "载入或更换参考音频": "参照音声を読み込む／変更",
    "更换音频": "音声を変更",
    "移除音频": "音声を解除",
    "移除参考音频": "参照音声を解除",
    "分析": "解析",
    "显示强度": "表示の強さ",
    "筛选与节奏": "フィルターとリズム",
    "乐器区分": "楽器の区別",
    "节奏网格": "リズムグリッド",
    "识别结果": "認識結果",
    "忽略所选": "選択を除外",
    "恢复忽略": "除外を復元",
    "应用所选": "選択を適用",
    "将所选识别音块加入当前轨道": (
        "選択した認識ノートを現在のトラックに追加"
    ),
    "载入音频，然后分析": "音声を読み込んで解析してください",
    "识别到 {count} 个音块 · 框选后点击“应用所选”": (
        "{count}個のノートを認識・範囲選択して［選択を適用］をクリック"
    ),
    "幽灵": "ゴースト",
    "幽灵音块透明度": "ゴーストノートの透明度",
    "扒谱工作区": "採譜ワークスペース",
    "候选审阅": "候補確認",
    "应用并关闭": "適用して閉じる",
    "绘制": "描画ツール",
    "完成": "編集を完了",
    "放弃": "変更を破棄",
    "显示": "表示",
    "分析设置": "解析設定",
    "显示参考": "参照表示",
    "更多操作": "その他の操作",
    "审阅工具": "確認ツール",
    "其他轨": "他トラック",
    "参照": "他軌",
    "点击开关其他轨参照；箭头可调整透明度": "クリックで他トラック参照を切り替え、矢印で透明度を調整します",
    "透明度": "透明度",
    "其他轨道参照透明度": "他トラック参照の透明度",
    "已创建当前轨音符": "現在のトラックにノートを作成しました",
    "候选音高不适用于当前轨道": "この候補の音高は現在のトラックでは使用できません",
    "当前位置已有相同音符": "同じ位置に一致するノートがあります",
    "以细线显示未静音的其他轨道；只作对位参考，不可编辑": "ミュートされていない他トラックを細線で表示します。参照専用で編集できません",
    "背景": "参照",
    "旋律线、Frame、Onset、Contour 与声谱透明度": (
        "メロディライン、Frame、Onset、Contour、スペクトルの透明度"
    ),
})
KO.update({
    "音频扒谱": "오디오 채보",
    "载入音频": "오디오 불러오기",
    "载入或更换参考音频": "참조 오디오 불러오기 또는 변경",
    "更换音频": "오디오 변경",
    "移除音频": "오디오 제거",
    "移除参考音频": "참조 오디오 제거",
    "分析": "분석",
    "显示强度": "표시 강도",
    "筛选与节奏": "필터 및 리듬",
    "乐器区分": "악기 구분",
    "节奏网格": "리듬 그리드",
    "识别结果": "인식 결과",
    "忽略所选": "선택 항목 무시",
    "恢复忽略": "무시 항목 복원",
    "应用所选": "선택 항목 적용",
    "将所选识别音块加入当前轨道": (
        "선택한 인식 음표를 현재 트랙에 추가"
    ),
    "载入音频，然后分析": "오디오를 불러온 뒤 분석하세요",
    "识别到 {count} 个音块 · 框选后点击“应用所选”": (
        "음표 {count}개 인식 · 영역을 선택한 뒤 선택 항목 적용을 클릭하세요"
    ),
    "幽灵": "고스트",
    "幽灵音块透明度": "고스트 노트 투명도",
    "扒谱工作区": "채보 작업 공간",
    "候选审阅": "후보 검토",
    "应用并关闭": "적용 후 닫기",
    "绘制": "그리기 도구",
    "完成": "편집 완료",
    "放弃": "변경 버리기",
    "显示": "보기",
    "分析设置": "분석 설정",
    "显示参考": "참조 보기",
    "更多操作": "추가 작업",
    "审阅工具": "검토 도구",
    "其他轨": "다른 트랙",
    "参照": "타 트랙",
    "点击开关其他轨参照；箭头可调整透明度": "클릭해 다른 트랙 참조를 켜고 끄며 화살표에서 투명도를 조절합니다",
    "透明度": "투명도",
    "其他轨道参照透明度": "다른 트랙 참조 투명도",
    "已创建当前轨音符": "현재 트랙에 음표를 만들었습니다",
    "候选音高不适用于当前轨道": "이 후보 음높이는 현재 트랙에서 사용할 수 없습니다",
    "当前位置已有相同音符": "이 위치에 같은 음표가 이미 있습니다",
    "以细线显示未静音的其他轨道；只作对位参考，不可编辑": "음소거되지 않은 다른 트랙을 가는 선으로 표시합니다. 참조 전용이며 편집할 수 없습니다",
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
    "乐器 {count} · {players}/{limit} 人": (
        "Instruments {count} · Players {players}/{limit}"
    ),
    "乐器 {count} · 超过 {limit} 人": "Instruments {count} · Over {limit} players",
    "按当前参与演奏且含音符的轨道统计；同一实体乐器只计一次": (
        "Counts active tracks with notes; each physical instrument counts once"
    ),
    "工程演奏人数": "Score performers",
    "当前工程没有需要演奏的实体乐器": (
        "The current score has no physical instruments to perform"
    ),
    "当前工程预计 {count}/{limit} 人演奏；同一实体乐器只计一人": (
        "Current score: {count}/{limit} performers; each physical instrument counts once"
    ),
    "当前工程预计 {count} 人演奏，超过 {limit} 人队伍上限": (
        "Current score needs {count} performers, over the {limit}-player party limit"
    ),
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
    "乐器 {count} · {players}/{limit} 人": (
        "楽器 {count} · 人数 {players}/{limit}"
    ),
    "乐器 {count} · 超过 {limit} 人": "楽器 {count} · {limit}人超過",
    "按当前参与演奏且含音符的轨道统计；同一实体乐器只计一次": (
        "演奏対象の音符があるトラックを集計し、同じ実楽器は1回だけ数えます"
    ),
    "工程演奏人数": "楽譜の演奏人数",
    "当前工程没有需要演奏的实体乐器": (
        "現在の楽譜には演奏が必要な実楽器がありません"
    ),
    "当前工程预计 {count}/{limit} 人演奏；同一实体乐器只计一人": (
        "現在の楽譜は{count}/{limit}人想定。同じ実楽器は1人として数えます"
    ),
    "当前工程预计 {count} 人演奏，超过 {limit} 人队伍上限": (
        "現在の楽譜は{count}人必要で、{limit}人のパーティー上限を超えています"
    ),
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
    "乐器 {count} · {players}/{limit} 人": (
        "악기 {count} · 인원 {players}/{limit}"
    ),
    "乐器 {count} · 超过 {limit} 人": "악기 {count} · {limit}명 초과",
    "按当前参与演奏且含音符的轨道统计；同一实体乐器只计一次": (
        "연주 대상이며 음표가 있는 트랙을 집계하고 같은 실제 악기는 한 번만 셉니다"
    ),
    "工程演奏人数": "악보 연주 인원",
    "当前工程没有需要演奏的实体乐器": (
        "현재 악보에는 연주가 필요한 실제 악기가 없습니다"
    ),
    "当前工程预计 {count}/{limit} 人演奏；同一实体乐器只计一人": (
        "현재 악보 예상 인원 {count}/{limit}명; 같은 실제 악기는 한 명으로 계산합니다"
    ),
    "当前工程预计 {count} 人演奏，超过 {limit} 人队伍上限": (
        "현재 악보는 {count}명이 필요해 {limit}명 파티 상한을 초과합니다"
    ),
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
    "此轨道仍含旧版隐藏力度倍率 {volume_scale:.3g}；请先将它写入音符力度。": (
        "This track still contains the legacy hidden velocity multiplier "
        "{volume_scale:.3g}; write it into note velocities first."
    ),
    "FX type {articulation} 不属于当前乐器。": (
        "FX type {articulation} is not available for this instrument."
    ),
    "FX type {articulation} 在当前乐器的 {count} 个音高上没有游戏路由。": (
        "FX type {articulation} has no game route for {count} pitches on this "
        "instrument."
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
    "此轨道仍含旧版隐藏力度倍率 {volume_scale:.3g}；请先将它写入音符力度。": (
        "このトラックには旧版の隠れたベロシティ倍率{volume_scale:.3g}が残っています。"
        "先にノートのベロシティへ書き込んでください。"
    ),
    "FX type {articulation} 不属于当前乐器。": (
        "FX type {articulation}はこの楽器では使用できません。"
    ),
    "FX type {articulation} 在当前乐器的 {count} 个音高上没有游戏路由。": (
        "FX type {articulation} は、この楽器の {count} 個の音高にゲーム内ルートがありません。"
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
    "此轨道仍含旧版隐藏力度倍率 {volume_scale:.3g}；请先将它写入音符力度。": (
        "이 트랙에 이전 버전의 숨겨진 벨로시티 배율 {volume_scale:.3g}이(가) "
        "남아 있습니다. 먼저 음표 벨로시티에 기록하세요."
    ),
    "FX type {articulation} 不属于当前乐器。": (
        "FX type {articulation}은(는) 이 악기에서 사용할 수 없습니다."
    ),
    "FX type {articulation} 在当前乐器的 {count} 个音高上没有游戏路由。": (
        "FX type {articulation}은(는) 이 악기의 {count}개 음높이에 게임 라우트가 없습니다."
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
    "{count} 轨 · {meter}/4": "{count} tracks · {meter}/4",
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
    "{count} 轨 · {meter}/4": "{count}トラック · {meter}/4",
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
    "{count} 轨 · {meter}/4": "트랙 {count}개 · {meter}/4",
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


EN.update({
    "实时试听缓冲不足 {count} 次 · 混音 P95 {p95:.1f} ms": "Real-time preview underruns: {count} · mix P95 {p95:.1f} ms",
    "导出、解析、试听与界面设置；保存后立即应用相关更改。": "Export, parsing, preview, and interface settings; related changes apply immediately after saving.",
    "无法读取 MIDI 拍号，已阻止导出：{error}": "Could not read the MIDI meter; export was blocked: {error}",
    "正在完成最终自动保存…": "Finishing the final autosave…",
    "游戏曲谱目录": "Game score folder",
    "游戏曲谱目录不可用": "Game Score Folder Unavailable",
    "请选择有效的游戏曲谱目录。": "Choose a valid game score folder.",
    "转换完成（未复制到游戏目录）": "Export complete (not copied to the game folder)",
    "选择游戏曲谱目录": "Choose Game Score Folder",
    "通用 MIDI 预览不可用": "Generic MIDI preview unavailable",
    "通用 MIDI 预览可用": "Generic MIDI preview available",
    "通用 MIDI 预览（非游戏原声）": "Generic MIDI preview (not game audio)",
    "正在准备通用 MIDI 预览…": "Preparing generic MIDI preview…",
    "分别设置导出保存位置和游戏曲谱安装位置。": "Set separate folders for exported scores and installed game scores.",
    " · 未复制到游戏目录：{error}": " · Game-folder copy failed: {error}",
})
JA.update({
    "实时试听缓冲不足 {count} 次 · 混音 P95 {p95:.1f} ms": "リアルタイム試聴のバッファ不足 {count} 回・ミックス P95 {p95:.1f} ms",
    "导出、解析、试听与界面设置；保存后立即应用相关更改。": "書き出し、解析、試聴、画面の設定です。関連する変更は保存後すぐに反映されます。",
    "无法读取 MIDI 拍号，已阻止导出：{error}": "MIDIの拍子を読み取れないため書き出しを停止しました：{error}",
    "正在完成最终自动保存…": "最後の自動保存を完了しています…",
    "游戏曲谱目录": "ゲーム楽譜フォルダー",
    "游戏曲谱目录不可用": "ゲーム楽譜フォルダーを使用できません",
    "请选择有效的游戏曲谱目录。": "有効なゲーム楽譜フォルダーを選択してください。",
    "转换完成（未复制到游戏目录）": "書き出し完了（ゲームフォルダーにはコピーされていません）",
    "选择游戏曲谱目录": "ゲーム楽譜フォルダーを選択",
    "通用 MIDI 预览不可用": "汎用MIDIプレビューを使用できません",
    "通用 MIDI 预览可用": "汎用MIDIプレビューを使用できます",
    "通用 MIDI 预览（非游戏原声）": "汎用MIDIプレビュー（ゲーム音源ではありません）",
    "正在准备通用 MIDI 预览…": "汎用MIDIプレビューを準備中…",
    "分别设置导出保存位置和游戏曲谱安装位置。": "書き出し先とゲーム楽譜のインストール先を個別に設定します。",
    " · 未复制到游戏目录：{error}": "・ゲームフォルダーへのコピー失敗：{error}",
})
KO.update({
    "实时试听缓冲不足 {count} 次 · 混音 P95 {p95:.1f} ms": "실시간 미리듣기 버퍼 부족 {count}회 · 믹싱 P95 {p95:.1f} ms",
    "导出、解析、试听与界面设置；保存后立即应用相关更改。": "내보내기, 분석, 미리듣기와 화면 설정입니다. 관련 변경은 저장 후 즉시 적용됩니다.",
    "无法读取 MIDI 拍号，已阻止导出：{error}": "MIDI 박자를 읽을 수 없어 내보내기를 차단했습니다: {error}",
    "正在完成最终自动保存…": "마지막 자동 저장을 완료하는 중…",
    "游戏曲谱目录": "게임 악보 폴더",
    "游戏曲谱目录不可用": "게임 악보 폴더를 사용할 수 없음",
    "请选择有效的游戏曲谱目录。": "유효한 게임 악보 폴더를 선택하세요.",
    "转换完成（未复制到游戏目录）": "내보내기 완료(게임 폴더에 복사되지 않음)",
    "选择游戏曲谱目录": "게임 악보 폴더 선택",
    "通用 MIDI 预览不可用": "일반 MIDI 미리듣기를 사용할 수 없음",
    "通用 MIDI 预览可用": "일반 MIDI 미리듣기 사용 가능",
    "通用 MIDI 预览（非游戏原声）": "일반 MIDI 미리듣기(게임 원음 아님)",
    "正在准备通用 MIDI 预览…": "일반 MIDI 미리듣기 준비 중…",
    "分别设置导出保存位置和游戏曲谱安装位置。": "내보내기 저장 폴더와 게임 악보 설치 폴더를 각각 설정합니다.",
    " · 未复制到游戏目录：{error}": " · 게임 폴더 복사 실패: {error}",
})


# Export consistency diagnostics intentionally distinguish serialized fields
# from unverified in-game DSP/audio behavior.
EN.update({
    " · 编辑器→BDO v9 数据一致": " · Editor → BDO v9 data consistent",
    " · 游戏目录副本一致": " · Game-folder copy consistent",
    " · 一致性检查发现 {count} 项差异": " · Consistency check found {count} difference(s)",
    " · 主文件已保存，但游戏目录副本未通过一致性检查": " · Primary file saved, but the game-folder copy failed consistency verification",
    "转换完成（数据一致性检查失败）": "Conversion completed (data consistency check failed)",
    "本次检查仅验证编辑器中的可导出字段、BDO v9 文件写入和已安装副本；不代表程序绝对无 Bug，也不证明游戏内音色、效果或响度已验证。": "This check only verifies exportable editor fields, BDO v9 file writing, and any installed copy; it does not mean the program has no bugs or prove in-game timbre, effects, or loudness.",
})
JA.update({
    " · 编辑器→BDO v9 数据一致": " · エディター→BDO v9 データ一致",
    " · 游戏目录副本一致": " · ゲームフォルダーのコピーも一致",
    " · 一致性检查发现 {count} 项差异": " · 整合性チェックで {count} 件の差異を検出",
    " · 主文件已保存，但游戏目录副本未通过一致性检查": " · メインファイルは保存されましたが、ゲームフォルダーのコピーは整合性チェックに失敗しました",
    "转换完成（数据一致性检查失败）": "変換完了（データ整合性チェック失敗）",
    "本次检查仅验证编辑器中的可导出字段、BDO v9 文件写入和已安装副本；不代表程序绝对无 Bug，也不证明游戏内音色、效果或响度已验证。": "このチェックで検証するのは、エディター内の書き出し可能な項目、BDO v9 ファイルの書き込み、インストール済みコピーだけです。プログラムにバグがないことや、ゲーム内の音色・エフェクト・音量感が検証済みであることを意味しません。",
})
KO.update({
    " · 编辑器→BDO v9 数据一致": " · 편집기→BDO v9 데이터 일치",
    " · 游戏目录副本一致": " · 게임 폴더 사본 일치",
    " · 一致性检查发现 {count} 项差异": " · 일관성 검사에서 차이 {count}건 발견",
    " · 主文件已保存，但游戏目录副本未通过一致性检查": " · 기본 파일은 저장했지만 게임 폴더 사본이 일관성 검사를 통과하지 못했습니다",
    "转换完成（数据一致性检查失败）": "변환 완료(데이터 일관성 검사 실패)",
    "本次检查仅验证编辑器中的可导出字段、BDO v9 文件写入和已安装副本；不代表程序绝对无 Bug，也不证明游戏内音色、效果或响度已验证。": "이 검사는 편집기에서 내보낼 수 있는 필드, BDO v9 파일 기록, 설치된 사본만 검증합니다. 프로그램에 버그가 전혀 없거나 게임 내 음색·효과·체감 음량이 검증되었다는 뜻은 아닙니다.",
})

EN.update({
    "Wwise 路由已确认": "Wwise route confirmed",
    "奏法 {articulation} 仅支持 {pitch_range}，未修改 {count} 个越界音符。": (
        "{articulation} only supports {pitch_range}; {count} out-of-range "
        "note(s) were left unchanged."
    ),
    "{track} 的 {mode} 游戏 WAV 音源不完整": (
        "The {mode} game WAV set for {track} is incomplete"
    ),
})
JA.update({
    "Wwise 路由已确认": "Wwiseルート確認済み",
    "奏法 {articulation} 仅支持 {pitch_range}，未修改 {count} 个越界音符。": (
        "奏法{articulation}は{pitch_range}のみ対応しています。範囲外の"
        "{count}ノートは変更しませんでした。"
    ),
    "{track} 的 {mode} 游戏 WAV 音源不完整": (
        "{track}の{mode}ゲームWAV音源が不完全です"
    ),
})
KO.update({
    "Wwise 路由已确认": "Wwise 라우트 확인됨",
    "奏法 {articulation} 仅支持 {pitch_range}，未修改 {count} 个越界音符。": (
        "{articulation} 주법은 {pitch_range}에서만 지원됩니다. 범위를 벗어난 "
        "노트 {count}개는 변경하지 않았습니다."
    ),
    "{track} 的 {mode} 游戏 WAV 音源不完整": (
        "{track}의 {mode} 게임 WAV 음원이 불완전합니다"
    ),
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


EN.update({
    "搜索项目或曲谱": "Search projects or scores",
    "打开所选项目": "Open Selected Project",
    "保存项目": "Save Project",
    "另存为": "Save As",
    "选择另存位置": "Choose Save Location",
    "另存为失败": "Save As Failed",
    "仍有项目写入正在进行，请稍后重试。": "A project write is still in progress. Please try again shortly.",
    "当前没有可保存的项目": "There is no project to save",
    "项目保存已排入队列": "Project save queued",
    "项目副本保存已排入队列": "Project-copy save queued",
    "重命名项目": "Rename Project",
    "重命名项目失败": "Rename Project Failed",
    "无法重命名项目：{error}": "Could not rename project: {error}",
    "项目已重命名": "Project renamed",
    "移到回收站": "Move to Recycle Bin",
    "无法删除项目": "Could Not Remove Project",
    "只能把自动保存目录中的项目移到回收站。": "Only projects inside the autosave directory can be moved to the Recycle Bin.",
    "当前打开的项目不能删除；请先打开其他项目。": "The open project cannot be removed. Open another project first.",
    "要把项目“{project}”移到回收站吗？": "Move project \"{project}\" to the Recycle Bin?",
    "系统未能把项目移到回收站。": "The system could not move the project to the Recycle Bin.",
    "项目已移到回收站": "Project moved to the Recycle Bin",
    "请先选择一个项目或曲谱": "Select a project or score first",
    "{time} · 版本 {index}/{count}": "{time} · Version {index}/{count}",
    "\n工程版本 {index}/{count}；此版本可独立打开": "\nProject version {index}/{count}; this version can be opened independently",
})
JA.update({
    "搜索项目或曲谱": "プロジェクトまたは楽譜を検索",
    "打开所选项目": "選択したプロジェクトを開く",
    "保存项目": "プロジェクトを保存",
    "另存为": "名前を付けて保存",
    "选择另存位置": "保存先を選択",
    "另存为失败": "名前を付けて保存できませんでした",
    "仍有项目写入正在进行，请稍后重试。": "プロジェクトの書き込み中です。しばらくしてから再試行してください。",
    "当前没有可保存的项目": "保存できるプロジェクトがありません",
    "项目保存已排入队列": "プロジェクトの保存を開始しました",
    "项目副本保存已排入队列": "プロジェクトのコピー保存を開始しました",
    "重命名项目": "プロジェクト名を変更",
    "重命名项目失败": "プロジェクト名を変更できませんでした",
    "无法重命名项目：{error}": "プロジェクト名を変更できません：{error}",
    "项目已重命名": "プロジェクト名を変更しました",
    "移到回收站": "ごみ箱に移動",
    "无法删除项目": "プロジェクトを削除できません",
    "只能把自动保存目录中的项目移到回收站。": "自動保存フォルダー内のプロジェクトだけをごみ箱に移動できます。",
    "当前打开的项目不能删除；请先打开其他项目。": "開いているプロジェクトは削除できません。先に別のプロジェクトを開いてください。",
    "要把项目“{project}”移到回收站吗？": "プロジェクト「{project}」をごみ箱に移動しますか？",
    "系统未能把项目移到回收站。": "プロジェクトをごみ箱に移動できませんでした。",
    "项目已移到回收站": "プロジェクトをごみ箱に移動しました",
    "请先选择一个项目或曲谱": "先にプロジェクトまたは楽譜を選択してください",
    "{time} · 版本 {index}/{count}": "{time} · バージョン {index}/{count}",
    "\n工程版本 {index}/{count}；此版本可独立打开": "\nプロジェクトのバージョン {index}/{count}・このバージョンを個別に開けます",
})
KO.update({
    "搜索项目或曲谱": "프로젝트 또는 악보 검색",
    "打开所选项目": "선택한 프로젝트 열기",
    "保存项目": "프로젝트 저장",
    "另存为": "다른 이름으로 저장",
    "选择另存位置": "저장 위치 선택",
    "另存为失败": "다른 이름으로 저장 실패",
    "仍有项目写入正在进行，请稍后重试。": "프로젝트를 기록하는 중입니다. 잠시 후 다시 시도하세요.",
    "当前没有可保存的项目": "저장할 프로젝트가 없습니다",
    "项目保存已排入队列": "프로젝트 저장을 시작했습니다",
    "项目副本保存已排入队列": "프로젝트 복사본 저장을 시작했습니다",
    "重命名项目": "프로젝트 이름 변경",
    "重命名项目失败": "프로젝트 이름 변경 실패",
    "无法重命名项目：{error}": "프로젝트 이름을 변경할 수 없습니다: {error}",
    "项目已重命名": "프로젝트 이름을 변경했습니다",
    "移到回收站": "휴지통으로 이동",
    "无法删除项目": "프로젝트를 삭제할 수 없음",
    "只能把自动保存目录中的项目移到回收站。": "자동 저장 폴더 안의 프로젝트만 휴지통으로 이동할 수 있습니다.",
    "当前打开的项目不能删除；请先打开其他项目。": "현재 열린 프로젝트는 삭제할 수 없습니다. 먼저 다른 프로젝트를 여세요.",
    "要把项目“{project}”移到回收站吗？": "프로젝트 ‘{project}’을(를) 휴지통으로 이동할까요?",
    "系统未能把项目移到回收站。": "시스템이 프로젝트를 휴지통으로 이동하지 못했습니다.",
    "项目已移到回收站": "프로젝트를 휴지통으로 이동했습니다",
    "请先选择一个项目或曲谱": "먼저 프로젝트 또는 악보를 선택하세요",
    "{time} · 版本 {index}/{count}": "{time} · 버전 {index}/{count}",
    "\n工程版本 {index}/{count}；此版本可独立打开": "\n프로젝트 버전 {index}/{count} · 이 버전을 개별적으로 열 수 있습니다",
})


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
    "效果值必须在 [0, 100] 范围内": (
        "Effect values must be in the [0, 100] range",
        "エフェクト値は[0, 100]の範囲内である必要があります",
        "효과 값은 [0, 100] 범위여야 합니다",
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


_HOME_LIBRARY_TRANSLATIONS = {
    "本地曲谱工作台": (
        "Local score workspace",
        "ローカル楽譜ワークスペース",
        "로컬 악보 작업 공간",
    ),
    "资料库": ("Library", "ライブラリ", "라이브러리"),
    "最近项目": ("Recent Projects", "最近のプロジェクト", "최근 프로젝트"),
    "最近项目、自动保存与示例": (
        "Recent projects, autosaves, and examples",
        "最近のプロジェクト、自動保存、サンプル",
        "최근 프로젝트, 자동 저장 및 예제",
    ),
    "Black Desert Music 目录中的曲谱": (
        "Scores in the Black Desert Music folder",
        "Black Desert Music フォルダーの楽譜",
        "Black Desert Music 폴더의 악보",
    ),
    "本地处理 · 不上传工程": (
        "Local processing · projects stay on this device",
        "ローカル処理 · プロジェクトはアップロードされません",
        "로컬 처리 · 프로젝트를 업로드하지 않음",
    ),
    "打开游戏目录": (
        "Open Game Folder",
        "ゲームフォルダーを開く",
        "게임 폴더 열기",
    ),
    "继续创作": ("Continue Creating", "制作を続ける", "계속 만들기"),
    "从最近工程继续，或开始一个新的编曲项目": (
        "Continue a recent project or start a new arrangement",
        "最近のプロジェクトを続けるか、新しい編曲を始めます",
        "최근 프로젝트를 계속하거나 새 편곡을 시작하세요",
    ),
    "新建空白项目\n从一条空白轨道开始": (
        "New Blank Project\nStart with an empty track",
        "空のプロジェクトを作成\n空のトラックから開始",
        "빈 프로젝트 만들기\n빈 트랙에서 시작",
    ),
    "导入 MIDI\n继续编排已有音乐": (
        "Import MIDI\nContinue arranging existing music",
        "MIDI を読み込む\n既存の曲を編曲",
        "MIDI 가져오기\n기존 음악 계속 편곡",
    ),
    "打开工程\n浏览本地项目文件": (
        "Open Project\nBrowse local project files",
        "プロジェクトを開く\nローカルファイルを参照",
        "프로젝트 열기\n로컬 프로젝트 파일 찾기",
    ),
    "{count} 人": (
        "{count} players",
        "{count}人",
        "{count}명",
    ),
    "上限 {limit} 人": (
        "{limit}-player limit",
        "上限{limit}人",
        "최대 {limit}명",
    ),
    "{count} 种乐器": (
        "{count} instruments",
        "{count}楽器",
        "{count}개 악기",
    ),
}

for _source, (_english, _japanese, _korean) in _HOME_LIBRARY_TRANSLATIONS.items():
    if _source in EN or _source in JA or _source in KO:
        raise RuntimeError(f"duplicate home localization source: {_source}")
    EN[_source] = _english
    JA[_source] = _japanese
    KO[_source] = _korean

del _source, _english, _japanese, _korean


_RELEASE_UPDATE_TRANSLATIONS = {
    "软件更新": ("Software Update", "ソフトウェア更新", "소프트웨어 업데이트"),
    "无感更新": ("Seamless Updates", "シームレス更新", "원활한 업데이트"),
    "后台检查并准备经过签名验证的新版本；不会上传工程、Owner ID 或本机路径。": (
        "Checks for and prepares signature-verified releases in the background; projects, Owner IDs, and local paths are never uploaded.",
        "署名検証済みの新しいバージョンをバックグラウンドで確認・準備します。プロジェクト、Owner ID、ローカルパスは送信しません。",
        "서명 검증된 새 버전을 백그라운드에서 확인하고 준비합니다. 프로젝트, Owner ID 및 로컬 경로는 업로드하지 않습니다.",
    ),
    "自动检查更新": ("Automatically check for updates", "更新を自動確認", "업데이트 자동 확인"),
    "发现新版本后在后台自动下载": (
        "Download new releases in the background",
        "新しいバージョンをバックグラウンドで自動ダウンロード",
        "새 버전을 백그라운드에서 자동 다운로드",
    ),
    "自动选择（优先可用镜像）": (
        "Automatic (prefer an available mirror)",
        "自動（利用可能なミラーを優先）",
        "자동(사용 가능한 미러 우선)",
    ),
    "Gitee 国内镜像": ("Gitee China mirror", "Gitee 中国ミラー", "Gitee 중국 미러"),
    "立即检查": ("Check Now", "今すぐ確認", "지금 확인"),
    "更新来源": ("Update source", "更新元", "업데이트 소스"),
    "正在后台检查更新…": (
        "Checking for updates in the background…",
        "バックグラウンドで更新を確認中…",
        "백그라운드에서 업데이트 확인 중…",
    ),
    "当前环境无法启动更新检查": (
        "Update checks are unavailable in this environment",
        "この環境では更新確認を開始できません",
        "현재 환경에서는 업데이트 확인을 시작할 수 없습니다",
    ),
    "正在检查更新…": ("Checking for updates…", "更新を確認中…", "업데이트 확인 중…"),
    "发现新版本 v{version}，正在后台下载": (
        "Version v{version} is available and is downloading in the background",
        "新しいバージョン v{version} をバックグラウンドでダウンロード中です",
        "새 버전 v{version}을(를) 백그라운드에서 다운로드 중입니다",
    ),
    "发现新版本 v{version}": (
        "Version v{version} is available",
        "新しいバージョン v{version} があります",
        "새 버전 v{version}이(가) 있습니다",
    ),
    "v{version} 已准备好，将在下次启动时更新": (
        "v{version} is ready and will be installed on the next launch",
        "v{version} の準備が完了しました。次回起動時に更新します",
        "v{version} 준비가 완료되었으며 다음 실행 시 업데이트됩니다",
    ),
    "检查更新失败，请稍后重试": (
        "Update check failed; try again later",
        "更新確認に失敗しました。後でもう一度お試しください",
        "업데이트 확인에 실패했습니다. 나중에 다시 시도하세요",
    ),
    "已更新至 v{version}": (
        "Updated to v{version}",
        "v{version} に更新しました",
        "v{version}(으)로 업데이트했습니다",
    ),
    "更新日志 · v{version}": (
        "Release notes · v{version}",
        "リリースノート · v{version}",
        "릴리스 노트 · v{version}",
    ),
    "更新日志": (
        "Release notes",
        "リリースノート",
        "릴리스 노트",
    ),
    "检查更新": (
        "Check",
        "更新確認",
        "업데이트 확인",
    ),
    "查看版本": (
        "View release",
        "リリースを見る",
        "릴리스 보기",
    ),
    "尚未检查更新": (
        "Not checked",
        "未確認",
        "확인 전",
    ),
    "正在检查…": (
        "Checking…",
        "確認中…",
        "확인 중…",
    ),
    "新版本 {version}": (
        "New version {version}",
        "新しいバージョン {version}",
        "새 버전 {version}",
    ),
    "已是最新版": (
        "Up to date",
        "最新版です",
        "최신 버전",
    ),
    "开发版本": (
        "Development build",
        "開発版",
        "개발 버전",
    ),
    "GitHub 请求受限": (
        "GitHub request limited",
        "GitHub のリクエスト制限",
        "GitHub 요청 제한",
    ),
    "暂无稳定版": (
        "No stable release",
        "安定版なし",
        "안정 버전 없음",
    ),
    "检查服务不可用": (
        "Check unavailable",
        "確認サービスを利用できません",
        "확인 서비스 사용 불가",
    ),
    "检查超时": (
        "Check timed out",
        "確認がタイムアウトしました",
        "확인 시간 초과",
    ),
    "安全连接失败": (
        "Secure connection failed",
        "安全な接続に失敗",
        "보안 연결 실패",
    ),
    "无法连接 GitHub": (
        "Can't reach GitHub",
        "GitHub に接続できません",
        "GitHub에 연결할 수 없음",
    ),
    "已取消": (
        "Cancelled",
        "キャンセル済み",
        "취소됨",
    ),
    "自检期间不联网": (
        "Offline during self-test",
        "セルフテスト中はオフライン",
        "자체 검사 중 오프라인",
    ),
    "版本信息无效": (
        "Invalid version data",
        "バージョン情報が無効",
        "버전 정보가 올바르지 않음",
    ),
    "检查失败": (
        "Check failed",
        "確認に失敗",
        "확인 실패",
    ),
    "开发中": ("In development", "開発中", "개발 중"),
    "稳定版": ("Stable", "安定版", "안정 버전"),
    "预发行版": ("Pre-release", "プレリリース", "사전 릴리스"),
    "更新日志暂不可用": (
        "Release notes are unavailable",
        "リリースノートを利用できません",
        "릴리스 노트를 사용할 수 없습니다",
    ),
    "此版本暂无详细说明。": (
        "No details are available for this version.",
        "このバージョンの詳細はありません。",
        "이 버전에 대한 자세한 설명이 없습니다.",
    ),
    "更新来源：{source}": (
        "Update source: {source}",
        "更新元：{source}",
        "업데이트 소스: {source}",
    ),
    "本次更新": (
        "What's new",
        "今回の更新",
        "이번 업데이트",
    ),
    "稍后": (
        "Later",
        "後で",
        "나중에",
    ),
    "正在后台下载更新…": (
        "Downloading the update in the background…",
        "更新をバックグラウンドでダウンロードしています…",
        "백그라운드에서 업데이트를 다운로드하고 있습니다…",
    ),
    "下载进度：{percent}%": (
        "Download progress: {percent}%",
        "ダウンロード進捗：{percent}%",
        "다운로드 진행률: {percent}%",
    ),
    "更新包已通过验证；将在下次启动时自动安装。": (
        "The update package is verified and will install automatically on the next launch.",
        "更新パッケージの検証が完了しました。次回起動時に自動インストールされます。",
        "업데이트 패키지 검증이 완료되었으며 다음 실행 시 자동으로 설치됩니다.",
    ),
    "已发现新版本；可在软件更新设置中启用后台下载。": (
        "A new version is available; background download can be enabled in Software Update settings.",
        "新しいバージョンがあります。ソフトウェア更新設定でバックグラウンドダウンロードを有効にできます。",
        "새 버전이 있습니다. 소프트웨어 업데이트 설정에서 백그라운드 다운로드를 활성화할 수 있습니다.",
    ),
    "准备完成": (
        "Ready",
        "準備完了",
        "준비 완료",
    ),
    "等待下载": (
        "Waiting to download",
        "ダウンロード待ち",
        "다운로드 대기",
    ),
}

for _source, (_english, _japanese, _korean) in _RELEASE_UPDATE_TRANSLATIONS.items():
    EN.setdefault(_source, _english)
    JA.setdefault(_source, _japanese)
    KO.setdefault(_source, _korean)

del _source, _english, _japanese, _korean


_ACCESSIBILITY_TRANSLATIONS = {
    "高级": ("Advanced", "詳細", "고급"),
    "高级扒谱选项": (
        "Advanced transcription options",
        "詳細な採譜オプション",
        "고급 채보 옵션",
    ),
    "轨道时间轴": (
        "Track timeline",
        "トラックタイムライン",
        "트랙 타임라인",
    ),
    (
        "上下键选择轨道；M 静音；S 独奏；F 打开效果；"
        "Enter 编辑音符；左右键调整轨道音量（Shift 5）"
    ): (
        "Use Up/Down to select a track; M mute; S solo; F open effects; "
        "Enter edit notes; Left/Right adjust track volume (Shift: 5)",
        "上下キーでトラックを選択；M ミュート；S ソロ；F エフェクトを開く；"
        "Enter ノート編集；左右キーでトラック音量調整（Shift: 5）",
        "위/아래 키로 트랙 선택; M 음소거; S 솔로; F 이펙트 열기; "
        "Enter 음표 편집; 왼쪽/오른쪽 키로 트랙 볼륨 조절(Shift: 5)",
    ),
    "当前轨道：{track}；音量 {volume}。{shortcuts}": (
        "Current track: {track}; volume {volume}. {shortcuts}",
        "現在のトラック：{track}；音量 {volume}。{shortcuts}",
        "현재 트랙: {track}; 볼륨 {volume}. {shortcuts}",
    ),
}

for _source, (_english, _japanese, _korean) in _ACCESSIBILITY_TRANSLATIONS.items():
    if _source in EN or _source in JA or _source in KO:
        raise RuntimeError(f"duplicate accessibility localization source: {_source}")
    EN[_source] = _english
    JA[_source] = _japanese
    KO[_source] = _korean

del _source, _english, _japanese, _korean


_REFERENCE_TIMBRE_TRANSLATIONS = {
    "分析音块": (
        "Analyzed notes",
        "解析ノート",
        "분석 음표",
    ),
    "分析音块 · {opacity}%": (
        "Analyzed notes · {opacity}%",
        "解析ノート・{opacity}%",
        "분석 음표 · {opacity}%",
    ),
    "离散识别结果；可框选、筛选并采纳为可编辑草稿": (
        "Discrete analysis results; select, filter, and add them to the editable draft",
        "離散的な解析結果。範囲選択、絞り込み、編集可能な下書きへの追加ができます",
        "개별 분석 결과이며 영역 선택, 필터링, 편집 가능한 초안 추가를 할 수 있습니다",
    ),
    "分析后的离散音块，用于框选、筛选并采纳为可编辑草稿": (
        "Discrete analyzed notes for selection, filtering, and adding to the editable draft",
        "範囲選択、絞り込み、編集可能な下書きへの追加に使う離散解析ノートです",
        "영역 선택, 필터링, 편집 가능한 초안 추가에 사용하는 개별 분석 음표입니다",
    ),
    "音高线": ("Pitch line", "ピッチライン", "음높이 선"),
    "连续音高证据；用于观察滑音、颤音和音准变化": (
        "Continuous pitch evidence for inspecting slides, vibrato, and intonation",
        "スライド、ビブラート、イントネーションを確認するための連続ピッチ証拠です",
        "슬라이드, 비브라토, 음정 변화를 살펴보는 연속 음높이 근거입니다",
    ),
    "连续音高证据，用于观察滑音、颤音和音准变化；与分析音块独立显示": (
        "Continuous pitch evidence for inspecting slides, vibrato, and intonation; displayed independently from analyzed notes",
        "スライド、ビブラート、イントネーションを確認する連続ピッチ証拠です。解析ノートとは独立して表示します",
        "슬라이드, 비브라토, 음정 변화를 살펴보는 연속 음높이 근거이며 분석 음표와 독립적으로 표시합니다",
    ),
    "去噪强度": ("Denoise strength", "ノイズ除去の強さ", "노이즈 제거 강도"),
    "线条透明度": ("Line opacity", "ラインの不透明度", "선 불투명도"),
    "音高线透明度": ("Pitch-line opacity", "ピッチラインの不透明度", "음높이 선 불투명도"),
    "只调整音高线，不影响分析音块和其他参考证据": (
        "Adjusts only the pitch line; analyzed notes and other reference evidence are unchanged",
        "ピッチラインだけを調整し、解析ノートや他の参照証拠には影響しません",
        "음높이 선만 조절하며 분석 음표와 다른 참조 근거에는 영향을 주지 않습니다",
    ),
    "旋律引导（弱证据）": (
        "Melody guidance (weak evidence)",
        "メロディガイド（弱い証拠）",
        "멜로디 안내(약한 근거)",
    ),
    "按时间段统计当前轨道手工音符命中的音色组；只渐进突出显示，不修改识别和乐器标签": (
        "Counts timbre-group hits from manually edited notes in time windows; only changes gradual emphasis and never recognition or instrument labels",
        "現在のトラックで手動編集したノートの音色グループ命中を時間区間ごとに集計します。段階的な強調表示だけを行い、認識結果や楽器ラベルは変更しません",
        "현재 트랙에서 수동 편집한 음표의 음색 그룹 적중을 시간 구간별로 집계합니다. 점진적 강조만 바꾸며 인식 결과나 악기 라벨은 수정하지 않습니다",
    ),
    "按时间段统计当前轨道手工音符命中的音色组；稳定后最高优先标记为当前轨道乐器，不修改声学识别或导出": (
        "Counts timbre-group hits from manually edited notes in time windows; once stable, labels that group as the current track instrument at highest priority without changing acoustic recognition or export",
        "現在のトラックで手動編集したノートの音色グループ命中を時間区間ごとに集計し、安定後は現在のトラック楽器を最優先で表示します。音響認識や書き出しは変更しません",
        "현재 트랙에서 수동 편집한 음표의 음색 그룹 적중을 시간 구간별로 집계하고 안정되면 현재 트랙 악기를 최우선으로 표시합니다. 음향 인식이나 내보내기는 변경하지 않습니다",
    ),
    "旋律引导已关闭": (
        "Melody guidance is off",
        "メロディガイドはオフです",
        "멜로디 안내가 꺼져 있습니다",
    ),
    "引导开启 · {notes} 个可用音符 · 尚未形成稳定音色倾向": (
        "Guidance on · {notes} usable notes · no stable timbre tendency yet",
        "ガイド有効・使用可能なノート {notes} 個・安定した音色傾向はまだありません",
        "안내 켜짐 · 사용 가능한 음표 {notes}개 · 아직 안정적인 음색 경향이 없습니다",
    ),
    "引导开启 · {windows} 个时间段 · {hits} 个去重命中 · {state}": (
        "Guidance on · {windows} windows · {hits} deduplicated hits · {state}",
        "ガイド有効・{windows} 区間・重複除外後 {hits} 命中・{state}",
        "안내 켜짐 · 시간 구간 {windows}개 · 중복 제거 적중 {hits}개 · {state}",
    ),
    "引导开启 · {windows} 个时间段 · {hits} 个去重命中 · {state}{target}": (
        "Guidance on · {windows} windows · {hits} deduplicated hits · {state}{target}",
        "ガイド有効・{windows} 区間・重複除外後 {hits} 命中・{state}{target}",
        "안내 켜짐 · 시간 구간 {windows}개 · 중복 제거 적중 {hits}개 · {state}{target}",
    ),
    " · 最高优先：{instrument}": (
        " · highest priority: {instrument}",
        "・最優先：{instrument}",
        " · 최우선: {instrument}",
    ),
    "{group} · 引导确认：{instrument}（最高优先） · 声学分类 {confidence}%": (
        "{group} · guidance-confirmed: {instrument} (highest priority) · acoustic classification {confidence}%",
        "{group}・ガイド確認：{instrument}（最優先）・音響分類 {confidence}%",
        "{group} · 안내 확인: {instrument}(최우선) · 음향 분류 {confidence}%",
    ),
    "引导：{instrument} · ": (
        "Guided: {instrument} · ",
        "ガイド：{instrument}・",
        "안내: {instrument} · ",
    ),
    "已形成渐进突出": (
        "gradual emphasis established",
        "段階的な強調を形成済み",
        "점진적 강조 형성됨",
    ),
    "已形成少样本预测 {confidence}%": (
        "few-sample prediction {confidence}%",
        "少数サンプル予測 {confidence}%",
        "소수 샘플 예측 {confidence}%",
    ),
    "证据仍在累积": (
        "evidence is still accumulating",
        "証拠を蓄積中",
        "근거 누적 중",
    ),
    "旋律线、Frame、Onset 与声谱透明度；音高线在其菜单内单独调整": (
        "Melody-line, Frame, Onset, and spectrogram opacity; adjust pitch lines separately in their menu",
        "メロディライン、Frame、Onset、スペクトログラムの不透明度。ピッチラインは専用メニューで個別に調整します",
        "멜로디 선, Frame, Onset 및 스펙트로그램 불투명도입니다. 음높이 선은 해당 메뉴에서 별도로 조절합니다",
    ),
    "专注音高线": ("Focus pitch line", "ピッチラインに集中", "음높이 선에 집중"),
    "临时隐藏分析音块和声部提示，只查看连续音高线": (
        "Temporarily hide analyzed notes and voice hints to inspect only the continuous pitch line",
        "解析ノートと声部ヒントを一時的に隠し、連続ピッチラインだけを表示します",
        "분석 음표와 성부 힌트를 잠시 숨기고 연속 음높이 선만 표시합니다",
    ),
    "按音色分组着色（实验）": (
        "Color by timbre (experimental)",
        "音色別に色分け（実験）",
        "음색별 색상(실험)",
    ),
    "从低重叠片段提取音色特征并稳定着色；结果只用于参考显示，不会修改候选音符或正式轨道": (
        "Extract timbre from low-overlap passages and apply stable colors. This is display-only and never changes candidates or score tracks.",
        "重なりの少ない区間から音色特徴を抽出して安定した色を付けます。表示専用で、候補音符や正式トラックは変更しません。",
        "겹침이 적은 구간에서 음색 특징을 추출해 안정적인 색상을 적용합니다. 표시 전용이며 후보 음표나 정식 트랙을 변경하지 않습니다.",
    ),
    "通用乐器标签（可选）": (
        "Generic instrument labels (optional)",
        "一般楽器ラベル（任意）",
        "일반 악기 라벨(선택)",
    ),
    "需要单独安装 MuScriptor；模型不随应用打包，首次运行可能由 MuScriptor 下载；不会写入分轨": (
        "Requires a separate MuScriptor installation. Models are not bundled and MuScriptor may download one on first use; no tracks are created.",
        "MuScriptorを別途インストールする必要があります。モデルは同梱されず、初回実行時にMuScriptorがダウンロードする場合があります。トラックは作成しません。",
        "MuScriptor를 별도로 설치해야 합니다. 모델은 포함되지 않으며 첫 실행 시 MuScriptor가 다운로드할 수 있습니다. 트랙은 생성하지 않습니다.",
    ),
    "由已安装的 MuScriptor small 提供通用乐器标签；结果不会自动分轨": (
        "Uses an installed MuScriptor small model for generic labels; results never create tracks automatically.",
        "インストール済みのMuScriptor smallで一般ラベルを付けます。結果から自動でトラックを作成しません。",
        "설치된 MuScriptor small로 일반 라벨을 제공합니다. 결과로 트랙을 자동 생성하지 않습니다.",
    ),
    "乐器颜色：自动分类": (
        "Instrument colors: automatic classification",
        "楽器カラー：自動分類",
        "악기 색상: 자동 분류",
    ),
    "完成分析后自动按乐器颜色显示分析音块": (
        "Analyzed notes automatically use instrument colors after analysis",
        "解析後、解析ノートを楽器カラーで自動表示します",
        "분석 후 분석 음표를 악기 색상으로 자동 표시합니다",
    ),
    "完成分析后自动按乐器颜色显示音高线": (
        "Pitch lines automatically use instrument colors after analysis",
        "解析後、ピッチラインを楽器カラーで自動表示します",
        "분석 후 음높이 선을 악기 색상으로 자동 표시합니다",
    ),
    "分析完成 · 未找到可分类音色；分析音块保持中性色": (
        "Analysis complete · no classifiable timbre found; analyzed notes remain neutral",
        "解析完了・分類可能な音色が見つからないため、解析ノートは中間色のままです",
        "분석 완료 · 분류 가능한 음색을 찾지 못해 분석 음표는 중립색으로 유지됩니다",
    ),
    "分析完成 · 未找到可分类音色；音高线保持中性色": (
        "Analysis complete · no classifiable timbre found; pitch lines remain neutral",
        "解析完了・分類可能な音色が見つからないため、ピッチラインは中間色のままです",
        "분석 완료 · 분류 가능한 음색을 찾지 못해 음높이 선은 중립색으로 유지됩니다",
    ),
    "少样本预测 · 声学复核中": (
        "Few-sample prediction · acoustic verification in progress",
        "少数サンプル予測・音響検証中",
        "소수 샘플 예측 · 음향 검증 중",
    ),
    "少样本预测 · 声学复核不可用": (
        "Few-sample prediction · acoustic verification unavailable",
        "少数サンプル予測・音響検証を利用できません",
        "소수 샘플 예측 · 음향 검증 사용 불가",
    ),
    "少样本预测 · 等待更多音频证据": (
        "Few-sample prediction · awaiting more audio evidence",
        "少数サンプル予測・追加の音声証拠を待機中",
        "소수 샘플 예측 · 추가 오디오 증거 대기 중",
    ),
    "颜色=乐器组 · 饱和度=分类把握 · 透明度=局部音频证据": (
        "Hue = instrument group · saturation = class confidence · opacity = local audio evidence",
        "色相＝楽器グループ・彩度＝分類の確信度・不透明度＝局所音声証拠",
        "색상=악기 그룹 · 채도=분류 확신도 · 불투명도=국소 오디오 증거",
    ),
    "正在提取低污染音色片段…": (
        "Extracting low-contamination timbre passages…",
        "混入の少ない音色区間を抽出中…",
        "혼입이 적은 음색 구간을 추출하는 중…",
    ),
    "正在自动分类并生成音高线颜色…": (
        "Automatically classifying and generating pitch-line colors…",
        "自動分類してピッチラインの色を生成中…",
        "자동 분류하고 음높이 선 색상을 생성하는 중…",
    ),
    "音色分组不可用；候选音符未受影响": (
        "Timbre grouping is unavailable; candidate notes were not changed",
        "音色グループ化を利用できません。候補音符は変更されていません",
        "음색 그룹화를 사용할 수 없습니다. 후보 음표는 변경되지 않았습니다",
    ),
    "乐器颜色不可用；音高线保持中性色": (
        "Instrument colors are unavailable; pitch lines remain neutral",
        "楽器カラーを利用できないため、ピッチラインは中間色のままです",
        "악기 색상을 사용할 수 없어 음높이 선은 중립색으로 유지됩니다",
    ),
    "外部标签不可用；仅显示匿名音色": (
        "External labels are unavailable; showing anonymous timbres only",
        "外部ラベルを利用できないため、匿名音色のみ表示します",
        "외부 라벨을 사용할 수 없어 익명 음색만 표시합니다",
    ),
    "外部标签分析失败；仅显示匿名音色": (
        "External label analysis failed; showing anonymous timbres only",
        "外部ラベル分析に失敗したため、匿名音色のみ表示します",
        "외부 라벨 분석에 실패하여 익명 음색만 표시합니다",
    ),
    "外部标签未通过一致性门槛；仅显示匿名音色": (
        "External labels did not meet the consensus threshold; showing anonymous timbres only",
        "外部ラベルが一致度の基準を満たさないため、匿名音色のみ表示します",
        "외부 라벨이 일치도 기준을 충족하지 않아 익명 음색만 표시합니다",
    ),
    "未分类": ("Unclassified", "未分類", "미분류"),
    "未分类 · 证据不足": (
        "Unclassified · insufficient evidence",
        "未分類・証拠不足",
        "미분류 · 근거 부족",
    ),
    "自动分类 {classified}/{total}": (
        "Auto-classified {classified}/{total}",
        "自動分類 {classified}/{total}",
        "자동 분류 {classified}/{total}",
    ),
    "已分为 {groups} 组 · 覆盖 {classified}/{total} · 平均可信 {confidence}%": (
        "{groups} groups · coverage {classified}/{total} · average confidence {confidence}%",
        "{groups}グループ・対象 {classified}/{total}・平均信頼度 {confidence}%",
        "{groups}개 그룹 · 범위 {classified}/{total} · 평균 신뢰도 {confidence}%",
    ),
    "预测中 · 正在用音频校正": (
        "Predicting · refining with audio",
        "予測中・音声で補正しています",
        "예측 중 · 오디오로 보정 중",
    ),
    "预测结果 · 音频校正不可用": (
        "Prediction · audio refinement unavailable",
        "予測結果・音声補正を利用できません",
        "예측 결과 · 오디오 보정 사용 불가",
    ),
    "预测结果 · 等待更多音频证据": (
        "Prediction · awaiting more audio evidence",
        "予測結果・追加の音声根拠を待っています",
        "예측 결과 · 추가 오디오 근거 대기 중",
    ),
    "声学已确认 · 少量片段仍为预测": (
        "Audio-confirmed · a few segments remain predicted",
        "音響確認済み・一部の区間は予測のままです",
        "음향 확인 완료 · 일부 구간은 아직 예측",
    ),
    "声学已确认": (
        "Audio-confirmed",
        "音響確認済み",
        "음향 확인 완료",
    ),
    "{group} · {confidence}% · {count} 个": (
        "{group} · {confidence}% · {count} notes",
        "{group}・{confidence}%・{count}音",
        "{group} · {confidence}% · {count}개",
    ),
    "{group} · 疑似{family} {confidence}% · {count} 个": (
        "{group} · likely {family} {confidence}% · {count} notes",
        "{group}・{family}の可能性 {confidence}%・{count}音",
        "{group} · {family} 추정 {confidence}% · {count}개",
    ),
    "{group} · {instrument} · 引导优先 · {count} 个": (
        "{group} · {instrument} · guidance priority · {count} notes",
        "{group}・{instrument}・ガイド優先・{count}音",
        "{group} · {instrument} · 가이드 우선 · {count}개",
    ),
    "未分类 · {count} 个": (
        "Unclassified · {count} notes",
        "未分類・{count}音",
        "미분류 · {count}개",
    ),
    "另有 {count} 组": (
        "{count} more groups",
        "ほか {count}グループ",
        "그 외 {count}개 그룹",
    ),
    "颜色越鲜明，判断越可靠": (
        "Brighter colors indicate more reliable results",
        "色が鮮明なほど判断の信頼性が高くなります",
        "색이 선명할수록 판단이 더 신뢰할 만합니다",
    ),
    "音色 {name}": ("Timbre {name}", "音色 {name}", "음색 {name}"),
    "{group} · 分类置信 {confidence}%": (
        "{group} · class confidence {confidence}%",
        "{group}・分類信頼度 {confidence}%",
        "{group} · 분류 신뢰도 {confidence}%",
    ),
    "识别 {recognition}% · 分类 {classification}%": (
        "recognition {recognition}% · class {classification}%",
        "認識 {recognition}%・分類 {classification}%",
        "인식 {recognition}% · 분류 {classification}%",
    ),
    "{group} · 疑似{family} {confidence}%": (
        "{group} · likely {family} {confidence}%",
        "{group}・{family}の可能性 {confidence}%",
        "{group} · {family} 추정 {confidence}%",
    ),
    "钢琴": ("Piano", "ピアノ", "피아노"),
    "键盘打击乐": (
        "Chromatic percussion",
        "鍵盤打楽器",
        "건반 타악기",
    ),
    "风琴": ("Organ", "オルガン", "오르간"),
    "吉他类": ("Guitar family", "ギター系", "기타 계열"),
    "贝斯类": ("Bass family", "ベース系", "베이스 계열"),
    "弦乐组": ("String family", "弦楽器群", "현악기군"),
    "合奏": ("Ensemble", "アンサンブル", "앙상블"),
    "铜管": ("Brass", "金管", "금관악기"),
    "簧管": ("Reed", "リード", "리드 악기"),
    "吹管": ("Pipe", "パイプ", "파이프"),
    "合成器主音": ("Synth lead", "シンセリード", "신스 리드"),
    "合成器铺底": ("Synth pad", "シンセパッド", "신스 패드"),
    "合成器效果": ("Synth effect", "シンセ効果", "신스 효과"),
    "民族乐器": ("Ethnic", "民族楽器", "민속 악기"),
    "鼓组": ("Drum kit", "ドラムキット", "드럼 키트"),
}

for _source, (_english, _japanese, _korean) in (
    _REFERENCE_TIMBRE_TRANSLATIONS.items()
):
    if _source in EN or _source in JA or _source in KO:
        raise RuntimeError(
            f"duplicate reference-timbre localization source: {_source}"
        )
    EN[_source] = _english
    JA[_source] = _japanese
    KO[_source] = _korean

del _source, _english, _japanese, _korean

EN.update({
    "MIDI {pitch} · 未映射鼓键": "MIDI {pitch} · Unmapped drum key",
})
JA.update({
    "MIDI {pitch} · 未映射鼓键": "MIDI {pitch}・未割り当てのドラムキー",
})
KO.update({
    "MIDI {pitch} · 未映射鼓键": "MIDI {pitch} · 매핑되지 않은 드럼 키",
})


_EFFECT_GUIDANCE_TRANSLATIONS = {
    "音源与外观": (
        "Audio & Appearance",
        "音源と外観",
        "음원 및 외관",
    ),
    "全局效果": (
        "Global FX",
        "グローバルFX",
        "전역 FX",
    ),
    "全局主效果": (
        "Global Master FX",
        "グローバルマスターFX",
        "전역 마스터 FX",
    ),
    "整首曲子共用这些参数；轨道使用多少效果仍由每条轨道的 FX 发送量决定。": (
        "These parameters are shared by the whole score; each track's FX sends still determine how much effect it uses.",
        "これらのパラメーターは曲全体で共有されます。各トラックの効果量は引き続きトラックFXの送信量で決まります。",
        "이 매개변수는 곡 전체가 공유합니다. 각 트랙의 효과 양은 계속 트랙 FX 전송량으로 결정됩니다.",
    ),
    "这里仅修改全局参数，不会改动任何轨道的混响、延迟或合唱发送量。": (
        "This changes only global parameters; no track's reverb, delay, or chorus send is modified.",
        "ここではグローバルパラメーターだけを変更し、各トラックのリバーブ／ディレイ／コーラス送信量は変更しません。",
        "여기서는 전역 매개변수만 변경하며 어떤 트랙의 리버브, 딜레이 또는 코러스 전송량도 바꾸지 않습니다.",
    ),
    "混响与延迟": (
        "Reverb & Delay",
        "リバーブとディレイ",
        "리버브 및 딜레이",
    ),
    "混响时间控制空间尾音；延迟反馈控制回声重复次数。": (
        "Reverb Time controls the room tail; Delay Feedback controls how many times the echo repeats.",
        "リバーブ時間は空間の残響を、ディレイフィードバックは反響の反復回数を調整します。",
        "리버브 시간은 공간의 잔향을, 딜레이 피드백은 에코 반복 횟수를 조절합니다.",
    ),
    "合唱（游戏中为 Flanger）": (
        "Chorus (Flanger in game)",
        "コーラス（ゲーム内ではFlanger）",
        "코러스(게임에서는 Flanger)",
    ),
    "反馈决定旋动感，LFO 深度决定摆动幅度，LFO 频率决定摆动速度。": (
        "Feedback sets the swirling character, LFO Depth sets its range, and LFO Frequency sets its speed.",
        "フィードバックは回転感、LFO深度は揺れ幅、LFO周波数は揺れる速さを決めます。",
        "피드백은 회전감을, LFO 깊이는 흔들림 폭을, LFO 주파수는 흔들림 속도를 결정합니다.",
    ),
    "全局主效果已更新": (
        "Global master FX updated",
        "グローバルマスターFXを更新しました",
        "전역 마스터 FX를 업데이트했습니다",
    ),
    "每轨发送在轨道 FX；延迟产生回声，合唱增加宽度与流动感。本地试听为未校准近似，导出值不变。": (
        "Per-track sends are in Track FX; delay creates echoes and chorus adds width and movement. Local preview is an uncalibrated approximation; export values are unchanged.",
        "トラックごとの送信量はトラックFXで設定します。ディレイは反響を、コーラスは広がりと揺らぎを加えます。ローカル試聴は未校正の近似で、書き出し値は変わりません。",
        "트랙별 전송량은 트랙 FX에서 설정합니다. 딜레이는 에코를 만들고 코러스는 폭과 움직임을 더합니다. 로컬 미리듣기는 보정되지 않은 근사치이며 내보내기 값은 바뀌지 않습니다.",
    ),
    "混响发送：控制此轨道进入共享混响的比例；0 为干声。": (
        "Reverb Send: controls how much of this track enters the shared reverb; 0 is dry.",
        "リバーブ送信：このトラックを共有リバーブへ送る量です。0はドライ音です。",
        "리버브 전송: 이 트랙을 공유 리버브로 보내는 양입니다. 0은 드라이 신호입니다.",
    ),
    "延迟发送：控制此轨道进入回声总线的比例；主“延迟反馈”决定重复次数与衰减。": (
        "Delay Send: controls how much of this track enters the echo bus; master Delay Feedback controls repeat count and decay.",
        "ディレイ送信：このトラックをエコーバスへ送る量です。マスターの「ディレイフィードバック」が反復回数と減衰を決めます。",
        "딜레이 전송: 이 트랙을 에코 버스로 보내는 양입니다. 마스터 딜레이 피드백이 반복 횟수와 감쇠를 정합니다.",
    ),
    "合唱发送：控制此轨道进入合唱/Flanger 总线的比例；用于加宽并产生流动感。": (
        "Chorus Send: controls how much of this track enters the chorus/flanger bus; it adds width and movement.",
        "コーラス送信：このトラックをコーラス／フランジャーバスへ送る量です。広がりと揺らぎを加えます。",
        "코러스 전송: 이 트랙을 코러스/플랜저 버스로 보내는 양입니다. 폭과 움직임을 더합니다.",
    ),
    "混响时间：控制混响尾音长度；本地试听按 0.2–8.0 秒近似。": (
        "Reverb Time: controls the reverb-tail length; local preview approximates 0.2–8.0 seconds.",
        "リバーブ時間：残響の長さを調整します。ローカル試聴では0.2～8.0秒として近似します。",
        "리버브 시간: 잔향 길이를 조절합니다. 로컬 미리듣기는 0.2–8.0초로 근사합니다.",
    ),
    "延迟反馈：控制回声返回延迟线的比例；游戏说明约 2–20 次延迟声，本地试听固定约 250 ms 并按该范围近似。": (
        "Delay Feedback: controls how much echo returns to the delay line. The game guide describes about 2–20 delayed sounds; local preview uses about 250 ms and approximates that range.",
        "ディレイフィードバック：エコーをディレイラインへ戻す量です。ゲームガイドの約2～20回のディレイ音に合わせ、ローカル試聴は約250 ms固定で近似します。",
        "딜레이 피드백: 에코가 딜레이 라인으로 돌아가는 양입니다. 게임 가이드의 약 2–20회 지연음을 기준으로 로컬 미리듣기는 약 250ms 고정으로 근사합니다.",
    ),
    "合唱反馈：控制调制延迟的反馈强度；越高，梳状与旋动感越明显。": (
        "Chorus Feedback: controls modulated-delay feedback; higher values make comb filtering and swirling more pronounced.",
        "コーラスフィードバック：変調ディレイのフィードバック量です。高いほどコーム感と回転感が強くなります。",
        "코러스 피드백: 변조 딜레이의 피드백 양입니다. 높을수록 콤 필터와 회전감이 강해집니다.",
    ),
    "LFO 深度：控制合唱延迟时间的摆动幅度；越高，空间宽度与音高摆动越明显。": (
        "LFO Depth: controls the chorus delay-time modulation; higher values increase width and pitch movement.",
        "LFO深度：コーラスのディレイ時間が揺れる幅です。高いほど広がりと音程の揺れが強くなります。",
        "LFO 깊이: 코러스 딜레이 시간이 흔들리는 폭입니다. 높을수록 공간 폭과 음높이 움직임이 커집니다.",
    ),
    "LFO 频率：控制合唱起伏速度；0 仍为慢速运动，本地试听按约 0.03–0.30 Hz 近似。": (
        "LFO Frequency: controls the chorus modulation speed. Zero still moves slowly; local preview approximates about 0.03–0.30 Hz.",
        "LFO周波数：コーラスの揺れる速さです。0でもゆっくり動き、ローカル試聴では約0.03～0.30 Hzとして近似します。",
        "LFO 주파수: 코러스가 움직이는 속도입니다. 0에서도 천천히 움직이며, 로컬 미리듣기는 약 0.03–0.30Hz로 근사합니다.",
    ),
}

for _source, (_english, _japanese, _korean) in _EFFECT_GUIDANCE_TRANSLATIONS.items():
    if _source in EN or _source in JA or _source in KO:
        raise RuntimeError(f"duplicate effect-guidance localization source: {_source}")
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


EN.update({
    "切换或锁定试听音源；仅用于本机试听，不会写入曲谱，也不会上传。": "Switch or lock the preview source. It is used only for local preview and is never written to scores or uploaded.",
    "自动选择音源": "Choose Source Automatically",
    "锁定本地 BDO 音源": "Lock Local BDO Source",
    "锁定内置通用 MIDI": "Lock Built-in General MIDI",
    "试听音源": "Preview Source",
    "自动音源 · 检测中": "Automatic Source · Detecting",
    "点击切换试听音源；不会改变导出结果": "Click to switch the preview source; export is unchanged",
    "管理本地音源包…": "Manage Local Sample Pack…",
    "未设置用户": "User Not Set",
    "设置角色名与 Owner ID": "Set character name and Owner ID",
    "用户 · {name}": "User · {name}",
    " · Owner ID 未设置": " · Owner ID not set",
    "尚未设置用户名称和 Owner ID；请在设置中补充后再导出。": "User name and Owner ID are not set. Add them in Settings before export.",
    "尚未设置用户名称；请在设置中补充。": "User name is not set. Add it in Settings.",
    "Owner ID 未设置；导出前需要从游戏曲谱读取。": "Owner ID is not set. Read it from an in-game score before export.",
    "内置通用 MIDI · 非游戏原声": "Built-in General MIDI · Not Game Audio",
    "内置通用 MIDI · 已锁定": "Built-in General MIDI · Locked",
    "本地 BDO 音源不可用": "Local BDO Source Unavailable",
    "自动音源 · 内置通用 MIDI": "Automatic Source · Built-in General MIDI",
    "本地 BDO 音源 · 已验证": "Local BDO Source · Verified",
    "自动音源 · BDO 已验证": "Automatic Source · BDO Verified",
    "本地 BDO 音源 · DSP 待 A/B": "Local BDO Source · DSP A/B Pending",
    "自动音源 · BDO 近似": "Automatic Source · Approximate BDO",
    "试听音源已切换：{source}": "Preview source changed: {source}",
    "已锁定本地 BDO 音源，当前无法试听：{reason}": "The local BDO source is locked but cannot preview now: {reason}",
    "{instrument} · {count} 音符": "{instrument} · {count} notes",
    "打开转换检查": "Open Conversion Check",
    "轨道存在 {count} 个导出错误 · 点击查看": "Tracks contain {count} export errors · Click to review",
    " · 相同乐器将合并": " · Duplicate instruments will be merged",
    "相同乐器轨道将在导出时合并 · 点击查看": "Tracks using the same instrument will be merged on export · Click to review",
    "设置演奏者": "Set Performer",
    "身份待完善": "Complete Identity",
    "Owner ID 已绑定": "Owner ID linked",
    "Owner ID 未设置": "Owner ID not set",
    "Owner ID 已绑定；点击可更改": "Owner ID linked; click to change it",
    "Owner ID 未设置；点击前往设置": "Owner ID not set; click to open Settings",
    "点击头像，从游戏曲谱快速设置 Owner ID": "Click the avatar to set the Owner ID from an in-game score",
    "Owner ID 已绑定；点击 Logo 可更改": "Owner ID linked; click the logo to change it",
    "Owner ID 未设置；点击 Logo 快速设置": "Owner ID not set; click the logo to set it",
    "Owner ID 快捷设置": "Owner ID quick setup",
    "导出错误": "Export Errors",
    "需要注意": "Attention",
    "发现 {count} 个导出错误；对应轨道已标红，可点击轨道标记查看。": "Found {count} export errors. Affected tracks are marked red; click a track marker to review.",
    "{count} 条轨道使用相同乐器；已标为琥珀色，导出时会合并。": "{count} tracks use the same instrument. They are marked amber and will be merged on export.",
})
JA.update({
    "切换或锁定试听音源；仅用于本机试听，不会写入曲谱，也不会上传。": "試聴音源を切り替えまたは固定します。ローカル試聴専用で、楽譜への書き込みやアップロードは行いません。",
    "自动选择音源": "音源を自動選択",
    "锁定本地 BDO 音源": "ローカルBDO音源に固定",
    "锁定内置通用 MIDI": "内蔵General MIDIに固定",
    "试听音源": "試聴音源",
    "自动音源 · 检测中": "自動音源 · 検出中",
    "点击切换试听音源；不会改变导出结果": "クリックして試聴音源を切り替えます。書き出し結果は変わりません",
    "管理本地音源包…": "ローカル音源パックを管理…",
    "未设置用户": "ユーザー未設定",
    "设置角色名与 Owner ID": "キャラクター名とOwner IDを設定",
    "用户 · {name}": "ユーザー · {name}",
    " · Owner ID 未设置": " · Owner ID未設定",
    "尚未设置用户名称和 Owner ID；请在设置中补充后再导出。": "ユーザー名とOwner IDが未設定です。書き出し前に設定で追加してください。",
    "尚未设置用户名称；请在设置中补充。": "ユーザー名が未設定です。設定で追加してください。",
    "Owner ID 未设置；导出前需要从游戏曲谱读取。": "Owner IDが未設定です。書き出し前にゲーム楽譜から読み取ってください。",
    "内置通用 MIDI · 非游戏原声": "内蔵General MIDI · ゲーム原音ではありません",
    "内置通用 MIDI · 已锁定": "内蔵General MIDI · 固定",
    "本地 BDO 音源不可用": "ローカルBDO音源を使用できません",
    "自动音源 · 内置通用 MIDI": "自動音源 · 内蔵General MIDI",
    "本地 BDO 音源 · 已验证": "ローカルBDO音源 · 検証済み",
    "自动音源 · BDO 已验证": "自動音源 · BDO検証済み",
    "本地 BDO 音源 · DSP 待 A/B": "ローカルBDO音源 · DSP A/B待ち",
    "自动音源 · BDO 近似": "自動音源 · BDO近似",
    "试听音源已切换：{source}": "試聴音源を切り替えました：{source}",
    "已锁定本地 BDO 音源，当前无法试听：{reason}": "ローカルBDO音源に固定されていますが、現在試聴できません：{reason}",
    "{instrument} · {count} 音符": "{instrument} · {count}ノート",
    "打开转换检查": "変換チェックを開く",
    "轨道存在 {count} 个导出错误 · 点击查看": "トラックに書き出しエラーが{count}件あります · クリックして確認",
    " · 相同乐器将合并": " · 同じ楽器は統合されます",
    "相同乐器轨道将在导出时合并 · 点击查看": "同じ楽器のトラックは書き出し時に統合されます · クリックして確認",
    "设置演奏者": "演奏者を設定",
    "身份待完善": "本人情報を完了",
    "Owner ID 已绑定": "Owner ID連携済み",
    "Owner ID 未设置": "Owner ID未設定",
    "Owner ID 已绑定；点击可更改": "Owner ID連携済み。クリックして変更できます",
    "Owner ID 未设置；点击前往设置": "Owner ID未設定。クリックして設定を開きます",
    "点击头像，从游戏曲谱快速设置 Owner ID": "アバターをクリックしてゲーム楽譜からOwner IDを設定します",
    "Owner ID 已绑定；点击 Logo 可更改": "Owner ID連携済み。ロゴをクリックして変更できます",
    "Owner ID 未设置；点击 Logo 快速设置": "Owner ID未設定。ロゴをクリックして設定します",
    "Owner ID 快捷设置": "Owner IDクイック設定",
    "导出错误": "書き出しエラー",
    "需要注意": "要確認",
    "发现 {count} 个导出错误；对应轨道已标红，可点击轨道标记查看。": "書き出しエラーが{count}件あります。対象トラックは赤で表示され、トラックマーカーをクリックして確認できます。",
    "{count} 条轨道使用相同乐器；已标为琥珀色，导出时会合并。": "{count}トラックが同じ楽器を使用しています。琥珀色で表示され、書き出し時に統合されます。",
})
KO.update({
    "切换或锁定试听音源；仅用于本机试听，不会写入曲谱，也不会上传。": "미리듣기 음원을 전환하거나 고정합니다. 로컬 미리듣기에만 사용되며 악보에 기록되거나 업로드되지 않습니다.",
    "自动选择音源": "음원 자동 선택",
    "锁定本地 BDO 音源": "로컬 BDO 음원 고정",
    "锁定内置通用 MIDI": "내장 General MIDI 고정",
    "试听音源": "미리듣기 음원",
    "自动音源 · 检测中": "자동 음원 · 감지 중",
    "点击切换试听音源；不会改变导出结果": "클릭하여 미리듣기 음원을 전환합니다. 내보내기 결과는 바뀌지 않습니다",
    "管理本地音源包…": "로컬 음원 팩 관리…",
    "未设置用户": "사용자 미설정",
    "设置角色名与 Owner ID": "캐릭터 이름과 Owner ID 설정",
    "用户 · {name}": "사용자 · {name}",
    " · Owner ID 未设置": " · Owner ID 미설정",
    "尚未设置用户名称和 Owner ID；请在设置中补充后再导出。": "사용자 이름과 Owner ID가 설정되지 않았습니다. 내보내기 전에 설정에서 추가하세요.",
    "尚未设置用户名称；请在设置中补充。": "사용자 이름이 설정되지 않았습니다. 설정에서 추가하세요.",
    "Owner ID 未设置；导出前需要从游戏曲谱读取。": "Owner ID가 설정되지 않았습니다. 내보내기 전에 게임 악보에서 읽으세요.",
    "内置通用 MIDI · 非游戏原声": "내장 General MIDI · 게임 원음 아님",
    "内置通用 MIDI · 已锁定": "내장 General MIDI · 고정됨",
    "本地 BDO 音源不可用": "로컬 BDO 음원을 사용할 수 없음",
    "自动音源 · 内置通用 MIDI": "자동 음원 · 내장 General MIDI",
    "本地 BDO 音源 · 已验证": "로컬 BDO 음원 · 검증됨",
    "自动音源 · BDO 已验证": "자동 음원 · BDO 검증됨",
    "本地 BDO 音源 · DSP 待 A/B": "로컬 BDO 음원 · DSP A/B 대기",
    "自动音源 · BDO 近似": "자동 음원 · BDO 근사",
    "试听音源已切换：{source}": "미리듣기 음원 전환: {source}",
    "已锁定本地 BDO 音源，当前无法试听：{reason}": "로컬 BDO 음원이 고정되어 있지만 현재 미리들을 수 없습니다: {reason}",
    "{instrument} · {count} 音符": "{instrument} · 노트 {count}개",
    "打开转换检查": "변환 검사 열기",
    "轨道存在 {count} 个导出错误 · 点击查看": "트랙에 내보내기 오류 {count}개가 있습니다 · 클릭하여 확인",
    " · 相同乐器将合并": " · 같은 악기는 병합됩니다",
    "相同乐器轨道将在导出时合并 · 点击查看": "같은 악기의 트랙은 내보낼 때 병합됩니다 · 클릭하여 확인",
    "设置演奏者": "연주자 설정",
    "身份待完善": "사용자 정보 완성",
    "Owner ID 已绑定": "Owner ID 연결됨",
    "Owner ID 未设置": "Owner ID 미설정",
    "Owner ID 已绑定；点击可更改": "Owner ID 연결됨. 클릭하여 변경",
    "Owner ID 未设置；点击前往设置": "Owner ID 미설정. 클릭하여 설정 열기",
    "点击头像，从游戏曲谱快速设置 Owner ID": "아바타를 클릭하여 게임 악보에서 Owner ID 설정",
    "Owner ID 已绑定；点击 Logo 可更改": "Owner ID 연결됨. 로고를 클릭하여 변경",
    "Owner ID 未设置；点击 Logo 快速设置": "Owner ID 미설정. 로고를 클릭하여 설정",
    "Owner ID 快捷设置": "Owner ID 빠른 설정",
    "导出错误": "내보내기 오류",
    "需要注意": "주의 필요",
    "发现 {count} 个导出错误；对应轨道已标红，可点击轨道标记查看。": "내보내기 오류 {count}개를 발견했습니다. 해당 트랙은 빨간색으로 표시되며 트랙 마커를 클릭해 확인할 수 있습니다.",
    "{count} 条轨道使用相同乐器；已标为琥珀色，导出时会合并。": "{count}개 트랙이 같은 악기를 사용합니다. 호박색으로 표시되며 내보낼 때 병합됩니다.",
})


EN.update({
    "轨道八度…": "Track Octave…",
    "轨道八度": "Track Octave",
    "只做声部八度适配，不改动工程中的原始音符；试听、检查和导出会使用同一结果。": (
        "Adapts only the voice octave without changing source notes; preview, "
        "validation, and export use the same result."
    ),
    "跟随全局": "Follow Global",
    "{octaves:+d} 个八度（{semitones:+d} 半音）": (
        "{octaves:+d} octaves ({semitones:+d} semitones)"
    ),
    "声部八度": "Voice Octave",
    "全局 {global_transpose:+d} + 轨道 {track_transpose:+d} = 最终 {effective:+d} 半音": (
        "Global {global_transpose:+d} + track {track_transpose:+d} = "
        "{effective:+d} semitones effective"
    ),
    "{track} · 轨道八度 {track_transpose:+d} · 最终移调 {effective:+d} 半音": (
        "{track} · track octave {track_transpose:+d} · "
        "{effective:+d} semitones effective"
    ),
})

JA.update({
    "轨道八度…": "トラック・オクターブ…",
    "轨道八度": "トラック・オクターブ",
    "只做声部八度适配，不改动工程中的原始音符；试听、检查和导出会使用同一结果。": (
        "元のノートを変更せず声部のオクターブだけを調整します。試聴、検証、書き出しは同じ結果を使用します。"
    ),
    "跟随全局": "グローバルに従う",
    "{octaves:+d} 个八度（{semitones:+d} 半音）": (
        "{octaves:+d} オクターブ（{semitones:+d} 半音）"
    ),
    "声部八度": "声部オクターブ",
    "全局 {global_transpose:+d} + 轨道 {track_transpose:+d} = 最终 {effective:+d} 半音": (
        "全体 {global_transpose:+d} + トラック {track_transpose:+d} = 最終 {effective:+d} 半音"
    ),
    "{track} · 轨道八度 {track_transpose:+d} · 最终移调 {effective:+d} 半音": (
        "{track} · トラック・オクターブ {track_transpose:+d} · 最終移調 {effective:+d} 半音"
    ),
})

KO.update({
    "轨道八度…": "트랙 옥타브…",
    "轨道八度": "트랙 옥타브",
    "只做声部八度适配，不改动工程中的原始音符；试听、检查和导出会使用同一结果。": (
        "원본 음표를 바꾸지 않고 성부 옥타브만 조정합니다. 미리듣기, 검사, 내보내기는 같은 결과를 사용합니다."
    ),
    "跟随全局": "전역 설정 따르기",
    "{octaves:+d} 个八度（{semitones:+d} 半音）": (
        "{octaves:+d} 옥타브({semitones:+d} 반음)"
    ),
    "声部八度": "성부 옥타브",
    "全局 {global_transpose:+d} + 轨道 {track_transpose:+d} = 最终 {effective:+d} 半音": (
        "전역 {global_transpose:+d} + 트랙 {track_transpose:+d} = 최종 {effective:+d} 반음"
    ),
    "{track} · 轨道八度 {track_transpose:+d} · 最终移调 {effective:+d} 半音": (
        "{track} · 트랙 옥타브 {track_transpose:+d} · 최종 조옮김 {effective:+d} 반음"
    ),
})


EN.update({
    "工程源文件路径无效（{path}）：{error}": (
        "The project source path is invalid ({path}): {error}"
    ),
    "工程轨道数据无效（{path}）：{error}": (
        "The project track data is invalid ({path}): {error}"
    ),
    "无法读取工程文件（{path}）：{error}": (
        "Unable to read the project file ({path}): {error}"
    ),
})

JA.update({
    "工程源文件路径无效（{path}）：{error}": (
        "プロジェクトのソースパスが無効です（{path}）：{error}"
    ),
    "工程轨道数据无效（{path}）：{error}": (
        "プロジェクトのトラックデータが無効です（{path}）：{error}"
    ),
    "无法读取工程文件（{path}）：{error}": (
        "プロジェクトファイルを読み取れません（{path}）：{error}"
    ),
})

KO.update({
    "工程源文件路径无效（{path}）：{error}": (
        "프로젝트 소스 경로가 잘못됨({path}): {error}"
    ),
    "工程轨道数据无效（{path}）：{error}": (
        "프로젝트 트랙 데이터가 잘못됨({path}): {error}"
    ),
    "无法读取工程文件（{path}）：{error}": (
        "프로젝트 파일을 읽을 수 없음({path}): {error}"
    ),
})

EN.update({
    "导出保存目录": "Export folder",
    "乐器图像": "Instrument images",
    "音符编辑器快捷键提示": "Note editor shortcut hints",
    "快捷键": "Shortcuts",
    "选择模式": "Select",
    "已选音符": "Selected",
    "绘制模式": "Draw",
    "双击": "Double-click",
    "B": "B",
    "Ctrl+拖动": "Ctrl-drag",
    "Space": "Space",
    "方向键": "Arrow keys",
    "Shift+←/→": "Shift+←/→",
    "Ctrl+↑/↓": "Ctrl+↑/↓",
    "Del": "Del",
    "拖动": "Drag",
    "Alt": "Alt",
    "B / Esc": "B / Esc",
    "新建音符": "Add note",
    "切换绘制模式": "Toggle draw",
    "复制音符": "Copy notes",
    "播放或暂停": "Play / pause",
    "移动音符": "Move notes",
    "调整时值": "Resize notes",
    "调整力度": "Adjust velocity",
    "删除音符": "Delete notes",
    "设置长度和力度": "Set length and velocity",
    "临时取消吸附": "Bypass snap",
    "退出绘制模式": "Exit draw mode",
})

JA.update({
    "导出保存目录": "書き出し先",
    "乐器图像": "楽器画像",
    "音符编辑器快捷键提示": "ノートエディターのショートカット",
    "快捷键": "ショートカット",
    "选择模式": "選択モード",
    "已选音符": "選択中のノート",
    "绘制模式": "描画モード",
    "双击": "ダブルクリック",
    "B": "B",
    "Ctrl+拖动": "Ctrl+ドラッグ",
    "Space": "Space",
    "方向键": "方向キー",
    "Shift+←/→": "Shift+←/→",
    "Ctrl+↑/↓": "Ctrl+↑/↓",
    "Del": "Del",
    "拖动": "ドラッグ",
    "Alt": "Alt",
    "B / Esc": "B / Esc",
    "新建音符": "ノート追加",
    "切换绘制模式": "描画切替",
    "复制音符": "ノート複製",
    "播放或暂停": "再生 / 一時停止",
    "移动音符": "ノート移動",
    "调整时值": "長さ調整",
    "调整力度": "ベロシティ調整",
    "删除音符": "ノート削除",
    "设置长度和力度": "長さ / ベロシティ設定",
    "临时取消吸附": "スナップ解除",
    "退出绘制模式": "描画モード終了",
})

KO.update({
    "导出保存目录": "내보내기 폴더",
    "乐器图像": "악기 이미지",
    "音符编辑器快捷键提示": "음표 편집기 단축키 안내",
    "快捷键": "단축키",
    "选择模式": "선택 모드",
    "已选音符": "선택한 음표",
    "绘制模式": "그리기 모드",
    "双击": "더블클릭",
    "B": "B",
    "Ctrl+拖动": "Ctrl+드래그",
    "Space": "Space",
    "方向键": "방향키",
    "Shift+←/→": "Shift+←/→",
    "Ctrl+↑/↓": "Ctrl+↑/↓",
    "Del": "Del",
    "拖动": "드래그",
    "Alt": "Alt",
    "B / Esc": "B / Esc",
    "新建音符": "음표 추가",
    "切换绘制模式": "그리기 전환",
    "复制音符": "음표 복제",
    "播放或暂停": "재생 / 일시정지",
    "移动音符": "음표 이동",
    "调整时值": "길이 조절",
    "调整力度": "벨로시티 조절",
    "删除音符": "음표 삭제",
    "设置长度和力度": "길이 / 벨로시티 설정",
    "临时取消吸附": "스냅 해제",
    "退出绘制模式": "그리기 모드 종료",
})

EN.update({
    "打开完整快捷键": "All shortcuts",
    "无法识别有效的 WAV/MP3 音频头；文件可能已损坏，或实际是 M4A/AAC/网页文件。请重新导出为 WAV 或标准 MP3。": (
        "No valid WAV/MP3 header was found. The file may be damaged or may actually be an M4A, AAC, or web page. Export it again as WAV or standard MP3."
    ),
    "参考音频的扩展名与实际格式不一致；请用音频软件重新导出为 WAV 或标准 MP3。": (
        "The reference-audio extension does not match its real format. Export it again as WAV or standard MP3."
    ),
    "当前仅支持 WAV 和标准 MP3 参考音频；请先转换后再载入。": (
        "Only WAV and standard MP3 reference audio are currently supported. Convert the file before loading it."
    ),
    "参考音频文件不存在或无法读取。": (
        "The reference-audio file is missing or cannot be read."
    ),
    "音块高度：{height}px": "Note height: {height}px",
    "基础操作": "Essentials",
    "全局": "Global",
    "选择全部音符": "Select all notes",
    "画布模式与选择": "Canvas modes and selection",
    "退出绘制或清除候选选择": "Exit draw mode or clear candidate selection",
    "按网格移动时间": "Move in time by the grid",
    "音块移动与缩放": "Note movement and resizing",
    "精细移动时间（网格的 1/8）": "Fine time move (1/8 of the grid)",
    "调整音符时值": "Adjust note duration",
    "精细调整音符时值": "Fine-adjust note duration",
    "移动一个半音": "Move by one semitone",
    "移动一个八度": "Move by one octave",
    "力度增减 1": "Change velocity by 1",
    "力度增减 8": "Change velocity by 8",
    "向后复制所选音符": "Duplicate selected notes forward",
    "剪贴板与历史": "Clipboard and history",
    "复制所选音符": "Copy selected notes",
    "剪切所选音符": "Cut selected notes",
    "在编辑光标处粘贴；同音高重叠时移至最近空位": (
        "Paste at the edit cursor; move to the nearest free position on overlap"
    ),
    "撤销音符编辑": "Undo note edit",
    "重做音符编辑": "Redo note edit",
    "删除所选音符（可撤销）": "Delete selected notes (undoable)",
    "双击空白": "Double-click empty space",
    "拖动空白": "Drag empty space",
    "框选音符": "Marquee-select notes",
    "Ctrl+点击 / 框选": "Ctrl+click / marquee",
    "切换或追加选择": "Toggle or add to selection",
    "Shift+点击": "Shift+click",
    "连续选择音符": "Select a contiguous note range",
    "拖动音块": "Drag a note block",
    "鼠标与视图": "Mouse and view",
    "拖动音块边缘": "Drag a note edge",
    "复制并移动音符": "Clone and move notes",
    "Alt+拖动": "Alt+drag",
    "右键音块": "Right-click a note block",
    "立即删除音符（可撤销）": "Delete the note immediately (undoable)",
    "滚轮": "Wheel",
    "纵向浏览音高": "Scroll pitches vertically",
    "Shift+滚轮": "Shift+wheel",
    "横向滚动时间": "Scroll time horizontally",
    "Ctrl+滚轮": "Ctrl+wheel",
    "缩放时间": "Zoom time",
    "Alt+滚轮": "Alt+wheel",
    "调整音块高度": "Adjust note-block height",
    "触控板双指滑动": "Two-finger touchpad scroll",
    "平移时间与音高": "Pan time and pitch",
    "时间 · 音高": "Time · Pitch",
    "Shift+方向键": "Shift+arrow keys",
    "时值 · 八度": "Duration · Octave",
    "力度 · 复制": "Velocity · Duplicate",
    "Del / 右键": "Del / right-click",
    "删除（可撤销）": "Delete (undoable)",
    "点击画布启用": "Click the canvas to enable",
    "音符编辑器快捷键": "Note editor shortcuts",
    "音块快捷键仅在钢琴卷帘画布获得焦点时生效；输入框保留文本编辑快捷键。F1 可随时打开本面板。": (
        "Note-block shortcuts work only while the piano-roll canvas has focus; text fields keep their editing shortcuts. Press F1 anytime to open this panel."
    ),
    "全窗口生效": "Works across the window",
    "查看完整快捷键（F1）": "View all shortcuts (F1)",
    "查看完整快捷键": "View all shortcuts",
})

JA.update({
    "打开完整快捷键": "ショートカット一覧を開く",
    "无法识别有效的 WAV/MP3 音频头；文件可能已损坏，或实际是 M4A/AAC/网页文件。请重新导出为 WAV 或标准 MP3。": (
        "有効な WAV/MP3 ヘッダーが見つかりません。ファイルが破損しているか、実際には M4A、AAC、または Web ページの可能性があります。WAV または標準 MP3 として再書き出ししてください。"
    ),
    "参考音频的扩展名与实际格式不一致；请用音频软件重新导出为 WAV 或标准 MP3。": (
        "参照オーディオの拡張子と実際の形式が一致しません。WAV または標準 MP3 として再書き出ししてください。"
    ),
    "当前仅支持 WAV 和标准 MP3 参考音频；请先转换后再载入。": (
        "現在対応している参照オーディオは WAV と標準 MP3 のみです。変換してから読み込んでください。"
    ),
    "参考音频文件不存在或无法读取。": (
        "参照オーディオファイルが存在しないか、読み取れません。"
    ),
    "音块高度：{height}px": "ノートの高さ: {height}px",
    "基础操作": "基本操作",
    "选择全部音符": "すべてのノートを選択",
    "画布模式与选择": "キャンバスのモードと選択",
    "退出绘制或清除候选选择": "描画を終了、または候補選択を解除",
    "按网格移动时间": "グリッド単位で時間移動",
    "音块移动与缩放": "ノートの移動と長さ調整",
    "精细移动时间（网格的 1/8）": "時間を微調整（グリッドの1/8）",
    "调整音符时值": "ノート長を調整",
    "精细调整音符时值": "ノート長を微調整",
    "移动一个半音": "半音移動",
    "移动一个八度": "1オクターブ移動",
    "力度增减 1": "ベロシティを1変更",
    "力度增减 8": "ベロシティを8変更",
    "向后复制所选音符": "選択ノートを後方へ複製",
    "剪贴板与历史": "クリップボードと履歴",
    "复制所选音符": "選択ノートをコピー",
    "剪切所选音符": "選択ノートを切り取り",
    "在编辑光标处粘贴；同音高重叠时移至最近空位": (
        "編集カーソルに貼り付け、同音高の重複時は最寄りの空き位置へ移動"
    ),
    "撤销音符编辑": "ノート編集を元に戻す",
    "重做音符编辑": "ノート編集をやり直す",
    "删除所选音符（可撤销）": "選択ノートを削除（元に戻せます）",
    "双击空白": "空白をダブルクリック",
    "拖动空白": "空白をドラッグ",
    "框选音符": "範囲でノートを選択",
    "Ctrl+点击 / 框选": "Ctrl+クリック / 範囲選択",
    "切换或追加选择": "選択を切替または追加",
    "Shift+点击": "Shift+クリック",
    "连续选择音符": "連続範囲を選択",
    "拖动音块": "ノートをドラッグ",
    "鼠标与视图": "マウスと表示",
    "拖动音块边缘": "ノート端をドラッグ",
    "复制并移动音符": "複製して移動",
    "Alt+拖动": "Alt+ドラッグ",
    "右键音块": "ノートを右クリック",
    "立即删除音符（可撤销）": "ノートをすぐ削除（元に戻せます）",
    "滚轮": "ホイール",
    "纵向浏览音高": "音高を縦スクロール",
    "Shift+滚轮": "Shift+ホイール",
    "横向滚动时间": "時間を横スクロール",
    "Ctrl+滚轮": "Ctrl+ホイール",
    "缩放时间": "時間ズーム",
    "Alt+滚轮": "Alt+ホイール",
    "调整音块高度": "ノートの高さを調整",
    "触控板双指滑动": "タッチパッドを2本指でスクロール",
    "平移时间与音高": "時間と音高を移動",
    "时间 · 音高": "時間・音高",
    "Shift+方向键": "Shift+方向キー",
    "时值 · 八度": "長さ・オクターブ",
    "力度 · 复制": "ベロシティ・複製",
    "Del / 右键": "Del / 右クリック",
    "删除（可撤销）": "削除（元に戻せます）",
    "点击画布启用": "キャンバスをクリックして有効化",
    "音符编辑器快捷键": "ノートエディター・ショートカット一覧",
    "音块快捷键仅在钢琴卷帘画布获得焦点时生效；输入框保留文本编辑快捷键。F1 可随时打开本面板。": (
        "ノートのショートカットはピアノロールにフォーカスがある時だけ有効です。入力欄ではテキスト編集キーが優先されます。F1 でいつでもこのパネルを開けます。"
    ),
    "全窗口生效": "ウィンドウ全体で有効",
    "查看完整快捷键（F1）": "ショートカット一覧（F1）",
    "查看完整快捷键": "ショートカット一覧",
})

KO.update({
    "打开完整快捷键": "전체 단축키 열기",
    "无法识别有效的 WAV/MP3 音频头；文件可能已损坏，或实际是 M4A/AAC/网页文件。请重新导出为 WAV 或标准 MP3。": (
        "유효한 WAV/MP3 헤더를 찾을 수 없습니다. 파일이 손상되었거나 실제로는 M4A, AAC 또는 웹 페이지일 수 있습니다. WAV 또는 표준 MP3로 다시 내보내세요."
    ),
    "参考音频的扩展名与实际格式不一致；请用音频软件重新导出为 WAV 或标准 MP3。": (
        "참조 오디오의 확장자와 실제 형식이 일치하지 않습니다. WAV 또는 표준 MP3로 다시 내보내세요."
    ),
    "当前仅支持 WAV 和标准 MP3 参考音频；请先转换后再载入。": (
        "현재 WAV와 표준 MP3 참조 오디오만 지원합니다. 변환한 후 다시 불러오세요."
    ),
    "参考音频文件不存在或无法读取。": (
        "참조 오디오 파일이 없거나 읽을 수 없습니다."
    ),
    "音块高度：{height}px": "음표 높이: {height}px",
    "基础操作": "기본 작업",
    "选择全部音符": "모든 음표 선택",
    "画布模式与选择": "캔버스 모드 및 선택",
    "退出绘制或清除候选选择": "그리기 종료 또는 후보 선택 해제",
    "按网格移动时间": "그리드 단위로 시간 이동",
    "音块移动与缩放": "음표 이동 및 길이 조정",
    "精细移动时间（网格的 1/8）": "시간 미세 이동(그리드의 1/8)",
    "调整音符时值": "음표 길이 조정",
    "精细调整音符时值": "음표 길이 미세 조정",
    "移动一个半音": "반음 이동",
    "移动一个八度": "한 옥타브 이동",
    "力度增减 1": "벨로시티 1 증감",
    "力度增减 8": "벨로시티 8 증감",
    "向后复制所选音符": "선택 음표를 뒤로 복제",
    "剪贴板与历史": "클립보드 및 기록",
    "复制所选音符": "선택 음표 복사",
    "剪切所选音符": "선택 음표 잘라내기",
    "在编辑光标处粘贴；同音高重叠时移至最近空位": (
        "편집 커서에 붙여넣고 같은 음높이가 겹치면 가장 가까운 빈 위치로 이동"
    ),
    "撤销音符编辑": "음표 편집 실행 취소",
    "重做音符编辑": "음표 편집 다시 실행",
    "删除所选音符（可撤销）": "선택 음표 삭제(실행 취소 가능)",
    "双击空白": "빈 공간 두 번 클릭",
    "拖动空白": "빈 공간 드래그",
    "框选音符": "영역으로 음표 선택",
    "Ctrl+点击 / 框选": "Ctrl+클릭 / 영역 선택",
    "切换或追加选择": "선택 전환 또는 추가",
    "Shift+点击": "Shift+클릭",
    "连续选择音符": "연속 범위 선택",
    "拖动音块": "음표 블록 드래그",
    "鼠标与视图": "마우스 및 보기",
    "拖动音块边缘": "음표 가장자리 드래그",
    "复制并移动音符": "복제 후 이동",
    "Alt+拖动": "Alt+드래그",
    "右键音块": "음표 블록 오른쪽 클릭",
    "立即删除音符（可撤销）": "음표 즉시 삭제(실행 취소 가능)",
    "滚轮": "휠",
    "纵向浏览音高": "음높이 세로 스크롤",
    "Shift+滚轮": "Shift+휠",
    "横向滚动时间": "시간 가로 스크롤",
    "Ctrl+滚轮": "Ctrl+휠",
    "缩放时间": "시간 확대/축소",
    "Alt+滚轮": "Alt+휠",
    "调整音块高度": "음표 블록 높이 조정",
    "触控板双指滑动": "터치패드 두 손가락 스크롤",
    "平移时间与音高": "시간과 음높이 이동",
    "时间 · 音高": "시간 · 음높이",
    "Shift+方向键": "Shift+방향키",
    "时值 · 八度": "길이 · 옥타브",
    "力度 · 复制": "벨로시티 · 복제",
    "Del / 右键": "Del / 오른쪽 클릭",
    "删除（可撤销）": "삭제(실행 취소 가능)",
    "点击画布启用": "캔버스를 클릭해 활성화",
    "音符编辑器快捷键": "음표 편집기 단축키 목록",
    "音块快捷键仅在钢琴卷帘画布获得焦点时生效；输入框保留文本编辑快捷键。F1 可随时打开本面板。": (
        "음표 단축키는 피아노 롤 캔버스에 포커스가 있을 때만 작동합니다. 입력란에서는 텍스트 편집 단축키가 유지됩니다. F1을 누르면 언제든지 이 패널을 열 수 있습니다."
    ),
    "全窗口生效": "창 전체에서 작동",
    "查看完整快捷键（F1）": "전체 단축키 보기(F1)",
    "查看完整快捷键": "전체 단축키 보기",
})

# Transcription candidate layers are provisional analysis results, distinct
# from editable notes and the optional other-track reference layer.
EN.update({
    "低置信": "Low confidence",
    "识别候选音块": "Recognized candidate notes",
    "点击开关识别音块；箭头可调整全部候选透明度和低置信弱化": (
        "Toggle recognized notes; use the arrow to adjust overall opacity and low-confidence attenuation"
    ),
    "候选音块透明度": "Candidate-note opacity",
    "调整全部识别候选音块的透明度": (
        "Adjust the opacity of all recognized candidate notes"
    ),
    "全部候选": "All candidates",
    "分析辅助": "Analysis guides",
    "音频校准": "Audio alignment",
    "候选音块": "Candidate notes",
    "分析结果 · 尚未写入轨道": "Analysis result · not yet written to the track",
    "识别参数": "Recognition",
    "场景": "Source",
    "灵敏度": "Sensitivity",
    "碎音整理": "Fragment cleanup",
    "参考层": "Guide layers",
    "识别音块 · {opacity}%": "Recognized notes · {opacity}%",
    "参考层 · {opacity}%": "Guide layers · {opacity}%",
})
JA.update({
    "低置信": "低信頼",
    "识别候选音块": "認識候補ノート",
    "点击开关识别音块；箭头可调整全部候选透明度和低置信弱化": (
        "クリックで認識ノートを切り替え、矢印で全体の透明度と低信頼候補の弱表示を調整します"
    ),
    "候选音块透明度": "候補ノートの透明度",
    "调整全部识别候选音块的透明度": "すべての認識候補ノートの透明度を調整します",
    "全部候选": "全候補",
    "分析辅助": "解析ガイド",
    "音频校准": "音声位置合わせ",
    "候选音块": "候補ノート",
    "分析结果 · 尚未写入轨道": "解析結果 · トラックへ未反映",
    "识别参数": "認識設定",
    "场景": "音源",
    "灵敏度": "感度",
    "碎音整理": "断片整理",
    "参考层": "ガイドレイヤー",
    "识别音块 · {opacity}%": "認識ノート · {opacity}%",
    "参考层 · {opacity}%": "ガイド · {opacity}%",
})
KO.update({
    "低置信": "낮은 신뢰도",
    "识别候选音块": "인식 후보 음표",
    "点击开关识别音块；箭头可调整全部候选透明度和低置信弱化": (
        "클릭해 인식 음표를 전환하고 화살표에서 전체 투명도와 낮은 신뢰도 약화를 조절합니다"
    ),
    "候选音块透明度": "후보 음표 투명도",
    "调整全部识别候选音块的透明度": "모든 인식 후보 음표의 투명도를 조절합니다",
    "全部候选": "모든 후보",
    "分析辅助": "분석 가이드",
    "音频校准": "오디오 정렬",
    "候选音块": "후보 음표",
    "分析结果 · 尚未写入轨道": "분석 결과 · 트랙에 아직 기록되지 않음",
    "识别参数": "인식 설정",
    "场景": "소스",
    "灵敏度": "민감도",
    "碎音整理": "파편 정리",
    "参考层": "가이드 레이어",
    "识别音块 · {opacity}%": "인식 음표 · {opacity}%",
    "参考层 · {opacity}%": "가이드 · {opacity}%",
})


# Simplified Chinese remains the exact source language.  Build the complete
# Traditional Chinese catalog only after every maintained source key (including
# the General MIDI names) has been registered, so all regional catalogs keep an
# identical coverage contract without a runtime conversion dependency.
def _build_traditional_catalog() -> dict[str, str]:
    catalog = {
        source: simplified_to_traditional_ui(source)
        for source in EN
    }
    equivalent_sources: dict[tuple[str, str, str], list[str]] = {}
    for source in EN:
        vector = (EN[source], JA[source], KO[source])
        equivalent_sources.setdefault(vector, []).append(source)
    for sources in equivalent_sources.values():
        if len(sources) < 2:
            continue
        preferred = min(
            sources,
            key=lambda source: (len(catalog[source]), catalog[source], source),
        )
        translated = catalog[preferred]
        for source in sources:
            catalog[source] = translated
    return catalog


ZH_TW = _build_traditional_catalog()
TRANSLATIONS["zh_TW"] = ZH_TW


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


EN.update({
    "节奏诊断": "Rhythm Diagnostic",
    "显式使用当前项目 BPM 与第一拍分析候选；只生成诊断建议，不修改音符": (
        "Explicitly analyze candidates with the current project BPM and first "
        "beat; creates diagnostic suggestions only and never changes notes"
    ),
    "节奏诊断中…": "Diagnosing Rhythm…",
    "节奏建议 {count}": "Rhythm Suggestions {count}",
    "请等待当前扒谱分析完成。": "Wait for the current transcription analysis to finish.",
    "请先生成扒谱候选，再运行节奏诊断。": (
        "Generate transcription candidates before running rhythm diagnostics."
    ),
    "节奏诊断未启动；没有修改任何音符。": (
        "Rhythm diagnostics did not start; no notes were changed."
    ),
    "正在读取缓存证据进行节奏诊断；不会运行模型。": (
        "Reading cached evidence for rhythm diagnostics; the model will not run."
    ),
    "节奏诊断完成 · 建议 {count} · 合并 {merged} · 弱音复核 {suppressed}；未修改候选或正式音符。": (
        "Rhythm diagnostic complete · Suggestions {count} · Merges {merged} · "
        "Weak-note reviews {suppressed}; candidates and formal notes are unchanged."
    ),
    "节奏诊断失败：{error}；没有修改任何音符。": (
        "Rhythm diagnostic failed: {error}; no notes were changed."
    ),
    "节奏诊断已取消；没有修改任何音符。": (
        "Rhythm diagnostic cancelled; no notes were changed."
    ),
})

JA.update({
    "节奏诊断": "リズム診断",
    "显式使用当前项目 BPM 与第一拍分析候选；只生成诊断建议，不修改音符": (
        "現在のプロジェクトBPMと第1拍を明示的に使用して候補を解析します。"
        "診断候補のみを生成し、音符は変更しません"
    ),
    "节奏诊断中…": "リズム診断中…",
    "节奏建议 {count}": "リズム候補 {count}",
    "请等待当前扒谱分析完成。": "現在の採譜解析が完了するまでお待ちください。",
    "请先生成扒谱候选，再运行节奏诊断。": (
        "採譜候補を生成してからリズム診断を実行してください。"
    ),
    "节奏诊断未启动；没有修改任何音符。": (
        "リズム診断は開始されませんでした。音符は変更されていません。"
    ),
    "正在读取缓存证据进行节奏诊断；不会运行模型。": (
        "キャッシュ済み証拠を読み込んでリズム診断しています。モデルは実行しません。"
    ),
    "节奏诊断完成 · 建议 {count} · 合并 {merged} · 弱音复核 {suppressed}；未修改候选或正式音符。": (
        "リズム診断完了・候補 {count}・結合 {merged}・弱音確認 {suppressed}。"
        "候補音符と正式音符は変更されていません。"
    ),
    "节奏诊断失败：{error}；没有修改任何音符。": (
        "リズム診断に失敗しました：{error}。音符は変更されていません。"
    ),
    "节奏诊断已取消；没有修改任何音符。": (
        "リズム診断をキャンセルしました。音符は変更されていません。"
    ),
})

KO.update({
    "节奏诊断": "리듬 진단",
    "显式使用当前项目 BPM 与第一拍分析候选；只生成诊断建议，不修改音符": (
        "현재 프로젝트 BPM과 첫 박을 명시적으로 사용해 후보를 분석합니다. "
        "진단 제안만 만들고 음표는 변경하지 않습니다"
    ),
    "节奏诊断中…": "리듬 진단 중…",
    "节奏建议 {count}": "리듬 제안 {count}",
    "请等待当前扒谱分析完成。": "현재 채보 분석이 끝날 때까지 기다려 주세요.",
    "请先生成扒谱候选，再运行节奏诊断。": (
        "채보 후보를 생성한 뒤 리듬 진단을 실행하세요."
    ),
    "节奏诊断未启动；没有修改任何音符。": (
        "리듬 진단이 시작되지 않았으며 음표는 변경되지 않았습니다."
    ),
    "正在读取缓存证据进行节奏诊断；不会运行模型。": (
        "캐시된 증거를 읽어 리듬을 진단합니다. 모델은 실행하지 않습니다."
    ),
    "节奏诊断完成 · 建议 {count} · 合并 {merged} · 弱音复核 {suppressed}；未修改候选或正式音符。": (
        "리듬 진단 완료 · 제안 {count} · 병합 {merged} · 약한 음 검토 "
        "{suppressed}; 후보와 정식 음표는 변경되지 않았습니다."
    ),
    "节奏诊断失败：{error}；没有修改任何音符。": (
        "리듬 진단 실패: {error}; 음표는 변경되지 않았습니다."
    ),
    "节奏诊断已取消；没有修改任何音符。": (
        "리듬 진단이 취소되었으며 음표는 변경되지 않았습니다."
    ),
})

# The practical transcription workflow presents evidence as a guide, then
# hands an editable draft to the game-fit check and ordinary editor.
EN.update({
    "参考音块 · {opacity}%": "Reference notes · {opacity}%",
    "参考识别音块": "Reference transcription notes",
    "显示或隐藏参考音块；箭头可调整透明度": (
        "Show or hide reference notes; use the arrow to adjust opacity"
    ),
    "线框表示识别建议，底部短线表示置信度；箭头可调整透明度": (
        "Outlines are transcription suggestions; the lower rail shows confidence; use the arrow to adjust opacity"
    ),
    "音高轨迹": "Pitch guide",
    "显示 Basic Pitch 的逐帧音高证据；它是扒谱参考，不是正式音符": (
        "Show Basic Pitch frame-level pitch evidence; it is a transcription guide, not a formal note"
    ),
    "显示蓝色音高细线；不确定或跨度过大的位置会自动断开": (
        "Show thin blue pitch lines; uncertain or excessively large jumps are left disconnected"
    ),
    "去噪：低": "Denoise: Low",
    "去噪：标准": "Denoise: Standard",
    "去噪：高": "Denoise: High",
    "音高轨迹去噪等级": "Pitch-guide denoise level",
    "只清理音高轨迹显示，不修改识别结果、草稿或导出": (
        "Clean only the pitch-guide display; recognition, draft notes, and exports are unchanged"
    ),
    "声部提示": "Voice hints",
    "分析后显示短距离声部提示": "Show short-range voice hints after analysis",
    "默认只提示主旋律；仅连接相邻且可信的短距离音符": (
        "Hint only the main melody by default; connect only adjacent, credible, short-range notes"
    ),
    "仅看轨迹": "Guide only",
    "仅看音高轨迹": "Show only the pitch guide",
    "临时隐藏参考音块和旋律连线，只查看音高轨迹": (
        "Temporarily hide reference notes and melody connectors to view only the pitch guide"
    ),
    "采纳为草稿": "Add to Draft",
    "将所选参考音块采纳为可编辑草稿": (
        "Add the selected reference notes to the editable draft"
    ),
    "将所选参考音块采纳为可编辑草稿；可以撤销": (
        "Add the selected reference notes to the editable draft; this can be undone"
    ),
    "检查游戏适配": "Check Game Fit",
    "只检查音域、奏法、时间和力度，不自动修改草稿": (
        "Check pitch range, articulation, timing, and velocity without changing the draft"
    ),
    "收起扒谱参考层，保留草稿并回到普通音符编辑": (
        "Hide transcription guides, keep the draft, and return to normal note editing"
    ),
    "识别到 {count} 个参考音块 · 框选后采纳为草稿": (
        "Found {count} reference notes · select notes and add them to the draft"
    ),
    "游戏适配检查": "Game Fit Check",
    "当前草稿没有音符。请先采纳参考音块或手动创建音符。": (
        "The draft has no notes. Add reference notes or create notes manually first."
    ),
    "已使用游戏音域证据": "Verified game pitch-range evidence used",
    "缺少已验证乐器音域，仅检查全局音高范围": (
        "No verified instrument range; only the global pitch range was checked"
    ),
    "游戏适配检查通过": "Game Fit Check Passed",
    "游戏适配基础检查完成": "Basic Game Fit Check Complete",
    "游戏适配发现需要处理的问题": "Game Fit Issues Found",
    "扒谱参考已收起；草稿保持可编辑，点击“完成”后写回项目。": (
        "Transcription guides are hidden. The draft remains editable and will be written back when you click Finish."
    ),
    "乐器：{instrument}\n草稿：{notes} 个音符\n发布分段：{chunks} 段（每段最多 {limit}，导出时自动拆分）\n音域问题：{pitch}\n奏法问题：{articulation}\n时间问题：{timing}\n力度问题：{velocity}\n证据：{evidence}\n\n此检查不会移动、删除、量化或改写任何音符。": (
        "Instrument: {instrument}\nDraft: {notes} notes\nPublication chunks: {chunks} (up to {limit} each; split automatically on export)\nPitch issues: {pitch}\nArticulation issues: {articulation}\nTiming issues: {timing}\nVelocity issues: {velocity}\nEvidence: {evidence}\n\nThis check does not move, delete, quantize, or rewrite any notes."
    ),
})
JA.update({
    "参考音块 · {opacity}%": "参照ノート · {opacity}%",
    "参考识别音块": "採譜参照ノート",
    "显示或隐藏参考音块；箭头可调整透明度": "参照ノートの表示を切り替え、矢印で透明度を調整します",
    "线框表示识别建议，底部短线表示置信度；箭头可调整透明度": "枠線は採譜候補、下の短い線は信頼度を示します。矢印で透明度を調整できます",
    "音高轨迹": "ピッチガイド",
    "显示 Basic Pitch 的逐帧音高证据；它是扒谱参考，不是正式音符": "Basic Pitch のフレーム単位の音高証拠を表示します。正式ノートではなく採譜ガイドです",
    "显示蓝色音高细线；不确定或跨度过大的位置会自动断开": "青い細い音高線を表示します。不確かな箇所や大きすぎる跳躍は自動的に切れます",
    "去噪：低": "ノイズ除去：低",
    "去噪：标准": "ノイズ除去：標準",
    "去噪：高": "ノイズ除去：高",
    "音高轨迹去噪等级": "ピッチガイドのノイズ除去レベル",
    "只清理音高轨迹显示，不修改识别结果、草稿或导出": "ピッチガイドの表示だけを整理し、認識結果、下書き、書き出しは変更しません",
    "声部提示": "声部ヒント",
    "分析后显示短距离声部提示": "解析後に短距離の声部ヒントを表示",
    "默认只提示主旋律；仅连接相邻且可信的短距离音符": "既定では主旋律のみを示し、隣接する信頼できる短距離ノートだけを接続します",
    "仅看轨迹": "ガイドのみ",
    "仅看音高轨迹": "ピッチガイドのみ表示",
    "临时隐藏参考音块和旋律连线，只查看音高轨迹": "参照ノートとメロディ接続線を一時的に隠し、ピッチガイドだけを表示します",
    "采纳为草稿": "下書きに追加",
    "将所选参考音块采纳为可编辑草稿": "選択した参照ノートを編集可能な下書きに追加",
    "将所选参考音块采纳为可编辑草稿；可以撤销": "選択した参照ノートを編集可能な下書きに追加します。元に戻せます",
    "检查游戏适配": "ゲーム適合を確認",
    "只检查音域、奏法、时间和力度，不自动修改草稿": "音域、奏法、タイミング、ベロシティだけを確認し、下書きは変更しません",
    "收起扒谱参考层，保留草稿并回到普通音符编辑": "採譜ガイドを閉じ、下書きを保ったまま通常編集へ戻ります",
    "识别到 {count} 个参考音块 · 框选后采纳为草稿": "参照ノート {count} 個 · 選択して下書きに追加",
    "游戏适配检查": "ゲーム適合チェック",
    "当前草稿没有音符。请先采纳参考音块或手动创建音符。": "下書きにノートがありません。参照ノートを追加するか手動で作成してください。",
    "已使用游戏音域证据": "検証済みゲーム音域証拠を使用",
    "缺少已验证乐器音域，仅检查全局音高范围": "検証済み楽器音域がないため、全体音域のみ確認",
    "游戏适配检查通过": "ゲーム適合チェック合格",
    "游戏适配基础检查完成": "ゲーム適合の基本チェック完了",
    "游戏适配发现需要处理的问题": "ゲーム適合の要修正項目",
    "扒谱参考已收起；草稿保持可编辑，点击“完成”后写回项目。": "採譜ガイドを閉じました。下書きは編集可能で、「完了」を押すとプロジェクトへ反映されます。",
    "乐器：{instrument}\n草稿：{notes} 个音符\n发布分段：{chunks} 段（每段最多 {limit}，导出时自动拆分）\n音域问题：{pitch}\n奏法问题：{articulation}\n时间问题：{timing}\n力度问题：{velocity}\n证据：{evidence}\n\n此检查不会移动、删除、量化或改写任何音符。": "楽器：{instrument}\n下書き：{notes} ノート\n公開チャンク：{chunks}（各 {limit} まで、書き出し時に自動分割）\n音域の問題：{pitch}\n奏法の問題：{articulation}\nタイミングの問題：{timing}\nベロシティの問題：{velocity}\n証拠：{evidence}\n\nこのチェックはノートの移動、削除、クオンタイズ、書き換えを行いません。",
})
KO.update({
    "参考音块 · {opacity}%": "참조 음표 · {opacity}%",
    "参考识别音块": "채보 참조 음표",
    "显示或隐藏参考音块；箭头可调整透明度": "참조 음표 표시를 전환하고 화살표에서 투명도를 조절합니다",
    "线框表示识别建议，底部短线表示置信度；箭头可调整透明度": "윤곽선은 채보 제안, 아래 짧은 선은 신뢰도를 나타냅니다. 화살표에서 투명도를 조절합니다",
    "音高轨迹": "음높이 가이드",
    "显示 Basic Pitch 的逐帧音高证据；它是扒谱参考，不是正式音符": "Basic Pitch의 프레임별 음높이 증거를 표시합니다. 정식 음표가 아닌 채보 가이드입니다",
    "显示蓝色音高细线；不确定或跨度过大的位置会自动断开": "파란색의 가는 음높이 선을 표시합니다. 불확실하거나 지나치게 큰 도약은 자동으로 끊어 표시합니다",
    "去噪：低": "노이즈 제거: 낮음",
    "去噪：标准": "노이즈 제거: 표준",
    "去噪：高": "노이즈 제거: 높음",
    "音高轨迹去噪等级": "음높이 가이드 노이즈 제거 수준",
    "只清理音高轨迹显示，不修改识别结果、草稿或导出": "음높이 가이드 표시만 정리하며 인식 결과, 초안, 내보내기는 변경하지 않습니다",
    "声部提示": "성부 힌트",
    "分析后显示短距离声部提示": "분석 후 짧은 거리의 성부 힌트 표시",
    "默认只提示主旋律；仅连接相邻且可信的短距离音符": "기본적으로 주선율만 표시하고 인접한 신뢰 가능한 짧은 거리 음표만 연결합니다",
    "仅看轨迹": "가이드만",
    "仅看音高轨迹": "음높이 가이드만 표시",
    "临时隐藏参考音块和旋律连线，只查看音高轨迹": "참조 음표와 멜로디 연결선을 잠시 숨기고 음높이 가이드만 봅니다",
    "采纳为草稿": "초안에 추가",
    "将所选参考音块采纳为可编辑草稿": "선택한 참조 음표를 편집 가능한 초안에 추가",
    "将所选参考音块采纳为可编辑草稿；可以撤销": "선택한 참조 음표를 편집 가능한 초안에 추가합니다. 실행 취소할 수 있습니다",
    "检查游戏适配": "게임 적합성 확인",
    "只检查音域、奏法、时间和力度，不自动修改草稿": "음역, 주법, 타이밍, 벨로시티만 확인하며 초안을 변경하지 않습니다",
    "收起扒谱参考层，保留草稿并回到普通音符编辑": "채보 가이드를 숨기고 초안을 유지한 채 일반 음표 편집으로 돌아갑니다",
    "识别到 {count} 个参考音块 · 框选后采纳为草稿": "참조 음표 {count}개 · 선택 후 초안에 추가",
    "游戏适配检查": "게임 적합성 검사",
    "当前草稿没有音符。请先采纳参考音块或手动创建音符。": "초안에 음표가 없습니다. 참조 음표를 추가하거나 직접 음표를 만드세요.",
    "已使用游戏音域证据": "검증된 게임 음역 증거 사용",
    "缺少已验证乐器音域，仅检查全局音高范围": "검증된 악기 음역이 없어 전체 음높이 범위만 확인",
    "游戏适配检查通过": "게임 적합성 검사 통과",
    "游戏适配基础检查完成": "기본 게임 적합성 검사 완료",
    "游戏适配发现需要处理的问题": "게임 적합성 문제 발견",
    "扒谱参考已收起；草稿保持可编辑，点击“完成”后写回项目。": "채보 가이드를 숨겼습니다. 초안은 계속 편집할 수 있으며 '완료'를 누르면 프로젝트에 반영됩니다.",
    "乐器：{instrument}\n草稿：{notes} 个音符\n发布分段：{chunks} 段（每段最多 {limit}，导出时自动拆分）\n音域问题：{pitch}\n奏法问题：{articulation}\n时间问题：{timing}\n力度问题：{velocity}\n证据：{evidence}\n\n此检查不会移动、删除、量化或改写任何音符。": "악기: {instrument}\n초안: 음표 {notes}개\n게시 청크: {chunks}개(각 {limit}개까지, 내보낼 때 자동 분할)\n음역 문제: {pitch}\n주법 문제: {articulation}\n타이밍 문제: {timing}\n벨로시티 문제: {velocity}\n증거: {evidence}\n\n이 검사는 음표를 이동, 삭제, 퀀타이즈 또는 변경하지 않습니다.",
})

EN.update({
    "显示音符力度；可点调或用柔化刷影响周边音符": "Show note velocity; edit one point or use a soft brush on nearby notes",
    "拖动力度杆；柔化刷按时间距离衰减，滚轮可调整影响范围。": "Drag velocity stems; the soft brush falls off over time and the wheel changes its radius.",
    "音符力度": "Note velocity",
    "音符力度 0–127（非轨道音量）": "Note velocity 0–127 (not track volume)",
    "点调": "Point",
    "柔化刷": "Soft brush",
    "影响 ±{beats:g} 拍": "Radius ±{beats:g} beats",
    "范围：全轨": "Scope: track",
    "范围：所选": "Scope: selection",
    "游戏层 {value}": "Game layer {value}",
    "选择一个音符可查看游戏采样层": "Select one note to inspect game sample layers",
    "正在读取 Wwise 力度分层…": "Reading Wwise velocity layers…",
    "Wwise 映射暂不可用": "Wwise mapping is unavailable",
    "虚线为 Wwise 路由分层；不代表实测响度": "Dashed lines are Wwise route layers, not measured loudness",
    "当前音符没有独立的 Wwise 力度分层": "This note has no separate Wwise velocity layers",
})
JA.update({
    "显示音符力度；可点调或用柔化刷影响周边音符": "ノートベロシティを表示し、ポイント編集またはソフトブラシで周辺ノートを調整",
    "拖动力度杆；柔化刷按时间距离衰减，滚轮可调整影响范围。": "ベロシティの棒をドラッグします。ソフトブラシは時間距離で減衰し、ホイールで範囲を変更できます。",
    "音符力度": "ノートベロシティ",
    "音符力度 0–127（非轨道音量）": "ノートベロシティ 0–127（トラック音量ではありません）",
    "点调": "ポイント",
    "柔化刷": "ソフトブラシ",
    "影响 ±{beats:g} 拍": "範囲 ±{beats:g} 拍",
    "范围：全轨": "対象：トラック",
    "范围：所选": "対象：選択",
    "游戏层 {value}": "ゲーム層 {value}",
    "选择一个音符可查看游戏采样层": "ゲームのサンプル層を確認するノートを1つ選択",
    "正在读取 Wwise 力度分层…": "Wwiseベロシティ層を読み込み中…",
    "Wwise 映射暂不可用": "Wwiseマッピングを利用できません",
    "虚线为 Wwise 路由分层；不代表实测响度": "破線はWwiseルート層で、実測音量ではありません",
    "当前音符没有独立的 Wwise 力度分层": "このノートには独立したWwiseベロシティ層がありません",
})
KO.update({
    "显示音符力度；可点调或用柔化刷影响周边音符": "노트 벨로시티를 표시하고 포인트 또는 소프트 브러시로 주변 노트 조정",
    "拖动力度杆；柔化刷按时间距离衰减，滚轮可调整影响范围。": "벨로시티 막대를 드래그합니다. 소프트 브러시는 시간 거리에 따라 감쇠하며 휠로 범위를 바꿀 수 있습니다.",
    "音符力度": "노트 벨로시티",
    "音符力度 0–127（非轨道音量）": "노트 벨로시티 0–127(트랙 음량 아님)",
    "点调": "포인트",
    "柔化刷": "소프트 브러시",
    "影响 ±{beats:g} 拍": "범위 ±{beats:g}박",
    "范围：全轨": "범위: 트랙",
    "范围：所选": "범위: 선택",
    "游戏层 {value}": "게임 레이어 {value}",
    "选择一个音符可查看游戏采样层": "게임 샘플 레이어를 볼 노트 하나를 선택하세요",
    "正在读取 Wwise 力度分层…": "Wwise 벨로시티 레이어 읽는 중…",
    "Wwise 映射暂不可用": "Wwise 매핑을 사용할 수 없음",
    "虚线为 Wwise 路由分层；不代表实测响度": "점선은 Wwise 라우팅 레이어이며 실측 음량이 아닙니다",
    "当前音符没有独立的 Wwise 力度分层": "이 노트에는 별도의 Wwise 벨로시티 레이어가 없습니다",
})

_OWNER_IDENTITY_TRANSLATIONS = {
    "解除绑定": (
        "Unlink",
        "連携を解除",
        "연결 해제",
    ),
    "这会清除当前项目和本机配置中的 Owner ID；之后导出前需要重新读取游戏曲谱。": (
        "This clears the Owner ID from the current project and this computer's configuration. Read an in-game score again before exporting.",
        "現在のプロジェクトとこのPCの設定からOwner IDを消去します。書き出す前にゲーム内楽譜からもう一度読み取ってください。",
        "현재 프로젝트와 이 컴퓨터의 설정에서 Owner ID를 지웁니다. 내보내기 전에 게임 내 악보에서 다시 읽으세요.",
    ),
}

for _source, (_english, _japanese, _korean) in _OWNER_IDENTITY_TRANSLATIONS.items():
    EN[_source] = _english
    JA[_source] = _japanese
    KO[_source] = _korean

del _source, _english, _japanese, _korean

_TRACK_ORDER_TRANSLATIONS = {
    "上移轨道": ("Move Track Up", "トラックを上へ移動", "트랙 위로 이동"),
    "下移轨道": ("Move Track Down", "トラックを下へ移動", "트랙 아래로 이동"),
}

for _source, (_english, _japanese, _korean) in _TRACK_ORDER_TRANSLATIONS.items():
    EN[_source] = _english
    JA[_source] = _japanese
    KO[_source] = _korean

del _source, _english, _japanese, _korean

_WORKSPACE_TEMPO_TRANSLATIONS = {
    "全局 BPM": ("Global BPM", "グローバル BPM", "글로벌 BPM"),
    "自动跟随": ("Follow", "追従", "따라가기"),
    "全局 BPM（高级）": ("Global BPM (advanced)", "グローバル BPM（詳細）", "글로벌 BPM(고급)"),
    "所有轨道共用；同步时间网格、试听、分析、自动保存和 BDO 导出。导出兼容范围 1–200；游戏官方作曲指南当前标注上限 180。": (
        "Shared by every track; synchronizes the time grid, preview, analysis, autosave, and BDO export. Export compatibility is 1–200; the current official game composing guide lists 180 as the maximum.",
        "全トラック共通。時間グリッド、試聴、解析、自動保存、BDO書き出しを同期します。書き出し互換範囲は1～200ですが、現在の公式作曲ガイドの上限は180です。",
        "모든 트랙이 공유하며 시간 그리드, 미리 듣기, 분석, 자동 저장 및 BDO 내보내기를 동기화합니다. 내보내기 호환 범위는 1–200이며 현재 공식 작곡 안내의 상한은 180입니다.",
    ),
    "跟随参考 BPM": ("Follow reference BPM", "参照 BPM に追従", "참조 BPM 따르기"),
    "参考音频分析得到可靠节拍后，自动更新工程全局 BPM": (
        "Automatically update the project Global BPM after reference-audio analysis finds a reliable tempo",
        "参照音声の解析で信頼できるテンポが得られたら、プロジェクトのグローバル BPM を自動更新します",
        "참조 오디오 분석에서 신뢰할 수 있는 템포를 찾으면 프로젝트 글로벌 BPM을 자동으로 업데이트합니다",
    ),
    "全局 BPM 已设为 {bpm}；已停止自动跟随参考音乐": (
        "Global BPM set to {bpm}; automatic reference-music following is off",
        "グローバル BPM を {bpm} に設定し、参照音楽への自動追従を停止しました",
        "글로벌 BPM을 {bpm}(으)로 설정하고 참조 음악 자동 추적을 중지했습니다",
    ),
    "参考 BPM 证据不足；保留当前全局 BPM，可手动调节": (
        "Insufficient reference-BPM evidence; keeping the current Global BPM, which can be adjusted manually",
        "参照 BPM の証拠が不足しています。現在のグローバル BPM を維持し、手動で調整できます",
        "참조 BPM 근거가 부족하여 현재 글로벌 BPM을 유지합니다. 수동으로 조절할 수 있습니다",
    ),
    "已跟随参考音乐：全局 BPM {bpm} · 置信 {confidence}%": (
        "Following reference music: Global BPM {bpm} · confidence {confidence}%",
        "参照音楽に追従：グローバル BPM {bpm}・信頼度 {confidence}%",
        "참조 음악 적용: 글로벌 BPM {bpm} · 신뢰도 {confidence}%",
    ),
    "参考音乐 BPM 与工程一致：{bpm}": (
        "Reference BPM matches the project: {bpm}",
        "参照音楽の BPM はプロジェクトと一致しています：{bpm}",
        "참조 음악 BPM이 프로젝트와 일치합니다: {bpm}",
    ),
    "正在检测参考音乐 BPM…": ("Detecting reference-music BPM…", "参照音楽の BPM を検出中…", "참조 음악 BPM 감지 중…"),
    "未能可靠检测参考 BPM；保留当前值，可手动调节": (
        "Reference BPM could not be detected reliably; keeping the current value, which can be adjusted manually",
        "参照 BPM を確実に検出できませんでした。現在の値を維持し、手動で調整できます",
        "참조 BPM을 안정적으로 감지하지 못해 현재 값을 유지합니다. 수동으로 조절할 수 있습니다",
    ),
    "所有轨道共用；同步时间网格、试听、分析、自动保存和 BDO 导出。游戏静态安全范围 1–200。": (
        "Shared by every track; synchronizes the time grid, preview, analysis, autosave, and BDO export. The static game-safe range is 1–200.",
        "全トラック共通。時間グリッド、試聴、解析、自動保存、BDO書き出しを同期します。ゲームの静的安全範囲は1～200です。",
        "모든 트랙이 공유하며 시간 그리드, 미리 듣기, 분석, 자동 저장 및 BDO 내보내기를 동기화합니다. 게임의 정적 안전 범위는 1–200입니다.",
    ),
    "全局 BPM 已设为 {bpm}；时间网格、试听与导出已同步": (
        "Global BPM set to {bpm}; time grid, preview, and export are synchronized",
        "グローバル BPM を {bpm} に設定しました。時間グリッド、試聴、書き出しを同期しました",
        "글로벌 BPM을 {bpm}(으)로 설정했습니다. 시간 그리드, 미리 듣기 및 내보내기가 동기화되었습니다",
    ),
    "多人同步器": ("Multiplayer Sync", "マルチプレイ同期", "멀티플레이 동기화"),
    "多人同步器暂未开放；网络房间功能仍在开发中": (
        "Multiplayer Sync is not available yet; network rooms are still in development",
        "マルチプレイ同期はまだ利用できません。ネットワークルーム機能は開発中です",
        "멀티플레이 동기화는 아직 사용할 수 없으며 네트워크 방 기능은 개발 중입니다",
    ),
    "网络合奏房间": ("Network Ensemble Room", "ネットワーク合奏ルーム", "네트워크 합주 방"),
    "未连接 · 功能预留": ("Disconnected · reserved", "未接続・準備中", "연결 안 됨 · 예약 기능"),
    "用于协调黑色沙漠双队伍或 FF14 合奏的共同开始时刻；不控制游戏按键。": (
        "Coordinates one shared start time for two Black Desert teams or an FFXIV ensemble; it does not control game input.",
        "黒い砂漠の2チームまたはFF14合奏の共通開始時刻を調整します。ゲーム入力は操作しません。",
        "검은사막 두 팀 또는 FF14 합주의 공통 시작 시각을 조율하며 게임 입력은 제어하지 않습니다.",
    ),
    "北京时间": ("Beijing time", "北京時間", "베이징 시간"),
    "工程节拍": ("Project tempo", "プロジェクトテンポ", "프로젝트 템포"),
    "房间状态": ("Room status", "ルーム状態", "방 상태"),
    "连接设置": ("Connection", "接続設定", "연결 설정"),
    "创建房间": ("Create room", "ルームを作成", "방 만들기"),
    "加入房间": ("Join room", "ルームに参加", "방 참가"),
    "IP 地址或主机名": ("IP address or host name", "IPアドレスまたはホスト名", "IP 주소 또는 호스트 이름"),
    "6 位数字 PIN": ("6-digit PIN", "6桁のPIN", "6자리 PIN"),
    "方式": ("Mode", "方式", "방식"),
    "IP 地址": ("IP address", "IPアドレス", "IP 주소"),
    "端口号": ("Port", "ポート", "포트"),
    "PIN 码": ("PIN", "PIN", "PIN"),
    "倒计时时间": ("Countdown", "カウントダウン", "카운트다운"),
    " 秒": (" s", " 秒", "초"),
    "同步设计": ("Synchronization design", "同期設計", "동기화 설계"),
    "房主广播未来的绝对开始时刻；成员先估计时钟偏移与往返延迟，再用本机单调时钟倒计时。PIN 只用于房间验证，不等同于加密。": (
        "The host broadcasts a future absolute start time. Members first estimate clock offset and round-trip delay, then count down on a local monotonic clock. The PIN authenticates the room; it is not encryption.",
        "ホストは将来の絶対開始時刻を配信します。メンバーは時計のずれと往復遅延を推定し、ローカルの単調時計でカウントダウンします。PINはルーム確認用で、暗号化ではありません。",
        "방장은 미래의 절대 시작 시각을 전송합니다. 참가자는 시계 오프셋과 왕복 지연을 추정한 뒤 로컬 단조 시계로 카운트다운합니다. PIN은 방 확인용이며 암호화가 아닙니다.",
    ),
    "延迟 -- ms · 偏移 -- ms · 抖动 -- ms": ("Delay -- ms · offset -- ms · jitter -- ms", "遅延 -- ms・ずれ -- ms・ジッター -- ms", "지연 -- ms · 오프셋 -- ms · 지터 -- ms"),
    "房间成员": ("Room members", "ルームメンバー", "방 참가자"),
    "0 人在线": ("0 online", "オンライン 0人", "0명 온라인"),
    "A 队 · 队长 · 等待连接": ("Team A · leader · waiting", "Aチーム・リーダー・接続待ち", "A팀 · 리더 · 연결 대기"),
    "B 队 · 队长 · 等待连接": ("Team B · leader · waiting", "Bチーム・リーダー・接続待ち", "B팀 · 리더 · 연결 대기"),
    "成员加入后显示队伍、角色、就绪状态和延迟": ("Joined members will show team, role, ready state, and latency", "参加後にチーム、役割、準備状態、遅延を表示します", "참가 후 팀, 역할, 준비 상태 및 지연을 표시합니다"),
    "创建房间（预留）": ("Create room (reserved)", "ルーム作成（準備中）", "방 만들기(예약)"),
    "加入房间（预留）": ("Join room (reserved)", "ルーム参加（準備中）", "방 참가(예약)"),
    "网络协议尚未启用；当前仅完成房间界面和数据边界": ("The network protocol is not enabled; only the room UI and data boundary are implemented", "ネットワークプロトコルは未実装です。現在はルームUIとデータ境界のみ完成しています", "네트워크 프로토콜은 아직 활성화되지 않았으며 방 UI와 데이터 경계만 구현되었습니다"),
    "排练辅助雏形 · 不控制游戏输入，也不宣称消除客户端或网络延迟": (
        "Rehearsal-assist prototype · Does not control game input or claim to remove client or network latency",
        "リハーサル補助の試作版・ゲーム入力は操作せず、クライアントやネットワーク遅延の解消を保証しません",
        "합주 보조 프로토타입 · 게임 입력을 제어하지 않으며 클라이언트 또는 네트워크 지연 제거를 보장하지 않습니다",
    ),
    "跟随工程全局 BPM": ("Follows project Global BPM", "プロジェクトのグローバル BPM に追従", "프로젝트 글로벌 BPM 연동"),
    "{bpm} BPM · {meter}/4": ("{bpm} BPM · {meter}/4", "{bpm} BPM・{meter}/4", "{bpm} BPM · {meter}/4"),
    "团队数": ("Teams", "チーム数", "팀 수"),
    "预备小节": ("Count-in bars", "予備小節", "카운트인 마디"),
    "本机倒计时": ("Local countdown", "ローカルカウントダウン", "로컬 카운트다운"),
    "按全局 BPM 给两位队长统一预备拍；适合语音或同屏排练。": (
        "Give both leaders the same count-in at the Global BPM; suited to voice chat or same-screen rehearsals.",
        "グローバル BPM で2人のリーダーに同じ予備拍を提示します。ボイスチャットや同じ画面での練習向けです。",
        "글로벌 BPM에 맞춰 두 리더에게 동일한 카운트인을 제공합니다. 음성 채팅 또는 같은 화면 합주에 적합합니다.",
    ),
    "网络广播": ("Network broadcast", "ネットワーク配信", "네트워크 브로드캐스트"),
    "预留房间时钟、延迟估计和重同步接口。": (
        "Reserved for room clocks, latency estimation, and resynchronization.",
        "ルームクロック、遅延推定、再同期のインターフェースを予約しています。",
        "룸 시계, 지연 추정 및 재동기화 인터페이스를 위해 예약되었습니다.",
    ),
    "硬件同步": ("Hardware sync", "ハードウェア同期", "하드웨어 동기화"),
    "预留外部同步器适配接口；当前不连接任何设备。": (
        "Reserved for external synchronizer adapters; no device is currently connected.",
        "外部同期装置のアダプター用インターフェースです。現在はどの機器にも接続しません。",
        "외부 동기화 장치 어댑터용 인터페이스이며 현재 어떤 장치에도 연결하지 않습니다.",
    ),
    "开始倒计时": ("Start countdown", "カウントダウン開始", "카운트다운 시작"),
    "现在开始": ("Start now", "スタート", "지금 시작"),
    "预备 {bar}/{bars} · 第 {beat} 拍": (
        "Count-in {bar}/{bars} · Beat {beat}",
        "予備 {bar}/{bars}・{beat} 拍目",
        "카운트인 {bar}/{bars} · {beat}박",
    ),
    "可用": ("Available", "利用可能", "사용 가능"),
    "预留": ("Reserved", "準備中", "예약됨"),
}

for _source, (_english, _japanese, _korean) in _WORKSPACE_TEMPO_TRANSLATIONS.items():
    EN[_source] = _english
    JA[_source] = _japanese
    KO[_source] = _korean

del _source, _english, _japanese, _korean

_REFERENCE_TIMBRE_HYBRID_TRANSLATIONS = {
    "声学分类 · 少样本补全未知片段": (
        "Acoustic classes · few-shot completion for unknown spans",
        "音響分類・未知区間を少数サンプルで補完",
        "음향 분류 · 미확인 구간을 소수 샘플로 보완",
    ),
}

for _source, (
    _english,
    _japanese,
    _korean,
) in _REFERENCE_TIMBRE_HYBRID_TRANSLATIONS.items():
    EN[_source] = _english
    JA[_source] = _japanese
    KO[_source] = _korean

del _source, _english, _japanese, _korean

_TIMELINE_VELOCITY_CURVE_TRANSLATIONS = {
    "力度节点": ("Velocity Points", "ベロシティポイント", "벨로시티 포인트"),
    "力度 0–127": ("Velocity 0–127", "ベロシティ 0–127", "벨로시티 0–127"),
    "力度 {velocity:.0f} · 左 {left:.0f}% · 右 {right:.0f}%": (
        "Velocity {velocity:.0f} · L {left:.0f}% · R {right:.0f}%",
        "ベロシティ {velocity:.0f}・左 {left:.0f}%・右 {right:.0f}%",
        "벨로시티 {velocity:.0f} · 왼쪽 {left:.0f}% · 오른쪽 {right:.0f}%",
    ),
    "当前可见区": ("Visible Range", "現在の表示範囲", "현재 표시 구간"),
    "A–B 区间": ("A–B Range", "A–B区間", "A–B 구간"),
    "正在编辑 · {count} 节点": (
        "Editing · {count} points",
        "編集中・{count}ポイント",
        "편집 중 · 포인트 {count}개",
    ),
    "精准力度 · {track} · {scope}": (
        "Precision Velocity · {track} · {scope}",
        "精密ベロシティ・{track}・{scope}",
        "정밀 벨로시티 · {track} · {scope}",
    ),
    "节点 {index}/{count} · 时间 {time:.2f}% · 力度 {gain:.1f}% · 左权重 {left:.1f}% · 右权重 {right:.1f}%": (
        "Point {index}/{count} · Time {time:.2f}% · Velocity {gain:.1f}% · Left {left:.1f}% · Right {right:.1f}%",
        "ポイント {index}/{count}・時間 {time:.2f}%・ベロシティ {gain:.1f}%・左 {left:.1f}%・右 {right:.1f}%",
        "포인트 {index}/{count} · 시간 {time:.2f}% · 벨로시티 {gain:.1f}% · 왼쪽 {left:.1f}% · 오른쪽 {right:.1f}%",
    ),
    "单击创建节点；拖动节点精调；拖动左右手柄改变权重；右键删除中间节点": (
        "Click to add a point; drag points to fine-tune; drag side handles to change weight; right-click an interior point to delete",
        "クリックでポイント追加・ポイントをドラッグして微調整・左右ハンドルで重みを変更・中間ポイントを右クリックで削除",
        "클릭해 포인트 추가 · 포인트 드래그로 미세 조정 · 좌우 핸들로 가중치 변경 · 중간 포인트 우클릭으로 삭제",
    ),
    "力度节点目标轨道已经失效": (
        "The velocity-point target track is no longer available",
        "ベロシティポイントの対象トラックは使用できなくなりました",
        "벨로시티 포인트 대상 트랙을 더 이상 사용할 수 없습니다",
    ),
    "已应用 {track} 的精准力度 · {count} 音符": (
        "Applied precision velocity to {track} · {count} notes",
        "{track}に精密ベロシティを適用・{count}ノート",
        "{track}에 정밀 벨로시티 적용 · 음표 {count}개",
    ),
}

for _source, (
    _english,
    _japanese,
    _korean,
) in _TIMELINE_VELOCITY_CURVE_TRANSLATIONS.items():
    EN[_source] = _english
    JA[_source] = _japanese
    KO[_source] = _korean

del _source, _english, _japanese, _korean

_TRACK_GLOBAL_GAIN_TRANSLATIONS = {
    "轨道力度基数…": ("Track Velocity Base…", "トラックベロシティ基数…", "트랙 벨로시티 기준값…"),
    "轨道力度基数": ("Track Velocity Base", "トラックベロシティ基数", "트랙 벨로시티 기준값"),
    "力度基数": ("Velocity Base", "ベロシティ基数", "벨로시티 기준값"),
    "均化到 0–127": ("Normalize to 0–127", "0～127に均一化", "0–127로 균등화"),
    "只调整当前轨道；基数从该轨道现有的原始主、副力度重新计算，不影响其他轨道或轨道音量。": (
        "Adjust only this track. The base is calculated from its current original primary and secondary velocities without affecting other tracks or mixer volume.",
        "現在のトラックだけを調整します。このトラックの現在の元の主・副ベロシティから基数を計算し、他のトラックやミキサー音量には影響しません。",
        "현재 트랙만 조절합니다. 이 트랙의 현재 원본 주·보조 벨로시티에서 기준값을 계산하며 다른 트랙이나 믹서 볼륨에는 영향을 주지 않습니다.",
    ),
    "全局力度基数": ("Global Velocity Base", "グローバルベロシティ基数", "전역 벨로시티 기준값"),
    "均化": ("Normalize", "均一化", "균등화"),
    "自由设置整首曲谱的力度基数；勾选均化后，先加基数，再把整组力度统一按比例映射到 0–127。": (
        "Set a free score-wide velocity base. With Normalize enabled, add the base first and then proportionally map the group into 0–127.",
        "曲全体のベロシティ基数を自由に設定します。均一化を有効にすると、基数を加算してからグループ全体を0～127へ比例マッピングします。",
        "전체 악보의 벨로시티 기준값을 자유롭게 설정합니다. 균등화를 켜면 기준값을 먼저 더한 뒤 전체 그룹을 0–127로 비례 매핑합니다.",
    ),
    "按整首曲谱的原始力度关系统一缩放，使调整后的力度落在 0–127。": (
        "Scale the whole score uniformly from its original velocity relationships so adjusted values fit within 0–127.",
        "曲全体の元の強弱関係を保って一括スケーリングし、調整後の値を0～127に収めます。",
        "전체 악보의 원래 강약 관계를 기준으로 함께 스케일링하여 조정값을 0–127에 맞춥니다.",
    ),
    "dB 全局增益": ("Global Gain (dB)", "dBグローバルゲイン", "dB 글로벌 게인"),
    "将同一个增益数值直接加到整首曲谱的每个音符力度；保持音符之间的力度差，并反映到试听和导出。": (
        "Add the same gain value directly to every note velocity in the score, preserving the differences between notes in preview and export.",
        "同じゲイン値を曲全体の各ノートベロシティに直接加算し、ノート間の強弱差を保ったまま試聴と書き出しに反映します。",
        "같은 게인 값을 전체 악보의 각 음표 벨로시티에 직접 더해 음표 사이의 강약 차이를 유지한 채 미리 듣기와 내보내기에 반영합니다.",
    ),
    "以力度中点为轴调整整首曲谱的动态范围：数值增大时低力度上抬、高力度下降；保留强弱轮廓并反映到试听和导出。": (
        "Adjust the score-wide dynamic range around its velocity midpoint: higher values raise quiet notes and lower loud notes while preserving the dynamic contour in preview and export.",
        "ベロシティの中点を軸に曲全体のダイナミックレンジを調整します。値を上げると弱い音を持ち上げ、強い音を下げ、強弱の輪郭を試聴と書き出しに反映します。",
        "벨로시티 중간값을 축으로 전체 악보의 다이내믹 레인지를 조절합니다. 값을 높이면 약한 음은 올리고 강한 음은 낮추며 강약 윤곽을 미리 듣기와 내보내기에 반영합니다.",
    ),
    "以 Base 百分比统一缩放曲谱中每个音符的力度；保持相对比例，并直接反映到试听和导出。": (
        "Scale every note velocity in the score by one Base percentage, preserving relative dynamics and applying directly to preview and export.",
        "楽譜内の全ノートのベロシティを同じBaseパーセントで拡大縮小し、相対的な強弱を保ったまま試聴と書き出しへ直接反映します。",
        "악보의 모든 음표 벨로시티를 하나의 Base 백분율로 조절해 상대적인 셈여림을 유지하고 미리듣기와 내보내기에 직접 반영합니다.",
    ),
}

for _source, (
    _english,
    _japanese,
    _korean,
) in _TRACK_GLOBAL_GAIN_TRANSLATIONS.items():
    EN[_source] = _english
    JA[_source] = _japanese
    KO[_source] = _korean

del _source, _english, _japanese, _korean

_CONTENT_BOUNDARY_TRANSLATIONS = {
    "内容边界": (
        "Content Boundary",
        "コンテンツ境界",
        "콘텐츠 경계",
    ),
    "本工具不提供受限制内容的获取或传播能力；外部内容须由用户自行确保来源与授权。": (
        "This tool does not provide access to or distribution of restricted content; users are responsible for the source and authorization of external content.",
        "本ツールは制限対象コンテンツの取得または配布機能を提供しません。外部コンテンツの入手元と利用許諾は利用者自身が確認してください。",
        "이 도구는 제한된 콘텐츠의 취득 또는 배포 기능을 제공하지 않습니다. 외부 콘텐츠의 출처와 이용 권한은 사용자가 직접 확인해야 합니다.",
    ),
}

for _source, (
    _english,
    _japanese,
    _korean,
) in _CONTENT_BOUNDARY_TRANSLATIONS.items():
    EN[_source] = _english
    JA[_source] = _japanese
    KO[_source] = _korean

del _source, _english, _japanese, _korean

# These feature-local catalog additions are declared after ``Localizer`` to
# keep the existing generated catalog blocks untouched. Refresh the derived
# lookup tables so live language switching sees the new source keys too.
ZH_TW = _build_traditional_catalog()
TRANSLATIONS["zh_TW"] = ZH_TW
_TRANSLATION_SOURCES = frozenset(EN)
_REVERSE_TRANSLATIONS = _translation_reverse_maps()


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
