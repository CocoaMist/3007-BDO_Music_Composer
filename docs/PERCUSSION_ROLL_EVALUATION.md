# 统一钢琴卷帘与打击乐键名适配评估

## 结论

项目只保留一套钢琴卷帘呈现和交互。所有乐器共用 `TrackState`、`Note`、连续
MIDI 纵轴、矩形音块、时值手柄、选择、命令、力度通道和事务提交；打击乐只
适配左侧键名和推荐可视范围，不再存在独立的打击乐模式或菱形音符。

当前规则：

- 所有音符都以实际 `dur` 绘制矩形，并支持与钢琴音符相同的移动、左右缩放、
  力度和奏法交互；
- GM 通道 10 鼓轨保留 GM 音高和 `ntype`，BDO 原生鼓保留 48–64 / 99；
- 架子鼓按来源显示 BDO 鼓件名或 GM 鼓键名；手鼓显示游戏验证的
  `Bng1/Bng2/Cng1/Cng2` 开放、闭合与 Flam 键名，钹显示游戏的 `HIT`，手碟
  尚无验证名称时回退标准音名；
- 打击乐音符块使用对应键轨的原始游戏名称（例如 `Kck`、`SnrHit`、
  `Bng2-Close`、`HIT`），左轨仍可追加当前语言说明；
- 超出当前鼓键映射的活动音高显示为 `MIDI n · 未映射鼓键`，保留原音并标红，
  不隐藏、删除或自动改音。

## 网络方案与开源技术评估

- Ardour 的 MIDNAM 提供按键名称，说明键名可作为共享 MIDI 编辑器的独立数据
  层，而不必改变正式音符：
  <https://manual.ardour.org/working-with-regions/region-editor/>、
  <https://manual.ardour.org/working-with-tracks/midi-track-controls/>。
- Rosegarden 的 Percussion Matrix 以鼓件名称替代普通键名；本项目只采用其
  “名称映射与音符数据分离”的概念，不采用隐藏时值的交互：
  <https://www.rosegardenmusic.com/doc/en/percussion-matrix-view.html>。
- MuseScore 的打击乐面板和 drumset 映射说明了鼓件集合应是数据，而不是散落
  在绘制代码里的判断；其当前发布也允许调整鼓垫列数：
  <https://github.com/musescore/MuseScore/releases>。
- LMMS 的 Beat/Bassline Step Editor 适合循环鼓机，但 BDO 工程需要任意毫秒
  起音、多速度和跨小节编辑，因此不应把步进机作为主编辑模型：
  <https://docs.lmms.io/user-manual/navigating-lmms/3.8>。
- 吉他模式可参考 TuxGuitar 和 Power Tab 的弦/品位模型，但它们分别使用
  LGPL/GPL，且技术栈与本项目不同。这里只借鉴公开交互概念，不复制代码或
  资源：<https://github.com/helge17/tuxguitar>、
  <https://github.com/powertab/powertabeditor>。

上述项目多为 GPL/LGPL。BDO Music Composer 本阶段不引入依赖、不复制实现，
只依据公开文档采用通用交互模式，因此不改变当前依赖清单和许可证边界。

## 架构方案

`editor/editor_models.py` 的 `percussion_key_label_for_track()` 是 Qt 无关键名
适配边界。它根据目标游戏乐器和架子鼓来源返回显示名；Qt 画布只消费显示名，
音符命令继续只处理原始 MIDI pitch/time/duration。专用 `editor_roll_modes.py`
已删除，避免未来重新形成两套几何和交互分支。

后续若实施稀疏鼓行，可在模式下增加 `pitch -> lane` 双射映射，并统一替换画布
的纵向坐标函数；任何未映射的源音符必须保留并进入明确的未映射 MIDI 行，
不能隐藏或删除。

吉他弦乐模式是下一阶段，不能直接把 pitch 当成唯一视觉行：同一音高可能有
多个弦/品位位置。实施前需设计以稳定音符身份关联的可选
`StringPosition(string, fret)` 侧车、调弦配置、冲突迁移和无侧车时的确定性
自动指法。该侧车不得改变 `Note` 五字段线格式，也不得影响未选择弦乐模式的
项目往返。

## 验收与风险

验收：架子鼓、手鼓、钹和手碟均使用与钢琴相同的矩形音符及缩放手柄；不存在
模式下拉框或模式状态；选择、移动、新建、试听、撤销、应用和导出保持同一音符
值；BDO、GM、其他游戏打击乐键名与未映射鼓键名称正确；离屏渲染、本地化、
编辑器与导出回归通过。

主要风险是画布仍有部分分析叠层使用连续 pitch 坐标。第一阶段不压缩纵轴，
避免破坏候选、旋律线和其他轨参考层；稀疏行作为单独里程碑，在统一纵坐标
适配器和性能基准就绪后实施。
