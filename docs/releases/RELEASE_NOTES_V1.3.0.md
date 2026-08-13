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

### 发行资产与验证

- `BDO-Music-Composer.exe`：`183,257,906` 字节；SHA-256
  `d96614c8c01c1645098d3bc9ac607c30b9bc1f0aef4bc98cad035fc39a50ba21`。
- 游戏映射、Marnian 模式、鼓组语义、BDO v9 编解码和导出回读专项测试
  102 项通过；本地完整套件 1,267 项通过、1 项跳过。
- 正式构建的依赖许可清单、冻结 Basic Pitch/CPU 推理和 10 秒 GUI 启动自检通过。

本版本未使用 Authenticode 发布者签名，Windows SmartScreen 可能显示“未知发布者”。
本项目是非官方社区工具，与 Pearl Abyss 无隶属关系。

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

### Release assets and verification

- `BDO-Music-Composer.exe`: `183,257,906` bytes; SHA-256
  `d96614c8c01c1645098d3bc9ac607c30b9bc1f0aef4bc98cad035fc39a50ba21`.
- All 102 focused game-mapping, Marnian-mode, percussion, BDO v9 codec, and
  export round-trip tests passed; all 1,267 local tests passed with one skipped.
- The public dependency inventory, frozen Basic Pitch/CPU inference, and
  ten-second GUI startup self-test passed.

This release is not Authenticode publisher-signed, so Windows SmartScreen may
show an unknown-publisher warning. This is an unofficial community tool and is
not affiliated with Pearl Abyss.
