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

from .i18n_catalogs import EN, JA, KO


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










# Text used by secondary dialogs and their initial dynamic summaries.  Keep
# these in the runtime catalog as well as the main-window vocabulary so a
# language switch translates every already-open dialog consistently.









TRANSLATIONS = {"en_US": EN, "ja_JP": JA, "ko_KR": KO}




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






# Semantic transcription review, harmony, phrase, and BDO instrument-matching
# vocabulary.  These exact Chinese source strings are shared by the embedded
# editor panel and the piano-roll review interactions.




















# Compact transcription command-strip labels.  Detailed explanations remain
# available through translated tooltips and accessible names.





# Local-only preview sources and optional lane artwork. The packaged defaults
# are original app artwork; configured game images remain private local data.














# Export validation and score comparison can be rendered outside the widget
# tree (reports, clipboard text and CLI output), so their complete templates
# live in the same catalogs and retain the source placeholder signatures.

















# Export consistency diagnostics intentionally distinguish serialized fields
# from unverified in-game DSP/audio behavior.



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

















# Transcription candidate layers are provisional analysis results, distinct
# from editable notes and the optional other-track reference layer.


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





# The practical transcription workflow presents evidence as a guide, then
# hands an editable draft to the game-fit check and ordinary editor.


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

_CLIP_EDITOR_SCOPE_TRANSLATIONS = {
    "片段编辑无法安全应用：{error}": (
        "The clip edit cannot be applied safely: {error}",
        "クリップ編集を安全に適用できません：{error}",
        "클립 편집을 안전하게 적용할 수 없습니다: {error}",
    ),
    "目标片段已在外部发生变化。请关闭并重新打开编辑器后再试。": (
        "The target clip changed outside this editor. Close and reopen the editor, then try again.",
        "対象クリップが外部で変更されました。エディターを閉じて開き直してから再試行してください。",
        "대상 클립이 편집기 밖에서 변경되었습니다. 편집기를 닫았다가 다시 연 후 재시도하세요.",
    ),
    "草稿中有音符超出当前片段的时间范围。请将音符移回片段内。": (
        "The draft contains notes outside the current clip. Move them back inside the clip.",
        "下書きに現在のクリップ範囲外のノートがあります。クリップ内へ戻してください。",
        "초안에 현재 클립 범위를 벗어난 음표가 있습니다. 클립 안으로 이동하세요.",
    ),
    "目标片段已不存在。": (
        "The target clip no longer exists.",
        "対象クリップは存在しません。",
        "대상 클립이 더 이상 존재하지 않습니다.",
    ),
    "草稿包含无效的音符时间。": (
        "The draft contains invalid note timing.",
        "下書きに無効なノート時刻があります。",
        "초안에 잘못된 음표 시간이 있습니다.",
    ),
    "无法应用优化": (
        "Cannot Apply Optimization",
        "最適化を適用できません",
        "최적화를 적용할 수 없음",
    ),
    "优化结果超出当前片段的时间范围，未修改草稿。": (
        "The optimization result exceeds the current clip's time range. The draft was not changed.",
        "最適化結果が現在のクリップ範囲を超えたため、下書きは変更されませんでした。",
        "최적화 결과가 현재 클립의 시간 범위를 벗어나 초안을 변경하지 않았습니다.",
    ),
}

for _source, (_english, _japanese, _korean) in _CLIP_EDITOR_SCOPE_TRANSLATIONS.items():
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

_ARRANGEMENT_WORKSPACE_TRANSLATIONS = {
    "窗口": ("Windows", "ウィンドウ", "창"),
    "音块编辑区域": ("Clip Edit Range", "クリップ編集範囲", "클립 편집 범위"),
    "切换或平铺已打开的音块编辑器": (
        "Switch or tile open clip editors",
        "開いているクリップエディターの切り替え・整列",
        "열린 클립 편집기 전환 또는 바둑판식 배열",
    ),
    "已打开 {count} 个音块编辑器": (
        "{count} clip editors open",
        "クリップエディターを{count}個開いています",
        "클립 편집기 {count}개 열림",
    ),
    "平铺编辑器窗口": (
        "Tile Editor Windows", "エディターを整列", "편집기 창 바둑판식 배열",
    ),
    "返回轨道时间轴": (
        "Return to Track Timeline", "トラックタイムラインへ戻る", "트랙 타임라인으로 돌아가기",
    ),
    "展开乐器组": ("Expand Instrument Group", "楽器グループを展開", "악기 그룹 펼치기"),
    "折叠乐器组": ("Collapse Instrument Group", "楽器グループを折りたたむ", "악기 그룹 접기"),
    "拖动调整轨道头宽度": (
        "Drag to resize track headers", "ドラッグでトラックヘッダー幅を変更", "드래그하여 트랙 헤더 너비 조절",
    ),
    "拖动调整轨道高度": (
        "Drag to resize track height", "ドラッグでトラックの高さを変更", "드래그하여 트랙 높이 조절",
    ),
    "拖动调整参考音频高度": (
        "Drag to resize reference audio", "ドラッグで参照オーディオの高さを変更", "드래그하여 참조 오디오 높이 조절",
    ),
    "F1 快捷键；Ctrl+D 复制片段；Ctrl+E 在播放头切分；Enter 编辑焦点；方向键导航；Alt+左右调整音量": (
        "F1 shortcuts; Ctrl+D duplicate clip; Ctrl+E split at playhead; Enter edits focus; arrows navigate; Alt+Left/Right adjusts volume",
        "F1 ショートカット、Ctrl+D クリップ複製、Ctrl+E 再生位置で分割、Enter フォーカス編集、矢印で移動、Alt+左右で音量調整",
        "F1 단축키, Ctrl+D 클립 복제, Ctrl+E 재생 헤드에서 분할, Enter 포커스 편집, 화살표 탐색, Alt+좌우 음량 조절",
    ),
}

for _source, (_english, _japanese, _korean) in _ARRANGEMENT_WORKSPACE_TRANSLATIONS.items():
    EN[_source] = _english
    JA[_source] = _japanese
    KO[_source] = _korean

del _source, _english, _japanese, _korean

_TRACK_MERGE_TRANSLATIONS = {
    "框选工具": ("Marquee Tool", "範囲選択ツール", "영역 선택 도구"),
    "框选工具：拖动框选多个片段；所选片段只在片段编辑状态下移动": (
        "Marquee: drag to select multiple clips; selected clips move only in Clip Edit mode",
        "範囲選択：ドラッグで複数クリップを選択します。選択したクリップの移動はクリップ編集モードでのみ行えます",
        "영역 선택: 드래그하여 여러 클립을 선택합니다. 선택한 클립은 클립 편집 모드에서만 이동합니다",
    ),
    "剃刀": ("Razor", "はさみ", "자르기"),
    "选择工具": ("Select Tool", "選択ツール", "선택 도구"),
    "片段编辑": ("Clip Edit", "クリップ編集", "클립 편집"),
    "剃刀工具": ("Razor Tool", "はさみツール", "자르기 도구"),
    "选择工具：移动或裁剪片段": ("Select: move or trim clips", "選択：クリップを移動またはトリム", "선택: 클립 이동 또는 트림"),
    "片段编辑：开启后拖动片段可移动或裁剪；再次点击关闭": (
        "Clip edit: enable to move or trim by dragging; click again to turn off",
        "クリップ編集：有効にするとドラッグで移動・トリムできます。もう一度クリックすると解除します",
        "클립 편집: 켜면 드래그로 이동하거나 트리밍할 수 있습니다. 다시 클릭하면 꺼집니다",
    ),
    "剃刀工具：单击片段进行切分": ("Razor: click a clip to split it", "はさみ：クリップをクリックして分割", "자르기: 클립을 클릭해 분할"),
    "剃刀工具：单击片段进行切分；再次点击关闭": (
        "Razor: click a clip to split it; click again to turn off",
        "はさみ：クリップをクリックして分割します。もう一度クリックすると解除します",
        "자르기: 클립을 클릭해 분할합니다. 다시 클릭하면 꺼집니다",
    ),
    "无法切分片段：{error}": ("Cannot split clip: {error}", "クリップを分割できません：{error}", "클립을 분할할 수 없음: {error}"),
    "片段已切分": ("Clip split", "クリップを分割しました", "클립 분할됨"),
    "无法删除所选片段：{error}": ("Cannot delete selected clips: {error}", "選択したクリップを削除できません：{error}", "선택한 클립을 삭제할 수 없음: {error}"),
    "已删除 {count} 个片段": ("Deleted {count} clips", "{count}個のクリップを削除しました", "클립 {count}개 삭제됨"),
    "无法移动所选片段：{error}": ("Cannot move selected clips: {error}", "選択したクリップを移動できません：{error}", "선택한 클립을 이동할 수 없음: {error}"),
    "已移动 {count} 个片段": ("Moved {count} clips", "{count}個のクリップを移動しました", "클립 {count}개 이동됨"),
    "单击音符内部即可用剃刀切分": ("Click inside a note to split it with the Razor tool", "ノート内部をクリックしてはさみツールで分割", "음표 안을 클릭해 자르기 도구로 분할"),
    "剃刀：单击音符内部即可切分": ("Razor: click inside a note to split it", "はさみ：ノート内部をクリックして分割", "자르기: 음표 안을 클릭해 분할"),
    "同乐器 Group · {instrument} · {count} 轨": ("Same-instrument Group · {instrument} · {count} tracks", "同じ楽器のGroup · {instrument} · {count}トラック", "같은 악기 Group · {instrument} · {count}개 트랙"),
    "对齐": ("Align", "整列", "정렬"),
    "自然": ("Humanize", "ヒューマナイズ", "휴머나이즈"),
    "扫弦": ("Strum", "ストラム", "스트럼"),
    "按当前网格量化所选音符；未选择时处理全部": ("Quantize selected notes to the current grid; all notes when none are selected", "選択ノートを現在のグリッドにクオンタイズ。未選択時はすべて", "선택 음표를 현재 그리드에 퀀타이즈하며 선택이 없으면 전체 적용"),
    "轻微改变时间与力度，使演奏更自然": ("Add subtle timing and velocity variation", "タイミングとベロシティをわずかに変えて自然にします", "타이밍과 벨로시티를 미세하게 바꿔 자연스럽게 연주합니다"),
    "将同起点和弦按低音到高音错开": ("Spread simultaneous chord notes from low to high", "同時発音のコードを低音から高音へずらします", "동시 시작 코드를 낮은 음부터 높은 음까지 펼칩니다"),
    "添加时间轴标记…": ("Add Timeline Marker…", "タイムラインマーカーを追加…", "타임라인 마커 추가…"),
    "重命名时间轴标记…": ("Rename Timeline Marker…", "タイムラインマーカー名を変更…", "타임라인 마커 이름 변경…"),
    "删除时间轴标记": ("Delete Timeline Marker", "タイムラインマーカーを削除", "타임라인 마커 삭제"),
    "时间轴标记": ("Timeline Marker", "タイムラインマーカー", "타임라인 마커"),
    "标记名称": ("Marker name", "マーカー名", "마커 이름"),
    "检查发现 {count} 项错误、近似结果或预期变化。\n仍可尝试导出，但可能出现丢音、音域或映射异常；Owner ID、非 /4 拍号等格式硬约束仍会阻止导出。确认继续吗？": ("The check found {count} errors, approximations, or expected changes.\nYou may still try to export, but notes, ranges, or mappings may be affected. Hard format requirements such as Owner ID and /4 meter still block export. Continue?", "チェックで{count}件のエラー、近似結果、または予想される変更が見つかりました。\n書き出しは試行できますが、ノート、音域、マッピングに影響する可能性があります。Owner IDや/4拍子などの形式要件は引き続き書き出しを停止します。続行しますか？", "검사에서 오류, 근사 결과 또는 예상 변경 {count}건을 찾았습니다.\n내보내기를 시도할 수 있지만 음표, 음역 또는 매핑에 문제가 생길 수 있습니다. Owner ID와 /4 박자표 같은 형식 필수 조건은 계속 내보내기를 차단합니다. 계속할까요?"),
    "工程状态": ("Project Status", "プロジェクト状態", "프로젝트 상태"),
    "轨道检查器": ("Track Inspector", "トラックインスペクター", "트랙 인스펙터"),
    "检查器": ("Inspector", "インスペクター", "인스펙터"),
    "显示或隐藏轨道检查器": ("Show or hide the track inspector", "トラックインスペクターを表示または非表示", "트랙 인스펙터 표시 또는 숨기기"),
    "未选择轨道": ("No track selected", "トラックが選択されていません", "선택한 트랙 없음"),
    "选择时间轴中的轨道以查看内容和游戏输出。": ("Select a timeline track to inspect its content and game output.", "タイムラインのトラックを選択すると内容とゲーム出力を確認できます。", "타임라인 트랙을 선택해 콘텐츠와 게임 출력을 확인하세요."),
    "轨道内容": ("Track Content", "トラック内容", "트랙 콘텐츠"),
    "八度与音高": ("Octave & Pitch", "オクターブと音高", "옥타브 및 음높이"),
    "游戏输出路由": ("Game Output Route", "ゲーム出力ルート", "게임 출력 라우트"),
    "路由与 FX": ("Route & FX", "ルートとFX", "라우트 및 FX"),
    "游戏检查": ("Game Check", "ゲームチェック", "게임 검사"),
    "合并同路由轨道…": ("Merge Same-Route Track…", "同じルートのトラックを結合…", "같은 라우트 트랙 병합…"),
    "Track 保存音乐内容；游戏输出路由决定导出乐器、音量与 FX。": ("Track stores musical content; the game output route determines the exported instrument, volume, and FX.", "Trackは音楽内容を保持し、ゲーム出力ルートが書き出す楽器、音量、FXを決定します。", "Track은 음악 콘텐츠를 저장하고 게임 출력 라우트가 내보낼 악기, 음량과 FX를 결정합니다."),
    "Track {track_id} · {state}": ("Track {track_id} · {state}", "Track {track_id} · {state}", "Track {track_id} · {state}"),
    "{count} 个音符\n音域 {pitch_range}": ("{count} notes\nRange {pitch_range}", "{count}ノート\n音域 {pitch_range}", "음표 {count}개\n음역 {pitch_range}"),
    "路由 ID {route_id} · 模式 {mode}\n音量 {volume} · Reverb {reverb} · Delay {delay} · Chorus {chorus}": ("Route ID {route_id} · Mode {mode}\nVolume {volume} · Reverb {reverb} · Delay {delay} · Chorus {chorus}", "ルートID {route_id} · モード {mode}\n音量 {volume} · Reverb {reverb} · Delay {delay} · Chorus {chorus}", "라우트 ID {route_id} · 모드 {mode}\n음량 {volume} · Reverb {reverb} · Delay {delay} · Chorus {chorus}"),
    "{track} · {count} 个音符": ("{track} · {count} notes", "{track} · {count}ノート", "{track} · 음표 {count}개"),
    "操作提示": ("Hints", "操作ヒント", "작업 힌트"),
    "在画布右上角显示当前操作提示": ("Show contextual operation hints at the top-right of the canvas", "現在の操作ヒントをキャンバス右上に表示", "현재 작업 힌트를 캔버스 오른쪽 위에 표시"),
    "游戏输出": ("Game Output", "ゲーム出力", "게임 출력"),
    "更换游戏乐器": ("Change Game Instrument", "ゲーム楽器を変更", "게임 악기 변경"),
    "合并同乐器轨道…": ("Merge Same-Instrument Track…", "同じ楽器のトラックを結合…", "같은 악기 트랙 병합…"),
    "没有可合并的同游戏乐器轨道": ("No track with the same game instrument is available", "結合できる同じゲーム楽器のトラックがありません", "병합할 수 있는 같은 게임 악기 트랙이 없습니다"),
    "{name} · {count} 个音符 · #{track_id}": ("{name} · {count} notes · #{track_id}", "{name} · {count}ノート · #{track_id}", "{name} · 음표 {count}개 · #{track_id}"),
    "合并同乐器轨道": ("Merge Same-Instrument Tracks", "同じ楽器のトラックを結合", "같은 악기 트랙 병합"),
    "选择要并入“{name}”的轨道：": ("Choose the track to merge into “{name}”: ", "「{name}」へ結合するトラックを選択：", "“{name}”에 병합할 트랙 선택:"),
    "无法合并轨道": ("Tracks Cannot Be Merged", "トラックを結合できません", "트랙을 병합할 수 없음"),
    "两条轨道必须使用相同游戏乐器、游戏音高映射、音量和全部混音参数。可先统一同乐器音量和 FX。": ("Both tracks must use the same game instrument, game pitch mapping, volume, and all mixer parameters. You can unify same-instrument volume and FX first.", "両方のトラックでゲーム楽器、ゲーム音高マッピング、音量、すべてのミキサー設定が一致している必要があります。先に同じ楽器の音量とFXを統一できます。", "두 트랙의 게임 악기, 게임 음높이 매핑, 음량 및 모든 믹서 설정이 같아야 합니다. 먼저 같은 악기의 음량과 FX를 통일할 수 있습니다."),
    "检测到 {regions} 个重叠区域，共 {duration:.0f} ms；涉及 {pairs} 对音块，其中同音高 {same_pitch} 对、完全重复 {duplicates} 个。合并不会自动删除或降音量：重叠可能造成叠音、突出的起音和更高复音占用，合并后会在时间轴高亮这些区域供你调节。": ("Found {regions} overlap regions totaling {duration:.0f} ms, involving {pairs} note-block pairs: {same_pitch} same-pitch pairs and {duplicates} exact duplicates. Merge will not delete notes or lower velocity automatically; overlaps can cause layering, pronounced attacks, and higher polyphony use. These regions will be highlighted on the timeline for adjustment.", "{regions}個の重複領域（合計{duration:.0f} ms）、{pairs}組のノートブロックを検出しました。同音高は{same_pitch}組、完全重複は{duplicates}個です。結合時に自動削除や音量低下は行いません。重なりによる二重発音、強いアタック、同時発音数の増加があり得るため、結合後にタイムラインで強調表示します。", "총 {duration:.0f}ms의 겹침 영역 {regions}개와 음표 블록 {pairs}쌍을 찾았습니다. 같은 음높이 {same_pitch}쌍, 완전 중복 {duplicates}개입니다. 병합 시 자동 삭제나 음량 감소는 하지 않습니다. 겹침은 중첩음, 강한 어택, 동시 발음 사용 증가를 일으킬 수 있어 병합 후 타임라인에 강조 표시합니다."),
    "未检测到两条轨道之间的重叠音块。": ("No overlapping note blocks were found between the tracks.", "2つのトラック間に重複するノートブロックはありません。", "두 트랙 사이에 겹치는 음표 블록이 없습니다."),
    "合并后共 {count} 个音符；游戏导出仍是 1 个乐器组，内部会拆为 {tracks} 条承载音符轨道（另有格式要求的空尾轨）。": ("The merge will contain {count} notes. Game export remains one instrument group, split internally into {tracks} note-bearing tracks (plus the format-required empty trailing track).", "結合後は{count}ノートです。ゲーム書き出しでは1つの楽器グループのまま、内部でノートを持つ{tracks}本のトラックに分割されます（形式上必要な空の末尾トラックが別に付きます）。", "병합 후 음표는 {count}개입니다. 게임 내보내기에서는 하나의 악기 그룹으로 유지되며 내부적으로 음표가 있는 트랙 {tracks}개로 분할됩니다(형식상 필요한 빈 마지막 트랙 별도)."),
    "合并后共 {count} 个音符，并导出为 1 个游戏乐器组。": ("The merge will contain {count} notes and export as one game instrument group.", "結合後は{count}ノートで、1つのゲーム楽器グループとして書き出されます。", "병합 후 음표는 {count}개이며 하나의 게임 악기 그룹으로 내보냅니다."),
    "确认合并轨道": ("Confirm Track Merge", "トラック結合の確認", "트랙 병합 확인"),
    "该操作可撤销。": ("This action can be undone.", "この操作は元に戻せます。", "이 작업은 실행 취소할 수 있습니다."),
    "轨道已合并；{count} 个重叠区域已标记": ("Tracks merged; {count} overlap regions marked", "トラックを結合し、{count}個の重複領域をマークしました", "트랙을 병합하고 겹침 영역 {count}개를 표시했습니다"),
}

for _source, (_english, _japanese, _korean) in _TRACK_MERGE_TRANSLATIONS.items():
    EN[_source] = _english
    JA[_source] = _japanese
    KO[_source] = _korean

del _source, _english, _japanese, _korean

_CLIP_MERGE_CONFIRMATION_TRANSLATIONS = {
    "确认合并片段": (
        "Confirm Clip Merge",
        "クリップ結合の確認",
        "클립 병합 확인",
    ),
    "目标位置与已有片段重叠。确认后会把两个片段合并；选择“否”将取消本次拖动，不会自动对齐或修改工程。": (
        "The target overlaps an existing clip. Confirm to merge the two clips; choose No to cancel this drag without automatic alignment or any project changes.",
        "移動先は既存のクリップと重なっています。確認すると2つのクリップを結合します。「いいえ」を選ぶと今回のドラッグを取り消し、自動整列もプロジェクトの変更も行いません。",
        "대상 위치가 기존 클립과 겹칩니다. 확인하면 두 클립을 병합합니다. 아니요를 선택하면 이번 드래그를 취소하며 자동 정렬이나 프로젝트 변경을 하지 않습니다.",
    ),
}

for _source, (_english, _japanese, _korean) in _CLIP_MERGE_CONFIRMATION_TRANSLATIONS.items():
    EN[_source] = _english
    JA[_source] = _japanese
    KO[_source] = _korean

del _source, _english, _japanese, _korean

_ARRANGEMENT_REFINEMENT_TRANSLATIONS = {
    "自动吸附已激活：移动或裁切片段时自动对齐；再次点击关闭（Alt 临时关闭）": ("Auto snap is on: clips align while moving or trimming; click again to turn it off (hold Alt to bypass)", "自動スナップはオンです。クリップの移動・トリミング時に整列します。もう一度クリックするとオフになります（Altで一時解除）", "자동 스냅이 켜져 있습니다. 클립 이동 또는 자르기 시 자동 정렬됩니다. 다시 클릭하면 꺼집니다(Alt로 일시 해제)"),
    "自动吸附未激活：移动和裁切片段时不会自动对齐；点击开启": ("Auto snap is off: clips will not align while moving or trimming; click to turn it on", "自動スナップはオフです。クリップの移動・トリミング時に整列しません。クリックするとオンになります", "자동 스냅이 꺼져 있습니다. 클립 이동 또는 자르기 시 자동 정렬되지 않습니다. 클릭하면 켜집니다"),
    "自动吸附已激活": ("Auto snap on", "自動スナップ オン", "자동 스냅 켜짐"),
    "自动吸附未激活": ("Auto snap off", "自動スナップ オフ", "자동 스냅 꺼짐"),
    "磁吸：对齐网格、其他片段边界与时间轴标记（Alt 临时关闭）": ("Snap to grid, clip edges, and timeline markers (hold Alt to bypass)", "グリッド、クリップ境界、タイムラインマーカーにスナップ（Altで一時解除）", "그리드, 클립 경계, 타임라인 마커에 스냅(Alt로 일시 해제)"),
    "磁吸对齐": ("Snap", "スナップ", "스냅"),
    "片段边界": ("Clip edge", "クリップ境界", "클립 경계"),
    "音符编辑器仍有未应用修改；请先应用或关闭，再撤销工程。": ("A note editor still has unapplied changes. Apply or close it before undoing the project.", "ノートエディターに未適用の変更があります。適用または閉じてからプロジェクトを元に戻してください。", "음표 편집기에 적용되지 않은 변경 사항이 있습니다. 적용하거나 닫은 후 프로젝트 실행을 취소하세요."),
    "片段已移动；目标乐器存在音高或映射问题，已标红": ("Clip moved; pitch or mapping problems on the target instrument are marked red", "クリップを移動しました。移動先の楽器にある音高またはマッピングの問題を赤で表示しました", "클립을 이동했습니다. 대상 악기의 음높이 또는 매핑 문제를 빨간색으로 표시했습니다"),
    "乐器组 ×{count}": ("Group ×{count}", "楽器グループ ×{count}", "악기 그룹 ×{count}"),
    "乐器组 · {instrument} · {count} 轨": ("Group · {instrument} · {count} tracks", "楽器グループ · {instrument} · {count}トラック", "악기 그룹 · {instrument} · {count}개 트랙"),
    "乐器组 · {instrument} · {count} 轨；点击组名选择整组，M/S 控制整组": ("Group · {instrument} · {count} tracks; click the group name to select it, M/S controls the group", "楽器グループ · {instrument} · {count}トラック。グループ名で選択、M/Sでグループ全体を操作", "악기 그룹 · {instrument} · {count}개 트랙. 그룹 이름으로 선택하고 M/S로 그룹 전체를 제어합니다"),
    "整组静音": ("Mute Group", "グループをミュート", "그룹 음소거"),
    "取消整组静音": ("Unmute Group", "グループのミュートを解除", "그룹 음소거 해제"),
    "整组独奏": ("Solo Group", "グループをソロ", "그룹 솔로"),
    "取消整组独奏": ("Unsolo Group", "グループのソロを解除", "그룹 솔로 해제"),
    "折叠所有乐器组": ("Collapse All Instrument Groups", "すべての楽器グループを折りたたむ", "모든 악기 그룹 접기"),
    "展开所有乐器组": ("Expand All Instrument Groups", "すべての楽器グループを展開", "모든 악기 그룹 펼치기"),
    "折叠所有组": ("Collapse All Groups", "すべてのグループを折りたたむ", "모든 그룹 접기"),
    "展开所有组": ("Expand All Groups", "すべてのグループを展開", "모든 그룹 펼치기"),
    "乐器组 · {instrument}": ("Instrument Group · {instrument}", "楽器グループ · {instrument}", "악기 그룹 · {instrument}"),
    "{tracks} 轨 · {clips} 音块 · {notes} 音符": ("{tracks} tracks · {clips} clips · {notes} notes", "{tracks}トラック · {clips}クリップ · {notes}ノート", "트랙 {tracks}개 · 클립 {clips}개 · 음표 {notes}개"),
    "组摘要 · {instrument} · {count} 轨；双击或 Enter 展开，U 折叠/展开，M/S 控制整组": ("Group summary · {instrument} · {count} tracks; double-click or press Enter to expand, U folds/unfolds, M/S controls the group", "グループ概要 · {instrument} · {count}トラック。ダブルクリックまたはEnterで展開、Uで折りたたみ／展開、M/Sでグループ全体を操作", "그룹 요약 · {instrument} · 트랙 {count}개. 두 번 클릭하거나 Enter로 펼치고 U로 접기/펼치며 M/S로 그룹 전체를 제어합니다"),
    "适配宽度 W": ("Fit Width W", "幅に合わせる W", "너비 맞춤 W"),
    "显示整首歌曲并回到时间轴起点（W）": ("Show the full song and return to the timeline start (W)", "曲全体を表示してタイムライン先頭へ戻ります（W）", "전체 곡을 표시하고 타임라인 시작으로 돌아갑니다(W)"),
    "适配整首歌曲宽度": ("Fit Full Song Width", "曲全体を幅に合わせる", "전체 곡 너비 맞춤"),
    "适配轨道 H": ("Fit Tracks H", "トラックを合わせる H", "트랙 맞춤 H"),
    "让当前轨道尽量填满可用高度（H）": ("Fit the current tracks into the available height (H)", "現在のトラックを利用可能な高さに合わせます（H）", "현재 트랙을 사용 가능한 높이에 맞춥니다(H)"),
    "适配全部轨道高度": ("Fit All Track Heights", "すべてのトラック高さを合わせる", "모든 트랙 높이 맞춤"),
    "恢复标准布局": ("Restore Standard Layout", "標準レイアウトに戻す", "표준 레이아웃 복원"),
    "恢复标准轨头宽度、轨道高度和参考音频高度": ("Restore standard track-header width, track height, and reference-audio height", "トラックヘッダー幅、トラック高さ、参照オーディオ高さを標準に戻します", "트랙 헤더 너비, 트랙 높이, 참조 오디오 높이를 표준으로 복원합니다"),
}
for _source, (_english, _japanese, _korean) in _ARRANGEMENT_REFINEMENT_TRANSLATIONS.items():
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
    "全轨道分贝调整": ("All-track dB", "全トラックdB", "전체 트랙 dB"),
    "抬高/降低": ("Raise/lower", "上げる／下げる", "올리기/내리기"),
    "百分比": ("Percentage", "パーセント", "백분율"),
    "Clip 力度基数…": ("Clip Velocity Base…", "Clipベロシティ基数…", "Clip 벨로시티 기준값…"),
    "Clip 力度基数（分贝）": ("Clip Velocity Base (dB)", "Clipベロシティ基数（dB）", "Clip 벨로시티 기준값(dB)"),
    "已选择 {count} 个Clip": ("{count} Clips selected", "{count}個のClipを選択", "Clip {count}개 선택"),
    "修改所选Clip的可恢复力度基准，再重新应用各自的分贝比例；不会重置百分比或影响其他Clip。": (
        "Change the recoverable velocity baseline of the selected Clips, then reapply each dB percentage without resetting it or affecting other Clips.",
        "選択したClipの復元可能なベロシティ基準を変更し、各dB比率をリセットせず再適用します。他のClipには影響しません。",
        "선택한 Clip의 복원 가능한 벨로시티 기준값을 변경한 뒤 각 dB 비율을 초기화하지 않고 다시 적용하며 다른 Clip에는 영향을 주지 않습니다.",
    ),
    "力度（分贝）": ("Velocity (dB)", "ベロシティ（dB）", "벨로시티(dB)"),
    "请选择轨道或Clip": ("Select a track or Clip", "トラックまたはClipを選択", "트랙 또는 Clip을 선택하세요"),
    "混合": ("Mixed", "混在", "혼합"),
    "作用域：Clip · {name}": ("Scope: Clip · {name}", "範囲：Clip · {name}", "범위: Clip · {name}"),
    "作用域：已选择 {count} 个Clip": ("Scope: {count} Clips selected", "範囲：{count}個のClipを選択", "범위: Clip {count}개 선택"),
    "作用域：轨道 · {name}": ("Scope: Track · {name}", "範囲：トラック · {name}", "범위: 트랙 · {name}"),
    "作用域：已选择 {count} 条轨道": ("Scope: {count} tracks selected", "範囲：{count}トラックを選択", "범위: 트랙 {count}개 선택"),
    "{name} · {count} 音块 · {percent}%": ("{name} · {count} notes · {percent}%", "{name} · {count}ノート · {percent}%", "{name} · 음표 {count}개 · {percent}%"),
    "{name} · {percent}%": ("{name} · {percent}%", "{name} · {percent}%", "{name} · {percent}%"),
    "将所选轨道或Clip的分贝比例烘焙到每个音块；100%可按工程记录恢复。": (
        "Bake the selected track or Clip dB percentage into every note; 100% restores from project history.",
        "選択したトラックまたはClipのdB比率を各ノートへ反映し、100%でプロジェクト記録から復元します。",
        "선택한 트랙 또는 Clip의 dB 비율을 각 음표에 반영하며 100%에서 프로젝트 기록으로 복원합니다.",
    ),
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

_ARRANGEMENT_IMPORT_TRANSLATIONS = {
    "追加音轨": ("Append External Tracks", "外部トラックを追加", "외부 트랙 추가"),
    "从 MIDI 文件…": ("From MIDI File…", "MIDIファイルから…", "MIDI 파일에서…"),
    "从游戏曲谱…": ("From Game Score…", "ゲーム楽譜から…", "게임 악보에서…"),
    "选择要追加的 MIDI 文件": ("Select MIDI File to Append", "追加するMIDIファイルを選択", "추가할 MIDI 파일 선택"),
    "选择要追加的游戏曲谱": ("Select Game Score to Append", "追加するゲーム楽譜を選択", "추가할 게임 악보 선택"),
    "游戏曲谱 (*.bdo);;所有文件 (*.*)": ("Game Score (*.bdo);;All Files (*.*)", "ゲーム楽譜 (*.bdo);;すべてのファイル (*.*)", "게임 악보 (*.bdo);;모든 파일 (*.*)"),
    "当前播放头": ("Current Playhead", "現在の再生ヘッド", "현재 재생 헤드"),
    "工程开头": ("Project Start", "プロジェクト先頭", "프로젝트 시작"),
    "放置追加音轨": ("Place Appended Tracks", "追加トラックを配置", "추가 트랙 배치"),
    "选择导入内容的起始位置": ("Choose where the imported material starts", "読み込む素材の開始位置を選択", "가져온 콘텐츠의 시작 위치 선택"),
    "追加音轨失败": ("Could Not Append Tracks", "トラックを追加できませんでした", "트랙을 추가하지 못했습니다"),
    "无法追加 {file}：{error}": ("Could not append {file}: {error}", "{file}を追加できません：{error}", "{file}을(를) 추가할 수 없습니다: {error}"),
    " · 已按源文件实际时间保留，工程 BPM/拍号未改变": (" · Source timing preserved; project BPM/meter unchanged", "・元ファイルの実時間を保持し、プロジェクトのBPM/拍子は変更していません", " · 원본 파일의 실제 시간을 유지했으며 프로젝트 BPM/박자는 변경하지 않았습니다"),
    "已追加 {file} · {tracks} 轨 · {notes} 音符{timing_note}": ("Appended {file} · {tracks} tracks · {notes} notes{timing_note}", "{file}を追加・{tracks}トラック・{notes}ノート{timing_note}", "{file} 추가됨 · {tracks}트랙 · 음표 {notes}개{timing_note}"),
}

for _source, (
    _english,
    _japanese,
    _korean,
) in _ARRANGEMENT_IMPORT_TRANSLATIONS.items():
    EN[_source] = _english
    JA[_source] = _japanese
    KO[_source] = _korean

del _source, _english, _japanese, _korean

_ARRANGEMENT_CLIP_TRANSLATIONS = {
    "在此处创建片段": ("Create Clip Here", "ここにクリップを作成", "여기에 클립 만들기"),
    "片段左边界": ("Clip Start", "クリップ左端", "클립 왼쪽 경계"),
    "片段右边界": ("Clip End", "クリップ右端", "클립 오른쪽 경계"),
    "完成并关闭": ("Done and Close", "完了して閉じる", "완료하고 닫기"),
    "音符与片段边界已实时同步；关闭编辑器": (
        "Notes and clip boundaries are already synchronized; close the editor",
        "ノートとクリップ境界は同期済みです。エディターを閉じます",
        "음표와 클립 경계가 이미 동기화되었습니다. 편집기를 닫습니다",
    ),
    "片段已从混音台同步；请继续编辑。": (
        "The clip was synchronized from the mixer; you can continue editing.",
        "ミキサーからクリップを同期しました。編集を続けられます。",
        "믹서에서 클립을 동기화했습니다. 계속 편집할 수 있습니다.",
    ),
    "无法实时同步片段：{error}": (
        "Could not synchronize clip in real time: {error}",
        "クリップをリアルタイム同期できません：{error}",
        "클립을 실시간으로 동기화할 수 없습니다: {error}",
    ),
    "片段边界不能越过已有音符。": (
        "A clip boundary cannot cross an existing note.",
        "クリップ境界を既存ノートより内側へ移動できません。",
        "클립 경계는 기존 음표를 지나갈 수 없습니다.",
    ),
    "无法调整片段边界：{error}": (
        "Could not adjust clip boundary: {error}",
        "クリップ境界を調整できません：{error}",
        "클립 경계를 조정할 수 없습니다: {error}",
    ),
    "片段左边界固定；调整右边界只会扩展或收缩编辑区域，不会缩放音符。": (
        "The clip's left edge is fixed; adjusting the right edge only expands or contracts the edit region and never scales notes.",
        "クリップの左端は固定され、右端の調整では編集領域だけが伸縮し、ノートは拡大縮小されません。",
        "클립의 왼쪽 경계는 고정되며 오른쪽 경계를 조절하면 편집 영역만 늘거나 줄고 음표는 비례 조정되지 않습니다.",
    ),
    "粘贴内容超出当前片段边界；请先扩展右侧编辑区域或移动编辑光标。": (
        "The pasted notes exceed the current clip boundary; expand the right edit region or move the edit cursor first.",
        "貼り付けるノートが現在のクリップ境界を超えています。先に右側の編集領域を広げるか、編集カーソルを移動してください。",
        "붙여넣을 음표가 현재 클립 경계를 벗어납니다. 먼저 오른쪽 편집 영역을 확장하거나 편집 커서를 이동하세요.",
    ),
    "目标位置存在同音高重叠，已将整组音符移至右侧最近空位。": (
        "The target has overlapping notes at the same pitch; the complete group was moved to the nearest free position on the right.",
        "貼り付け先で同じピッチのノートが重なるため、グループ全体を右側の最も近い空き位置へ移動しました。",
        "대상 위치에 같은 음높이의 음표가 겹쳐 전체 그룹을 오른쪽의 가장 가까운 빈 위치로 이동했습니다.",
    ),
    "无法复制音符：选择内容过大或包含无效音符。": (
        "Could not copy notes: the selection is too large or contains invalid notes.",
        "ノートをコピーできません。選択内容が大きすぎるか、無効なノートが含まれています。",
        "음표를 복사할 수 없습니다. 선택 내용이 너무 크거나 잘못된 음표가 포함되어 있습니다.",
    ),
    "已保留粘贴音符的原始音高与奏法；其中部分内容不适用于目标乐器，请检查红色提示后再导出。": (
        "The pasted notes kept their original pitches and articulations; some are not valid for the target instrument, so review the red warnings before export.",
        "貼り付けたノートの元のピッチと奏法を保持しました。対象楽器に適さない内容があるため、書き出す前に赤い警告を確認してください。",
        "붙여넣은 음표의 원래 음높이와 주법을 유지했습니다. 일부는 대상 악기에 맞지 않으므로 내보내기 전에 빨간 경고를 확인하세요.",
    ),
    "片段左边界固定，请调整右边界。": (
        "The clip's left edge is fixed; adjust the right edge.",
        "クリップの左端は固定されています。右端を調整してください。",
        "클립의 왼쪽 경계는 고정됩니다. 오른쪽 경계를 조절하세요.",
    ),
    "调整后的片段不能与其他片段重叠。": (
        "A resized clip cannot overlap another clip.",
        "調整後のクリップを別のクリップと重ねることはできません。",
        "조절된 클립은 다른 클립과 겹칠 수 없습니다.",
    ),
    "无法编辑片段：{error}": ("Could not edit clip: {error}", "クリップを編集できません：{error}", "클립을 편집할 수 없습니다: {error}"),
    "片段编辑已应用": ("Clip edit applied", "クリップ編集を適用しました", "클립 편집을 적용했습니다"),
    "无法创建片段：{error}": ("Could not create clip: {error}", "クリップを作成できません：{error}", "클립을 만들 수 없습니다: {error}"),
    "导出标准 MIDI…": ("Export Standard MIDI…", "標準MIDIを書き出す…", "표준 MIDI 내보내기…"),
    "导出标准 MIDI": ("Export Standard MIDI", "標準MIDIを書き出す", "표준 MIDI 내보내기"),
    "未命名曲谱": ("Untitled Score", "名称未設定の楽譜", "제목 없는 악보"),
    "当前工程没有可导出的轨道": ("The project has no tracks to export", "書き出せるトラックがありません", "내보낼 트랙이 없습니다"),
    "导出 MIDI 失败": ("MIDI Export Failed", "MIDIの書き出しに失敗", "MIDI 내보내기 실패"),
    "无法导出 MIDI：{error}": ("Could not export MIDI: {error}", "MIDIを書き出せません：{error}", "MIDI를 내보낼 수 없습니다: {error}"),
    "已导出 {file} · {tracks} 轨": ("Exported {file} · {tracks} tracks", "{file}を書き出しました・{tracks}トラック", "{file} 내보냄 · {tracks}트랙"),
}

for _source, (
    _english,
    _japanese,
    _korean,
) in _ARRANGEMENT_CLIP_TRANSLATIONS.items():
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

_FILE_DROP_IMPORT_TRANSLATIONS = {
    "拖入文件失败": (
        "File Drop Failed",
        "ファイルのドロップに失敗しました",
        "파일 끌어놓기 실패",
    ),
    "一次只能拖入一个 MIDI 或游戏曲谱文件。": (
        "Drop only one MIDI or game-score file at a time.",
        "MIDIまたはゲーム楽譜ファイルは一度に1つだけドロップしてください。",
        "MIDI 또는 게임 악보 파일을 한 번에 하나만 끌어놓으세요.",
    ),
    "仅支持 MIDI 文件（.mid、.midi）和游戏曲谱（.bdo）。": (
        "Only MIDI files (.mid, .midi) and game scores (.bdo) are supported.",
        "MIDIファイル（.mid、.midi）とゲーム楽譜（.bdo）のみ対応しています。",
        "MIDI 파일(.mid, .midi)과 게임 악보(.bdo)만 지원합니다.",
    ),
    "导入文件": ("Import File", "ファイルを読み込む", "파일 가져오기"),
    "当前混音台已有内容。如何处理 {file}？": (
        "The mixer already contains material. How should {file} be handled?",
        "ミキサーには既に内容があります。{file}をどう処理しますか？",
        "믹서에 이미 내용이 있습니다. {file}을(를) 어떻게 처리할까요?",
    ),
    "保存当前工程后打开该文件，或将它追加到现有混音台。": (
        "Save the current project and open this file, or append it to the existing mixer.",
        "現在のプロジェクトを保存してこのファイルを開くか、既存のミキサーに追加します。",
        "현재 프로젝트를 저장하고 이 파일을 열거나 기존 믹서에 추가합니다.",
    ),
    "保存并打开": ("Save and Open", "保存して開く", "저장하고 열기"),
    "追加": ("Append", "追加", "추가"),
    "关闭": ("Close", "閉じる", "닫기"),
    "保存当前工程失败": (
        "Could Not Save Current Project",
        "現在のプロジェクトを保存できませんでした",
        "현재 프로젝트 저장 실패",
    ),
    "当前工程未能安全保存，已取消打开 {file}。": (
        "The current project could not be saved safely, so opening {file} was cancelled.",
        "現在のプロジェクトを安全に保存できなかったため、{file}を開く操作を取り消しました。",
        "현재 프로젝트를 안전하게 저장하지 못해 {file} 열기를 취소했습니다.",
    ),
    "暂时无法导入文件": (
        "File Import Is Temporarily Unavailable",
        "現在ファイルを読み込めません",
        "현재 파일을 가져올 수 없음",
    ),
    "当前有导出或分析任务正在运行。请等待任务完成后再拖入文件。": (
        "An export or analysis task is running. Wait for it to finish before dropping a file.",
        "書き出しまたは解析を実行中です。完了してからファイルをドロップしてください。",
        "내보내기 또는 분석 작업이 실행 중입니다. 완료된 후 파일을 끌어놓으세요.",
    ),
}

for _source, (
    _english,
    _japanese,
    _korean,
) in _FILE_DROP_IMPORT_TRANSLATIONS.items():
    EN[_source] = _english
    JA[_source] = _japanese
    KO[_source] = _korean

del _source, _english, _japanese, _korean

_DAW_WORKFLOW_TRANSLATIONS = {
    "F1 快捷键；W/H 适配视图；U 折叠/展开组；Ctrl+D 复制片段；Ctrl+E 在播放头切分；Enter 编辑焦点；方向键导航": (
        "F1 shortcuts; W/H fit the view; U folds/unfolds groups; Ctrl+D duplicates a clip; Ctrl+E splits at the playhead; Enter edits the focus; arrows navigate",
        "F1 ショートカット。W/Hで表示を合わせ、Uでグループを折りたたみ／展開、Ctrl+Dでクリップ複製、Ctrl+Eで再生ヘッド位置を分割、Enterでフォーカスを編集、矢印キーで移動",
        "F1 단축키, W/H 보기 맞춤, U 그룹 접기/펼치기, Ctrl+D 클립 복제, Ctrl+E 재생 헤드에서 분할, Enter 포커스 편집, 화살표 탐색",
    ),
    "Ctrl+C 复制片段 · Ctrl+V 粘贴到播放头 · Ctrl+D 向后复制\nCtrl+E 在播放头切分 · Delete 删除 · Enter 打开编辑器\nCtrl+L 重复 · Ctrl+J 合并 · Ctrl+Shift+J 收紧右边界\nF2 重命名 · Ctrl+Shift+D 复制轨道\n↑/↓ 选择轨道 · Home/End 首尾轨道 · M 静音 · S 独奏\n←/→ 移动播放头或音块 · Shift 扩展范围/粗调\nCtrl+←/→ 上/下一个音块或标记边界 · Alt+←/→ 调整音量\nZ 缩放到范围/音块 · X 恢复视图 · F 轨道效果\nW 适配整首宽度 · H 适配轨道高度 · U 折叠/展开当前组\nCtrl+滚轮缩放 · Shift+滚轮横向滚动 · Alt 临时取消吸附": (
        "Ctrl+C Copy clip · Ctrl+V Paste at playhead · Ctrl+D Duplicate forward\nCtrl+E Split at playhead · Delete Remove · Enter Open editor\nCtrl+L Repeat · Ctrl+J Consolidate · Ctrl+Shift+J Tighten right edge\nF2 Rename · Ctrl+Shift+D Duplicate track\n↑/↓ Select track · Home/End First/last track · M Mute · S Solo\n←/→ Move playhead or clip · Shift Extend range/coarse step\nCtrl+←/→ Previous/next clip or marker boundary · Alt+←/→ Adjust volume\nZ Fit range/clip · X Restore view · F Track effects\nW Fit full-song width · H Fit track heights · U Fold/unfold current group\nCtrl+wheel Zoom · Shift+wheel Horizontal scroll · Alt Temporarily bypass snap",
        "Ctrl+C クリップをコピー · Ctrl+V 再生ヘッドへペースト · Ctrl+D 後方へ複製\nCtrl+E 再生ヘッド位置で分割 · Delete 削除 · Enter エディターを開く\nCtrl+L 反復 · Ctrl+J 結合 · Ctrl+Shift+J 右端を詰める\nF2 名前変更 · Ctrl+Shift+D トラック複製\n↑/↓ トラック選択 · Home/End 先頭/末尾 · M ミュート · S ソロ\n←/→ 再生ヘッドまたはクリップ移動 · Shift 範囲拡張／粗調整\nCtrl+←/→ 前後のクリップまたはマーカー境界 · Alt+←/→ 音量調整\nZ 範囲／クリップに合わせる · X 表示を戻す · F トラックエフェクト\nW 曲全体を幅に合わせる · H トラック高さを合わせる · U 現在のグループを折りたたみ／展開\nCtrl+ホイール ズーム · Shift+ホイール 横スクロール · Alt 一時的にスナップ解除",
        "Ctrl+C 클립 복사 · Ctrl+V 재생 헤드에 붙여넣기 · Ctrl+D 뒤로 복제\nCtrl+E 재생 헤드에서 분할 · Delete 삭제 · Enter 편집기 열기\nCtrl+L 반복 · Ctrl+J 합치기 · Ctrl+Shift+J 오른쪽 경계 조이기\nF2 이름 변경 · Ctrl+Shift+D 트랙 복제\n↑/↓ 트랙 선택 · Home/End 처음/마지막 트랙 · M 음소거 · S 솔로\n←/→ 재생 헤드 또는 클립 이동 · Shift 범위 확장/거친 조절\nCtrl+←/→ 이전/다음 클립 또는 마커 경계 · Alt+←/→ 음량 조절\nZ 범위/클립 맞춤 · X 보기 복원 · F 트랙 효과\nW 전체 곡 너비 맞춤 · H 트랙 높이 맞춤 · U 현재 그룹 접기/펼치기\nCtrl+휠 확대/축소 · Shift+휠 가로 스크롤 · Alt 임시 스냅 해제",
    ),
    "打开音符编辑器": (
        "Open Note Editor", "ノートエディターを開く", "음표 편집기 열기",
    ),
    "复制音块": ("Duplicate Clip", "クリップを複製", "클립 복제"),
    "在播放头切分": (
        "Split at Playhead", "再生ヘッド位置で分割", "재생 헤드에서 분할",
    ),
    "重命名音块…": (
        "Rename Clip…", "クリップ名を変更…", "클립 이름 바꾸기…",
    ),
    "音块颜色…": (
        "Clip Color…", "クリップの色…", "클립 색상…",
    ),
    "音块": ("Clip", "クリップ", "클립"),
    "时间轴快捷键": (
        "Timeline Shortcuts", "タイムラインのショートカット", "타임라인 단축키",
    ),
    "F1 快捷键；Ctrl+D 复制片段；Ctrl+E 在播放头切分；Enter 编辑；M 静音；S 独奏；上下键选择轨道": (
        "F1 shortcuts; Ctrl+D duplicate clip; Ctrl+E split at playhead; Enter edit; M mute; S solo; Use Up/Down to select a track",
        "F1 ショートカット；Ctrl+D クリップ複製；Ctrl+E 再生ヘッドで分割；Enter 編集；M ミュート；S ソロ；上下キーでトラック選択",
        "F1 단축키; Ctrl+D 클립 복제; Ctrl+E 재생 헤드에서 분할; Enter 편집; M 음소거; S 솔로; 위/아래 키로 트랙 선택",
    ),
    "时间轴快捷键…": (
        "Timeline Shortcuts…", "タイムラインのショートカット…", "타임라인 단축키…",
    ),
    "Ctrl+C 复制片段 · Ctrl+V 粘贴到播放头 · Ctrl+D 向后复制\nCtrl+E 在播放头切分 · Delete 删除 · Enter 打开编辑器\nCtrl+L 重复 · Ctrl+J 合并 · Ctrl+Shift+J 收紧右边界\nF2 重命名 · Ctrl+Shift+D 复制轨道\n↑/↓ 选择轨道 · Home/End 首尾轨道 · M 静音 · S 独奏\nF 轨道效果 · ←/→ 调整音量 · Shift 每次调整 5\nCtrl+滚轮缩放 · Shift+滚轮横向滚动 · Alt 临时取消吸附": (
        "Ctrl+C Copy clip · Ctrl+V Paste at playhead · Ctrl+D Duplicate forward\nCtrl+E Split at playhead · Delete Remove · Enter Open editor\nCtrl+L Repeat · Ctrl+J Consolidate · Ctrl+Shift+J Tighten right edge\nF2 Rename · Ctrl+Shift+D Duplicate track\n↑/↓ Select track · Home/End First/last track · M Mute · S Solo\nF Track effects · ←/→ Adjust volume · Shift changes by 5\nCtrl+wheel Zoom · Shift+wheel Horizontal scroll · Alt temporarily bypass snap",
        "Ctrl+C クリップをコピー · Ctrl+V 再生ヘッドへペースト · Ctrl+D 後方へ複製\nCtrl+E 再生ヘッド位置で分割 · Delete 削除 · Enter エディターを開く\nCtrl+L 反復 · Ctrl+J 統合 · Ctrl+Shift+J 右端を詰める\nF2 名前変更 · Ctrl+Shift+D トラックを複製\n↑/↓ トラック選択 · Home/End 先頭/末尾 · M ミュート · S ソロ\nF トラックエフェクト · ←/→ 音量調整 · Shift で5ずつ変更\nCtrl+ホイール ズーム · Shift+ホイール 横スクロール · Alt 一時的にスナップ解除",
        "Ctrl+C 클립 복사 · Ctrl+V 재생 헤드에 붙여넣기 · Ctrl+D 뒤로 복제\nCtrl+E 재생 헤드에서 분할 · Delete 삭제 · Enter 편집기 열기\nCtrl+L 반복 · Ctrl+J 통합 · Ctrl+Shift+J 오른쪽 경계 조이기\nF2 이름 변경 · Ctrl+Shift+D 트랙 복제\n↑/↓ 트랙 선택 · Home/End 처음/마지막 트랙 · M 음소거 · S 솔로\nF 트랙 효과 · ←/→ 볼륨 조절 · Shift는 5씩 변경\nCtrl+휠 확대/축소 · Shift+휠 가로 스크롤 · Alt 임시 스냅 해제",
    ),
    "Ctrl+C 复制片段 · Ctrl+V 粘贴到播放头 · Ctrl+D 向后复制\nCtrl+E 在播放头切分 · Delete 删除 · Enter 打开编辑器\nCtrl+L 重复 · Ctrl+J 合并 · Ctrl+Shift+J 收紧右边界\n↑/↓ 选择轨道 · Home/End 首尾轨道 · M 静音 · S 独奏\nF 轨道效果 · ←/→ 调整音量 · Shift 每次调整 5\nCtrl+滚轮缩放 · Shift+滚轮横向滚动 · Alt 临时取消吸附": (
        "Ctrl+C Copy clip · Ctrl+V Paste at playhead · Ctrl+D Duplicate forward\nCtrl+E Split at playhead · Delete Remove · Enter Open editor\nCtrl+L Repeat · Ctrl+J Consolidate · Ctrl+Shift+J Tighten right edge\n↑/↓ Select track · Home/End First/last track · M Mute · S Solo\nF Track effects · ←/→ Adjust volume · Shift changes by 5\nCtrl+wheel Zoom · Shift+wheel Horizontal scroll · Alt temporarily bypass snap",
        "Ctrl+C クリップをコピー · Ctrl+V 再生ヘッドへペースト · Ctrl+D 後方へ複製\nCtrl+E 再生ヘッド位置で分割 · Delete 削除 · Enter エディターを開く\nCtrl+L 反復 · Ctrl+J 結合 · Ctrl+Shift+J 右端を詰める\n↑/↓ トラック選択 · Home/End 先頭/末尾 · M ミュート · S ソロ\nF トラックエフェクト · ←/→ 音量調整 · Shift は5ずつ変更\nCtrl+ホイール ズーム · Shift+ホイール 横スクロール · Alt 一時的にスナップ解除",
        "Ctrl+C 클립 복사 · Ctrl+V 재생 헤드에 붙여넣기 · Ctrl+D 뒤로 복제\nCtrl+E 재생 헤드에서 분할 · Delete 삭제 · Enter 편집기 열기\nCtrl+L 반복 · Ctrl+J 합치기 · Ctrl+Shift+J 오른쪽 경계 조이기\n↑/↓ 트랙 선택 · Home/End 처음/마지막 트랙 · M 음소거 · S 솔로\nF 트랙 효과 · ←/→ 음량 조절 · Shift는 5씩 변경\nCtrl+휠 확대/축소 · Shift+휠 가로 스크롤 · Alt 일시적으로 스냅 해제",
    ),
    "重命名轨道…": (
        "Rename Track…", "トラック名を変更…", "트랙 이름 바꾸기…",
    ),
    "复制轨道": ("Duplicate Track", "トラックを複製", "트랙 복제"),
    "轨道颜色…": ("Track Color…", "トラックの色…", "트랙 색상…"),
    "移动/调整音块": (
        "Move/Resize Clips", "クリップの移動／サイズ変更", "클립 이동/크기 조절",
    ),
    "移动/调整音块：拖动主体移动，拖动右边界改变编辑区域": (
        "Move/resize clips: drag the body to move; drag the right edge to change the edit region",
        "クリップの移動／サイズ変更：本体をドラッグして移動し、右端をドラッグして編集領域を変更します",
        "클립 이동/크기 조절: 본문을 끌어 이동하고 오른쪽 경계를 끌어 편집 영역을 바꿉니다",
    ),
    "小节与拍位置；左边界锁定，右边界只改变编辑区域": (
        "Bar and beat positions; the left edge is locked and the right edge changes only the edit region",
        "小節と拍の位置。左端は固定され、右端は編集領域だけを変更します",
        "마디와 박 위치입니다. 왼쪽 경계는 잠겨 있고 오른쪽 경계는 편집 영역만 바꿉니다",
    ),
    "范围 {start} → {end} · 左侧锁定": (
        "Range {start} → {end} · Left locked",
        "範囲 {start} → {end} · 左端固定",
        "범위 {start} → {end} · 왼쪽 잠김",
    ),
    "🔒 {start} → {end}": (
        "🔒 {start} → {end}", "🔒 {start} → {end}", "🔒 {start} → {end}",
    ),
    "左边界 {left:.1f} ms 已锁定；右边界 {right:.1f} ms 只改变编辑区域": (
        "Left edge {left:.1f} ms is locked; right edge {right:.1f} ms changes only the edit region",
        "左端 {left:.1f} ms は固定されています。右端 {right:.1f} ms は編集領域だけを変更します",
        "왼쪽 경계 {left:.1f}ms는 잠겨 있습니다. 오른쪽 경계 {right:.1f}ms는 편집 영역만 바꿉니다",
    ),
    "音块已向后复制": (
        "Clip duplicated forward", "クリップを後方へ複製しました", "클립을 뒤로 복제했습니다",
    ),
    "无法复制音块：{error}": (
        "Could not duplicate clip: {error}",
        "クリップを複製できません：{error}",
        "클립을 복제할 수 없습니다: {error}",
    ),
    "重命名音块": ("Rename Clip", "クリップ名を変更", "클립 이름 바꾸기"),
    "音块名称：": ("Clip name:", "クリップ名：", "클립 이름:"),
    "无法重命名音块：{error}": (
        "Could not rename clip: {error}",
        "クリップ名を変更できません：{error}",
        "클립 이름을 바꿀 수 없습니다: {error}",
    ),
    "音块颜色": ("Clip Color", "クリップの色", "클립 색상"),
    "重复音块…": ("Repeat Clip…", "クリップを反復…", "클립 반복…"),
    "收紧右边界到最后音符": (
        "Tighten Right Edge to Last Note", "右端を最後のノートまで詰める", "오른쪽 경계를 마지막 음표까지 조이기",
    ),
    "合并所选音块": (
        "Consolidate Selected Clips", "選択クリップを結合", "선택한 클립 합치기",
    ),
    "重复音块": ("Repeat Clip", "クリップを反復", "클립 반복"),
    "追加副本数量：": (
        "Additional copies:", "追加するコピー数：", "추가 복사본 수:",
    ),
    "无法重复音块：{error}": (
        "Could not repeat clip: {error}", "クリップを反復できません：{error}", "클립을 반복할 수 없습니다: {error}",
    ),
    "已追加 {count} 个音块副本": (
        "Added {count} clip copies", "クリップのコピーを{count}個追加しました", "클립 복사본 {count}개를 추가했습니다",
    ),
    "无法收紧音块边界：{error}": (
        "Could not tighten clip edge: {error}", "クリップ端を詰められません：{error}", "클립 경계를 조일 수 없습니다: {error}",
    ),
    "音块右边界已收紧": (
        "Clip right edge tightened", "クリップの右端を詰めました", "클립 오른쪽 경계를 조였습니다",
    ),
    "只能合并同一轨道中的音块": (
        "Only clips on the same track can be consolidated", "同じトラックのクリップだけを結合できます", "같은 트랙의 클립만 합칠 수 있습니다",
    ),
    "无法合并音块：{error}": (
        "Could not consolidate clips: {error}", "クリップを結合できません：{error}", "클립을 합칠 수 없습니다: {error}",
    ),
    "所选音块已合并": (
        "Selected clips consolidated", "選択したクリップを結合しました", "선택한 클립을 합쳤습니다",
    ),
    "{name} · {count} 音符": (
        "{name} · {count} notes", "{name} · {count}ノート", "{name} · 음표 {count}개",
    ),
    "{name} 副本": ("{name} copy", "{name} のコピー", "{name} 복사본"),
    "轨道已复制": ("Track duplicated", "トラックを複製しました", "트랙을 복제했습니다"),
    "重命名轨道": ("Rename Track", "トラック名を変更", "트랙 이름 바꾸기"),
    "轨道名称：": ("Track name:", "トラック名：", "트랙 이름:"),
    "轨道已重命名": ("Track renamed", "トラック名を変更しました", "트랙 이름을 바꿨습니다"),
    "轨道颜色": ("Track Color", "トラックの色", "트랙 색상"),
    "轨道颜色已更新": (
        "Track color updated", "トラックの色を更新しました", "트랙 색상을 업데이트했습니다",
    ),
}

for _source, (_english, _japanese, _korean) in _DAW_WORKFLOW_TRANSLATIONS.items():
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
