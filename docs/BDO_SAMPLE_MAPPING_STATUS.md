# BDO 原始采样映射状态

数据来源：`midi_instrument_*.bnk` 的 Wwise HIRC MIDI Tracking 属性。

已从 HIRC 恢复并用于 GUI 试听的字段：

- 采样源 WEM/WAV。
- 根音（`MidiTrackingRootNote`）。
- 键位范围（`MidiKeyRangeMin/Max`）。
- 力度范围（`MidiVelocityRangeMin/Max`）。

## 已映射并使用 BDO WAV 试听

- 新手：吉他、长笛、笛子、手鼓、钹、竖琴、钢琴、小提琴。
- 弗洛凯斯特菈：原声吉他、长笛、架子鼓、贝斯、肯特拉贝斯、竖琴、钢琴、小提琴、手碟、单簧管、圆号。
- 玛勒尼斯：银色水波、高速路、赫赛德兰三把电吉他。

这部分覆盖 GUI 的 22 种直接命名 BNK 乐器，并使用 BNK 中实际 WAV 样本渲染。

## 待人工确认

四种玛勒尼斯键盘乐器已接入实时试听的 synth 4×4 路由：

- 波纹行星（`0x14`）
- 幻象树（`0x18`）
- 秘密笔记（`0x1c`）
- 三明治（`0x20`）

每种乐器默认 `basic`，可选择 `stereo`、`super`、`superoct`；16 个格子均已找到解包 WAV。底层波形族对应关系仍是暂定路由，GUI 会标记为“原声近似 / 待游戏 A/B 验证”，不会标记为 1:1 已验证。

## 关键产物

- `data/mappings/bdo_wwise_midi_map.tsv`：3579 条 Sound 节点到 WAV 的键位/力度映射。
- `data/mappings/bdo_wwise_midi_map.json`：GUI 渲染器读取的映射。
- `data/manifests/bdo_instrument_samples.tsv`：1465 个提取 WAV 的音频参数索引。
