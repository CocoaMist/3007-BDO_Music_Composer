# BDO Music Composer

Unofficial desktop music editor and Black Desert score workbench.

## Interface preview

![Project home with local projects and game scores](docs/images/readme-home.png)

| Multitrack timeline | Piano-roll note editor |
|---|---|
| ![Multitrack arrangement timeline](docs/images/readme-timeline.png) | ![Piano-roll editor with velocity lane and shortcut HUD](docs/images/readme-piano-roll.png) |

## Choose your language / 选择语言

Each link opens a concise guide for using and contributing to the project.

| Language | Full README |
|---|---|
| 简体中文 | [中文指南](docs/locales/zh-CN.md) |
| English | [English guide](docs/locales/en.md) |
| 日本語 | [日本語ガイド](docs/locales/ja.md) |
| 한국어 | [한국어 안내](docs/locales/ko.md) |

## Agent / maintainer handoff

AI coding agents and new maintainers must start with [`AGENTS.md`](AGENTS.md), then read the [Agent handoff and collaboration guide](docs/AGENT_HANDOFF.md). The guide contains the repository routing map, invariants, validation matrix, privacy rules, and a reusable handoff packet.

继续开发前，AI Agent 与新维护者必须先阅读 [`AGENTS.md`](AGENTS.md)，再阅读 [Agent 接手与协作手册](docs/AGENT_HANDOFF.md)。

## Project status

The core editing, autosave, optimization, preview, transcription-assist, and score-export flows are regression tested, but hardware and game-version compatibility can vary. This is an unofficial community project and is not affiliated with Pearl Abyss.

The application processes projects locally. It has no account login, telemetry, or file upload. It does not provide restricted-content acquisition or distribution; users are responsible for the source and permission of external content.

## Quick links

- [Documentation index](docs/README.md)
- [Developer SDK and reusable UI](docs/DEVELOPER_SDK.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Content and audio boundary](docs/CONTENT_BOUNDARY.md)
- [AI change-routing context](docs/AI_CONTEXT.md)
- [Agent handoff guide](docs/AGENT_HANDOFF.md)
- [Decoupling, performance, and extension roadmap](docs/OPTIMIZATION_EXTENSION_ROADMAP.md)
- [Windows packaging](docs/WINDOWS_PACKAGING.md)
- [BDO v9 codec](docs/BDO_V9_CODEC.md)
- [Localization policy](docs/LOCALIZATION.md)
- [Contributing](CONTRIBUTING.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)
- [MIT license for original project code](LICENSE)
