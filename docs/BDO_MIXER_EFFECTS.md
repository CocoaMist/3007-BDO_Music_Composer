# BDO 作曲混音与效果证据

本文只记录可由游戏作曲界面与 v9 曲谱结构支持的事实。`0–100` 是游戏
authoring 控件值，不是 dB、毫秒、Hz 或 Wwise 原生参数；没有游戏录音 A/B
前，不得据此猜测 DSP 换算或宣称试听 1:1。

## 本地只读证据

2026-08-03 对用户提供的 PAZ meta v782 做了同样的限定只读复核。meta 包含
8,363 个 archive，文件大小 40,282,440 bytes，SHA-256 为
`ab149341b97aadf8855c82bc7a3f52492e9115ce201559c9d7b66d7ea67499e8`。
作曲页 `musiccomposition.js` 与 `index.html` 的 SHA-256 均与 v757 完全相同，
所以现有 authoring 控件/字段契约没有版本差异。新版 `init.bnk` 为 46,085 bytes，
SHA-256 为 `41e76febfd561ca30508fa5d0c1dcb2807df3ed9ab4ca0903087475ab5a509fd`；
它仍是 Wwise v145，117 Audio Bus、45 Aux Bus、34 FX ShareSet、11 FX Custom
及 RoomVerb、Stereo Delay、Flanger、Meter、Peak Limiter 拓扑数量均未改变。
二进制变化不能据此解释为听感变化；v9 byte 到 RTPC 的运行时绑定和游戏录音
A/B 边界仍保持“未校准”。

2026-07-26 对 PAZ meta v757 做了限定路径扫描，只读取以下资源：

- `ui_data/ui_html/contents/js/musiccomposition.js`
  (`sha256=714f2fa753997ae397a509b0010b2a892d79a2fb551e1513021fdd98b2038a23`)；
- `ui_data/ui_html/window/musiccomposition/index.html`
  (`sha256=6e25e5876941eb57bcc0892a920022afd39ef44d7667410468bd6d6400e9fa1e`)。

PAZ meta 哈希为
`5bf64283d48aaee328486f027e41af13fbe10375ab18b7db324d9a4e539bdb81`。
没有导出或签入游戏文件；以上哈希和字段结构足以复核版本。

2026-07-29 再次对同一 v757 meta 的 8,310 个归档路径表做了只读索引，
共检查 759,865 条路径且无缺失归档。40 个 `midi_instrument*.bnk` 位于
`PAD07706`–`PAD07711`，现有映射覆盖 40 banks、3,579 个音区行与 1,465 个
唯一媒体源。另发现：

- `gamecommondata/audioreverbpreset.xml`
  (`sha256=7270d964e037bb0a4b8ed09d84677cbd9bde07199cdd5ec0c42313e6a5c5b996`)；
- `gamecommondata/audioreverbpreset_remaster.xml`
  (`sha256=8dfda91f8fb4fb426e38378abecac13dc41d22e4997ef589d4bd44b637410f72`)。

两份文件各含 9 个环境 `ReverbPreset`，以及 221/206 个 BGM
`MusicStatePreset`。它们没有 composer、Aux/Bus ID、Delay 或 Chorus 字段，
只能证明世界环境/BGM 的另一套混响状态机制，不能用于换算作曲器参数。
路径中还存在通用 `effect_N_N.bnk` 与 `environment*.bnk`，但命名和位置不能
证明它们属于作曲器共享效果链，因此未接入工具。

共享 `sound2022/windows/init.bnk` 位于 `PAD07705`，解包后为 46,066 bytes，
`sha256=1add410a6a2459ed3a5e2ec730d2fc9eb4565cec45ffb350f6338c70e3b613df`，
BKHD 为 Wwise v145。HIRC 包含 117 Audio Bus、45 Aux Bus、34 FX ShareSet 与
11 FX Custom；插件类型可识别出 RoomVerb、Stereo Delay、Delay、Flanger、
Meter 与 Peak Limiter。固定/曲线块中能看到：

进一步交叉检查 40 个 `midi_instrument*.bnk` 的 HIRC 原始引用后，确认所有作曲
乐器都指向同三条共享 AuxBus：

- `121ef8f5` → RoomVerb ShareSet `cf841d41`；
- `15826347` → Stereo Delay ShareSet `2f24d5de`；
- `d62c1941` → Flanger ShareSet `fcbaa4ab`（承担界面 Chorus 类效果）。

这是 **bank-derived verified topology**。关联固定/曲线块显示：

- 此 RoomVerb 的 `0–100` RTPC 曲线映射到 Decay `0.2–8.0 s`；
- 两个 Delay 对象约为 `100 ms / 4% feedback` 与
  `250 ms / 15% feedback`；
- Flanger 使用约 `10 ms` 基础延迟，并带 `0–100 → -1..+1 feedback`、
  `0–0.3 Hz LFO frequency`、`30–100% LFO depth` 三条 RTPC 曲线。

这证明作曲乐器共用上述三总线及算法形态，但对象仍只有哈希 ID/ParamID；目前
没有客户端调用证据把 v9 八字节逐项绑定到具体 RTPC 输入。因此总线拓扑与曲线
是直接证据，八字节到 RTPC 的最终运行时绑定仍是推断边界。

## 已确认的 authoring 模型

游戏发送给客户端的是一份 XML：

- 每个 `<tracks>` 独立保存 `midiProgramNo`、`volume`、`reverb`、`delay`、
  `chorus`；
- 单一 `<header>` 保存 `reverbTime`、`delayFeedback`、`chorusFeedback`、
  `chorusLFODepth`、`chorusLFOFrequency`；
- 音符仍独立保存 `onVelocity` 与 `offVelocity`，因此轨道音量不是力度改写。

层级、名称、保存/加载回写路径均为 **verified**。界面范围同样明确：

| 值 | 层级 | 范围 | 默认 |
|---|---|---:|---:|
| Volume | 每乐器 | 0–100，步长 1 | 70 |
| Reverb send | 每乐器 | 0–100 | 0 |
| Delay send | 每乐器 | 0–100 | 0 |
| Chorus send | 每乐器 | 0–100 | 0 |
| Reverb Time | Master | 0–100 | 0 |
| Delay Feedback | Master | 0–100 | 0 |
| Chorus Feedback | Master | 0–100 | 0 |
| Chorus LFO Depth | Master | 0–100 | 0 |
| Chorus LFO Frequency | Master | 0–100 | 0 |

`musiccomposition.js` 会逐乐器序列化和恢复三个 Aux Send，所以它们不能用
一个全局数值覆盖所有轨道。五个 Master 参数只有一份，并在预览、正式保存、
临时保存和重新加载中走同一 XML 路径。

游戏简体中文分支把 `Chorus` 显示成“副歌”，但同一代码又明确使用
`Feedback / LFO Depth / LFO Frequency`，因此这里是 **合唱音效**，不是歌曲
结构中的副歌段落。工具应使用“合唱”或“Chorus”。

## v9 八字节设置映射

v9 每个物理轨道保存八个 setting bytes。现有曲谱差分工具与 XML 字段顺序
共同支持以下映射：

| Byte | 语义 | 层级 |
|---:|---|---|
| 0 | Reverb send | 每乐器 |
| 1 | Reverb Time | Master（在各物理轨重复） |
| 2 | Delay send | 每乐器 |
| 3 | Delay Feedback | Master（在各物理轨重复） |
| 4 | Chorus send | 每乐器 |
| 5 | Chorus Feedback | Master（在各物理轨重复） |
| 6 | Chorus LFO Depth | Master（在各物理轨重复） |
| 7 | Chorus LFO Frequency | Master（在各物理轨重复） |

八字节的宽度与无损 round-trip 是 **verified**；上表的逐字节声音语义仍是
**inferred**，直到完成每次只改一个游戏控件的保存差分、导入和游戏重保存。
因此编辑器可以按该模型保留和写回数据，但不得把声音效果标为已校准。

同一乐器超过 730 个音符时会拆成多个物理轨；其音量与八字节设置必须在这些
块中重复。工具内部有多条同乐器轨道时，游戏最终只对应一个乐器条目，冲突的
Volume/Aux 值不能静默择一。导入现在会拒绝同组物理块的 Volume/八字节冲突，
也会拒绝不同乐器组的 Master 五字节冲突；导出继续拒绝同乐器不同设置。

工具以最终写入 v9 的乐器 ID 作为共享 mixer 键；Marnian 的
Basic/Stereo/Super/Super Octave 偏移因此属于不同键。时间轴上的每条逻辑轨
只是该游戏乐器 mixer 的一个视图：

- 修改 Volume 会同步到同键的全部逻辑轨，但不改音符力度；
- 普通 FX 提交只同步本次实际改动的 Aux byte，保留其他 Aux 和五个 Master
  bytes；
- 新建同乐器轨、改乐器或改 Marnian mode 时，只能从一个内部一致的目标组
  继承；旧组已有冲突则停止操作，禁止按列表第一条静默取值；
- 历史冲突必须由用户明确执行“以此轨统一同乐器音量和 FX”，导出校验仍是
  最后一道阻断防线；
- 所有传播先完整预检再一次性应用，非法目标不得造成部分写入。

## 试听与兼容边界

- 游戏 UI 把 XML 传给原生客户端 `ToClient_RequestToPlayMusic`；JS 本身没有
  DSP、参数单位或 Wwise bus scaling。
- 当前乐器 SoundBank 已证明三条共享 AuxBus 与 RoomVerb/Delay/Flanger 曲线，
  但仍不能证明 v9 八字节在客户端运行时逐项写入哪一个 RTPC。
- 在取得共享效果 bank、运行时 RTPC 值和游戏 A/B 前，实时试听应保持
  “近似/未校准”标签。精确保存字段与近似试听必须是两个独立承诺。
- Wire byte 可容纳 `0–255`，但本工具新建/编辑值应限制在游戏 authoring
  范围 `0–100`；导入旧曲谱的 `101–255` 应原样保留并提示，不得静默截断。
  优化器插件同样只能生成 `0–100` 的效果写操作。

## 工具中的近似试听

`bdo_music_composer/audio/bdo_preview_effects.py` 按已确认的层级实现三条有界本地总线：每条轨道分别
把 PCM 送入 Reverb、Delay、Chorus；五个共享参数只配置对应主效果。所有环形
缓冲和路由 scratch 均在播放前分配，音频回调不读文件、不解析 JSON，也不按
工程规模分配内存。Stop/Seek 会清除近似效果尾音。

本地算法使用反馈梳状混响（0.2–8 s 有界曲线）、固定 250 ms 反馈延迟和
10 ms 基础调制延迟合唱。混响与 Flanger LFO/深度曲线采用上述 bank 范围；
feedback 在本地轻量处理器中限制在绝对值 0.85 以内以避免失稳。Stereo Delay
的 ParamID 语义与八字节运行时绑定仍未闭环，**不能**称作 1:1。界面因此固定
显示“未校准近似”，而 v9 导出仍由
`bdo_common/bdo_track_effects.py` 原样保留/写回八字节设置，不消费这些预览换算。

## 工具界面与状态边界

- 时间轴每个乐器行的“轨道 FX”只编辑 Reverb、Delay、Chorus 三个 Aux
  Send；它不会修改五个共享主效果参数。
- 工作区工具栏的“全局效果”打开独立主效果窗口，只编辑整首曲子共享的
  Reverb Time、Delay Feedback 与三项 Chorus/Flanger 参数；常规“设置”页面
  不再承载歌曲效果。
- 两层修改均作为工程操作进入撤销、转换检查、近似试听刷新和自动保存，但
  各自只写自己拥有的字段。主效果保存在工程/曲谱中，不写入应用级偏好。
- 新建空白工程或直接导入 MIDI 时主效果从全零开始；打开 BDO 曲谱或已有工程
  时才恢复该曲自身的主效果，避免上一首曲子的状态串入下一首。

## 可继续落实的游戏机制

同一 JS 还证明可用乐器、乐器子类型、可播放奏法和账号 `codeCount / noteCount /
max_bpm` 均由客户端运行时下发。离线 profile 只能作为版本化兼容基线，不能
冒充当前账号权限。界面静态提供 `3/4`、`4/4`、`6/8`；但 v9 单字段如何区分
分母仍缺少一变量游戏保存证据，因此本轮不修改现有节拍导出约束。
