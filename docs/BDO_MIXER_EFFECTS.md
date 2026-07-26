# BDO 作曲混音与效果证据

本文只记录可由游戏作曲界面与 v9 曲谱结构支持的事实。`0–100` 是游戏
authoring 控件值，不是 dB、毫秒、Hz 或 Wwise 原生参数；没有游戏录音 A/B
前，不得据此猜测 DSP 换算或宣称试听 1:1。

## 本地只读证据

2026-07-26 对 PAZ meta v757 做了限定路径扫描，只读取以下资源：

- `ui_data/ui_html/contents/js/musiccomposition.js`
  (`sha256=714f2fa753997ae397a509b0010b2a892d79a2fb551e1513021fdd98b2038a23`)；
- `ui_data/ui_html/window/musiccomposition/index.html`
  (`sha256=6e25e5876941eb57bcc0892a920022afd39ef44d7667410468bd6d6400e9fa1e`)。

PAZ meta 哈希为
`5bf64283d48aaee328486f027e41af13fbe10375ab18b7db324d9a4e539bdb81`。
没有导出或签入游戏文件；以上哈希和字段结构足以复核版本。

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
Volume/Aux 值不能静默择一，应在导出前要求合并或选择。

## 试听与兼容边界

- 游戏 UI 把 XML 传给原生客户端 `ToClient_RequestToPlayMusic`；JS 本身没有
  DSP、参数单位或 Wwise bus scaling。
- 当前乐器 SoundBank 只能证明采样、Event、父链增益和部分 Aux/Bus 引用，
  不能证明上述 `0–100` 如何映射到混响时长、延迟时间或 Chorus LFO。
- 在取得共享效果 bank、运行时 RTPC 值和游戏 A/B 前，实时试听应保持
  “近似/未校准”标签。精确保存字段与近似试听必须是两个独立承诺。
- Wire byte 可容纳 `0–255`，但本工具新建/编辑值应限制在游戏 authoring
  范围 `0–100`；导入旧曲谱的 `101–255` 应原样保留并提示，不得静默截断。

## 可继续落实的游戏机制

同一 JS 还证明可用乐器、乐器子类型、可播放奏法和账号 `codeCount / noteCount /
max_bpm` 均由客户端运行时下发。离线 profile 只能作为版本化兼容基线，不能
冒充当前账号权限。界面静态提供 `3/4`、`4/4`、`6/8`；但 v9 单字段如何区分
分母仍缺少一变量游戏保存证据，因此本轮不修改现有节拍导出约束。
