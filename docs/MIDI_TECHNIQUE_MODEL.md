# MIDI 奏法语义模型

## 设计边界

真实奏法、MIDI 表达和 BDO `ntype` 是三个不同层次：

1. `TechniqueProfile` 表示乐器演奏语义，不依赖某一音源。
2. MIDI 证据由音符门限、力度、CC、Pitch Bend、Aftertouch、Poly Aftertouch 和节奏形态组成。
3. `TechniqueMap` 只描述某个厂商、产品或预置的 Keyswitch/CC/Program Change 映射。
4. BDO `ntype` 只有通过游戏内 A/B 验证后才允许自动写入。

不得把厂商预置的 C-1、CC32 等映射当成通用 MIDI 标准。

## MIDI 2.0 分类

内部注册表覆盖 MIDI Orchestral Articulation Profile 的八个公共分类：

| 分类 | 内部用途 |
|---|---|
| `0x10` | 核心持续音与击奏 |
| `0x11` | 持续型附加音色 |
| `0x12` | Staccato 与短奏 |
| `0x13` | 快速 Tremolo、同音重复 |
| `0x14` | 音程颤音 |
| `0x15` | 音高与力度手势 |
| `0x16` | 音阶、跑动、琶音 |
| `0x17` | 效果与噪声 |

`0x18..0x1F` 保留给设备或厂商自定义，不参与通用自动推断。

## 当前 MIDI 证据

- 音符：门限比例、音间间隙、局部力度峰值、重复速度、音程方向、滚奏和弦方向。
- 踏板：CC64 延音/半踏板、CC66 Sostenuto、CC67 Soft Pedal。
- 动态：CC11 曲线及音符力度曲线。
- 音高：Pitch Bend 单向手势、振荡手势和 Portamento CC65。
- 音色：CC74 曲线。
- 压力：Channel Aftertouch 与 Poly Aftertouch。
- MPE：保留逐音符通道事件；当前 MIDI 1.0 轨模型先作为证据读取，未来升级为逐音符控制归属。

## 乐器家族词表

注册表覆盖弓弦、木管、铜管、吉他、贝斯、键盘、竖琴、鼓组、手打击、合成器和人声。当前包含 69 个语义奏法，包括：

- 弓弦：legato、detache、spiccato、pizzicato、tremolo、harmonic、sul ponticello、sul tasto、col legno、con sordino、上下弓。
- 木管/铜管：吐音、双吐、三吐、flutter tongue、key click、whistle tone、growl、stopped、fall、doit、scoop、换气。
- 吉他/贝斯：palm mute、bend、slide、hammer-on、pull-off、harmonic、slap/pop、ghost、strum、tapping、rake。
- 键盘/竖琴：延音、半踏板、sostenuto、soft pedal、琶音、滑奏、制音。
- 鼓与打击：ghost、flam、roll、rim shot、cross stick、brush、开闭镲、choke、damp。
- 合成器：gate、filter sustain、arpeggiator、CC74 timbre sweep、aftertouch swell。
- 通用：accent、marcato、tenuto、staccatissimo、vibrato、portamento、crescendo、diminuendo、sforzando。

未映射到 BDO 的奏法必须显示为 MIDI 近似或仅建议。

## 主要资料

- MIDI Association, Orchestral Articulation Profile overview: https://midi.org/wp-content/uploads/2024/03/Orchestral-APE-Profile-Intro-Final.pdf
- MIDI Association, MPE Profile: https://midi.org/midi-ci-profile-for-midi-polyphonic-expression
- MIDI Association, adopted MIDI-CI Profiles: https://midi.org/6-new-profile-specifications-adopted
- Steinberg, Dorico playing techniques: https://www.steinberg.help/r/dorico-se/6.1/en/_shared/topics/dorico/dorico_popovers/dorico_popovers_playing_techniques_playing_techniques_r.html
- Steinberg, Cubase Expression Maps: https://www.steinberg.help/r/cubase-pro/15.0/en/cubase_nuendo/topics/expression_maps/expression_maps_c.html
- Orchestral Tools controller reference: https://orchestraltools.helpscoutdocs.com/article/199-controller-table-annotated-list
- Spitfire Audio articulation switching: https://support.spitfireaudio.com/en/articles/11816120-switching-articulations-in-spitfire-libraries

