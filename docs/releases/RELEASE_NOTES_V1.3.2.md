# BDO Music Composer v1.3.2

[中文](#中文) | [English](#english)

## 中文

v1.3.2 是 Clip 编辑工作流的 P0 稳定性版本。时间线、混音轨道与 Clip
音块编辑器现在共享一致的实时数据源，补齐了创建、选中、缩放、删除、提交、
自动保存和恢复链路，避免编辑看似成功但实际丢失。

### 主要变化

- Clip 音块编辑器与外部时间线实时同步；新增、移动、缩放和删除音块会立即反映到混音视图，完成或关闭编辑器不会丢失已提交修改。
- Clip 外部边界缩放不能越过已有音块；编辑器内可安全调整 Clip 时长，并保持绝对时间和相邻 Clip 不变。
- 时间线右键可创建 Clip；Clip 右键菜单和选中后的 Delete/Backspace 均可删除，并纳入撤销与自动保存。
- Clip 获得明确、逐 Clip 的可见选中态；切换选择、点击空白和轨道数据刷新都会正确清理过期选择。
- 自动保存快照覆盖 Clip 结构、当前 TrackState 和多编辑器提交，恢复后保持最新编辑内容。
- 修正属性输入框按 Enter 时意外触发播放、暂停后播放头继续推进，以及复制粘贴、空 Clip、并发编辑和编辑作用域中的同类边界问题。
- 时间线继续使用可见区间索引、静态绘制缓存和增量刷新，降低多轨大工程中选择与编辑的重绘成本。

### 验证

- 完整自动化回归：1296 项通过，1 项跳过。
- 覆盖 Clip 事务、编辑器交互、选择渲染、时间线增量更新、区间索引、力度刷新效率、导出与自动保存。
- 正式 Windows EXE 由云端发布工作流完成依赖审计、完整测试、打包、转录自检和离屏启动自检。

### 可选 CC0 音源包（复用 v1.2.1 资产）

本版本继续兼容 v1.2.1 已发布的
[`BDO-Approximate-CC0-Full-Coverage-v4-Compact.bdosamples`](https://github.com/CocoaMist/3007-BDO_Music_Composer/releases/download/v1.2.1/BDO-Approximate-CC0-Full-Coverage-v4-Compact.bdosamples)。
已有本地副本无需重新下载。该包仅包含独立许可的 CC0 近似试听素材，
不含 Black Desert 客户端音频。

## English

v1.3.2 is a P0 stability release for the Clip editing workflow. The timeline,
mixer tracks, and Clip note editor now share one live source of truth across
creation, selection, resizing, deletion, commit, autosave, and recovery, so an
edit can no longer appear successful while being silently discarded.

### Highlights

- The Clip note editor and external timeline synchronize live; note creation, movement, resizing, and deletion are reflected immediately, and completing or closing the editor preserves committed work.
- External Clip bounds cannot be resized across occupied notes; Clip duration can be adjusted safely inside the editor without displacing sibling Clips or absolute timing.
- The timeline context menu can create Clips; the Clip menu and Delete/Backspace remove the selected Clip with undo and autosave coverage.
- Clips have an explicit per-Clip visual selection state; switching selection, clicking empty space, and refreshing track data clear stale selections correctly.
- Autosave snapshots cover Clip structure, current TrackState data, and multi-editor commits, preserving the latest authored state on recovery.
- Fixed Enter in property fields accidentally starting playback, the playhead advancing after Pause, and related copy/paste, empty-Clip, concurrent-edit, and editor-scope edge cases.
- Visible-range indexing, static paint caching, and incremental refreshes reduce redraw work in large multitrack projects.

### Verification

- Full automated regression: 1296 passed, 1 skipped.
- Coverage includes Clip transactions, editor interaction, selection rendering, incremental timeline updates, interval indexing, velocity refresh efficiency, export, and autosave.
- The official Windows EXE is produced by the cloud release workflow with dependency auditing, the complete test suite, packaging, transcription self-test, and offscreen startup self-test.

### Optional CC0 sample pack (reused v1.2.1 asset)

This release remains compatible with the v1.2.1
[`BDO-Approximate-CC0-Full-Coverage-v4-Compact.bdosamples`](https://github.com/CocoaMist/3007-BDO_Music_Composer/releases/download/v1.2.1/BDO-Approximate-CC0-Full-Coverage-v4-Compact.bdosamples)
asset. Existing local copies do not need to be downloaded again. The pack
contains independently licensed CC0 material for approximate preview only,
not Black Desert client audio.
