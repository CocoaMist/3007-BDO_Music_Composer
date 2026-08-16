# 文档从这里走 ♪

别从头翻到尾。先找你正在做的事，读一条主线就够了。代码和测试描述今天的程序；
旧版说明和历史审计只描述它们写下来的那一天。

## 我想……

| 你要做的事 | 先看 | 需要时再看 |
|---|---|---|
| 使用软件 | [中文指南](locales/zh-CN.md) | [游戏作曲界面](BDO_COMPOSITION_AUTHORING.md) |
| 接手开发 | [接手手册](AGENT_HANDOFF.md) | [改动地图](AI_CONTEXT.md)、[编辑指南](AI_EDITING_GUIDE.md) |
| 看懂程序 | [架构](ARCHITECTURE.md) | [目录与依赖](PROJECT_STRUCTURE.md) |
| 修改格式或导出 | [BDO v9 编解码](BDO_V9_CODEC.md) | [转换设置](CONVERSION_SETTINGS.md)、[算法锁](NOTE_ARTICULATION_TRANSPOSE_ALGORITHM_LOCK.md) |
| 修改界面 | [界面语言](CREATIVE_LANGUAGE_AND_UI_AUDIT.md) | [桌面端门禁](PROFESSIONAL_DESKTOP_PHASE6_10.md) |
| 打包发布 | [Windows 打包](WINDOWS_PACKAGING.md) | [本地化](LOCALIZATION.md)、[内容红线](CONTENT_BOUNDARY.md) |
| 查性能 | [原生核心计划](PERFORMANCE_NATIVE_CORE_PLAN.md) | [实测记录](benchmarks/) |
| 使用 SDK | [Developer SDK](DEVELOPER_SDK.md) | [优化器扩展](OPTIMIZATION_EXTENSION_ROADMAP.md) |

## 按领域找

- **音符与导出：** [曲谱转换说明](BDO_MUSIC_NOTES.md)、[BDO v9](BDO_V9_CODEC.md)、
  [转换设置](CONVERSION_SETTINGS.md)、[移调与奏法算法锁](NOTE_ARTICULATION_TRANSPOSE_ALGORITHM_LOCK.md)。
- **编辑器与游戏证据：** [作曲界面](BDO_COMPOSITION_AUTHORING.md)、
  [混音效果](BDO_MIXER_EFFECTS.md)、[乐器适配](INSTRUMENT_EDITOR_ADAPTATION.md)、
  [打击乐卷帘](PERCUSSION_ROLL_EVALUATION.md)。
- **乐理与奏法：** [BDO 奏法规则](BDO_ARTICULATION_RULES.md)、
  [通用乐器奏法](INSTRUMENT_ARTICULATION_GUIDE.md)、[MIDI 奏法模型](MIDI_TECHNIQUE_MODEL.md)、
  [乐理知识库](MUSIC_THEORY_KNOWLEDGE_BASE.md)。
- **扒谱：** [声部骨架](TRANSCRIPTION_VOICE_GUIDES.md)、
  [片段连续性](TRANSCRIPTION_FRAGMENT_AND_TIMBRE_PLAN.md)、
  [音色分组](REFERENCE_TIMBRE_GROUPING.md)、[Marnian Muse](MARNIAN_MUSE_OPTIONAL_BOUNDARY.md)、
  [Basic Pitch 许可证据](BASIC_PITCH_LICENSE_REVIEW.md)。
- **试听与素材：** [音源选择](AUDIO_SOURCE_STRATEGY.md)、
  [采样映射状态](BDO_SAMPLE_MAPPING_STATUS.md)、[内容红线](CONTENT_BOUNDARY.md)。
- **协作排练：** [多人同步器](MULTIPLAYER_SYNCHRONIZER.md)。

## 证据抽屉

- [`releases/`](releases/)：每个版本改了什么；最新记录是 [v1.3.6](releases/RELEASE_NOTES_V1.3.6.md)。
- [`benchmarks/`](benchmarks/)：可复现的性能步骤和当时测到的结果。
- [`history/`](history/)：旧实现与审计快照，别拿它替代今天的代码。
- [`reference/game-ui/`](reference/game-ui/)：经过筛选的游戏界面对照证据。

## 文档也有口吻

新增或整理文档时遵循[《文档说话方式》](WRITING_STYLE.md)：先说结论、少用套话、
把事实和推断拆开。可以可爱一点，但别让颜文字挡住错误和风险 `( •̀ ω •́ )✧`
