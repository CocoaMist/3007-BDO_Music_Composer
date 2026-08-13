# BDO Music Composer v1.3.0

[中文](#中文) | [English](#english)

## 中文

v1.3.0 重点升级多音轨编排：加入可移动、裁切、剃刀切分和合并的 Clip，
并为使用同一游戏乐器的轨道提供自动分组。吸附是可切换状态，优先级为时间标记、
其他 Clip、网格。跨轨移动保持音符位于 Clip 边界内；合并前会报告重叠并要求确认。

### 主要变化

- 多音轨 Clip 选择、移动、调整边界、剃刀切分与安全合并。
- 同游戏乐器轨道自动成组，提供整组选择、静音与独奏，并使用音轨组颜色呈现。
- 吸附开关与稳定的“时间标记 > Clip > 网格”优先级。
- 改进多音轨工具栏、右键菜单、乐器切换与音量/效果共享冲突提示。
- 更新英文界面截图、README 与第三方开源项目致谢。
- 保持当前编辑模型到 BDO v9 导出的完整性，不回退读取原始 MIDI。

### 可选 CC0 音源包（复用 v1.2.1 资产）

本版本继续兼容 v1.2.1 已发布的
[`BDO-Approximate-CC0-Full-Coverage-v4-Compact.bdosamples`](https://github.com/CocoaMist/3007-BDO_Music_Composer/releases/download/v1.2.1/BDO-Approximate-CC0-Full-Coverage-v4-Compact.bdosamples)。
无需重新下载或重新选择已有本地副本。该包为 753,225,838 字节，SHA-256：
`82cea29f1316b943571663e4150b31e353da4ab9f556141ed65b6598a384db63`。
它仅包含独立许可的 CC0 近似试听素材，不含 Black Desert 客户端音频。

## English

v1.3.0 focuses on multitrack arrangement. Clips can be moved, trimmed, split
with the razor, and merged, while tracks routed to the same in-game instrument
are grouped automatically. Snap is a toggle with marker, clip, then grid
priority. Cross-track moves keep notes inside clip bounds, and merges report
overlap and require confirmation.

### Highlights

- Multitrack clip selection, movement, trimming, razor splitting, and safe merge.
- Automatic same-instrument groups with group selection, mute, solo, and track-group colors.
- Stateful snapping with stable marker > clip > grid priority.
- Improved multitrack controls, context menus, instrument switching, and shared mixer conflict notices.
- Refreshed English-interface screenshots, README, and open-source acknowledgements.
- Preserved current-editor-model export to BDO v9 without falling back to the original MIDI.

### Optional CC0 sample pack (reused v1.2.1 asset)

This release remains compatible with the v1.2.1
[`BDO-Approximate-CC0-Full-Coverage-v4-Compact.bdosamples`](https://github.com/CocoaMist/3007-BDO_Music_Composer/releases/download/v1.2.1/BDO-Approximate-CC0-Full-Coverage-v4-Compact.bdosamples)
asset. Existing local copies do not need to be downloaded or selected again.
The pack is 753,225,838 bytes with SHA-256
`82cea29f1316b943571663e4150b31e353da4ab9f556141ed65b6598a384db63`.
It contains independently licensed CC0 material for approximate preview only,
not Black Desert client audio.
