# BDO Music Composer ♪

给《黑色沙漠》作曲玩家准备的本地多轨编辑器。导入 MIDI、拆分和排列 Clip、
细修音符与力度，最后导出游戏可读的 BDO v9 曲谱。欢迎来写谱
`(｡•̀ᴗ-)✧`

[简体中文](docs/locales/zh-CN.md) · [English](docs/locales/en.md) ·
[日本語](docs/locales/ja.md) · [한국어](docs/locales/ko.md)

[下载 Windows 版](https://github.com/CocoaMist/3007-BDO_Music_Composer/releases/latest) ·
[查看更新记录](docs/releases/RELEASE_NOTES_V1.3.5.md) ·
[报告问题](https://github.com/CocoaMist/3007-BDO_Music_Composer/issues)

![BDO Music Composer 多轨编排界面](docs/images/readme-timeline.png)

> **关于稳定版：** 如果游戏内部的曲谱机制没有变化，当前版本大概率会先作为
> 暂时的长期稳定版维护。之后会优先处理兼容性和确实影响写谱的问题，不为了凑
> 版本号频繁更新。能安稳写歌，比数字一直往上跳重要一点 `( •̀ ω •́ )✧`

## 这是做什么的？

BDO Music Composer 负责从“手里有一份 MIDI”到“游戏里能继续检查和演奏”之间
最麻烦的那段工作。它有多轨时间轴、钢琴卷帘、Clip 编辑、自动保存、本地试听、
优化与扒谱辅助，也能重新打开已有的 BDO 曲谱。

最重要的一点很朴素：你现在看见并改过的音符，就是保存、试听和导出的音符。
程序不会在最后一步偷偷换回最初导入的 MIDI。

它不是完整 DAW，也不会替你判断一首曲子最终该怎么写。自动功能给建议，决定权
还是在你手里。

## 下载与上手

普通用户直接从 [GitHub Releases](https://github.com/CocoaMist/3007-BDO_Music_Composer/releases)
下载 `BDO-Music-Composer.exe`。这是 Windows 单文件程序，不需要另外安装 Python。

1. 新建工程、导入 MIDI，或者打开一份已有 BDO 曲谱。
2. 在时间轴上移动、裁切、复制和排列 Clip。
3. 双击 Clip 进入音符编辑器，调整音高、时值、奏法和力度。
4. 填写有效的 Owner ID，导出后进游戏复核。

第一次使用不用把所有按钮都研究完。先导入、试听、改几颗音，再导出一份小曲子，
很快就能摸清它的脾气啦 `ฅ^•ﻌ•^ฅ`

## 写谱时能用到什么？

- **多轨编排：** 框选或多选 Track/Clip，移动、切分、复制、重复、合并；吸附顺序
  是时间标记、Clip、网格，按住 `Alt` 可以临时绕过吸附。
- **音符编辑：** 在钢琴卷帘中处理音高、时值、力度、奏法、量化和复制粘贴，
  普通编辑与 Clip 编辑都能撤销和恢复。
- **力度控制：** 全局调整作用于整首曲子的力度基线；选择 Track 时批量调整该轨
  所有 Clip；选择 Clip 时只改当前分块。百分比会写进实际音符，同时保留工程内
  的还原基线，试听与导出不会再暗中乘一次。
- **导入与导出：** 支持 MIDI 和 BDO v9。游戏要求的双力度、物理分轨、空尾轨、
  乐器、Volume 与效果设置都会经过导出校验。
- **本地试听：** 内置通用试听音色，也可选择合法来源的兼容音源包。试听只用来
  辅助编辑，最终效果请以游戏内为准。
- **辅助工具：** MIDI 优化和参考音频扒谱都在本机运行，结果先交给你审阅，不会
  一键替换整份工程。

## 音符编辑器

![BDO Music Composer 音符编辑器](docs/images/readme-piano-roll.png)

界面截图使用英文语言包；Track、乐器名和文件名属于工程数据，不会被翻译。

## 用之前请知道

- 这是社区项目，与 Pearl Abyss 没有隶属关系。
- 工程、Owner ID、设置、缓存和参考音频留在本机；应用没有账户登录、遥测或文件
  上传。
- 程序不提供游戏客户端音频的提取、下载或传播功能。外部内容请自行确认来源和
  授权，具体边界见[内容政策](docs/CONTENT_BOUNDARY.md)。
- BDO 文件保存的是游戏最终曲谱，不保存 Clip 名字、颜色、选区和百分比基线。
  想继续完整编辑，请把工程文件也留好。
- 硬件、声卡驱动和未来游戏版本都可能带来差异。重要作品导出后请进游戏听一遍，
  这一步不丢人，反而很专业。

## 源码、文档与参与开发

源码开发使用 Python 3.12，入口是 `main.py`。环境准备、测试和提交方式见
[贡献指南](CONTRIBUTING.md)。

| 想找什么 | 去哪里 |
|---|---|
| 中文完整说明 | [简体中文指南](docs/locales/zh-CN.md) |
| English / 日本語 / 한국어 | [English](docs/locales/en.md) · [日本語](docs/locales/ja.md) · [한국어](docs/locales/ko.md) |
| 文档总目录 | [docs/README.md](docs/README.md) |
| 架构与数据流 | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Windows 打包 | [docs/WINDOWS_PACKAGING.md](docs/WINDOWS_PACKAGING.md) |
| Agent 或维护者接手 | [AGENTS.md](AGENTS.md) → [docs/AGENT_HANDOFF.md](docs/AGENT_HANDOFF.md) |

## 谢谢

感谢 CN 服务器「彩虹乐队」玩家参与测试、录屏和反馈。很多看起来不起眼的小问题，
都是大家真的拿去写歌以后才抓出来的。

项目使用 Python、Qt/PySide6、NumPy、SciPy、Mido、Basic Pitch、ONNX Runtime
等开放项目，也参考了社区对 BDO 曲谱格式的研究。开发过程中使用过 ChatGPT
协助代码和文档整理；应用本身不接入 OpenAI API，也不包含云端模型运行时。
完整来源、许可和作者信息见[第三方声明](THIRD_PARTY_NOTICES.md)。

原创代码使用 [MIT License](LICENSE)。第三方组件继续遵循各自许可。

写谱愉快，游戏里见 ♪
