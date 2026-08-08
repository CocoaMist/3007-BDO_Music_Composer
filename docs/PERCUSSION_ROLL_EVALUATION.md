# 专属打击乐卷帘与可扩展乐器布局评估

## 结论

项目适合按乐器自动提供钢琴/打击乐两种卷帘呈现，但不应复制第二套音符模型、
撤销栈、试听或导出管线。推荐边界是：共用 `TrackState`、`Note`、时间坐标、
选择、命令、力度通道和事务提交，仅把纵轴语义、左轨道、音符外形以及时值
交互封装为 Qt 无关的卷帘模式能力，再由现有画布呈现。

第一阶段由目标乐器自动选择，不显示手动切换控件：

- 钢琴模式保留连续 MIDI 键盘、矩形音块和时值手柄；
- 打击乐模式使用鼓件名称轨、菱形击打标记，不把视觉宽度描述为可听时值；
- GM 通道 10 鼓轨保留 GM 音高和 `ntype`，BDO 原生鼓保留 48–64 / 99；
- BDO 架子鼓目标轨固定进入打击乐卷帘，其他乐器固定进入钢琴卷帘；
- 超出当前鼓键映射的活动音高显示为 `MIDI n · 未映射鼓键`，保留原音并标红，
  不隐藏、删除或自动改音。

## 网络方案与开源技术评估

- Ardour 同一 MIDI 编辑器支持普通和 drum note mode，并在打击模式以菱形
  表示击打；MIDNAM 提供按键名称。这支持“共享编辑器、替换呈现能力”的方案：
  <https://manual.ardour.org/working-with-regions/region-editor/>、
  <https://manual.ardour.org/working-with-tracks/midi-track-controls/>。
- Rosegarden 的 Percussion Matrix 与普通 Matrix 共用编辑行为，但以鼓件名称
  替代钢琴键并隐藏音符时值；缺少映射时才回退钢琴视图：
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

`editor/editor_roll_modes.py` 是 Qt 无关能力注册表。每个模式声明稳定键、固定
源语言标签、是否显示钢琴键、是否显示时值和音符外形。Qt 画布消费能力，
音符命令继续只处理原始 MIDI pitch/time/duration。

后续若实施稀疏鼓行，可在模式下增加 `pitch -> lane` 双射映射，并统一替换画布
的纵向坐标函数；任何未映射的源音符必须保留并进入明确的未映射 MIDI 行，
不能隐藏或删除。

吉他弦乐模式是下一阶段，不能直接把 pitch 当成唯一视觉行：同一音高可能有
多个弦/品位位置。实施前需设计以稳定音符身份关联的可选
`StringPosition(string, fret)` 侧车、调弦配置、冲突迁移和无侧车时的确定性
自动指法。该侧车不得改变 `Note` 五字段线格式，也不得影响未选择弦乐模式的
项目往返。

## 验收与风险

第一阶段验收：架子鼓自动进入打击乐卷帘且不显示模式下拉框；其他乐器自动
进入钢琴卷帘；选择、移动、新建、试听、撤销、应用和导出保持同一音符值；
打击模式不暴露误导性的左右时值手柄；GM、BDO 与未映射鼓键名称正确；离屏
渲染、本地化、优化器、编辑器与导出回归通过。

主要风险是画布仍有部分分析叠层使用连续 pitch 坐标。第一阶段不压缩纵轴，
避免破坏候选、旋律线和其他轨参考层；稀疏行作为单独里程碑，在统一纵坐标
适配器和性能基准就绪后实施。
