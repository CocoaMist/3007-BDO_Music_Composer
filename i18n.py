"""Lightweight runtime localization for the PySide desktop interface."""

from __future__ import annotations

from datetime import datetime
from weakref import WeakKeyDictionary

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QSpinBox,
    QWidget,
)


LANGUAGES = (
    ("zh_CN", "简体中文"),
    ("en_US", "English"),
    ("ja_JP", "日本語"),
    ("ko_KR", "한국어"),
)
AUTO_LANGUAGE = ("auto", "自动（根据时区）")
LANGUAGE_CHOICES = (AUTO_LANGUAGE, *LANGUAGES)


def detect_language_from_timezone(
    timezone_name: str | None = None,
    utc_offset_minutes: int | None = None,
) -> str:
    """Map the local system timezone to the closest supported UI language."""
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
    # UTC+8 is a useful fallback for Windows installations that expose only a
    # generic abbreviation. UTC+9 remains English unless Japan/Korea is named.
    return "zh_CN" if utc_offset_minutes == 8 * 60 else "en_US"


def resolve_language(language: str) -> str:
    return detect_language_from_timezone() if language == "auto" else language


EN = {
    "设置": "Settings", "致谢": "Credits", "转换": "Export", "时间轴": "Timeline",
    "导入 MIDI": "Import MIDI", "打开工程": "Open Project", "全局优化": "Optimize All",
    "播放": "Play", "暂停": "Pause", "继续": "Resume", "停止": "Stop",
    "新建轨道": "New Track", "删除轨道": "Delete Track", "清除 Solo": "Clear Solo",
    "取消静音": "Unmute All", "等待 MIDI": "Waiting for MIDI", "未导入 MIDI": "No MIDI imported",
    "曲谱名": "Score name", "就绪": "Ready", "音符属性": "Note Properties",
    "音高": "Pitch", "开始 ms": "Start ms", "时值 ms": "Duration ms", "力度": "Velocity",
    "奏法": "Articulation", "色板": "Palette", "吸附": "Snap", "量化": "Quantize",
    "缩放": "Zoom", "撤销": "Undo", "重做": "Redo", "删除": "Delete",
    "优化此轨": "Optimize Track", "应用": "Apply", "确定": "OK", "取消": "Cancel",
    "关闭": "Close", "普通": "Normal", "延音": "Sustain", "弱音": "Mute",
    "泛音": "Harmonic", "滑音": "Glissando", "三连音": "Triplet",
    "向上滑动": "Slide Up", "滑弦下降": "Slide Down", "滑音上升": "Rising Glissando",
    "剪切": "Cut", "标签": "Accent Tag", "颤音小调": "Minor Trill",
    "大调和弦": "Major Chord", "和弦小调": "Minor Chord", "拍弦": "Slap",
    "基础导出": "Basic Export", "写入角色名": "Character Name", "使用 MIDI": "Use MIDI",
    "BPM 覆盖": "BPM Override", "移调": "Transpose", " 半音": " semitones",
    "游戏编辑权限": "In-game Edit Permission", "从游戏曲谱读取": "Load from Game Score",
    "MIDI 解析": "MIDI Parsing", "读取并展开 MIDI sustain 踏板": "Read and expand MIDI sustain pedal",
    "忽略中途 tempo 变化，按主 BPM 拉平": "Ignore tempo changes and flatten to the main BPM",
    "力度处理": "Velocity Processing", "分层": "Layered", "阶梯": "Stepped",
    "重映射": "Rescale", "抬底": "Raise Floor", "禁用": "Off",
    "底": "Base", "步长": "Step", "阶梯参数": "Step Parameters", "最小": "Minimum",
    "最大": "Maximum", "重映射范围": "Rescale Range", "抬底值": "Floor Value",
    "MIDI 效果": "MIDI Effects", "混响": "Reverb", "延迟": "Delay",
    "合唱反馈": "Chorus Feedback", "深度": "Depth", "频率": "Frequency",
    "保存设置": "Save Settings", "界面语言": "Interface Language",
    "优化等级": "Optimization Level", "曲风": "Style", "歌词表达": "Lyric Expression",
    "游戏安全优化": "Game-safe Optimization", "自动识别曲风": "Auto-detect Style",
    "分析奏法": "Analyze Articulations", "轻微自然化": "Light Humanization",
    "声音效果": "Sound Effects", "修复音块": "Repair Notes", "平衡力度": "Balance Velocity",
    "乐理分析（保守）": "Music Theory (Conservative)", "柔性对齐": "Soft Quantize",
    "应用游戏安全优化": "Apply Game-safe Optimization", "详细说明 ▸": "Details ▸",
    "详细说明 ▾": "Details ▾", "单轨优化": "Track Optimization", "全局 MIDI 优化": "Global MIDI Optimization",
    "转换检查": "Export Check", "复制报告": "Copy Report", "轨道 FX": "Track FX",
    "默认": "Default", "玛勒尼斯音源": "Marnian Source", "单声道（Basic）": "Mono (Basic)",
    "双声（Stereo）": "Stereo", "增强（Super）": "Super", "超级增强（Super Octave）": "Super Octave",
    "感谢，让音乐工具成为可能": "Thanks for Making This Music Tool Possible",
    "项目组成": "Project Makeup", "致谢名单": "Credits", "复制致谢名单": "Copy Credits",
    "OPEN SOURCE  ·  COMMUNITY": "OPEN SOURCE  ·  COMMUNITY",
    "新建轨道": "New Track", "选择新轨道的 BDO 乐器": "Choose a BDO instrument",
    "更换乐器": "Change Instrument", "编辑音符…": "Edit Notes…", "优化此轨道": "Optimize This Track",
    "所有文件 (*.*)": "All Files (*.*)", "MIDI 文件 (*.mid *.midi)": "MIDI Files (*.mid *.midi)",
}


JA = {
    "设置": "設定", "致谢": "クレジット", "转换": "書き出し", "时间轴": "タイムライン",
    "导入 MIDI": "MIDIを読み込む", "打开工程": "プロジェクトを開く", "全局优化": "全体を最適化",
    "播放": "再生", "暂停": "一時停止", "继续": "再開", "停止": "停止",
    "新建轨道": "トラックを追加", "删除轨道": "トラックを削除", "清除 Solo": "Soloを解除",
    "取消静音": "ミュートを解除", "等待 MIDI": "MIDIを待機中", "未导入 MIDI": "MIDI未読み込み",
    "曲谱名": "楽譜名", "就绪": "準備完了", "音符属性": "ノート属性",
    "音高": "音高", "开始 ms": "開始 ms", "时值 ms": "長さ ms", "力度": "ベロシティ",
    "奏法": "奏法", "色板": "パレット", "吸附": "スナップ", "量化": "クオンタイズ",
    "缩放": "ズーム", "撤销": "元に戻す", "重做": "やり直す", "删除": "削除",
    "优化此轨": "このトラックを最適化", "应用": "適用", "确定": "OK", "取消": "キャンセル",
    "关闭": "閉じる", "普通": "通常", "延音": "サステイン", "弱音": "ミュート",
    "泛音": "ハーモニクス", "滑音": "グリッサンド", "三连音": "三連符",
    "向上滑动": "スライドアップ", "滑弦下降": "スライドダウン", "滑音上升": "上昇グリッサンド",
    "剪切": "カット", "标签": "アクセント", "颤音小调": "短2度トリル",
    "大调和弦": "メジャーコード", "和弦小调": "マイナーコード", "拍弦": "スラップ",
    "基础导出": "基本書き出し", "写入角色名": "キャラクター名", "使用 MIDI": "MIDIを使用",
    "BPM 覆盖": "BPM上書き", "移调": "トランスポーズ", " 半音": " 半音",
    "游戏编辑权限": "ゲーム内編集権限", "从游戏曲谱读取": "ゲーム楽譜から読み込む",
    "MIDI 解析": "MIDI解析", "读取并展开 MIDI sustain 踏板": "MIDIサステインペダルを読み込んで展開",
    "忽略中途 tempo 变化，按主 BPM 拉平": "途中のテンポ変更を無視して主BPMに統一",
    "力度处理": "ベロシティ処理", "分层": "レイヤー", "阶梯": "ステップ",
    "重映射": "再マッピング", "抬底": "下限を上げる", "禁用": "オフ",
    "底": "基準", "步长": "刻み", "阶梯参数": "ステップ設定", "最小": "最小",
    "最大": "最大", "重映射范围": "再マッピング範囲", "抬底值": "下限値",
    "MIDI 效果": "MIDIエフェクト", "混响": "リバーブ", "延迟": "ディレイ",
    "合唱反馈": "コーラス・フィードバック", "深度": "深さ", "频率": "周波数",
    "保存设置": "設定を保存", "界面语言": "表示言語",
    "优化等级": "最適化レベル", "曲风": "スタイル", "歌词表达": "歌詞表現",
    "游戏安全优化": "ゲーム安全最適化", "自动识别曲风": "スタイルを自動判定",
    "分析奏法": "奏法を分析", "轻微自然化": "軽いヒューマナイズ", "声音效果": "サウンドエフェクト",
    "修复音块": "ノートを修復", "平衡力度": "ベロシティを調整", "乐理分析（保守）": "楽理分析（保守的）",
    "柔性对齐": "ソフトクオンタイズ", "应用游戏安全优化": "ゲーム安全最適化を適用",
    "详细说明 ▸": "詳細 ▸", "详细说明 ▾": "詳細 ▾", "单轨优化": "トラック最適化",
    "全局 MIDI 优化": "MIDI全体最適化", "转换检查": "書き出しチェック", "复制报告": "レポートをコピー",
    "轨道 FX": "トラックFX", "默认": "デフォルト", "玛勒尼斯音源": "マルニス音源",
    "单声道（Basic）": "モノ（Basic）", "双声（Stereo）": "ステレオ", "增强（Super）": "Super",
    "超级增强（Super Octave）": "Super Octave", "感谢，让音乐工具成为可能": "この音楽ツールを支えてくださった皆様へ",
    "项目组成": "プロジェクト構成", "致谢名单": "クレジット", "复制致谢名单": "クレジットをコピー",
    "选择新轨道的 BDO 乐器": "BDO楽器を選択", "更换乐器": "楽器を変更",
    "编辑音符…": "ノートを編集…", "优化此轨道": "このトラックを最適化",
}


KO = {
    "设置": "설정", "致谢": "크레딧", "转换": "내보내기", "时间轴": "타임라인",
    "导入 MIDI": "MIDI 가져오기", "打开工程": "프로젝트 열기", "全局优化": "전체 최적화",
    "播放": "재생", "暂停": "일시정지", "继续": "계속", "停止": "정지",
    "新建轨道": "트랙 추가", "删除轨道": "트랙 삭제", "清除 Solo": "Solo 해제",
    "取消静音": "음소거 해제", "等待 MIDI": "MIDI 대기 중", "未导入 MIDI": "MIDI 없음",
    "曲谱名": "악보 이름", "就绪": "준비", "音符属性": "노트 속성",
    "音高": "음높이", "开始 ms": "시작 ms", "时值 ms": "길이 ms", "力度": "벨로시티",
    "奏法": "주법", "色板": "팔레트", "吸附": "스냅", "量化": "퀀타이즈",
    "缩放": "확대/축소", "撤销": "실행 취소", "重做": "다시 실행", "删除": "삭제",
    "优化此轨": "이 트랙 최적화", "应用": "적용", "确定": "확인", "取消": "취소",
    "关闭": "닫기", "普通": "일반", "延音": "서스테인", "弱音": "뮤트",
    "泛音": "하모닉스", "滑音": "글리산도", "三连音": "셋잇단음표",
    "向上滑动": "슬라이드 업", "滑弦下降": "슬라이드 다운", "滑音上升": "상승 글리산도",
    "剪切": "컷", "标签": "악센트", "颤音小调": "단2도 트릴",
    "大调和弦": "메이저 코드", "和弦小调": "마이너 코드", "拍弦": "슬랩",
    "基础导出": "기본 내보내기", "写入角色名": "캐릭터 이름", "使用 MIDI": "MIDI 사용",
    "BPM 覆盖": "BPM 덮어쓰기", "移调": "조옮김", " 半音": " 반음",
    "游戏编辑权限": "게임 편집 권한", "从游戏曲谱读取": "게임 악보에서 읽기",
    "MIDI 解析": "MIDI 분석", "读取并展开 MIDI sustain 踏板": "MIDI 서스테인 페달 읽기 및 펼치기",
    "忽略中途 tempo 变化，按主 BPM 拉平": "중간 템포 변경을 무시하고 주 BPM으로 통일",
    "力度处理": "벨로시티 처리", "分层": "레이어", "阶梯": "스텝",
    "重映射": "재매핑", "抬底": "하한 올리기", "禁用": "끔",
    "底": "기준", "步长": "간격", "阶梯参数": "스텝 설정", "最小": "최소",
    "最大": "최대", "重映射范围": "재매핑 범위", "抬底值": "하한값",
    "MIDI 效果": "MIDI 효과", "混响": "리버브", "延迟": "딜레이",
    "合唱反馈": "코러스 피드백", "深度": "깊이", "频率": "주파수",
    "保存设置": "설정 저장", "界面语言": "인터페이스 언어",
    "优化等级": "최적화 수준", "曲风": "스타일", "歌词表达": "가사 표현",
    "游戏安全优化": "게임 안전 최적화", "自动识别曲风": "스타일 자동 감지",
    "分析奏法": "주법 분석", "轻微自然化": "가벼운 휴머니즈", "声音效果": "사운드 효과",
    "修复音块": "노트 복구", "平衡力度": "벨로시티 균형", "乐理分析（保守）": "음악 이론 분석(보수적)",
    "柔性对齐": "소프트 퀀타이즈", "应用游戏安全优化": "게임 안전 최적화 적용",
    "详细说明 ▸": "상세 ▸", "详细说明 ▾": "상세 ▾", "单轨优化": "트랙 최적화",
    "全局 MIDI 优化": "전체 MIDI 최적화", "转换检查": "내보내기 검사", "复制报告": "보고서 복사",
    "轨道 FX": "트랙 FX", "默认": "기본값", "玛勒尼斯音源": "마르니안 음원",
    "单声道（Basic）": "모노(Basic)", "双声（Stereo）": "스테레오", "增强（Super）": "Super",
    "超级增强（Super Octave）": "Super Octave", "感谢，让音乐工具成为可能": "이 음악 도구를 가능하게 해주신 분들께",
    "项目组成": "프로젝트 구성", "致谢名单": "크레딧", "复制致谢名单": "크레딧 복사",
    "选择新轨道的 BDO 乐器": "BDO 악기 선택", "更换乐器": "악기 변경",
    "编辑音符…": "노트 편집…", "优化此轨道": "이 트랙 최적화",
}

EN.update({
    "自动（根据时区）": "Automatic (by Time Zone)",
    "选择目录": "Choose Folder", "本地音源目录": "Local Audio Folder", "选择音源包": "Choose Sample Pack",
    "本地音源包": "Local Sample Pack", "选择本地音源目录": "Choose Local Audio Folder",
    "选择本地音源包": "Choose Local Sample Pack", "音源包不可用": "Sample Pack Unavailable",
    "本地音源": "Local Audio Source", "音源路径不可用": "Audio Source Path Unavailable",
    "导出规则、MIDI 解析、力度策略与游戏效果。设置只在下次导出时生效。": "Export rules, MIDI parsing, velocity strategy, and in-game effects. Changes apply to the next export.",
    "角色名会写入乐谱；BPM 与移调会在导出时应用。": "The character name is stored in the score; BPM and transpose are applied during export.",
    "与 midi-to-bdo 相同：选择一份游戏内保存的单音符曲谱，读取角色名和 Owner ID。": "Choose a one-note score saved by the game to read its character name and Owner ID.",
    "这两项会影响 MIDI 读入方式；修改后会重新载入当前文件。": "These options affect MIDI parsing; changing them reloads the current file.",
    "选择一种输出力度策略；下方仅显示当前策略需要的参数。": "Choose an output velocity strategy; only its relevant parameters are shown.",
    "数值范围为 0–127；设为 0 即不写入对应效果。": "Values range from 0–127; zero disables the corresponding effect.",
    "轨道 FX 中的奏法会写入支持的 BDO 乐器。": "Track FX articulations are written to supported BDO instruments.",
    "选择轨道查看详情。右键可修复和优化轨道或更换乐器；FX 可设置支持乐器的 BDO 奏法。": "Select a track for details. Right-click to optimize or change its instrument; FX configures supported BDO articulations.",
    "导入 MIDI 后显示轨道与音符时间轴": "Import a MIDI file to display tracks and notes",
    "打开输出目录": "Open Output Folder", "无法原声试听": "Preview Unavailable",
    "读取全曲乐理与配器上下文，但只写入当前轨道。": "Analyze full-song theory and orchestration context, but modify only the current track.",
    "分析全部轨道；静音和独奏不改变作用域，可在下方选择允许写入的轨道。": "Analyze every track; Mute and Solo do not change scope. Select writable tracks below.",
})
EN.update({
    "优化算法": "Optimization Algorithm", "算法包目录": "Algorithm Packages", "刷新": "Refresh",
    "优化强度": "Optimization Intensity", "保守": "Conservative", "均衡": "Balanced", "深入": "Deep",
    "选择算法和强度，然后分析优化。": "Choose an algorithm and intensity, then analyze.",
    "分析优化": "Analyze Optimization", "详细信息 ▸": "Details ▸", "详细信息 ▾": "Details ▾",
    "允许写入的轨道": "Writable Tracks", "应用预览": "Apply Preview",
    "设置已变化，请重新分析优化。": "Settings changed. Analyze again.",
    "没有可用的优化算法。": "No optimization algorithm is available.",
    "请至少选择一条允许写入的轨道。": "Select at least one writable track.",
    "正在分析优化…": "Analyzing optimization…",
    "作用轨道：Track {track_id}": "Scope: Track {track_id}",
    "作用轨道：{selected} / {total}": "Scope: {selected} / {total}",
})

JA.update({
    "自动（根据时区）": "自動（タイムゾーン）",
    "选择目录": "フォルダーを選択", "本地音源目录": "ローカル音源フォルダー", "选择音源包": "音源パックを選択",
    "本地音源包": "ローカル音源パック", "选择本地音源目录": "ローカル音源フォルダーを選択",
    "选择本地音源包": "ローカル音源パックを選択", "音源包不可用": "音源パックを使用できません",
    "本地音源": "ローカル音源", "音源路径不可用": "音源パスを使用できません",
    "OPEN SOURCE  ·  COMMUNITY": "OPEN SOURCE  ·  COMMUNITY",
    "所有文件 (*.*)": "すべてのファイル (*.*)", "MIDI 文件 (*.mid *.midi)": "MIDIファイル (*.mid *.midi)",
    "导出规则、MIDI 解析、力度策略与游戏效果。设置只在下次导出时生效。": "書き出し規則、MIDI解析、ベロシティ処理、ゲーム内エフェクトを設定します。次回の書き出しから反映されます。",
    "角色名会写入乐谱；BPM 与移调会在导出时应用。": "キャラクター名を楽譜に保存し、BPMとトランスポーズを書き出し時に適用します。",
    "与 midi-to-bdo 相同：选择一份游戏内保存的单音符曲谱，读取角色名和 Owner ID。": "ゲーム内で保存した1音の楽譜からキャラクター名とOwner IDを読み込みます。",
    "这两项会影响 MIDI 读入方式；修改后会重新载入当前文件。": "MIDIの読み込み方法に影響します。変更すると現在のファイルを再読み込みします。",
    "选择一种输出力度策略；下方仅显示当前策略需要的参数。": "ベロシティの出力方式を選択します。必要な設定だけが表示されます。",
    "数值范围为 0–127；设为 0 即不写入对应效果。": "値は0～127です。0にすると対応するエフェクトを書き込みません。",
    "轨道 FX 中的奏法会写入支持的 BDO 乐器。": "トラックFXの奏法は対応するBDO楽器へ書き込まれます。",
    "选择轨道查看详情。右键可修复和优化轨道或更换乐器；FX 可设置支持乐器的 BDO 奏法。": "トラックを選択すると詳細を表示します。右クリックで最適化や楽器変更、FXで奏法を設定できます。",
    "导入 MIDI 后显示轨道与音符时间轴": "MIDIを読み込むとトラックとノートを表示します",
    "打开输出目录": "出力フォルダーを開く", "无法原声试听": "プレビューできません",
    "读取全曲乐理与配器上下文，但只写入当前轨道。": "曲全体の楽理と編成を分析し、現在のトラックだけを変更します。",
    "分析全部轨道；静音和独奏不改变作用域，可在下方选择允许写入的轨道。": "全トラックを分析します。Mute/Soloは範囲に影響せず、変更可能なトラックを下で選択できます。",
})
JA.update({
    "优化算法": "最適化アルゴリズム", "算法包目录": "アルゴリズムパッケージ", "刷新": "更新",
    "优化强度": "最適化の強度", "保守": "保守的", "均衡": "バランス", "深入": "詳細",
    "选择算法和强度，然后分析优化。": "アルゴリズムと強度を選択して解析してください。",
    "分析优化": "最適化を解析", "详细信息 ▸": "詳細 ▸", "详细信息 ▾": "詳細 ▾",
    "允许写入的轨道": "書き込み可能なトラック", "应用预览": "プレビューを適用",
    "设置已变化，请重新分析优化。": "設定が変更されました。再解析してください。",
    "没有可用的优化算法。": "利用可能な最適化アルゴリズムがありません。",
    "请至少选择一条允许写入的轨道。": "書き込み可能なトラックを1つ以上選択してください。",
    "正在分析优化…": "最適化を解析中…",
    "作用轨道：Track {track_id}": "対象：Track {track_id}",
    "作用轨道：{selected} / {total}": "対象：{selected} / {total}",
})

KO.update({
    "自动（根据时区）": "자동(시간대 기준)",
    "选择目录": "폴더 선택", "本地音源目录": "로컬 음원 폴더", "选择音源包": "음원 팩 선택",
    "本地音源包": "로컬 음원 팩", "选择本地音源目录": "로컬 음원 폴더 선택",
    "选择本地音源包": "로컬 음원 팩 선택", "音源包不可用": "음원 팩을 사용할 수 없음",
    "本地音源": "로컬 음원", "音源路径不可用": "음원 경로를 사용할 수 없음",
    "OPEN SOURCE  ·  COMMUNITY": "OPEN SOURCE  ·  COMMUNITY",
    "所有文件 (*.*)": "모든 파일 (*.*)", "MIDI 文件 (*.mid *.midi)": "MIDI 파일 (*.mid *.midi)",
    "导出规则、MIDI 解析、力度策略与游戏效果。设置只在下次导出时生效。": "내보내기 규칙, MIDI 분석, 벨로시티 전략과 게임 효과를 설정합니다. 다음 내보내기부터 적용됩니다.",
    "角色名会写入乐谱；BPM 与移调会在导出时应用。": "캐릭터 이름은 악보에 저장되고 BPM과 조옮김은 내보낼 때 적용됩니다.",
    "与 midi-to-bdo 相同：选择一份游戏内保存的单音符曲谱，读取角色名和 Owner ID。": "게임에서 저장한 한 음짜리 악보를 선택해 캐릭터 이름과 Owner ID를 읽습니다.",
    "这两项会影响 MIDI 读入方式；修改后会重新载入当前文件。": "MIDI 읽기 방식에 영향을 주며 변경하면 현재 파일을 다시 불러옵니다.",
    "选择一种输出力度策略；下方仅显示当前策略需要的参数。": "벨로시티 출력 전략을 선택합니다. 필요한 설정만 아래에 표시됩니다.",
    "数值范围为 0–127；设为 0 即不写入对应效果。": "값 범위는 0–127이며 0이면 해당 효과를 기록하지 않습니다.",
    "轨道 FX 中的奏法会写入支持的 BDO 乐器。": "트랙 FX의 주법은 지원되는 BDO 악기에 기록됩니다.",
    "选择轨道查看详情。右键可修复和优化轨道或更换乐器；FX 可设置支持乐器的 BDO 奏法。": "트랙을 선택하면 세부 정보를 봅니다. 우클릭으로 최적화하거나 악기를 바꾸고 FX에서 주법을 설정합니다.",
    "导入 MIDI 后显示轨道与音符时间轴": "MIDI를 가져오면 트랙과 노트를 표시합니다",
    "打开输出目录": "출력 폴더 열기", "无法原声试听": "미리듣기 불가",
    "读取全曲乐理与配器上下文，但只写入当前轨道。": "전체 곡의 음악 이론과 편성 맥락을 분석하지만 현재 트랙만 변경합니다.",
    "分析全部轨道；静音和独奏不改变作用域，可在下方选择允许写入的轨道。": "모든 트랙을 분석합니다. 음소거와 Solo는 범위를 바꾸지 않으며 아래에서 변경할 트랙을 선택합니다.",
})
KO.update({
    "优化算法": "최적화 알고리즘", "算法包目录": "알고리즘 패키지", "刷新": "새로 고침",
    "优化强度": "최적화 강도", "保守": "보수적", "均衡": "균형", "深入": "심층",
    "选择算法和强度，然后分析优化。": "알고리즘과 강도를 선택한 뒤 분석하세요.",
    "分析优化": "최적화 분석", "详细信息 ▸": "세부 정보 ▸", "详细信息 ▾": "세부 정보 ▾",
    "允许写入的轨道": "쓰기 허용 트랙", "应用预览": "미리보기 적용",
    "设置已变化，请重新分析优化。": "설정이 변경되었습니다. 다시 분석하세요.",
    "没有可用的优化算法。": "사용 가능한 최적화 알고리즘이 없습니다.",
    "请至少选择一条允许写入的轨道。": "쓰기 가능한 트랙을 하나 이상 선택하세요.",
    "正在分析优化…": "최적화 분석 중…",
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
    "只在游戏支持范围内调整奏法、力度、轻微时序和全局声音效果。不会增删音符、改音高、换乐器或新增轨道；未通过游戏 A/B 的奏法不会写入。": "Adjust articulations, velocity, subtle timing, and global effects only within game-supported limits. Notes, pitches, instruments, and tracks are preserved; articulations without in-game A/B validation are not written.",
    "复制到游戏目录": "Copy to Game Folder", "修复可自动处理项": "Apply Automatic Fixes",
    "未读取 Owner ID；导出的曲谱无法在游戏内编辑。": "No Owner ID loaded; exported scores cannot be edited in the game.",
    "当前乐器暂未收录奏法。": "No articulations are currently cataloged for this instrument.",
    "未指定奏法，导出时保留普通音符。 此设置会把该轨导出为同一种 BDO 奏法。": "No articulation selected; export keeps normal notes. This setting applies one BDO articulation to the entire track.",
    "延音": "Sustain", "延音踏板": "Sustain Pedal", "延音 (type 0)": "Sustain (type 0)",
    "延音踏板 (type 11)": "Sustain Pedal (type 11)", "无法原声还原": "Original Preview Unavailable",
    "状态\n可转换": "Status\nReady", "问题\n0": "Issues\n0", "人工确认\n0": "Review\n0",
    "可自动修复\n0 项": "Auto-fixable\n0 items", "已选 0 · 共 0 音符": "Selected 0 · 0 notes total",
    "奏法 0 处 · 轻微自然化 0 个音符\n效果：混响 0→0 · 延迟 0→0 · 合唱 (0, 0, 0)→(0, 0, 0)": "Articulations 0 · Humanized 0 notes\nEffects: Reverb 0→0 · Delay 0→0 · Chorus (0, 0, 0)→(0, 0, 0)",
    "已选 {selected} · 共 {total} 音符{position}{warning}": "Selected {selected} · {total} notes total{position}{warning}",
    "状态\n{status}": "Status\n{status}", "问题\n{count}": "Issues\n{count}",
    "人工确认\n{count}": "Review\n{count}", "可自动修复\n{count} 项": "Auto-fixable\n{count} items",
    "已读取 Owner ID：0x{owner_id:08x}": "Owner ID loaded: 0x{owner_id:08x}",
    "可转换": "Ready", "不可转换": "Blocked",
    "需处理": "Action Required", "需人工确认": "Review Required", " · 移调 {transpose:+d}": " · Transpose {transpose:+d}",
    " · 越界 {count}": " · Out of range {count}",
    "从 MIDI 解析、游戏曲谱研究到原声试听，每一份开源代码、文档和测试都很重要。": "From MIDI parsing and game-score research to original-sample preview, every piece of open-source code, documentation, and testing matters.",
    "以当前代码中实际承担的功能作粗略估算": "A rough estimate based on responsibilities in the current code",
    "占比仅用于表达感谢，不代表代码所有权或精确工作量。Python 与 Qt 作为运行基础未计入图表。": "These proportions express appreciation, not code ownership or exact effort. Python and Qt are runtime foundations and are not included.",
    "6 项核心依赖与贡献": "6 Core Dependencies and Contributions",
    "这不是一份排名，而是一张合作地图。谢谢每一个把工具、文档和经验分享出来的人。": "This is not a ranking, but a map of collaboration. Thank you to everyone who shared tools, documentation, and experience.",
    "复制为纯文本，便于放入项目说明或发布页面": "Copy as plain text for project documentation or release pages",
    "01 · MIDI 与游戏采样试听": "01 · MIDI and Game-sample Preview", "把 MIDI 音符一颗颗读出来、写回去。": "Reads and writes MIDI notes one by one.",
    "BDO 原始采样映射": "BDO Original-sample Mapping", "试听只使用从游戏提取并验证过的键位映射。": "Preview uses only key mappings extracted from and verified against the game.",
    "02 · GitHub 开源项目": "02 · GitHub Open-source Projects", "感谢 midi-to-bdo 作者，提供 MIDI 转黑色沙漠曲谱格式的核心基础。": "Thanks to the midi-to-bdo author for the core foundation of MIDI-to-BDO score conversion.",
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
    "未读取 Owner ID；导出的曲谱无法在游戏内编辑。": "Owner IDが読み込まれていないため、書き出した楽譜はゲーム内で編集できません。",
    "当前乐器暂未收录奏法。": "この楽器の奏法はまだ登録されていません。",
    "未指定奏法，导出时保留普通音符。 此设置会把该轨导出为同一种 BDO 奏法。": "奏法未指定のため通常ノートのまま書き出します。この設定はトラック全体に同じBDO奏法を適用します。",
    "延音": "サステイン", "延音踏板": "サステインペダル", "延音 (type 0)": "サステイン (type 0)",
    "延音踏板 (type 11)": "サステインペダル (type 11)", "无法原声还原": "原音プレビュー不可",
    "状态\n可转换": "状態\n書き出し可能", "问题\n0": "問題\n0", "人工确认\n0": "要確認\n0",
    "可自动修复\n0 项": "自動修正可能\n0件", "已选 0 · 共 0 音符": "選択 0・全 0 ノート",
    "奏法 0 处 · 轻微自然化 0 个音符\n效果：混响 0→0 · 延迟 0→0 · 合唱 (0, 0, 0)→(0, 0, 0)": "奏法 0・ヒューマナイズ 0ノート\nエフェクト：リバーブ 0→0・ディレイ 0→0・コーラス (0, 0, 0)→(0, 0, 0)",
    "已选 {selected} · 共 {total} 音符{position}{warning}": "選択 {selected}・全 {total} ノート{position}{warning}",
    "状态\n{status}": "状態\n{status}", "问题\n{count}": "問題\n{count}",
    "人工确认\n{count}": "要確認\n{count}", "可自动修复\n{count} 项": "自動修正可能\n{count}件",
    "已读取 Owner ID：0x{owner_id:08x}": "Owner ID 読み込み済み：0x{owner_id:08x}",
    "可转换": "書き出し可能", "不可转换": "書き出し不可",
    "需处理": "対応が必要", "需人工确认": "要確認", " · 移调 {transpose:+d}": " · トランスポーズ {transpose:+d}",
    " · 越界 {count}": " · 範囲外 {count}",
    "从 MIDI 解析、游戏曲谱研究到原声试听，每一份开源代码、文档和测试都很重要。": "MIDI解析、ゲーム楽譜研究、原音プレビューまで、すべてのオープンソースコード、文書、テストが重要です。",
    "以当前代码中实际承担的功能作粗略估算": "現在のコードで担う機能に基づく概算", "占比仅用于表达感谢，不代表代码所有权或精确工作量。Python 与 Qt 作为运行基础未计入图表。": "割合は感謝を表すためのもので、コード所有権や正確な作業量を示しません。基盤のPythonとQtは含みません。",
    "6 项核心依赖与贡献": "6つの主要な依存関係と貢献", "这不是一份排名，而是一张合作地图。谢谢每一个把工具、文档和经验分享出来的人。": "これは順位ではなく協力の地図です。ツール、文書、経験を共有してくださった皆様に感謝します。",
    "复制为纯文本，便于放入项目说明或发布页面": "プロジェクト説明やリリースページ用にプレーンテキストでコピー",
    "01 · MIDI 与游戏采样试听": "01 · MIDIとゲームサンプル試聴", "把 MIDI 音符一颗颗读出来、写回去。": "MIDIノートを一音ずつ読み書きします。", "BDO 原始采样映射": "BDO原音サンプルマッピング", "试听只使用从游戏提取并验证过的键位映射。": "ゲームから抽出・検証したキーマッピングのみを試聴に使用します。",
    "02 · GitHub 开源项目": "02 · GitHubオープンソースプロジェクト", "感谢 midi-to-bdo 作者，提供 MIDI 转黑色沙漠曲谱格式的核心基础。": "MIDIからBDO楽譜への変換基盤を提供したmidi-to-bdo作者に感謝します。", "感谢黑色沙漠音乐文件研究与解码相关资料作者，帮助理解外部曲谱制作方向。": "外部楽譜制作の理解を助けた黒い砂漠の音楽ファイル研究・解析資料の作者に感謝します。",
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
    "未读取 Owner ID；导出的曲谱无法在游戏内编辑。": "Owner ID를 읽지 않아 내보낸 악보를 게임에서 편집할 수 없습니다.",
    "当前乐器暂未收录奏法。": "이 악기의 주법은 아직 등록되지 않았습니다.",
    "未指定奏法，导出时保留普通音符。 此设置会把该轨导出为同一种 BDO 奏法。": "주법을 지정하지 않아 일반 음표로 내보냅니다. 이 설정은 트랙 전체에 같은 BDO 주법을 적용합니다.",
    "延音": "서스테인", "延音踏板": "서스테인 페달", "延音 (type 0)": "서스테인 (type 0)",
    "延音踏板 (type 11)": "서스테인 페달 (type 11)", "无法原声还原": "원음 미리듣기 불가",
    "状态\n可转换": "상태\n내보내기 가능", "问题\n0": "문제\n0", "人工确认\n0": "검토 필요\n0",
    "可自动修复\n0 项": "자동 수정 가능\n0개", "已选 0 · 共 0 音符": "선택 0 · 전체 0개 음표",
    "奏法 0 处 · 轻微自然化 0 个音符\n效果：混响 0→0 · 延迟 0→0 · 合唱 (0, 0, 0)→(0, 0, 0)": "주법 0 · 휴머니즈 0개 음표\n효과: 리버브 0→0 · 딜레이 0→0 · 코러스 (0, 0, 0)→(0, 0, 0)",
    "已选 {selected} · 共 {total} 音符{position}{warning}": "선택 {selected} · 전체 {total}개 음표{position}{warning}",
    "状态\n{status}": "상태\n{status}", "问题\n{count}": "문제\n{count}",
    "人工确认\n{count}": "검토 필요\n{count}", "可自动修复\n{count} 项": "자동 수정 가능\n{count}개",
    "已读取 Owner ID：0x{owner_id:08x}": "Owner ID 읽음: 0x{owner_id:08x}",
    "可转换": "내보내기 가능", "不可转换": "내보내기 불가",
    "需处理": "조치 필요", "需人工确认": "검토 필요", " · 移调 {transpose:+d}": " · 조옮김 {transpose:+d}",
    " · 越界 {count}": " · 범위 초과 {count}",
    "从 MIDI 解析、游戏曲谱研究到原声试听，每一份开源代码、文档和测试都很重要。": "MIDI 분석과 게임 악보 연구부터 원음 미리듣기까지 모든 오픈 소스 코드, 문서와 테스트가 중요합니다.",
    "以当前代码中实际承担的功能作粗略估算": "현재 코드에서 담당하는 기능을 기준으로 한 대략적인 추정", "占比仅用于表达感谢，不代表代码所有权或精确工作量。Python 与 Qt 作为运行基础未计入图表。": "비율은 감사를 표현하기 위한 것이며 코드 소유권이나 정확한 작업량을 뜻하지 않습니다. 기반인 Python과 Qt는 포함하지 않았습니다.",
    "6 项核心依赖与贡献": "6개 핵심 의존성과 기여", "这不是一份排名，而是一张合作地图。谢谢每一个把工具、文档和经验分享出来的人。": "순위가 아니라 협업 지도입니다. 도구, 문서와 경험을 공유한 모든 분께 감사드립니다.", "复制为纯文本，便于放入项目说明或发布页面": "프로젝트 설명이나 릴리스 페이지용 일반 텍스트로 복사",
    "01 · MIDI 与游戏采样试听": "01 · MIDI와 게임 샘플 미리듣기", "把 MIDI 音符一颗颗读出来、写回去。": "MIDI 음표를 하나씩 읽고 씁니다.", "BDO 原始采样映射": "BDO 원본 샘플 매핑", "试听只使用从游戏提取并验证过的键位映射。": "게임에서 추출하고 검증한 키 매핑만 미리듣기에 사용합니다.",
    "02 · GitHub 开源项目": "02 · GitHub 오픈 소스 프로젝트", "感谢 midi-to-bdo 作者，提供 MIDI 转黑色沙漠曲谱格式的核心基础。": "MIDI를 BDO 악보로 변환하는 핵심 기반을 제공한 midi-to-bdo 작성자에게 감사드립니다.", "感谢黑色沙漠音乐文件研究与解码相关资料作者，帮助理解外部曲谱制作方向。": "외부 악보 제작 방향을 이해하도록 도운 검은사막 음악 파일 연구 및 디코딩 자료 작성자에게 감사드립니다.",
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
    "轨道音量": "Track Volume",
    "显示力度编辑 ▸": "Show Velocity Editor ▸", "隐藏力度编辑 ▾": "Hide Velocity Editor ▾",
    "拖动柱形可直接调整所选音符力度": "Drag bars to adjust note velocity",
    "拖动手柄 · 横向拖绘渐变 · 多选后整体调整 · Ctrl+↑↓ 微调": "Drag handles · Paint ramps horizontally · Adjust selections together · Ctrl+↑↓ to fine-tune",
    "音符检查器": "Note Inspector", "未选择音符": "No note selected",
    "未选择音符 · 单击网格新建": "No note selected · Click the grid to add one",
    "在网格空白处单击即可新建": "Click an empty grid cell to add a note",
    "音符": "Note", "音符属性": "Note", "奏法": "Articulation", "网格": "Grid",
    "绘制 B": "Draw B", "点击试听": "Audition",
    "绘制模式：拖动可同时设置音符长度与力度（B）": "Draw mode: drag to set note length and velocity (B)",
    "绘制模式：拖动设置长度，上下调整力度，Alt 取消吸附": "Draw mode: drag for length, move vertically for velocity, Alt bypasses snap",
    "选择模式：拖动音符编辑，拖动空白框选": "Select mode: drag notes to edit, drag empty space to marquee-select",
    "选择音符后应用奏法": "Select notes, then apply an articulation",
    "常用奏法": "Common Articulations", "网格与参考": "Grid and Reference", "水平缩放": "Horizontal Zoom",
    "右键删除音符 · Ctrl 拖选追加 · 拖动音符两端调整时值": "Right-click to delete · Ctrl-drag to add selection · Drag note edges to resize",
    "右键删除 · Ctrl 拖选追加 · 拖动两端调整时值": "Right-click to delete · Ctrl-drag to add selection · Drag edges to resize",
    "Alt 临时取消吸附 · 方向键移动 · Ctrl+D 复制": "Alt bypasses snap · Arrow keys move · Ctrl+D duplicates",
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
    "轨道音量": "トラック音量",
    "显示力度编辑 ▸": "ベロシティ編集を表示 ▸", "隐藏力度编辑 ▾": "ベロシティ編集を隠す ▾",
    "拖动柱形可直接调整所选音符力度": "バーをドラッグしてベロシティを調整",
    "拖动手柄 · 横向拖绘渐变 · 多选后整体调整 · Ctrl+↑↓ 微调": "ハンドルをドラッグ・横方向にランプを描画・複数選択を一括調整・Ctrl+↑↓で微調整",
    "音符检查器": "ノートインスペクタ", "未选择音符": "ノート未選択",
    "未选择音符 · 单击网格新建": "ノート未選択・グリッドをクリックして追加",
    "在网格空白处单击即可新建": "空のグリッドをクリックしてノートを追加",
    "音符": "ノート", "音符属性": "ノート属性", "奏法": "奏法", "网格": "グリッド",
    "绘制 B": "描画 B", "点击试听": "試聴",
    "绘制模式：拖动可同时设置音符长度与力度（B）": "描画モード：ドラッグでノート長とベロシティを設定（B）",
    "绘制模式：拖动设置长度，上下调整力度，Alt 取消吸附": "描画モード：ドラッグで長さ、上下でベロシティ、Altでスナップ解除",
    "选择模式：拖动音符编辑，拖动空白框选": "選択モード：ノートをドラッグして編集、空白をドラッグして範囲選択",
    "选择音符后应用奏法": "ノートを選択して奏法を適用",
    "常用奏法": "よく使う奏法", "网格与参考": "グリッドと参照", "水平缩放": "横方向ズーム",
    "右键删除音符 · Ctrl 拖选追加 · 拖动音符两端调整时值": "右クリックで削除・Ctrlドラッグで選択追加・端をドラッグして長さを調整",
    "右键删除 · Ctrl 拖选追加 · 拖动两端调整时值": "右クリックで削除・Ctrlドラッグで選択追加・端をドラッグして長さを調整",
    "Alt 临时取消吸附 · 方向键移动 · Ctrl+D 复制": "Altでスナップ解除・矢印キーで移動・Ctrl+Dで複製",
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
    "轨道音量": "트랙 볼륨",
    "显示力度编辑 ▸": "벨로시티 편집 표시 ▸", "隐藏力度编辑 ▾": "벨로시티 편집 숨기기 ▾",
    "拖动柱形可直接调整所选音符力度": "막대를 드래그하여 음표 벨로시티 조정",
    "拖动手柄 · 横向拖绘渐变 · 多选后整体调整 · Ctrl+↑↓ 微调": "핸들 드래그 · 가로로 램프 그리기 · 다중 선택 함께 조정 · Ctrl+↑↓ 미세 조정",
    "音符检查器": "음표 검사기", "未选择音符": "선택한 음표 없음",
    "未选择音符 · 单击网格新建": "선택한 음표 없음 · 그리드를 클릭하여 추가",
    "在网格空白处单击即可新建": "빈 그리드를 클릭하여 음표 추가",
    "音符": "음표", "音符属性": "음표 속성", "奏法": "주법", "网格": "그리드",
    "绘制 B": "그리기 B", "点击试听": "미리듣기",
    "绘制模式：拖动可同时设置音符长度与力度（B）": "그리기 모드: 드래그하여 음표 길이와 벨로시티 설정(B)",
    "绘制模式：拖动设置长度，上下调整力度，Alt 取消吸附": "그리기 모드: 드래그로 길이, 위아래로 벨로시티, Alt로 스냅 해제",
    "选择模式：拖动音符编辑，拖动空白框选": "선택 모드: 음표를 드래그해 편집하고 빈 공간을 드래그해 범위 선택",
    "选择音符后应用奏法": "음표를 선택한 뒤 주법 적용",
    "常用奏法": "자주 쓰는 주법", "网格与参考": "그리드 및 참조", "水平缩放": "가로 확대/축소",
    "右键删除音符 · Ctrl 拖选追加 · 拖动音符两端调整时值": "우클릭으로 삭제 · Ctrl 드래그로 선택 추가 · 음표 가장자리를 드래그하여 길이 조절",
    "右键删除 · Ctrl 拖选追加 · 拖动两端调整时值": "우클릭으로 삭제 · Ctrl 드래그로 선택 추가 · 가장자리를 드래그하여 길이 조절",
    "Alt 临时取消吸附 · 方向键移动 · Ctrl+D 复制": "Alt로 스냅 해제 · 방향키로 이동 · Ctrl+D로 복제",
    "已选择 1 个音符 · {note} · {start} ms": "음표 1개 선택 · {note} · {start} ms",
    "已选择 {count} 个音符 · 可批量修改共同属性": "음표 {count}개 선택 · 공통 속성을 함께 편집할 수 있습니다",
    "准备中…": "준비 중…", "正在准备游戏音源… {loaded}/{total}": "게임 음원 준비 중… {loaded}/{total}",
    "游戏音源已缓存 · 开始试听": "게임 음원 캐시 완료 · 미리듣기 시작",
    "当前音符没有可用的游戏音源": "이 음표에 사용할 수 있는 게임 음원이 없습니다",
    "正在准备音符试听… {note}": "음표 미리듣기 준비 중… {note}",
    "试听 {note}": "{note} 미리듣기",
    "音符试听不可用：{message}": "음표 미리듣기를 사용할 수 없음: {message}",
})

TRANSLATIONS = {"en_US": EN, "ja_JP": JA, "ko_KR": KO}
class Localizer(QObject):
    def __init__(self, app: QApplication, language: str = "zh_CN") -> None:
        super().__init__(app)
        self.app = app
        self.requested_language = language if language in {code for code, _ in LANGUAGE_CHOICES} else "zh_CN"
        self.language = resolve_language(self.requested_language)
        self.sources: WeakKeyDictionary[QWidget, dict[str, object]] = WeakKeyDictionary()
        app.installEventFilter(self)

    def translate(self, text: str) -> str:
        return TRANSLATIONS.get(self.language, {}).get(text, text)

    def set_language(self, language: str) -> None:
        self.requested_language = language if language in {code for code, _ in LANGUAGE_CHOICES} else "zh_CN"
        self.language = resolve_language(self.requested_language)
        for widget in self.app.topLevelWidgets():
            self.translate_tree(widget)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Show and isinstance(watched, QWidget):
            self.translate_tree(watched)
        return False

    def _translate_text(self, widget: QWidget, getter, setter) -> None:
        source_data = self.sources.setdefault(widget, {})
        source = source_data.setdefault("text", getter())
        setter(self.translate(str(source)))

    def translate_tree(self, root: QWidget) -> None:
        widgets = [root, *root.findChildren(QWidget)]
        for widget in widgets:
            if isinstance(widget, (QMainWindow,)) or widget.isWindow():
                self._translate_text(widget, widget.windowTitle, widget.setWindowTitle)
            if isinstance(widget, (QLabel, QAbstractButton, QGroupBox)):
                self._translate_text(widget, widget.text, widget.setText)
            if isinstance(widget, QLineEdit):
                source_data = self.sources.setdefault(widget, {})
                source = source_data.setdefault("placeholder", widget.placeholderText())
                widget.setPlaceholderText(self.translate(str(source)))
            if isinstance(widget, QSpinBox):
                source_data = self.sources.setdefault(widget, {})
                source = source_data.setdefault("special", widget.specialValueText())
                widget.setSpecialValueText(self.translate(str(source)))
            if isinstance(widget, QComboBox) and not widget.property("i18nSkipItems"):
                source_data = self.sources.setdefault(widget, {})
                item_sources = source_data.get("items")
                if not isinstance(item_sources, list) or len(item_sources) != widget.count():
                    item_sources = [widget.itemText(index) for index in range(widget.count())]
                    source_data["items"] = item_sources
                for index in range(widget.count()):
                    widget.setItemText(index, self.translate(str(item_sources[index])))


_localizer: Localizer | None = None


def install_localizer(app: QApplication, language: str) -> Localizer:
    global _localizer
    _localizer = Localizer(app, language)
    return _localizer


def localizer() -> Localizer | None:
    return _localizer


def tr(text: str) -> str:
    return _localizer.translate(text) if _localizer else text


def trf(text: str, /, **values: object) -> str:
    """Translate a stable template before interpolating dynamic UI values."""
    return tr(text).format(**values)
