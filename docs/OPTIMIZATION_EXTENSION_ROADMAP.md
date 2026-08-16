# 解耦、性能与扩展路线图

这里只留还没过期的结构目标和性能门槛。做完的事交给 Git 和测试，不在路线图里
反复报喜。

## 当前边界

- `src/bdo_music_composer/ui/main_window.py` 是 Qt 组合根和主窗口编排层，保持在 8,600 行以内；新领域
  逻辑优先进入已有 owner。
- 编辑器模型、导入、命令、区间索引、revision、标准 MIDI 试听投影和力度曲线
  位于 `src/bdo_music_composer/editor/`，保持 Qt-free。
- 工程加载、生命周期、schema 和不可变保存快照位于
  `src/bdo_music_composer/project/`；导出继续使用当前 `TrackState`，不得回读原 MIDI。
- 扒谱候选索引、审阅历史、分析 generation 和正式提交计划已有单一事实源；UI
  只负责呈现、显式确认和副作用执行。
- 实时音频 callback 不读盘、不解码、不解析配置，voice pool 和临时内存有界。
- 首页扫描、首页控件和主窗口内启动揭幕层分别拥有数据发现、展示和启动编排；
  启动不再创建第二个顶层窗口。

依赖方向和 owner 表以 [`AI_EDITING_GUIDE.md`](AI_EDITING_GUIDE.md) 为准，任务
路由和最小验证以 [`AI_CONTEXT.md`](AI_CONTEXT.md) 为准。

## 当前重构优先级

### 主窗口刷新域

`_on_track_changed()` 仍串联模型 revision、网格、元信息、合奏指标、扒谱呈现和
校验调度。后续应把刷新意图分为 model、view、transport 三类，确保缩放、适配
视图或主页切换不会触发与模型无关的全曲工作。

完成判据：纯视图变化不推进模型 revision；模型提交仍触发校验、自动保存和必要
的传输失效；现有导出 round trip 不变。

### 扒谱呈现边界

候选 route、撤销/重做和正式 Apply 决策不再扩展主窗口 helper。下一层只允许增加
窄的 presenter，将领域状态投影为按钮可用性、状态文本和可见图层；presenter 不得
重新计算候选资格或提交规则，也不得拥有第二套候选缓存。

### 工程计划提交

`ProjectLoadPlan` 已在修改 UI 前完成解析和验证。待收口的是提交阶段的显式回滚：
资源或视图应用失败时恢复旧工程，后台 writer 只接收不可变快照，不读取 Qt 控件
或可变 `TrackState`。

### 预览传输命令

`PreviewTransportCoordinator` 已拥有 Play 分类和 session 状态。暂停、定位、参考
音频对齐和采样包准备应逐步返回 Qt-free 命令计划，由主窗口执行设备和 UI 副作用；
DSP 仍归 `src/bdo_music_composer/audio/bdo_realtime_audio.py`。

小型响应式布局、工具栏组合和页面切换与 QWidget 生命周期紧密相关，除非出现
重复实现或独立测试需求，不为减少行数机械拆分。

## 性能门槛

- 时间轴和钢琴卷帘只查询可见区间并批量绘制。
- 扒谱证据使用固定时间 tile 与有界 LRU；paint 路径不读取 NPY、不运行模型。
- 首页目录枚举分批让出事件循环，小索引不读取大型工程正文。
- 转换校验按 `(model revision, UI language)` 复用不可变快照；不得用未可靠失效
  的全局 cache 包裹可变轨道。
- `tools/benchmark_dense_ui.py` 覆盖 48k 时间轴、12k+8k 卷帘和大规模可见查询；
  `tools/benchmark_conversion_validation.py` 与
  `tools/benchmark_transcription_candidate_queries.py` 分别守住校验和候选索引。
- 墙钟结果只用于发现退化。结构检查数、缓存身份和正确性测试才是跨机器门槛。

禁止把磁盘 I/O 移入 paint/audio callback，禁止后台线程直接读取变化中的 QWidget
或 `TrackState`，禁止跳过结构校验换取更快导出，也不以减少 Python 文件数量为
目标重新合并已经独立的领域模块。

## 扩展边界

| 能力 | 当前扩展点 | 必须保持 |
|---|---|---|
| 优化算法 | `src/optimization/registry.py`, `.bdoopt` | 确定性、作用域隔离、game-safe 不变量、可信本地包 |
| 对话框/展示 | 聚焦 UI 模块 + 主窗口 host | 不反向导入主窗口；显式接受后才应用 |
| BDO 编解码 | `bdo_codec` | little-endian v9、round trip、结构测试 |
| MIDI 变换 | `bdo_midi` | 不可变 note 语义和规范鼓组映射 |
| 导出 | `ExportRequest` / `prepare_export` / `publish_export` | 当前编辑器快照、原子发布、Owner ID gate |
| 扒谱分析 | transcription owner + worker | 可编辑辅助，不自动覆盖正式模型 |
| 本地音源 | manifest/sample-map | 私有、哈希校验、播放前预载、不打包上传 |

每轮优化在变更说明中记录数据规模、结构或指标变化、相关不变量、聚焦测试和完整
回归；不再把一次性验收日志追加到本文件。
