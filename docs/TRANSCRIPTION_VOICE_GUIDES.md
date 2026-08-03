# 扒谱声部骨架：交互依据与实现边界

## 目标

“声部骨架”是候选审阅层，不是连续音高曲线、分轨模型或自动配器。
它只消费已经解码的候选、`VoiceGroup` 与和声 sidecar，帮助用户在拥挤的
钢琴卷帘中辨认主旋律、低音和和弦支撑。点击骨架只选中来源候选，不创建、
移动或修改正式 `Note`。

## 同类产品中可复用的交互原则

- Sonic Visualiser 把声谱、音高与标注作为可独立开关的 layer；其 Melodic
  Range Spectrogram 使用面向旋律的频段和与感知音高一致的纵轴。这里借鉴
  “按任务开启层”，不把原始声谱设为默认背景。
  [Sonic Visualiser 官方参考](https://www.sonicvisualiser.org/doc/reference/1.9/en/index.html)
- Melodyne 将音符块与细音高曲线分开显示，允许独立开启音高曲线、音符边界、
  intended notes；潜在音符使用轮廓而不是伪装成已确认音符。这里借鉴“检测结果、
  弱候选和细节层使用不同视觉语法”，但不复刻其界面或编辑行为。
  [Melodyne 显示选项](https://helpcenter.celemony.com/M5/doc/melodyneEditor5/en/M5tour_ViewOptions-stand-alone?env=standAlone)
  · [Melodyne Note Assignment](https://helpcenter.celemony.com/M5/doc/melodyneStudio5/en/M5tour_NA_Mode_Tools?env=standAlone)
- Logic Pro 在缩小的 Tracks 视图只保留有限音高信息，进入 Audio Track
  Editor 后才开放完整音符和参数编辑。这里采用同样的逐级披露思想：远景只画
  连续轮廓，中景画音符骨架，近景才显示弱分支。
  [Logic Pro Flex Pitch 官方指南](https://support.apple.com/guide/logicpro/quickly-edit-audio-pitch-in-the-tracks-area-lgcpc355ded2/10.7/mac/11.0)
  · [Flex Pitch 音符编辑](https://support.apple.com/en-ae/guide/logicpro/lgcpc53e6bef/10.7/mac/11.0)
- RipX 以有颜色的 layer 区分声部，并把编辑限制在用户当前选择的 layer。
  这里仅采用“颜色恒定、声部可过滤”的信息架构；当前程序不做 stem separation，
  角色仍是启发式建议。
  [RipX 官方 Layers 说明](https://hitnmix.com/2023/07/16/ripx-deepcreate-for-revolutionary-music-recording-creation/)
- Moises 的和弦结果与播放同步，并提供简化程度不同的和弦视图。这里将和弦
  sidecar 压缩为拍对齐的紫色支撑带；和弦仍可在既有和弦栏人工校正。
  [Moises 官方和弦检测说明](https://help.moises.ai/hc/en-us/articles/6569274648220-How-do-I-use-Chord-Detection)
  · [和弦 Grid 模式](https://help.moises.ai/hc/en-us/articles/9570133423772-How-to-use-the-new-Chords-view-Grid-Mode)

上述资料只用于确定一般交互原则，不证明本程序的声部判断准确率，也不构成对
任何第三方算法、外观或商标的使用授权。

## 当前实现

`bdo_music_composer/transcription/bdo_transcription_melody_lines.py` 输出统一的只读 `MelodyLineSegment`：

- `note`：候选持续区间；
- `connector`：间隔不超过 0.35 拍（并限制在 80–220 ms）、跳进不超过 7 半音的相邻候选；
- `contour`：按半拍聚合的远景轮廓；
- `chord_span`：和声 sidecar 与实际候选共同支持的和弦支撑区间。

横向 LOD 固定为：

| 缩放 | 显示 |
|---|---|
| `<52 px/beat` | 不绘制声部骨架，避免全曲折线覆盖音块 |
| `52–143 px/beat` | 相邻音块之间的短曲线桥接与和弦支撑 |
| `≥144 px/beat` | 中景内容加低置信/第二声部虚线桥接 |

候选 sidecar 尚未生成时，fallback 使用固定 10 状态 beam，在每个同起音簇中按
候选置信度、音域偏好、时值、相邻跳进和间隙选择连续路径。工作量受 beam 上限
约束，不随和弦内候选数平方增长。输入相同则输出、来源 lineage 和排序相同。

## 视觉与交互

- 金色、青色、紫色分别表示主旋律、低音、和声；不再叠加 `M/B/H` 字符徽标。
- 细线宽和低透明度编码候选及声部置信度；虚线表示低置信分支。
- “声部提示”按钮右侧菜单可以独立显示三类声部，至少保留一类；默认只启用主旋律并保持整层关闭。
- 点击音符块仍优先选择该候选；点击块间骨架会选择线段记录的来源候选。
- 骨架点击、显示过滤和 LOD 均不得写入 `TrackState`、`Note` 或工程 schema。

## 限制

- 当前没有独立 stem separation，因此“主旋律/低音/和声”是音乐结构提示，
  不是原录音的乐器身份识别。
- 线宽表示模型/启发式置信度，不表示音准偏差，也不能当作发布质量指标。
- 和弦支撑必须同时有和声段与候选音级证据；证据不足时宁可不画。
- 任何自动改音高、改时值、分轨或写入正式音符的功能都应走独立的预览、审阅
  与 Apply 边界，不能借用本层的点击行为隐式执行。
