# 解耦、性能与扩展路线图

本文记录对当前代码结构的持续审计。目标不是追求文件数量，而是在保持编辑、预览、自动保存和 BDO v9 导出不变量的前提下，给下一轮重构提供可量化的边界。

## 当前基线

- `pyside_bdo_gui.py` 已从约 24,540 行降至 8,800 行以内，职责从“大型组件定义集合”收敛为主窗口编排和兼容导出。
- 设置、轨道 FX、转换检查、优化器、致谢、时间轴、钢琴卷帘、音符编辑器、参考音频、后台 worker 和共享控件均已有独立模块。
- 新抽离模块禁止反向导入 `pyside_bdo_gui`，由边界测试锁定。
- 时间轴与钢琴卷帘已经使用可见时间区间索引、绘制批处理和缓存；实时音频已经使用有界 voice pool 和预分配 scratch buffer。
- 自动保存和导出都在 GUI 线程冻结不可变快照，再交给后台线程和原子发布边界。
- `bdo_music_composer/editor/model_revision.py` 现提供显式、单调递增的模型 revision；转换校验不再依赖可变列表身份或额外的全曲指纹扫描。
- 扒谱分析、混合审阅历史、工程载入和预览传输状态已分别进入 Qt-free controller/coordinator，主窗口保留兼容属性和 UI/I/O 编排。
- `bdo_music_composer/project/project_document.py` 已把迁移、路径/字段校验、完整轨道构造和所有工程 metadata
  收敛为 `ProjectLoadPlan`；`ProjectOpenRequest` 只保留其中的 source-format 与恢复
  路由事实。主窗口读取文本、映射错误并一次性提交计划。
- `ProjectMetadataSnapshot` 已递归深冻结保存 metadata；自动保存 worker 不再持有
  GUI 所有的嵌套字典/列表。
- 第二阶段包迁移先迁移 6 个 Qt-free 编辑器 owner，再迁移 5 个对话框 owner
  和 2 个主题 owner；后续又将 5 个编辑器 Qt owner 收拢到
  `bdo_music_composer/ui/editor/`。调用方全部直接使用 canonical 包路径，未
  保留根目录 shim；应用版本事实也已收归
  `bdo_music_composer/app/application_metadata.py`。根 Python 文件约束由
  69 降到 52；7–10 个根文件仍是长期演进方向，不是当前已完成状态。
  `bdo_music_composer/editor/` 保持 Qt-free，
  `bdo_music_composer/ui/{dialogs,editor,theme}/` 的 initializer 保持 inert。

## 本轮已落实

`bdo_music_composer/ui/dialogs/acknowledgements_dialog.py` 现在拥有致谢 HTML、许可证链接、复制动作和完整 Qt 布局。主窗口只注入当前主题并打开对话框。这样许可证展示可独立测试，也避免新增致谢项时触碰主窗口编排。

第一批控制器边界也已接入：

- `ConversionValidationController` 按 `(model revision, UI language)` 保留一个不可变 `ValidationSnapshot`，相邻的转换检查与时间轴提示复用同一结果。
- `TranscriptionAnalysisCoordinator` 统一拥有整曲/区间 worker generation，并确定性合并 assist restart 请求。
- `TranscriptionReviewController` 统一拥有 session/assist 混合动作顺序、不可变 assist 快照撤销/重做、分支失效和 100 项有界历史；`TranscriptionSession` 仍拥有候选领域命令。
- `TranscriptionSession` 现统一拥有候选稳定顺序、ID→候选、起点时间和前缀最大结束时间索引；主窗口与编辑器不再各自扫描候选来解释 selected-first/A–B 审阅范围。
- `ProjectLifecycleController` 用 generation 防止陈旧载入完成回调提前解除 loading gate。
- `PreviewTransportCoordinator` 统一拥有试听 generation、loading/active/source/start/tracks 和验证状态，并把 Play 请求确定性归类为等待载入、恢复或新建 session；音频引擎仍只负责 DSP 与设备生命周期。
- `TranscriptionCommitPlan` 已把编辑器草稿、候选 route、正式轨重复/失效判断和
  sidecar 结果收敛为确定性纯计划；Qt 执行器现先原子发布 sidecar、轨道和撤销
  历史，失败恢复原 `TrackState` 对象与两套历史；view 刷新失败仍继续 autosave。

本轮全局结构收口继续完成：事务式
`bdo_music_composer.editor.editor_import` 取代主窗口里的三套解析；
配置、延迟 profile、首页/启动展示、可见区间查询分别进入小型 owner；Codec
不再包含编辑器适配，原 BDO 文档复用与摘要归入 `bdo_export`；当前 schema 不再
重复烘焙力度；`validate_tracks()` 拆成按规则域命名的阶段。架构测试同时限制依赖
方向、主窗口行数和聚焦函数跨度，防止这些边界再次长回去。
标准 MIDI 投影也已迁入
`bdo_music_composer/editor/preview_midi_writer.py`；主窗口仅兼容重导出同一函数，
不会把标准 MIDI 与 BDO v9 导出/游戏效果表达混成一条路径。

### MIDI 优化界面统一

全局优化能力继续保留，但不再作为独立工具展示。主工具栏和轨道入口共用一个“MIDI 优化”工作台，作用范围提升到算法之前：

- `整个工程` 读取全部轨道，可在详细信息中收窄允许写入的轨道，并允许算法返回跨轨、派生轨和全局效果写操作。
- `单轨` 同样读取全曲乐理/配器上下文，但只允许写入目标轨，禁止全局效果与派生轨。
- 从主工具栏或轨道上下文打开时可切换范围；音符编辑器持有未提交草稿，只能以 `scope_locked=True` 锁定当前轨。
- 范围变化会使旧预览失效，并在内存中按算法声明的 scope 重新筛选；只有显式刷新才扫描算法包目录。应用状态使用最终范围，不依赖最初入口。

这项统一减少了入口和概念重复，同时保留了真实的作用域权限边界。后续新增算法只声明能力与 scope，不得自行增加另一套“全局优化”窗口。

## 下一阶段解耦优先级

### P1：扒谱工作区控制器

目前 `MidiToBdoWindow` 中最密集的区域仍是扒谱候选路由、和声/声部分组和 UI 同步。worker generation 与 restart 状态已迁入 `TranscriptionAnalysisCoordinator`，混合审阅历史已迁入 `TranscriptionReviewController`，正式 Apply/OK 决策已迁入 `TranscriptionCommitPlan`；下一步建立 `TranscriptionWorkspaceHost` 协议，再按三段迁移：

1. `TranscriptionReviewController`：混合撤销/重做、eligible/reject/restore、疑似碎音选择和索引化 route 暂存已完成。
2. `TranscriptionCommitPlan`：最终音符、创建/满足/无效/孤立/未解决 route、临时新轨和 sidecar 变化的纯计划已完成；UI 执行的 rollback/补偿边界也已落地。下一切片不再扩展提交器，转向 presenter；不得向 planner 传入 `QWidget` 或可变 `TrackState`。
3. `TranscriptionAnalysisCoordinator`：继续迁移启动/取消、worker 结果和缓存恢复；generation/restart 已完成。
4. `TranscriptionWorkspacePresenter`：把领域状态投影成按钮状态、状态文本和可见图层，不重新计算 route/commit 规则。

完成判据：控制器不导入主窗口；领域决策可在无 Qt 窗口条件下测试；主窗口只连接 signal、选择当前轨和提交用户确认结果。

### P1：工程生命周期控制器

打开 MIDI/BDO、工程快照、自动保存和首页刷新仍由主窗口串联。`ProjectLifecycleController` 已接管 loading generation/gate；`bdo_music_composer.project.project_document.prepare_project_load()` 已生成完整 `ProjectLoadPlan`，`ProjectMetadataSnapshot` 已递归冻结保存 metadata。类型化 load/save 输入已经完成，且 `bdo_music_composer/project/project_persistence.py` 和 `export_workflow.py` 继续分别作为工程存储与导出事实源。下一步不是再造 request，而是为计划的 UI 提交阶段建立窄的执行/回滚边界，并把 model/view/transport 刷新域分开。不要把 `QWidget` 或可变 `TrackState` 交给后台 writer。

下一阶段判据：载入计划提交中任何 UI/资源步骤失败都能恢复旧工程状态；纯 view 刷新不推进模型 revision；现有迁移、深冻结、路径和隐私测试保持通过。

### P2：预览传输编排

`PreviewTransportCoordinator` 已接管试听 session 状态、陈旧 generation 判定和 Play 请求分类。下一步迁移暂停、定位、参考音频对齐和采样包准备命令；这些命令应返回 Qt-free plan，由主窗口执行设备/UI 副作用。实时 DSP 继续留在 `bdo_realtime_audio.py`，不能因抽层把磁盘读取带入 callback。

### 暂不拆分

小型窗口响应布局、工具栏构建和主页面切换仍与 Qt widget 生命周期紧密相关。除非出现重复实现或独立测试需求，不为了行数单独抽取。

## 性能审计

### 已有正确性门槛

- 时间轴/钢琴卷帘只查询可见音符，且对绘制状态批处理。
- 证据层使用固定时间 tile 和有界 LRU，`paintEvent` 不加载 NPY、不运行模型。
- 首页目录枚举分批让出事件循环，小索引避免读取大型工程正文。
- 音频样本解码并发去重；callback 不读盘，临时数组和 voice pool 有界。
- `tools/benchmark_dense_ui.py` 覆盖 48k 时间轴、12k+8k 卷帘和 12k/50k/100k 可见查询。

### 已落实：转换校验快照

`_refresh_timeline_validation()` 经 80 ms 防抖后调用全曲 `validate_tracks()`。大工程中，音符变化后全量校验是正确的，但纯视图变化或紧邻的“转换检查 + 时间轴刷新”可能重复扫描。

现已引入不可变 `ValidationSnapshot` 和显式 model revision。结构、pitch plan、乐器/奏法或影响导出的设置变化通过统一 mutation/refresh 边界推进 revision；语言作为独立 scope key。缩放适配调用明确使用 `model_changed=False`，不会使快照失效。

`TrackState.notes` 仍可原地修改，因此直接修改者必须经过 `_refresh_tracks()` / `_on_track_changed()` 或显式 revision 边界。控制器不会根据对象身份或列表长度猜测变化，也不会为了缓存再做一次 O(N) 指纹扫描。`tools/benchmark_conversion_validation.py` 分别记录 10k、50k、100k 音符的首次全量校验、cache-hit 延迟和快照身份复用。

### 已落实：时间轴共享区间索引

`bdo_music_composer/ui/editor/timeline_canvas.py` 不再维护匿名八元组索引，而是构建类型化轨道索引并复用
`bdo_music_composer/editor/interval_index.py`。开始/结束投影只在轨道替换时计算一次；可见查询通过二分和
block-max 排除不可能重叠的前缀，同时保留跨越整个视口的长音符。结构测试直接
限制检查项数量，不把受机器负载影响的墙钟数据冒充已验证提速。

### 已落实：扒谱候选索引与审阅计划

分析候选、审阅 sidecar 和正式轨道之间存在多种投影。`TranscriptionSession.set_candidates()` 现在一次建立稳定顺序、ID 映射、起点数组、结束时间和前缀最大结束时间；普通状态审阅不会重建。selected-first/A–B eligibility、reject、restore、疑似碎音选择、和弦区间重叠与编辑器 route 暂存均复用这些索引。

`tools/benchmark_transcription_candidate_queries.py` 覆盖 10k/50k/100k 候选。固定含 11 个候选的 A–B 查询在三种规模下都只检查 11 项，本轮中位数均约 2 μs；100k 索引冷构建约 672 ms。构建发生在候选集合发布时，不进入 paint/audio callback。墙钟值仍为诊断证据，结构门槛是查询检查数随命中区间而不是全曲规模增长。

### P1 候选：主窗口刷新域

`_on_track_changed()` 同时负责时间轴 pitch plan、网格、元信息、合奏指标、扒谱区和校验调度。下一步应拆成 model、view、transport 三类刷新信号，避免缩放/适配视图触发与模型无关的工作。

### 明确禁止的“优化”

- 不用未可靠失效的全局 cache 包裹可变轨道。
- 不在 paint/audio callback 中延迟加载或解码。
- 不用后台线程直接读取正在变化的 Qt widget/TrackState。
- 不用跳过结构校验换取更快导出。
- 不以减少 Python 文件数为目标重新合并领域模块。

## 扩展边界

| 能力 | 当前扩展点 | 新扩展必须遵守 |
|---|---|---|
| 优化算法 | `optimization/registry.py`, plugin API, `.bdoopt` | 确定性、作用域隔离、game-safe 不变量、可信本地包 |
| 对话框/展示 | 聚焦 dialog 模块 + 主窗口 host 方法 | 不反向导入主窗口；结果经显式接受后应用 |
| BDO 编解码 | `bdo_codec` model/reader/writer | 二进制变化高风险；必须 round trip 和结构测试 |
| MIDI 变换 | `bdo_midi` 纯 note transforms | 保持不可变 note 语义和鼓组规范映射 |
| 导出目标 | `ExportRequest` / `prepare_export` / `publish_export` | 快照不可变；用户目标原子写入 |
| 扒谱分析 | `bdo_transcription*.py` + worker | 结果是可编辑辅助，不自动覆盖正式模型 |
| 本地音源 | manifest/sample-map 边界 | 本地私有、哈希校验、播放前预载、不得打包上传 |

未来如增加新的扒谱 provider，应先定义 Qt-free `TranscriptionProvider` 协议、能力描述、取消语义和路径无关结果；不要把云端凭据或 provider SDK 直接接入主窗口。

## 每轮优化的验收记录

每次提交应记录：基线场景、数据规模、改前/改后结构或指标、相关不变量、聚焦测试、完整回归，以及尚未验证的假设。没有基准证据的性能想法保留在本文，不宣称已经提速。

### 2026-07-30：游戏优先数据边界与 AI 可编辑性

- 结构：导入、游戏混音身份、配置/profile、首页展示、区间查询、原文档复用和
  验证阶段拥有唯一 owner；主窗口降至 8,800 行以内。
- 正确性：损坏导入整体失败；当前 schema 不重复力度变换；复用与重编码使用同一
  最终文档摘要；默认游戏音量只引用 `DEFAULT_TRACK_VOLUME`。
- 防回退：AST 测试锁定层级依赖、兼容重导出身份和核心函数跨度预算。
- 导出请求 factory 已完成：正式轨冻结、奏法/Volume/双力度映射和 Aux/Master
  合成都由一个 Qt-free 边界派生，非法设置不再静默清零。
- 工程 load/save plan 与扒谱正式提交 plan 已完成。下一步拆 model/view/transport
  刷新域，并在计划执行侧增加 rollback/补偿边界或迁移扒谱 presenter；不要用
  新的中间字典或主窗口 helper 重建第二套事实源。

### 2026-07-30：审阅历史与预览 Play 命令边界

- 结构：四个主窗口审阅列表收敛为一个 `TranscriptionReviewController` owner；原属性保留为兼容视图。`PreviewPlayAction` 将 Play 请求归类为 wait/resume/start，主窗口只执行 UI/设备副作用。
- 正确性：混合 session/assist 撤销顺序、redo 分支失效、正式 Apply 清栈、首页播放入口和音频生命周期聚焦测试通过；完整回归 789 项通过、1 项跳过。
- 性能门槛：48,000 音符时间轴最后一次可见查询检查 400 项；100,000 音符卷帘可见查询中位数约 0.038 ms。转换校验 10k/50k/100k cold scan 约 3.9/17.7/32.6 ms，cache-hit 中位数约 0.2–0.4 μs，且复用同一快照身份。
- 结论边界：本轮没有改动 paint/audio callback，也不宣称渲染或 DSP 提速；墙钟绘制值只用于发现退化。候选 route、类型化工程 load/save 与正式提交计划随后已落地；下一轮聚焦刷新域、提交执行回滚或 presenter。

### 2026-07-30：候选索引与审阅命令计划

- 结构：`TranscriptionSession` 成为候选顺序/区间索引的唯一事实源；`TranscriptionReviewController` 输出无 Qt 的 eligible/reject/restore/select-fragments plan。主窗口只执行 session mutation、UI 刷新和 autosave。
- 性能：10k/50k/100k 候选、11 项命中范围的检查数恒为 11，中位查询约 2 μs；声部拆分和跨轨/新轨暂存按 group/request ID 查询，不再先构造全曲 ID 映射。
- 正确性：新增 20k 候选结构测试锁定 11 项检查上限，并覆盖 offset、拒绝、已路由和 include-routed；65 项 session/controller/边界/编辑器/语义 Qt 聚焦测试通过，完整回归 793 项通过、1 项跳过。
- 后续：正式提交 mutation 决策和类型化工程 load/save 已落地；下一步迁移 presenter 或执行回滚边界。不要把候选索引复制到主窗口或 canvas。

### 2026-07-30：工程 load/save 与扒谱正式提交计划

- `bdo_music_composer/project/project_document.py` 在任何 UI 修改前完成 JSON 解码/迁移、路径与字段校验、
  事务式轨道构造，并输出包含转换、混音、音高、参考音频和 review sidecar 的
  完整 `ProjectLoadPlan`；失败使用稳定 code/path。
- `ProjectMetadataSnapshot.capture()` 递归脱离嵌套 mapping/sequence，拒绝非有限
  数和不可移植引用；writer 每次解冻独立 payload，不与 GUI 共享可变容器。
- `plan_transcription_commit()` 对草稿、正式轨和 pending/local routes 做确定性、
  非修改输入的分类，输出最终音符、sidecar 和临时新轨意图；单一 Apply/OK gate
  使用模型回滚检查点和可补偿刷新，sidecar 故障不留下半提交轨道，view 故障不
  跳过 autosave。
- `bdo_music_composer/editor/preview_midi_writer.py` 成为标准 MIDI 事件投影的唯一 owner；它与游戏 BDO v9
  序列化和效果字节边界明确分离。
- 聚焦守卫位于 `test_project_document`、`test_project_persistence`、
  `test_transcription_commit_plan`、`test_transcription_editor_commit_ui` 和
  `test_preview_midi_writer`。下一步不再扩展 plan/执行器字段，先处理刷新域、
  `ProjectLoadPlan` 执行回滚或 `TranscriptionWorkspacePresenter`。

### 2026-07-30：MIDI 优化作用域界面统一

- 评估：全工程能力仍是跨轨写入、派生轨与全局效果的唯一合法入口，因此保留领域能力，但移除独立“全局优化”界面概念。
- 结构：`MidiOptimizeDialog` 统一窗口、工具栏与轨道入口；作用范围成为首层选择。音符编辑器工厂锁定草稿单轨，主窗口按对话框最终范围应用结果。
- UI 与本地化：范围摘要明确可写轨道、全曲上下文和全局效果权限；简体/繁体中文、英文、日文、韩文可实时切换；旧独立入口翻译键已移除。
- 正确性：优化器聚焦测试 84 项通过、1 项跳过；UI/本地化/README 聚焦测试 23 项通过；完整回归 793 项通过、1 项跳过。
- 性能边界：范围切换只筛选已缓存的算法描述符，不再重新扫描插件目录；优化算法复杂度、paint 路径和音频 callback 未改变。
