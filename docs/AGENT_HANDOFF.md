# Agent 接手与协作手册

本手册是 AI Agent、自动化编码助手和新维护者接手 BDO Music Composer 的统一入口。它不替代根目录的 `AGENTS.md`：`AGENTS.md` 是强制规则，本手册负责把规则转化为可执行的接手、开发、验证和交接流程。

## 1. 必读顺序

开始改动前按顺序完整阅读：

1. [`AGENTS.md`](../AGENTS.md)：仓库级硬约束、命令和完成定义。
2. 对应语言的完整 README：[`简体中文`](../README.zh-CN.md)、[`English`](../README.en.md)、[`日本語`](../README.ja.md)、[`한국어`](../README.ko.md)。
3. [`ARCHITECTURE.md`](ARCHITECTURE.md)：组件和端到端数据流。
4. [`AI_CONTEXT.md`](AI_CONTEXT.md)：按任务类型定位文件、约束和验证矩阵。
5. 当前任务对应的领域文档，不要无目的地读取整个 `docs/`。

如果这些资料与代码冲突，以可重复测试和当前代码为事实，并在同一个变更中修正文档；二进制格式、许可和隐私边界不允许仅凭猜测修改。

## 2. 接手前五分钟

先建立可追踪的基线：

```powershell
git status --short
git diff --stat
rg --files -g "AGENTS.md" -g "!build" -g "!dist"
.\.venv\Scripts\python.exe -m py_compile main.py project_paths.py pyside_bdo_gui.py i18n.py
```

- 工作树中的既有改动都属于用户；不要重置、覆盖或顺手格式化无关文件。
- 确认任务是“检查/解释”还是“实现”。检查类任务默认只读；实现类任务才修改文件。
- 先找到现有扩展边界和测试，再决定是否新建模块。
- 记录变更前失败项。不要把既有失败误报成新回归，也不要用跳过测试掩盖失败。

## 3. 系统使命与核心数据流

本项目把 MIDI 或当前编辑器模型转换为 Black Desert v9 曲谱，并提供本地预览、扒谱辅助、优化、自动保存和无损 BDO 文档编辑。

```text
MIDI / BDO v9
  -> TrackState + Note（当前编辑器事实源）
  -> 编辑 / 扒谱审阅 / 优化
  -> 不可变导出快照
  -> bdo_export
  -> bdo_codec
  -> 原子发布到输出目录与游戏目录
```

最重要的原则：导出必须使用当前 `direct_tracks` / `TrackState`，绝不能偷偷重新读取原始 MIDI。手工创建、删除、移动、缩放和 `ntype=0` 编辑都必须保留。

## 4. 模块路由

| 任务 | 首要模块 | 边界说明 |
|---|---|---|
| 主窗口信号和工作流编排 | `pyside_bdo_gui.py` | 只放 UI 编排；新领域逻辑优先进入聚焦模块 |
| 模型 revision / 转换校验 | `model_revision.py`, `conversion_validation_controller.py` | 可变轨道必须经过显式 mutation boundary；快照只按 revision/语言复用 |
| 轨道/音符共享模型 | `editor_models.py`, `bdo_midi/` | `Note(pitch, vel, start, dur, ntype)` 线形状不可随意改变 |
| 时间轴/钢琴卷帘 | `timeline_canvas.py`, `piano_roll_canvas.py`, `midi_note_editor.py` | 绘制必须保持可见区索引和批处理 |
| 设置、检查、优化、致谢 | `application_settings_dialog.py`, `conversion_check_dialog.py`, `optimizer_dialog.py`, `acknowledgements_dialog.py` | 对话框自主管布局和展示，主窗口只注入状态并应用结果 |
| 优化算法 | `optimization/` | `builtin.py` 是生产管线，`registry.py` / plugin API 是扩展边界 |
| 实时预览 | `bdo_realtime_audio.py`, `bdo_sample_renderer.py` | 音频回调禁止磁盘 I/O、解码和无界分配 |
| 扒谱 | `bdo_transcription*.py`, `transcription_workers.py` | 分析后台运行；正式音符只能经用户确认写回 |
| 扒谱 worker/审阅编排 | `transcription_workspace_controller.py`, `bdo_transcription_session.py` | coordinator 输出范围/审阅 plan；session 拥有候选命令和稳定时间索引，陈旧结果不得写回 |
| 导出 | `export_workflow.py`, `bdo_export/`, `bdo_codec/` | GUI 线程冻结快照；发布必须原子化 |
| 工程与首页 | `project_persistence.py`, `project_schema.py`, `home_catalog.py` | 自动保存后台序列化；首页只读安全小索引 |
| 工程载入 gate | `project_lifecycle_controller.py` | generation 防止陈旧完成事件解除新载入状态 |
| 预览传输状态 | `preview_transport_controller.py` | coordinator 只选择命令并保存 session 状态，不做 I/O/DSP；设备与 callback 仍归音频引擎 |
| 本地化 | `i18n.py` | 现有中文固定文本是 source key；动态音乐数据不翻译 |
| 路径与打包 | `project_paths.py`, `BDOMusicComposer.spec`, `packaging/` | 冻结构建的可写数据不得进入 `sys._MEIPASS` |

更具体的路由见 [`AI_CONTEXT.md`](AI_CONTEXT.md)，当前重构候选和性能门槛见 [`OPTIMIZATION_EXTENSION_ROADMAP.md`](OPTIMIZATION_EXTENSION_ROADMAP.md)。

## 5. 不可破坏的不变量

### 编辑和导出

- `Note` wire shape 保持 `Note(pitch, vel, start, dur, ntype)`，除非同时设计迁移和回归测试。
- 鼓组采用规范 BDO 音高 48–64，需要时使用 `ntype=99`。
- Marnian 模式 ID 为基础乐器 ID 加 `0..3` 偏移。
- BDO v9 小端；音符记录 20 字节 `<BBBBdd>`；单物理轨最多 730 音符；每乐器必须带空结尾轨；加密明文按 8 字节对齐。
- Owner ID 无效或拍号不是 `/4` 时必须明确拒绝导出。
- 用户目标文件不得原地截断；用同目录临时文件、刷新后原子替换。

### 优化器

- game-safe 模式不应意外改变音符数量、音高多重集、乐器映射或无关轨道。
- 单轨优化可以读全曲上下文，但只能写目标轨。
- UI 只有一个“MIDI 优化”工作台；作用范围是算法之前的首层选择，不要重新维护全局/单轨两套对话框。
- 全工程范围不可删除：跨轨写入、派生轨和全局效果写操作只允许在该范围发生；允许写入的轨道仍在详细信息中显式限制。
- 音符编辑器传入的是未提交草稿，必须用 `scope_locked=True` 固定为当前轨；主窗口应用结果时使用对话框最终的 `target_track_id`，不要复用打开入口的参数。
- 手工奏法除非对当前乐器无效，否则保留。
- 相同输入必须产生确定性输出；适用时还要验证幂等性。

### 实时音频与 UI

- 音频回调中不得读文件、解析 JSON、解码 WAV 或无界分配。
- 采样预载和解码必须在播放前或 GUI/音频线程外完成。
- 时间轴、钢琴卷帘和证据层绘制不得退化为全量音符/帧扫描。
- 缺少游戏 A/B 证据的预览只能标为 approximate，不能称为 verified。

### 隐私、许可和本地化

- Owner ID、角色名、游戏音频、参考音频、导出曲谱、本机路径和本地配置不可提交。
- 不得把游戏提取资产或 `.bdosamples` 放进构建和仓库。
- 第三方许可仍归上游；根 `LICENSE` 只覆盖原创项目代码。
- 新固定 UI 文本必须补齐英文、日文和韩文目录；曲名、轨名、文件名和音符名不翻译。

## 6. 标准实施流程

1. 用 `rg` 找到入口、调用者、测试和文档。
2. 写下改动会触及的模型、线程、文件和用户数据边界。
3. 优先扩展现有聚焦模块；如果主窗口只是在拼装 UI，把新逻辑放到独立模块。
4. 对后台工作创建不可变请求/快照，不把可变 Qt/编辑器对象直接交给 worker。
5. 直接改变 `TrackState` 或其 `notes` 后必须经过模型 mutation boundary 推进 revision；纯缩放、平移和绘制刷新不得推进。
6. 迁移主窗口公开状态时保留兼容 property，并让单一控制器成为唯一 owner；不要让兼容列表和控制器各保留一份副本。
7. 修改最小范围，并保留旧导入路径或显式迁移接口。
8. 先跑聚焦测试，再跑完整回归。
9. 同步架构、README 或领域文档，最后检查 diff 和私密/生成文件。

不要为了降低文件行数机械拆分相互强耦合的方法。一个成功的拆分应当同时满足：拥有清晰职责、没有反向导入 `pyside_bdo_gui`、可独立测试、主窗口只保留编排。

## 7. 验证矩阵

| 改动类型 | 最低验证 |
|---|---|
| UI/布局 | `py_compile`、完整单元测试、`QT_QPA_PLATFORM=offscreen` 控件烟测 |
| 音符编辑/选择 | 编辑器烟测、导出 round trip |
| 优化/理论/奏法 | 优化器测试、确定性和幂等性检查 |
| 音频引擎 | 实时音频测试、检查 callback 分配和 I/O |
| 序列化/导出 | `test_bdo_codec.py`、`test_bdo_export_roundtrip.py`、二进制结构检查 |
| 本地化/README | `test_i18n_catalog.py`、语言切换烟测、`test_readme_locales.py` |
| 打包/资源 | 干净 PyInstaller 构建、转录自测、10 秒以上启动测试 |

常用命令：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -q
.\.venv\Scripts\python.exe -m py_compile main.py project_paths.py pyside_bdo_gui.py i18n.py
git diff --check
git status --short
```

除非用户明确需要可分发产物，不要构建 EXE。

## 8. 性能变更规则

- 先用 `tools/benchmark_dense_ui.py` 或聚焦基准记录数据，再改热点。
- 转换校验快照使用 `tools/benchmark_conversion_validation.py` 记录 10k、50k、100k 音符的 cold scan 与 cache hit。
- 扒谱候选范围使用 `tools/benchmark_transcription_candidate_queries.py`；同时记录索引构建、命中数和 `query_inspections`，不要只记录墙钟时间。
- 记录数据规模、可见范围、冷/热缓存、运行次数和机器环境。
- 墙钟时间用于诊断；正确性门槛优先约束可见查询数量、缓存身份、分配上限和回调 I/O。
- 不以“可能更快”为理由引入模型缓存；可变 `TrackState` 的缓存必须有可靠失效边界。
- 当前转换校验缓存的唯一合法失效键是显式 model revision 加语言 scope；不要另建平行 fingerprint/cache。
- 候选集合查询必须复用 `TranscriptionSession` 的稳定顺序和区间 API；不要在主窗口、editor 或 canvas 再建 selected/A–B 全曲扫描。
- 绘制、音频回调和 GUI 线程 I/O 是高风险区，必须增加回归测试。

## 9. Agent 对接包模板

当任务需要转交给另一个 Agent 或维护者时，提供以下信息，不要只写“继续优化”：

```markdown
## 目标
一句话描述最终可验证结果。

## 当前状态
- 已完成：
- 未完成：
- 当前工作树/分支：

## 变更范围
- 已改文件：
- 不应触碰的用户改动：
- 关键入口与调用链：

## 不变量与风险
- 相关数据/线程/二进制/隐私约束：
- 已知风险或未证实假设：

## 验证证据
- 已运行命令和结果：
- 尚需运行：

## 下一步
1. 可执行步骤
2. 完成判据
```

接手者应先验证这份对接包仍与工作树一致；文件会被其他协作者同时修改时，重新读取再打补丁。

## 10. 完成定义

只有在以下条件同时满足时才算完成：行为已经实现；相关测试和完整回归通过；用户数据和生成物没有进入 Git；接口或不变量变化已同步文档；未请求的 EXE 没有被构建；最终交付明确列出变更、验证和仍存在的风险。
