# 乐理、配器与拟真奏法知识库

状态：2026-07-10。此文档与 `bdo_articulation_profiles.py` 配套：文档供审阅，资料表供优化器生成可追溯建议。真实演奏依据、BDO 映射验证和算法推断严格分层；只有已验证映射才可能自动进入预览。

## 保守分析原则

- **节拍与乐句**：小节第一拍最强；常见四拍子第三拍次强。休止、长时值和旋律收束共同界定乐句，不能只依固定毫秒切段。
- **旋律与织体**：同起点多音是和弦屏障；单声部才可讨论滑音、颤音、连奏。低音重复短音更可能是 riff，分离短音可能是节奏伴奏，其他单线才默认视作旋律。
- **调性与和声**：仅当全曲时值加权音级能稳定匹配一个大/小调时启用。和弦外音按进入/离开方式理解；调性不明、调式/爵士/无调性素材不套功能和声。
- **终止与换气**：句尾、明显停顿、长音与和声收束优先保持原表达；管乐在乐句边缘避免密集奏法，弦乐避免把收束长音改成连续滑音或颤音。

## 乐器族速查

| 乐器族 | 可自动分析的可靠语境 | 仅建议/禁用条件 |
| --- | --- | --- |
| 弦乐 | 紧密同向旋律、短而分离的节奏型、原音-邻音-原音装饰 | 和弦、交叉声部、句尾长音不自动滑音/颤音 |
| 吉他/贝斯 | 低中音重复短时值 riff 的弱音；高力度短音重击 | 电吉他 FX、泛音与 X 音符默认只建议 |
| 管乐/铜管 | 长音按原力度映射持续层；连奏依赖同一旋律线 | 句尾/换气边缘避免装饰；不凭空插入休止 |
| 竖琴 | 同向快速级进的音阶性 run；明确大/小三和弦 | 普通旋律不判 gliss；gliss 映射未验证时只建议 |
| 钢琴 | 已有 CC64 优先；长音跨入后续和声可建议踏板 | 踏板不等于所有长音；不破坏同拍和弦的力度关系 |
| 打击乐 | 保留 timing/velocity 优化 | 不从单一长音生成滚奏或 crash |

## 机器规则与置信度

候选评分由演奏语境、节拍/乐句、织体角色、音区、调性稳定度和冲突风险组成。当前所有自动分析结果均仅建议；只有本地游戏 A/B 验证矩阵明确通过某个 `乐器 × ntype` 后，才允许它进入自动预览。手工 `ntype`、轨道 FX、同拍和弦和未验证映射优先级更高。

## 资料来源

- Music Theory for the 21st-Century Classroom：非和弦音以接近与离开方式分类。<https://musictheory.pugetsound.edu/mt21c/NonChordTonesIntroduction.html>
- Open Music Theory：和声、终止与乐句结束的听觉语境。<https://viva.pressbooks.pub/openmusictheorycopy/chapter/intro-to-harmony/>
- University of Minnesota, Techniques of Orchestration：配器应兼顾音域、可演奏性、音色与织体透明度。<https://open.lib.umn.edu/musiccomposition/chapter/type-i-orchestration/>
- Timbre and Orchestration：乐器发声与传统/扩展技法资料。<https://timbreandorchestration.org/learn-about-orchestration>
