# 性能与原生核心：先测，再决定要不要换

状态：**门禁规范（2026-08-10 更新）**。P0–P4 的 Windows-only 落实与实测见
[`benchmarks/windows_p0_p4_2026-08-10.md`](benchmarks/windows_p0_p4_2026-08-10.md)。
本文件仍定义后续测量、决策和迁移门槛；当前证据不代表已经批准新的第三方依赖、
许可证库存、原生混音器生产替换或发布形态。

## 先说结论

目标不是把 Python 文件机械翻译为 C++，而是在保持当前 `TrackState` / `Note`、
撤销、自动保存、试听和 BDO v9 导出不变量的前提下，达到可重复验证的专业编辑器
响应性与实时试听稳定性。

当前建议采用混合架构：

- PySide6 继续拥有产品 UI、工程编排、BDO 规则、转写审阅和非实时领域逻辑；
- 先通过精确失效、缓存和批量化解决 Python 层热点；
- 只有实时音频调度、声部/DSP/PCM 生成等无法容忍 Python 长尾的路径进入原生核心；
- 钢琴卷帘仅在真实窗口、高 DPI、低端硬件或高刷新率门槛失败后评估 Qt Quick/C++；
- 不以插件宿主、录音、延迟补偿或通用 DAW 为本轮范围。

## 当前证据与限制

2026-08-09 在 Windows 11、Ryzen 9 5900X、CPython 3.12.10、PySide6 6.11.1、
NumPy 2.4.6 上串行运行仓库基准：

| 工作负载 | 观测值 | 判断 |
|---|---:|---|
| 120 轨 / 48,000 音符时间轴 paint | P95 2.53–2.84 ms | 当前有充足 60 Hz 余量 |
| 12,000 正式音符 + 8,000 参考音符卷帘 paint | P95 10.45–11.42 ms | 当前机器满足 60 Hz，尚未覆盖真实窗口/高 DPI |
| 100,000 音符可见查询 | P95 0.06–0.08 ms | 索引不是热点 |
| 100,000 音符转换冷校验 | 68.7 ms | 可接受；revision 缓存命中约 0.3 微秒 |
| 100,000 转写候选索引建立 | 962 ms | 明确的非实时热点 |
| 100,000 转写候选范围查询 | 中位数约 2 微秒 | 建立后查询良好 |
| 176 声部 + Reverb/Delay/Chorus 合成负载 | P95 12.41 ms | 2,048-frame 离线生产者下零 underrun |
| 256 请求声部合成负载 | P95 13.28 ms | 峰值 224 声部，32 次受控抢占 |

这些数字是诊断证据，不是专业级认证：UI 使用 offscreen 平台，卷帘视口只绘制
当前可见集合；音频负载只有一个合成样本源，未打开真实设备，也未测量 48 kHz
下的 128/256/512-frame 模式、P99/P99.9、端到端延迟或长时间 XRUN。

调用级 profile 进一步表明：100,000 候选的 `TranscriptionSession.set_candidates()`
主要成本不是范围索引，而是 100,000 个 `CandidateAnnotation.__post_init__()` 和
200,000 次注释 token 规范化；`typing.Sequence` / `Mapping` 的运行时实例检查占据
显著比例。应先为可信内部 `frozenset[str]` 增加无损快路径、避免默认注释的重复
归一化，并在候选 generation 未变时复用索引。该热点暂不构成引入 C++ 的理由。

## 性能等级和验收口径

下列值是本项目的工程目标，不声明为统一行业标准。所有发布判断同时依赖正确性
测试，不允许用跳过校验、扩大无界缓存或改变声部/导出语义换取数字。

### 交互 UI

| 场景 | 通过门槛 |
|---|---|
| 60 Hz 真实窗口 | 核心画布 paint P95 < 12 ms，P99 < 16.7 ms |
| 120 Hz 可选目标 | 核心画布 paint P95 < 8.3 ms |
| 密集编辑 | 100k 音符的局部拖动、力度编辑和单轨提交不重建无关轨索引 |
| 视觉压力 | 4K/200% DPI 下同时开启候选、轮廓、力度和旋律线仍满足 60 Hz 门槛 |
| 主线程阻塞 | 可取消后台任务之外，单个同步刷新阶段 P95 < 8 ms |

至少保存高端桌面、普通笔记本和低端集成显卡三档结果。offscreen 只作为结构回归，
不得替代真实窗口结果。

### 实时音频

分别验证 48 kHz、512/256/128 frame；每档记录 render P50/P95/P99/max、XRUN、
声部峰值、抢占、设备 buffer 和端到端交互延迟。

- P99 混音时间低于块预算的 70%；
- 连续 30 分钟真实设备测试 0 XRUN；
- 覆盖 64/176/256 请求声部、多真实样本源和全效果负载；
- Seek、Pause/Resume、反复试听、设备丢失/恢复和预载取消不产生旧 PCM；
- 实时线程禁止文件/JSON/WAV I/O、Python 回调、锁竞争等待、堆分配和无界工作；
- 256 声部上限、实例限制、精确事件 frame、Limiter 和现有短释放抢占保持不变。

若 512 frame 未通过，不进入 256/128 的产品承诺。设备测试结果必须注明设备、
驱动、共享/独占模式、采样率和实际协商 buffer。

### 批处理和转写

- 100k 候选首次建立相对当前基线至少下降 35%，GUI 发布阶段保持可取消且不重复建立；
- generation 相同的重复呈现不得重新规范化和排序完整候选集；
- 100k 音符转换冷校验目标 < 100 ms，缓存身份必须由 model revision 可靠失效；
- 转写继续分别记录 decode、resample、ONNX、postprocess、index 和 publish；
- ONNX Runtime Python/C++ 共用原生执行内核，不因语言迁移预设推理加速收益。

## 推荐目标架构

```text
PySide6 / Python
  TrackState、Note、工程、撤销、转写审阅、BDO 校验与导出
       |
       | PlaybackPlanV1（一次性不可变批量提交）
       v
原生实时核心（可选、窄边界）
  事件时间线 -> 固定 voice pool -> BDO 生命周期 -> DSP buses -> limiter
       |                                      |
       | 固定容量命令队列                      | 原子/快照遥测
       v                                      v
  原生设备 callback                         Python 低频轮询
```

`PlaybackPlanV1` 应使用定宽标量和连续数组，至少承载 event frame、sample handle、
ratio、gain、duration/audible/fade frame、instrument/ntype、track slot、loop、实例
限制和三个 send。跨语言边界不得逐音符回调，也不得让原生线程持有 Python 对象。

原生核心必须可以由现有 Python 引擎替换，并对同一冻结计划产生可比较的 PCM、事件
边界、声部生命周期和状态快照。Python 引擎在完成等价性与设备门槛前保持生产默认，
作为回退和差分 oracle。

## 框架与依赖决策

| 候选 | 决策 | 用途与约束 |
|---|---|---|
| Qt/PySide6 + Shiboken6 | 保留 | 已在锁定库存；适合暴露窄 C++ API，但需验证一文件打包和 ABI |
| miniaudio | 首选设备后端 PoC | public-domain/MIT-0、WASAPI 和 ring buffer；只使用低层设备 API，不建立第二事实源 |
| FluidSynth | 独立可选 PoC | 仅通用 SF2/SF3 预览；LGPL 动态可替换边界和 SoundFont 许可证必须另审 |
| JUCE | 暂缓 | 仅在插件/ASIO目标成立且 AGPL/EULA/商业许可决策完成后考虑 |
| Tracktion Engine | 拒绝本轮引入 | GPL/商业双许可且会建立第二套 sequencer/工程模型 |
| libremidi | 延后 | 未来外部 MIDI 1/2 设备与热插拔；不解决当前混音或编辑热点 |
| Qt Quick/C++ scene graph | 条件性 PoC | 仅当真实画布门槛失败；保持 Python 编辑模型为唯一事实源 |

任何新依赖都会改变 `requirements/windows-py312.txt`、第三方 notices、PyInstaller
二进制库存和 `packaging/transcription_release_policy.json` 的批准摘要。未经维护者
重新审查，不得进入公共 EXE。PoC 应先保持可选、开发者本地构建且不改变生产包。

框架判断基于各项目的一手资料：

- [Qt Quick Scene Graph](https://doc.qt.io/qt-6/qtquick-visualcanvas-scenegraph.html)
  和 [Qt Quick 性能建议](https://doc.qt.io/qt-6/qtquick-performance.html)；
- [Qt for Python / Shiboken6](https://doc.qt.io/qtforpython-6/)；
- [miniaudio 官方仓库](https://github.com/mackron/miniaudio)；
- [FluidSynth 开发文档](https://www.fluidsynth.org/documentation/)；
- [JUCE 官方仓库](https://github.com/juce-framework/JUCE)和
  [JUCE 许可证](https://github.com/juce-framework/JUCE/blob/master/LICENSE.md)；
- [Tracktion Engine 官方仓库](https://github.com/Tracktion/tracktion_engine)；
- [libremidi 官方文档](https://celtera.github.io/libremidi/)；
- [ONNX Runtime Execution Providers](https://onnxruntime.ai/docs/execution-providers/)
  和 [C/C++ API](https://onnxruntime.ai/docs/api/c/c_cpp_api.html)。

## 分阶段实施方案

### Phase 0：建立可相信的基线

1. 扩展 `tools/benchmark_dense_ui.py`：支持真实窗口采样、DPI、刷新率、各图层组合、
   事件循环输入延迟和 P99。
2. 扩展 `tools/benchmark_realtime_audio.py`：显式 frame size、48 kHz、P99/P99.9、
   多样本合成夹具；真实 sink 模式记录设备协商参数。
3. 将启动、首页扫描、自动保存关闭等待与纯 paint profile 分离，避免基准噪声。
4. 结果 JSON 写入临时/明确输出路径；只把经过说明的紧凑证据提交到 `docs/benchmarks/`。

**出口门槛：** 至少两档真实硬件 UI 结果和一个真实音频设备 30 分钟结果；可以明确
复现失败场景，而不是仅有平均值。

### Phase 1：Python 内部低风险优化

1. 为内部已规范化 `CandidateAnnotation` 建立可信快路径，避免重复 `typing` 检查；
   对外 payload 仍走完整防御性验证。
2. 在候选 generation/identity 未变化时复用 order、starts、ends、prefix maxima 和
   默认注释，候选变化时保持稳定 ID 与 orphan 规则。
3. 清点 `_on_track_changed()` 兼容调用方，改用 `ModelChange.view/transport/notes/...`
   和 `WorkspaceRefreshController`；纯视图操作不得刷新校验、转写或 preview。
4. 为卷帘静态网格、文本、参考图层分别记录 paint 成本和失效次数，先做缓存/脏层，
   不建立每音符 QWidget/QGraphicsItem。

**出口门槛：** 100k 候选建立相对基线至少下降 35%；所有 session、editor、转写和 UI 回归通过；
真实 UI 门槛若已全部通过，则停止 UI 原生化工作。

### Phase 2：原生音频可行性原型

1. 定义 Qt-free `PlaybackPlanV1` 与 `AudioStatusV1`，先由 Python 生产和验证。
2. 建立独立原生测试目标；不得直接修改 BDO codec、Note wire shape 或项目 schema。
3. 实现固定 voice/event/bus 内存、无锁 SPSC 命令队列和离线 PCM renderer；先不接
   真实设备。
4. 对同一冻结计划逐项差分：事件 frame、Seek 恢复、实例限制、声部抢占、loop、
   articulation、track meter、效果 send、Limiter、最终 PCM 容差。
5. 通过后用 miniaudio 低层设备 callback 做可选 PoC；Python 线程只提交命令和轮询
   快照，不进入设备 callback。

**出口门槛：** 聚焦正确性全部通过，AddressSanitizer/UBSan（适用平台）无问题，
离线 64/176/256 负载至少不慢于 Python 基线，真实 512/256-frame 门槛通过。

### Phase 3：受控生产集成

1. 原生后端保持显式 feature flag；缺失/加载失败时清晰回退 Python 后端，不得静默
   改变音色来源或播放语义。
2. 将原生二进制纳入确定性构建、hash、notices、架构测试和一文件启动自测。
3. 维护同计划差分测试和 Python fallback，直到至少一个稳定发布周期无回归。
4. 重新生成精确依赖库存并由维护者审查发布策略摘要。

**出口门槛：** 完整单元套件、源启动、冻结启动、30 分钟真实设备、更新替换/回滚
和仓库 hygiene 全部通过；发布包未携带私有样本、路径或 Owner ID。

### Phase 4：条件性 GPU 画布原型

仅当 Phase 1 后仍有明确真实 UI 失败时启动。使用 C++ `QQuickItem`/scene graph 接受
不可变可见投影，Python 继续拥有选择、命令、撤销和正式 `TrackState`。先迁移一个
只读钢琴卷帘图层；若跨边界同步、输入命中或文字质量抵消收益，立即停止，不扩展为
全 UI 重写。

### Phase 5：认证、发布门禁与最终决策

1. 运行完整单元套件、`py_compile`、`compileall`、仓库 hygiene 和 `git diff --check`。
2. 串行复测100k候选、真实Windows画布、Python低延迟、原生低延迟和真实sink长稳。
3. 将每个阶段记录为通过、否决或外部门禁；“阶段完成”不等于强行晋级生产。
4. 未通过完整语义差分、真实设备和许可证库存审查的原生组件保持实验性且不进公共包。
5. 把环境、数字、限制、回退和下一里程碑写入 `docs/benchmarks/` 的紧凑证据。

**出口门槛：** 所有源代码回归和仓库门禁通过；任何未满足的生产/发布条件明确列出，
不得把offscreen、合成样本或不等功能的原生结果描述成完整专业认证。

## 代码所有权和最小验证

| 工作 | 主要 owner | 最小验证 |
|---|---|---|
| 候选建立快路径 | `transcription/bdo_transcription_session.py` | session、candidate projection、transcription UI、benchmark |
| 刷新收口 | `app/workspace_refresh_controller.py`、`editor/model_change.py`、主窗口 host | workspace refresh、timeline incremental、dense UI、完整套件 |
| UI 性能仪器 | `tools/benchmark_dense_ui.py`、聚焦 canvas | offscreen 结构门、真实窗口证据、paint regression |
| 播放计划 ABI | 新的 Qt-free focused owner | lifecycle、event frame、seek、export/editor 不变量 |
| 原生音频核心 | 新的独立 native owner + 窄绑定 | realtime audio 全套、差分 PCM、sanitizer、长稳测试 |
| 设备后端 | native owner，不放入 Python callback | sink、设备恢复、buffer/latency、冻结启动 |
| 可选 FluidSynth | 独立 sidecar/component owner | 许可证库存、hash、GM map、无 callback I/O |

每一阶段都运行完整回归和 `tools/check_repository_hygiene.py`。音频或 UI 数字改善若伴随
Note 数量、pitch/ntype、实例限制、事件 frame、导出字节或项目 schema 改变，视为失败。

## 风险、回退与停止条件

- **双引擎漂移：** 冻结计划和差分测试是唯一允许的迁移桥；不维护两个领域模型。
- **ABI/打包：** Python 3.12、MSVC runtime、PySide/Shiboken 和 PyInstaller 必须固定；
  原生加载失败必须可诊断并可回退。
- **许可证：** PoC 可行不等于允许发布；任何库存变化都要重新审查。
- **私有资产：** 原生缓存和日志同样不得序列化样本路径、音频或 Owner ID。
- **复杂度反噬：** 若 Phase 1 已满足目标，停止相应 C++ 工作；若原生原型不能在
  256 frame 下提供显著 P99 余量，停止生产集成并保留 Python 引擎。
- **全量重写：** 除非产品使命正式扩展为通用 DAW，且另有数据迁移、许可证和多年
  维护计划，否则不启动。

## 立项决策

当前可以立即批准 Phase 0 和 Phase 1。Phase 2 只批准一个不进入公共包的原型；
Phase 3 必须由真实设备数据、差分正确性和新的许可证库存共同触发。Phase 4 默认不
启动。该顺序能先获取大部分低风险收益，同时把 C++ 投入限制在确有证据的实时边界。
