# BDO Music Composer

Unofficial PySide6 MIDI editor, local transcription workbench, optimizer, sample preview, and Black Desert v9 music-score exporter.

## Choose your language / 选择语言

Each link opens a complete, standalone project guide with features, setup, workflow, architecture, testing, packaging, privacy, limitations, and licensing.

| Language | Full README |
|---|---|
| 简体中文 | [README.zh-CN.md](README.zh-CN.md) |
| English | [README.en.md](README.en.md) |
| 日本語 | [README.ja.md](README.ja.md) |
| 한국어 | [README.ko.md](README.ko.md) |

## Agent / maintainer handoff

AI coding agents and new maintainers must start with [`AGENTS.md`](AGENTS.md), then read the [Agent handoff and collaboration guide](docs/AGENT_HANDOFF.md). The guide contains the repository routing map, invariants, validation matrix, privacy rules, and a reusable handoff packet.

继续开发前，AI Agent 与新维护者必须先阅读 [`AGENTS.md`](AGENTS.md)，再阅读 [Agent 接手与协作手册](docs/AGENT_HANDOFF.md)。

## Project status

v1.0.0 is the first public stable major release. Core editor, autosave, optimization, preview, transcription-assist, and BDO v9 export flows are regression tested, but hardware-specific audio and game-version compatibility can still vary. This is an unofficial community project, not affiliated with Pearl Abyss.

The application processes MIDI, Owner IDs, audio, autosaves, and exported scores locally. It does not include account login, telemetry, file upload, an OpenAI API client, extracted game audio, or game-owned artwork.

## Quick links

- [Architecture](docs/ARCHITECTURE.md)
- [AI change-routing context](docs/AI_CONTEXT.md)
- [Agent handoff guide](docs/AGENT_HANDOFF.md)
- [Decoupling, performance, and extension roadmap](docs/OPTIMIZATION_EXTENSION_ROADMAP.md)
- [Windows packaging](docs/WINDOWS_PACKAGING.md)
- [BDO v9 codec](docs/BDO_V9_CODEC.md)
- [Localization policy](docs/LOCALIZATION.md)
- [Contributing](CONTRIBUTING.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)
- [MIT license for original project code](LICENSE)
