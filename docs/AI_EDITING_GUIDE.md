# AI 编辑与结构演进指南

本文面向继续维护 BDO Music Composer 的 AI Agent 和贡献者。它补充
[`AGENTS.md`](../AGENTS.md) 的硬约束，回答三个容易混淆的问题：一个行为由谁
拥有、依赖应朝哪个方向、怎样拆分主窗口而不制造第二套事实源。

第二阶段包迁移已按两段完成并分别验证：先迁移 6 个 Qt-free 编辑器 owner，
再迁移 5 个对话框 owner 和 2 个主题 owner。后续又将 5 个时间轴/钢琴卷帘
Qt owner 收拢到 `src/bdo_music_composer/ui/editor/`，并把版本与公开仓库身份收归
`src/bdo_music_composer/app/application_metadata.py`。后续领域迁移已将全部调用方
改用 canonical 包路径；根目录目前只保留 `main.py`，且不保留导入 shim。

## 1. 先找所有者，再改调用者

`src/bdo_music_composer/ui/main_window.py` 是 Qt 组合根和兼容门面，不是默认的领域逻辑所有者。历史
调用者仍可从该模块取得部分公开名称，但新代码应直接导入下表中的实际所有者。
兼容重导出只能指向同一个实现，不能复制类、函数、常量或状态。

| 行为或数据 | 唯一所有者 | 调用方职责 |
|---|---|---|
| `TrackState` 和编辑器共享轨道字段 | `src/bdo_music_composer/editor/editor_models.py` | UI 只显示、提交显式修改 |
| MIDI、BDO、工程数据到完整编辑器轨道 | `src/bdo_music_composer/editor/editor_import.py` | 主窗口注入本地化名称和颜色，并原子应用成功结果 |
| 工程命令快照和撤销/重做 | `src/bdo_music_composer/editor/editor_commands.py` | UI 只在显式提交边界压入命令 |
| 力度曲线变换 | `src/bdo_music_composer/editor/velocity_curve.py` | Canvas 提交参数，不复制曲线算法 |
| 正式谱面/试听作用域、最终游戏乐器 ID、同乐器 Volume/Aux | `src/bdo_music_composer/editor/game_score_model.py` | UI 发出意图，预览/验证/导出消费同一规则 |
| 游戏默认轨道音量及 FX wire 值 | `src/bdo_common/bdo_track_effects.py` | 其他模块引用命名常量，不复制 `70` 等游戏语义值 |
| 转换设置与音高计划 | `src/bdo_music_composer/core/conversion_settings.py`, `src/bdo_music_composer/editor/pitch_transform.py` | 设置界面替换不可变快照，不重建字典规则 |
| 用户配置读写和安全文件名 | `src/bdo_music_composer/app/application_config.py` | 对话框/主窗口只收集值并显示错误，不直接改 JSON |
| 游戏约束 profile 的延迟缓存 | `src/bdo_music_composer/app/game_profile_provider.py` | 在真正验证时获取，不在模块导入期读盘 |
| 应用版本与公开 GitHub 仓库身份 | `src/bdo_music_composer/app/application_metadata.py` | UI、链接和请求复用命名常量，不再创建平行版本源或硬编码仓库地址 |
| 内部休眠的本地更新日志数据 | `src/bdo_music_composer/app/release_notes.py`, 可选的 `data/releases/release_notes.json` | JSON 仅为本机内部、Git 忽略的可选记录，可不存在且不得进入公开 Git 历史或安装包；只有显式内部测试消费有界不可变模型，生产首页、启动、菜单和导航无入口 |
| 内部休眠的 GitHub 稳定版比较与异步传输 | `src/bdo_music_composer/app/update_check.py`, `src/bdo_music_composer/ui/update_check_qt.py` | 只有显式内部测试可构造弹窗并发起请求；生产流程不得接线，也不自动下载、执行或把失败说成最新版 |
| 生产冻结版无感自更新 | `src/bdo_music_composer/update/`, `src/bdo_music_composer/ui/self_update_qt.py`, `src/bdo_music_composer/ui/self_update_host.py`, `scripts/generate_update_manifest.py` | 只在冻结 Windows 版启动；GitHub/Gitee 是镜像，签名清单才是信任根；下载、下次启动交棒、健康提交和回滚保持聚焦且失败关闭 |
| 首页目录数据与首页/启动展示 | `src/bdo_music_composer/app/home_catalog.py`, `src/bdo_music_composer/ui/home_widgets.py`, `src/bdo_music_composer/ui/startup_widgets.py` | 扫描器不创建控件；展示组件不反向导入主窗口 |
| 通用闭区间可见项查询 | `src/bdo_music_composer/editor/interval_index.py` | Canvas 在数据替换时建索引，paint 只查询可见范围 |
| 工程 schema 和历史迁移 | `src/bdo_music_composer/project/project_schema.py` | 读取方先迁移，再交给类型化导入边界 |
| 完整工程文档校验与加载计划 | `src/bdo_music_composer/app/project_document.py` | UI 只读取文本、注入端口、本地化错误，并一次性提交 `ProjectLoadPlan` |
| 工程打开路由和 loading generation | `src/bdo_music_composer/project/project_lifecycle_controller.py` | 主窗口执行文件读取与 Qt 状态应用 |
| 工程 metadata/轨道深冻结、自动保存请求和原子写入 | `src/bdo_music_composer/project/project_persistence.py` | GUI 线程捕获 `ProjectMetadataSnapshot`，单一 writer 解冻独立 payload 并执行 I/O |
| 当前编辑器轨道到标准 MIDI 的确定性投影 | `src/bdo_music_composer/editor/preview_midi_writer.py` | 调用者提供轨道、速度/节拍和目标路径；不得在主窗口复制事件排序规则 |
| 聚焦对话框和应用语义主题 | `src/bdo_music_composer/ui/dialogs/`, `src/bdo_music_composer/ui/theme/` | 主窗口注入状态并应用结果；子包 initializer 保持 inert |
| 扒谱草稿与候选路由的正式提交计划 | `src/bdo_music_composer/transcription/transcription_commit_plan.py` | UI 做 preflight、单次撤销快照、应用计划、提交 sidecar、刷新和 autosave |
| 不可变导出请求 factory、准备和发布 | `src/bdo_music_composer/export/export_workflow.py` | 主窗口只完成路径/Owner/本地化 gate，并传入当前编辑器事实源 |
| 编辑器到 BDO v9 的字段级一致性诊断 | `src/bdo_music_composer/export/export_verification.py` | Qt-free 投影并检查 prepared、主文件、游戏副本；UI 只显示有范围限定的报告 |
| 编辑器/MIDI 到 BDO 文档的适配、原文档复用与摘要 | `src/bdo_export/` | 不读取或修改 Qt 控件、工程文件；摘要只从最终文档生成 |
| BDO v9 wire model、ICE、读写和验证 | `src/bdo_codec/` | 不认识 `TrackState`、项目生命周期或 UI |
| 游戏规则问题的确定性收集与排序 | `src/bdo_music_composer/export/bdo_validation.py` | UI 只本地化/展示 `ValidationIssue`，不复制校验规则 |

如果现有逻辑位于主窗口，但表中已有所有者，应先给所有者补充小型 API 和纯逻辑
测试，再把主窗口缩成参数收集、信号连接和结果应用。不要为降低行数机械拆分一组
仍然共享可变状态的方法。

## 2. 依赖方向

生产代码的主依赖方向是：

```text
Qt composition / widgets
  -> application workflows
  -> editor and game domain
  -> BDO export adapter
  -> BDO wire codec
```

`bdo_music_composer` 及其各领域子包的 `__init__.py` 必须保持惰性，只声明包职责，
不得聚合或提前导入聚焦所有者。生产代码直接导入具体子模块，避免仅使用一个配置、
工程或 UI 所有者时连带初始化无关的 Qt、音频或扒谱模块。

工程持久化是并列的应用基础设施：UI 可以调用
`src/bdo_music_composer/app/project_document.py`、
`src/bdo_music_composer/project/project_lifecycle_controller.py`、
`src/bdo_music_composer/project/project_schema.py` 和
`src/bdo_music_composer/project/project_persistence.py`，这些模块可以使用 Qt-free
领域值，但不得反向导入 UI、Codec 或导出工作流。

具体规则由 `tests/test_architecture_dependencies.py` 执行：

- `src/bdo_music_composer/editor/editor_import.py` 和 `src/bdo_music_composer/editor/game_score_model.py`
  不依赖 PySide、主窗口或任何控件；
- `src/bdo_codec/` 不依赖编辑器、游戏模型、工程、导出适配器或 UI；
- `src/bdo_export/` 可以依赖 Codec、MIDI 和 wire-safe 效果值，但不依赖应用工作流、
  工程或 UI；
- `src/bdo_music_composer/export/export_workflow.py` 和 `src/bdo_music_composer/export/export_verification.py` 可以向下调用
  `bdo_export`/`bdo_codec`，不能回头读取 Qt
  或工程存储；
- `src/bdo_music_composer/project/` 边界不依赖 Codec、导出层或 Qt；
  `src/bdo_music_composer/app/project_document.py` 在状态修改前产出完整
  `ProjectLoadPlan`，不能把半成品 mapping 交回主窗口；
- `src/bdo_music_composer/app/application_config.py`、
  `src/bdo_music_composer/app/game_profile_provider.py`、
  `src/bdo_music_composer/app/application_metadata.py`、
  `src/bdo_music_composer/app/release_notes.py`、
  `src/bdo_music_composer/app/update_check.py` 和
  `src/bdo_music_composer/editor/interval_index.py`、
  `src/bdo_music_composer/editor/preview_midi_writer.py`、
  `src/bdo_music_composer/transcription/transcription_commit_plan.py` 保持 Qt-free；主窗口不能直接绕过
  `src/bdo_music_composer/export/export_workflow.py` 调用 Codec/导出适配器；
- 聚焦所有者有可执行的函数跨度预算。超过预算时应拆出有领域名称的 helper，
  不能通过关闭守卫或把逻辑搬进匿名闭包规避。

新增模块时先判断它属于哪一层，再更新守卫中的显式所有者集合。不能只为让测试
通过而删除禁用项；真正需要反向依赖时，应引入窄协议、不可变 DTO 或由组合根
注入的 callable。

## 3. 类型化边界

跨线程、跨格式或跨持久化层时，不传递“差不多能用”的字典和可变 Qt 对象。

- MIDI/BDO/工程导入先由
  `src/bdo_music_composer/editor/editor_import.py` 完整解析。`EditorImportError` 携带
  稳定错误码和数据路径；任一权威轨道或音符损坏时整体失败，不返回部分谱面。
- 工程 JSON 由 `prepare_project_load()` 在任何 UI 状态修改前完成解码、迁移、
  路径校验、轨道构造和全部 metadata 解析。`ProjectLoadPlan` 是完整加载事实；
  主窗口不得再从原始 mapping 补读字段或分段提交。
- 本地化轨名和颜色通过 `TrackImportPresentation` 注入。纯导入模块不读取翻译器、
  调色板或控件。
- 导出和自动保存在线程启动前创建不可变请求；`ProjectMetadataSnapshot.capture()`
  递归冻结嵌套 JSON 值，writer 的 `to_payload()` 每次解冻出新的容器。仅把外层
  dataclass 标成 frozen 不算线程隔离。worker 不再读取当前窗口、
  `TrackState.notes` 列表或设置控件。
- `plan_transcription_commit()` 只计算最终音符、路由分类、sidecar 变化和新轨提交
  意图，不创建控件、不改 `TrackState`、不写 sidecar。Qt 层仍必须完成一次
  preflight、一次工程撤销快照、一次执行与一次刷新/autosave。
- `bdo_music_composer.editor.preview_midi_writer.build_filtered_midi()` 是标准
  MIDI 投影的唯一实现；
  `src/bdo_music_composer/ui/main_window.py` 只兼容重导出同一对象。它不属于 BDO v9 导出，也不证明
  游戏内效果可由标准 MIDI 无损表达。
- schema migration 只负责历史 wire payload 的升级；当前编辑器行为由领域模型
  拥有，不能在 UI 和迁移器中各实现一次。当前 schema 只验证已经物化的力度
  策略，不得每次打开都重扫并再次烘焙音符。
- 原始 BDO 文档是否可复用由 `bdo_export.source_reuse` 判断；无论复用原字节还是
  规范重编码，导出摘要都从最终 `BdoDocument` 生成。复用门必须覆盖所有会改变
  游戏投影的字段，包括 Volume、双力度 B、打击乐语义和非 1.0 时值缩放；音符
  容器顺序本身不是编辑语义。
- 双力度 B 必须先按原始音符 occurrence 绑定，再携带经过移调、时值、奏法、
  音域和鼓映射。禁止在这些变换之后用旧五字段 identity 重新查找 B。
- 原始 MIDI/BDO 是 provenance，不是恢复或导出的事实源。完整工程快照和当前
  `TrackState` 始终优先。

为兼容旧接口保留 mapping 投影时，应把它标为单向兼容适配器。新实现使用类型化
请求；不得让旧字典重新成为内部事实源。

## 4. 修改流程

1. 从 [`AI_CONTEXT.md`](AI_CONTEXT.md) 定位所有者和相关不变量。
2. 在所有者模块添加或修改最小的纯函数、不可变值或类型化错误。
3. 先写所有者单元测试，包括无效输入、确定性和不修改输入。
4. 在 `src/bdo_music_composer/ui/main_window.py` 或控件模块只连接信号、注入展示值并应用已验证结果。
5. 若必须保留旧公开路径，在主窗口门面重导出同一对象，并增加身份测试。
6. 运行聚焦测试、架构依赖守卫、任务对应回归和完整测试。
7. 同步本指南、架构或领域文档；接口未改变时不要重复描述实现细节。

架构守卫至少运行：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_architecture_dependencies tests.test_gui_module_boundaries -v
```

## 5. 分阶段结构路线

### 已落地：所有权与安全入口

- `src/bdo_music_composer/editor/editor_models.py` 成为共享轨道模型；
- `src/bdo_music_composer/editor/editor_import.py` 承担事务式 MIDI、BDO 和工程轨道构造；
- `src/bdo_music_composer/editor/game_score_model.py` 统一正式谱面、试听和游戏混音身份；
- 配置、游戏 profile、首页/启动展示和可见区间索引均有独立 owner；
- BDO 原文档复用逻辑已从 Codec 上移到 `bdo_export`，Codec 不再认识编辑器字段；
- `build_export_request()` 统一冻结正式轨、派生奏法/Volume/双力度映射并合成
  Aux/Master；非法八字节设置失败封闭，不再由 UI 静默清零；
- Marnian 模式、已物化力度模式、默认轨道音量和 730 物理轨限制均有权威来源或
  跨层契约测试；
- `bdo_validation.validate_tracks()` 已拆为按规则域命名的小型验证阶段，保持原有
  问题顺序；当前 schema 不再重复烘焙力度；
- `src/bdo_music_composer/app/project_document.py` 已将工程 JSON 完整准备成
  `ProjectLoadPlan`，加载失败带稳定 code/path；`ProjectMetadataSnapshot`
  已递归深冻结工程 metadata，保存 worker 不再持有 GUI 可变字典/列表；
- `src/bdo_music_composer/transcription/transcription_commit_plan.py` 已提供确定性、非修改输入的正式提交计划；
  UI 执行器先提交 sidecar/轨道/撤销历史，模型阶段异常时恢复原对象与两套历史，
  Timeline 等后续刷新异常不再阻断 autosave；
  `src/bdo_music_composer/editor/preview_midi_writer.py` 已成为标准 MIDI
  事件投影的唯一实现和兼容重导出所有者；
- 项目、预览、转换校验和扒谱已有独立 Qt-free lifecycle/controller；
- 主窗口保留兼容门面并已降至 8,600 行以内，架构与函数跨度测试阻止回退。

### 下一阶段：继续缩小应用组装

- 拆分 model、view、transport 刷新域，纯布局/缩放不得推进 model revision 或触发
  无关的校验、扒谱和 transport 工作；
- 将已用于 `TranscriptionCommitPlan` 的 model-publish / compensable-effects 模式
  扩展到 `ProjectLoadPlan`：模型阶段失败恢复旧工程，资源/UI 刷新失败不丢失已
  提交数据或跳过必要持久化；
- 建立 `TranscriptionWorkspacePresenter`，只把领域状态投影成按钮、文本和图层，
  不重新计算候选路由或正式提交结果；
- 复用统一的游戏乐器分组投影，避免验证、导出和 UI 各自分组。

### 后续阶段：隔离兼容面

- 把旧 mapping 导出入口和直接 MIDI 转换入口放入明确的 compatibility 模块；
- 新生产调用只使用类型化请求，脚本按需使用兼容入口；
- 在调用者完成迁移并有发布说明后，才删除旧门面名称。

每个阶段都必须保持当前测试通过，并单独交付可验证收益。不要一次移动全部符号，
也不要让临时双实现跨越多个阶段。

## 6. AI 自检清单

- 我修改的是行为所有者，还是在调用者复制了规则？
- 新模块能否在不创建 `QApplication` 的情况下测试？
- worker 收到的是否为冻结快照？
- 错误是否带稳定 code/path，且在首次状态修改前发生？
- 正式导出是否仍使用所有当前轨道，而不是 Mute/Solo 或原 MIDI？
- 新兼容导出是否只是重导出同一对象？
- 是否运行了依赖守卫和领域回归？

任一答案不明确时，先停在纯边界设计，不要继续向主窗口加入条件分支。
