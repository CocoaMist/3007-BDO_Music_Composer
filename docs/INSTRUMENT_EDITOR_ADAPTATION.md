# 乐器编辑适配与游戏兼容边界

`bdo_music_composer/editor/bdo_instrument_adaptation.py` 是 Qt 无关的编辑提示层。它把 26 个逻辑
BDO 乐器的游戏分类、编排角色、推荐可视音域、鼓件行、奏法路由证据和
背景视觉键集中在一个只读接口中。实时播放、离线渲染和导出仍以原有
`Note(pitch, vel, start, dur, ntype)`、`bdo_music_composer/core/bdo_profile.py`、
`bdo_music_composer/audio/bdo_instrument_samples.py` 与 `bdo_codec` 为准。

## 三种音高事实必须分开

- `legal_pitches`：只来自状态为 `verified` 的游戏谱音域证据。只有这一项
  可以用于明确的合法/不合法判断。
- `preview_pitches`：Wwise MIDI Tracking 音区覆盖，只证明本地试听存在对应
  zone，不证明游戏编辑器一定允许或禁止该音高。
- `recommended_pitches` / `recommended_visible_range`：打开编辑器时的视觉
  聚焦建议。它不裁剪、移调或删除音符。

当游戏谱音域为 `approximate` 或未知时，`legal_pitches=None`，
`legal_pitch_support()` 返回 `None`。UI 可以突出 Wwise 推荐音区，但必须保留
滚动到所有 MIDI 行的能力。缺少映射文件时也不得把“无试听样本”解释为
“游戏不合法”。

唯一已有完整离散键位证据的现有乐器是已由游戏谱确认的架子鼓套装：

- 乐器 ID `0x0D`；
- canonical pitches `48–64`；
- 新建鼓音默认 `ntype=99`；
- 17 个鼓件行沿用 Kck、SnrSide、SnrHit、RimShot、SnrFlam、Tom、Hi-hat、
  Cymbal 与 Roll 标签。

2026-08-08 依据用户提供的当前游戏作曲界面截图逐行复核，游戏从低到高的
标签与项目 48–64 映射完全一致。应用显示时保留游戏缩写，并追加当前界面语言
的解释，例如 `CymCrsh · 碎音镲`；翻译只属于 UI，不改写鼓件身份或音高。

PAZ meta v757 的 `musiccomposition.js` 进一步给出了新手手鼓和钹的静态
可编辑键位，并且游戏 UI 会把表中空名称的行标为 `disable`：

- 新手手鼓 `0x04`：`60, 65, 66, 67, 72, 73, 74, 77, 78, 79`；
- 钹 `0x05`：`60, 65, 71`。

因此这两件乐器现在可以做明确的合法性检查。所有打击乐与旋律乐器使用同一套
钢琴卷帘矩形、时值和缩放交互，不存在专用打击乐模式。架子鼓原生 BDO
48–64 / `ntype=99` 显示 BDO 鼓件名；尚未在导出投影中转换的 MIDI 通道 10
鼓轨保留原始 GM 音高和 `ntype`，但显示 Kick、Snare、Hi-Hat、Crash、Ride
等 GM 鼓键名并保持完整滚动范围；活动音符若超出映射则显示为
`MIDI n · 未映射鼓键` 并标为无效。2026-08-09 的游戏内导入截图进一步确认：
手鼓按 60、65–67、72–74、77–79 依次使用 `Bng1-Open`、三组
`Bng2-*`、`Cng1-*`、`Cng2-*` 键名，钹的 60、65、71 均显示 `HIT`；应用按
这些游戏原名显示，只改标签而不改正式音符。截图中的音块宽度受用户缩放影响，
不能单凭不同缩放的画面判断游戏是否保留打击乐时值。手碟 `0x13` 仍只有近似
音域证据。三者的正式音符均保持 `ntype=0`，不能静默改成试听内部使用的
Event 99。

## 分类、角色与视觉键

`family` 使用游戏作曲界面的四个稳定分类 ID：`wind`、`strings`、`keys`、
`percussion`。`primary_role` 和 `roles` 是可纠正的配器提示，包括主旋律、
低音、和弦、和声、节奏、打击与琶音；它们不是混音中的乐器识别结果。

`visual_key` 是应用内部的语义键，例如：

- `wind.flute`、`wind.recorder`、`wind.clarinet`、`wind.horn`；
- `strings.guitar.*`、`strings.bass.electric`、`strings.contrabass`、
  `strings.harp*`、`strings.violin*`；
- `keys.piano*`、`keys.synth.{saw,sine,square,triangle}`；
- `percussion.{hand_drum,cymbals,drum_set,handpan}`。

视觉键不是磁盘路径。解析器只能指向仓库自有素材或用户明确配置的本地素材，
不能把游戏资源打包进程序或工程文件。

时间轴现已使用 `bdo_music_composer/ui/editor/bdo_instrument_lane_art_qt.py` 绘制应用自有的抽象乐器线稿。
用户也可以在“设置 → 音源与效果 → 轨道背景”选择一个本地目录。图片在设置
生效时一次性解码并缩小，时间轴 `paintEvent` 只查询内存缓存，不访问磁盘。
支持 PNG、WebP 和 JPEG；单图上限 8 MiB、解码像素上限 2000 万。文件名按
以下顺序匹配：

1. `instrument_0a.png` 或 `0a.png` 这类两位十六进制乐器 ID；
2. `visual_key` 将点替换为下划线，例如
   `strings_guitar_acoustic_pro.png`；
3. 家族回退名，例如 `guitar.png`、`piano.png`、`drum_set.png`。

目录路径只保存在本机配置中，不进入工程 schema、自动保存或导出文件。图片
消失、损坏、过大或格式不支持时会回退到内置线稿，不影响音符与导出。

## 当前 PAZ/Wwise 只读证据

2026-08-03 复核的 PAZ meta v782（8,363 archives）仍包含相同的 40 个
`midi_instrument_*.bnk`，全部为 Wwise v145。3,579 条 Sound 路由没有任何
Bank/Sound/Source/Event/键域/力度层增删；四条已知部分奏法路由也保持不变：
三把电吉他的 type 25 只覆盖 MIDI 36–43，圆号 type 3 只覆盖 MIDI 24–72。
编辑器在写入前阻止这些越界组合，转换检查也会把历史导入或已有工程中的越界组合
列为错误；它不会删音、移调或把奏法静默回退到延音。新版映射同时暴露 1,024 条
尚未建模的 Pitch RTPC，因此“Wwise 路由已确认”只表示结构路由，不表示听感 1:1。

2026-07-26 使用 `tools/list_bdo_paz_audio.py` 对一份本地游戏安装做了纯路径
索引：PAZ meta 版本为 757，声明的 8310 个归档全部存在。索引确认了 40 个
`sound2022/windows/midi_instrument_*.bnk`，与签入的 Wwise v145 MIDI 映射
集合一致。它还确认存在 `gamecommondata/binary/midiinstrument.bss`，但其字段
结构尚未被完整解码，因此当前适配层没有从未知字段猜测新的音域、奏法或限制。
对该文件做同样的只读 ICE/`0x6f` 解压后，已确认 `PABR` 头与记录数 38；其
字符串表恰好包含 8 个入门、9 个高级传统、16 个玛勒尼恩
（4 组基础乐器 × 4 模式）、3 把电吉他、Clarinet 和 Horn。也就是 26 个
逻辑乐器加四组各自额外三个模式，共 38 个物理乐器。字符串还明确给出
`MIDI_Instrument_02_Recorder`、`MIDI_Instrument_27_ProClarinet` 与
`Advanced_Clarinet`，但不存在独立 `MIDI_Instrument_12` 条目。这进一步确认
ID `0x27` 是单簧管，CSS 中 ID 12 的 Whistle 图标不能升级为可用乐器。除头、
记录数和字符串身份外的二进制字段仍标记为未知。

路径索引还找到以下视觉资源候选：

- `ui_data/ui_html/contents/img/icn_instrument_spr.png`
- `ui_data/ui_html/contents/img/icn_music_spr.png`
- `ui_data/ui_html/contents/img/spr_bg_instrument.jpg`
- `ui_data/ui_html/contents/img/spr_bg_instrument_1.png`
- `ui_data/ui_html/contents/img/spr_instrument.png`
- `ui_data/ui_html/contents/img/spr_instrument_icn.png`
- `character/texture/` 下包含
  `com_tool_{guitar,eguitar,flute,harp,piano,clarinet,horn}` 的 DDS 候选

进一步只读解密 `musiccomposition.css` 与 `spr_instrument.png` 后，CSS 已确认
大图单元为 `240×100`，并直接给出游戏乐器 ID 到 sprite 坐标的映射。这里
得到的是 UI 身份证据，不是音高或听感证据：

- `20–23`、`24–27`、`28–31`、`32–35` 分别共享四个玛勒尼恩基础外观，
  与 base instrument ID 加 `0..3` 音源模式的现有编码规则一致；
- `36/37/38` 是三把独立电吉他，`39` 是 Clarinet，`40` 是 Horn；
- CSS 还保留 ID `12` 的 Whistle 小图标，但当前 PAZ/Wwise 证据没有对应
  `midi_instrument_12` SoundBank。因此它只能记录为潜在/遗留 UI 项，不能
  据此添加为可播放或可导出的乐器。

`tools/import_bdo_game_art.py` 提供显式的本地导入边界。它只允许读取上述 CSS
和大图两个固定游戏路径，通过 ICE 解密和有界 `0x6e/0x6f` 解压，随后按 CSS
动态裁出 26 张 `instrument_XX.png`。输出只能进入用户选择的本地缓存：PAZ
目录、磁盘根目录和 Git 工作区都会被拒绝，manifest 不记录源安装路径；未知
meta 版本默认失败，必须由用户显式允许后才会继续执行同样的路径、尺寸、
坐标和完整性检查。导入在临时目录完成后再原子发布，既有损坏缓存不会被静默
覆盖。

仓库和安装包仍不复制或分发这些游戏图像。应用时间轴只读取用户显式选择的
普通图片目录；无法读取时回退到应用自有的抽象背景。sprite/UI 身份映射不得
升级成音高、奏法、播放或导出约束。

## 作曲 JS 的运行时兼容契约

同一版本的 `musiccomposition.js` 还确认，CSS 与离线资源并不是当前账号能力
的最终事实源：

- 可用乐器列表、每个乐器的主/子类型、分类、音域和可播放奏法均由游戏客户端
  在运行时回调给 Web UI；静态 CSS 中存在一个 ID 不等于它当前可用。
- `codeCount`、`noteCount` 和 `max_bpm` 由
  `FromClient_SetMusicLimit(...)` 动态下发。JS 的 `BPM_MAX=200` 只是未收到
  回调时的缺省值。v9 的每物理轨 730 音符是二进制分块规则，不是玩家等级、
  全曲或每乐器配额。
- XML 层使用独立的 `onVelocity`/`offVelocity`、毫秒 `startTime/length`，并
  保存每轨 volume/reverb/delay/chorus；当前 UI 默认 velocity 100、上限 127、
  音量 70、拍号分母界面默认 4。这些缺省值不覆盖已导入谱中的真实字段。
- 游戏加载旧 XML 时会拒绝未知乐器轨，并跳过音域外音符。游戏内“复制到其他
  乐器”还会删除目标音域外音符并把奏法重置为目标默认值。

因此本工具不得把离线 CSS 列表当成动态授权列表，不得把 10,000 等应用保护值
描述为已验证的游戏配额，也不得在跨乐器复制时静默模仿游戏的删除行为。兼容
检查应保留原音并列出越域/未知项，只有用户明确确认后才允许破坏性适配；无法
从当前账号取得动态限额时，应显示“需游戏内等级确认”，而不是伪造硬上限。

## 奏法证据

`articulations` 只列出当前编辑器声明的 `ntype`。每项分别记录：

- `native_route_pitches`：该 Event 在 Wwise 中实际覆盖的音高；
- `route_evidence`：完整覆盖、部分覆盖或未知；
- `audible_behavior_verified`：是否完成游戏录音 A/B；
- `auto_apply_allowed`：是否允许算法自动写入。

Wwise Event 路由是结构证据，不等于听感验证。目前所有奏法的游戏听感 A/B
标志仍为 false，因此 `auto_apply_allowed` 也全部为 false。三把电吉他的
type 25 仅覆盖 MIDI 36–43；圆号 type 3 仅覆盖 MIDI 24–72。超出范围可以
保留正式音符，但不能伪装成已有原生试听路由。

除架子鼓使用 `ntype=99` 的“打击乐”外，当前注册表中每件可编辑乐器的首项与
默认值都是 `ntype=0`，编辑器显示为“延音”。这是普通基础奏法；弗洛凯斯特拉
钢琴（`0x11`）的“延音踏板”是另一个 `ntype=11`，不能把两者合并；新手钢琴
（`0x07`）目前只有普通 `ntype=0`。切换选中音符的奏法时，
试听链路必须携带变更后的 `ntype`；若 Wwise 有对应 Event 则使用原生路由，
否则只能明确作为本地近似预览，不能据此提高 `audible_behavior_verified`。

## UI 集成约束

```python
from bdo_instrument_adaptation import instrument_editor_display_adaptation

profile = instrument_editor_display_adaptation(track.bdo_instrument_id)
```

UI 可以使用 `family`/`roles` 分组，用 `recommended_visible_range` 定位，用
`drum_lanes` 替换架子鼓的普通音名，并为其他打击乐显示游戏键位音名，再用
`visual_key` 选择背景。键名适配不得改变钢琴卷帘的矩形、时值或缩放交互。任何
实际音符变更仍必须经过现有编辑命令、撤销栈和显式 Apply/OK；适配对象本身
不提供 Note 变换函数。同步 UI 路径只读取很小的 game profile；它不会解析
约 6.7 MB 的 Wwise JSON。后台检查需要原生 route/zone 证据时再调用
`instrument_editor_adaptation(instrument_id, synth_mode)` 完整接口。

发布前必须保持以下限制：

1. 推荐范围不能成为导出过滤器。
2. `preview_pitches` 缺失不能生成音域错误。
3. 打击乐键名不得成为压缩、隐藏或改写音高行的依据。
4. 鼓组新建音符必须使用 48–64 / `ntype=99`，但不得静默改写既有音符。
5. 部分奏法路由必须显式显示为部分覆盖，不跨接到其他 Event。
6. 未完成游戏 A/B 的奏法不能自动应用或标为 1:1。
7. 游戏图像路径不得写入工程 schema、可执行文件或 Git 历史。
8. 本地 PAZ 图像导入必须保持 allowlist、只读、版本提示和失败关闭；不得扩展
   成任意路径解包器，也不得自动上传、分享或嵌入工程。
