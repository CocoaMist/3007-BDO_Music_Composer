# BDO Music Composer

[简体中文](zh-CN.md) · [English](en.md) · [日本語](ja.md) · [한국어](ko.md) · [项目主页](../../README.md)

这是给 Black Desert 作曲玩家准备的本地多轨编辑器：导入 MIDI、编排 Clip、细修音符和力度，再导出游戏可读的曲谱。它不是通用 DAW，也不隶属于 Pearl Abyss `(｡•̀ᴗ-)✧`

> 本工具不提供受限制内容的获取或传播能力；外部内容须由用户自行确保来源与授权。

<!-- section:status -->
## 现在适不适合用

v1.3.6 已覆盖编辑、自动保存、优化、试听、扒谱辅助和曲谱导出。如果游戏内部的曲谱机制没有变化，这一版大概率会先作为暂时的长期稳定版维护。电脑、音频设备和游戏版本不同，仍可能遇到兼容差异。

<!-- section:features -->
## 能做什么

- 导入 MIDI 或创建空白工程，在多音轨时间轴中编排、裁切、移动和合并 Clip。
- 分别调整全轨道、多个 Track 或多个 Clip 的力度，结果能撤销、保存并进入导出。
- 使用按“时间标记、Clip、网格”排序的自动吸附，并在钢琴卷帘中编辑音符、力度、节奏和奏法。
- 打开现有曲谱继续编辑，保留当前工程状态进行导出。
- 使用本地辅助功能整理参考音频，并将结果作为可审阅草稿。
- 提供可撤销优化、自动保存、自动导出校验和本地项目管理。

<!-- section:requirements -->
## 下载和启动

普通用户优先使用发布页面提供的 Windows 版本。源码开发需要 Python 3.12，并按照[贡献指南](../../CONTRIBUTING.md)准备环境。项目入口为 `main.py`。

<!-- section:workflow -->
## 写一首曲子的最短路线

1. 新建工程、导入 MIDI 或打开曲谱。
2. 在时间轴中编排 Clip，并在音符编辑器中完成细节调整。
3. 使用试听和自动校验确认结果。
4. 填写有效的 Owner ID 后导出，并在游戏内复核。

<!-- section:local-assets -->
## 本地内容

工程、设置、缓存和外部内容都保留在本机。外部内容不会自动进入仓库或发布包。缺少可选内容时，主要编辑与导出流程仍可使用。

发行页可另行提供 `BDO-Approximate-CC0-Full-Coverage-v4-Compact.bdosamples`
近似试听音源包。主程序不内嵌该包；在设置中选择“音源包”后定位文件即可，亦可改选其他兼容且具有合法使用权限的包。内置通用音源始终可用。

v4 包的 WAV 字节来自三个独立的 CC0 开放音源库：
[VSCO 2 Community Edition](https://github.com/sgossner/VSCO-2-CE)、
[Versilian Community Sample Library](https://github.com/sgossner/VCSL) 和
[FreePats CC0 音色库](https://freepats.zenvoid.org/)。包内 `manifest.json`
逐槽记录来源库、上游相对路径和 SHA-256。它不包含 Black Desert 客户端音频，
仅用于近似编辑试听，不代表游戏原声或已完成 A/B 验证。v1.2.1 发布包摘要为
`82cea29f1316b943571663e4150b31e353da4ab9f556141ed65b6598a384db63`。

<!-- section:architecture -->
## 想看看源码

代码按应用、编辑器、音频、导出、文档、测试和打包分开。找路先看[文档索引](../README.md)，想深挖再看[架构](../ARCHITECTURE.md)和[扩展路线](../OPTIMIZATION_EXTENSION_ROADMAP.md)。

<!-- section:invariants -->
## 正确性边界

当前编辑状态必须贯穿试听、保存和导出；工具不会静默改用原始导入文件，也不会在不支持的条件下假装导出成功。详细约束见 [Agent 指南](../../AGENTS.md)。

<!-- section:testing -->
## 验证

维护者应执行完整测试、结构检查和相应的界面或打包冒烟测试。任务路由和最低验证要求见 [AI 上下文](../AI_CONTEXT.md)与[接手手册](../AGENT_HANDOFF.md)。

<!-- section:packaging -->
## 发布

公开版本必须通过依赖、许可、隐私、资源和启动检查。用户工程、身份信息、缓存、外部内容和私有密钥不得进入发布包。

<!-- section:privacy -->
## 隐私

应用不要求账户登录，不包含遥测或文件上传。曲谱可能包含 Owner ID 与角色信息，请勿提交到公开仓库。

<!-- section:docs -->
## 文档

从[文档索引](../README.md)开始；开发者还应阅读[架构](../ARCHITECTURE.md)、[AI 上下文](../AI_CONTEXT.md)和[接手手册](../AGENT_HANDOFF.md)。

<!-- section:license -->
## 许可与致谢

原创代码适用 [MIT License](../../LICENSE)。第三方组件、资料和引用遵循各自条款，详见[第三方声明](../../THIRD_PARTY_NOTICES.md)。
