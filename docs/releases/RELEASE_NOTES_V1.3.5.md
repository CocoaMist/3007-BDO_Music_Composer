# BDO Music Composer v1.3.5

[中文](#中文) | [English](#english)

## 中文

v1.3.5 是多轨 Clip 编排工作流的正式版本。它完成多选、移动、导航、文件拖放、
跨编辑器复制粘贴与持久化链路，并进一步降低大型 UI 所有者的维护负担。

### 主要变化

- 时间线支持框选、Ctrl 切换和 Shift 范围选择；跨轨 Clip 可作为一个确定性事务
  移动，并保持撤销、自动保存、恢复、试听和导出一致。
- 选择、剃刀和移动工具保持明确的激活状态；Clip 本体、起止手柄、吸附和悬停
  光标使用一致的命中规则。
- 支持从文件拖放插入 MIDI/BDO、键盘导航、跨音符编辑器复制粘贴，以及 Clip
  范围内的安全音符投影。
- 当前 `TrackState`/`Note` 始终是试听和导出的权威数据；工程迁移与恢复不会静默
  回退到原始 MIDI。
- 四语翻译数据从运行逻辑中分离；候选音符分类与 Clip 命中判定迁移到聚焦模块，
  并清理未使用代码。
- 新增 UI 文件/方法规模守卫和只读死代码报告；自动分析不能直接删除动态回调或
  已记录的兼容接口。

### 验证

- 本地完整自动化回归：1,351 项通过，12 项可选环境测试跳过。
- 定向契约、时间线、候选音符、国际化和架构测试：103 项通过。
- 仓库卫生、语法、补丁格式和死代码候选检查通过；死代码候选为 0。
- 本次合并发布源码；Windows 单文件发行物仍由受审查的云端发布流程构建和验证。

### 可选 CC0 音源包

本版本继续兼容 v1.2.1 的
`BDO-Approximate-CC0-Full-Coverage-v4-Compact.bdosamples`。该音源包仅包含
独立许可的 CC0 近似试听素材，不包含 Black Desert 客户端音频。

## English

v1.3.5 is the stable release of the multitrack Clip arrangement workflow. It
completes selection, movement, navigation, file-drop, cross-editor clipboard,
and persistence paths while reducing maintenance weight in the largest UI
owners.

### Highlights

- The timeline supports marquee, Ctrl-toggle, and Shift-range selection.
  Cross-track Clips move as one deterministic transaction through undo,
  autosave, recovery, preview, and export.
- Select, razor, and move tools retain explicit active state. Clip bodies,
  handles, snapping, and hover cursors share consistent hit rules.
- MIDI/BDO file-drop insertion, keyboard navigation, cross-editor note
  copy/paste, and Clip-bounded note projection are supported.
- Current `TrackState`/`Note` data remains authoritative through project
  migration, preview, recovery, and BDO export without falling back to the
  imported MIDI.
- Four-locale translation data is separated from localization logic; candidate
  classification and Clip hit-testing now have focused owners, and unused code
  has been removed.
- File/method size ratchets and a read-only dead-code report keep future UI
  growth and compatibility cleanup reviewable.

### Verification

- Full local automated regression: 1,351 passed, 12 optional-environment tests
  skipped.
- Focused contract, timeline, candidate, localization, and architecture suite:
  103 passed.
- Repository hygiene, syntax, patch-format, and dead-code-candidate checks
  passed; zero dead-code candidates remain.
- This merge publishes source. The reviewed cloud release workflow remains the
  owner of Windows one-file packaging and frozen-runtime verification.

### Optional CC0 sample pack

This release remains compatible with the v1.2.1
`BDO-Approximate-CC0-Full-Coverage-v4-Compact.bdosamples` asset. It contains
independently licensed CC0 material for approximate preview only, not Black
Desert client audio.
