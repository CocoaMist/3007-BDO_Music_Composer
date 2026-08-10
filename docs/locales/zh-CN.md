# BDO Music Composer

[简体中文](zh-CN.md) · [English](en.md) · [日本語](ja.md) · [한국어](ko.md) · [项目主页](../../README.md)

BDO Music Composer 是一款非官方桌面音乐编辑器，用于本地创作、整理、试听和导出 Black Desert 曲谱。它不是通用数字音频工作站，也不隶属于 Pearl Abyss。

> 本工具不提供受限制内容的获取或传播能力；外部内容须由用户自行确保来源与授权。

<!-- section:status -->
## 状态

编辑、自动保存、优化、试听、扒谱辅助和曲谱导出均有自动回归验证。不同电脑、音频设备和游戏版本仍可能存在兼容差异。

<!-- section:features -->
## 功能

- 导入 MIDI 或创建空白工程，并编辑多轨音符、力度、节奏和奏法。
- 打开现有曲谱继续编辑，保留当前工程状态进行导出。
- 使用本地辅助功能整理参考音频，并将结果作为可审阅草稿。
- 提供可撤销优化、自动保存、导出检查和本地项目管理。

<!-- section:requirements -->
## 获取与启动

普通用户优先使用发布页面提供的 Windows 版本。源码开发需要 Python 3.12，并按照[贡献指南](../../CONTRIBUTING.md)准备环境。项目入口为 `main.py`。

<!-- section:workflow -->
## 基本流程

1. 新建工程、导入 MIDI 或打开曲谱。
2. 在时间轴和音符编辑器中完成调整。
3. 使用试听和检查功能确认结果。
4. 填写有效的 Owner ID 后导出，并在游戏内复核。

<!-- section:local-assets -->
## 本地内容

工程、设置、缓存和外部内容都保留在本机。外部内容不会自动进入仓库或发布包。缺少可选内容时，主要编辑与导出流程仍可使用。

<!-- section:architecture -->
## 项目结构

仓库采用清晰的应用、核心能力、文档、测试、脚本与打包分区。完整说明见[架构](../ARCHITECTURE.md)和[扩展路线](../OPTIMIZATION_EXTENSION_ROADMAP.md)。

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
