# BDO Music Composer

[简体中文](zh-CN.md) · [English](en.md) · [日本語](ja.md) · [한국어](ko.md) · [Project home](../../README.md)

BDO Music Composer is an unofficial desktop music editor for creating, reviewing, previewing, and exporting Black Desert scores locally. It is not a general-purpose DAW and is not affiliated with Pearl Abyss.

> The tool does not acquire or distribute restricted content. Users are responsible for the source and permission of external content.

<!-- section:status -->
## Status

Editing, autosave, optimization, preview, transcription assistance, and score export have automated regression coverage. Compatibility can still vary by computer, audio device, and game version.

<!-- section:features -->
## Features

- Import MIDI or begin with an empty project and edit multitrack notes, velocity, rhythm, and articulations.
- Continue editing existing scores while preserving the current project state through export.
- Review local transcription assistance as an editable draft before committing it.
- Use undoable optimization, autosave, export checks, and local project management.

<!-- section:requirements -->
## Install and run

Most users should use the published Windows build. Source development requires Python 3.12 and the environment described in the [contributing guide](../../CONTRIBUTING.md). The project entry point is `main.py`.

<!-- section:workflow -->
## Basic workflow

1. Create a project, import MIDI, or open a score.
2. Edit the arrangement and notes.
3. Review the result with preview and validation.
4. Export with a valid Owner ID and verify the score in game.

<!-- section:local-assets -->
## Local content

Projects, settings, caches, and external content remain local. External content is never added automatically to the repository or a release. Core editing and export continue without optional content.

The release page may separately provide
`BDO-Approximate-CC0-Full-Coverage-v4-Compact.bdosamples` for approximate
preview. It is not embedded in the application. Choose **Sample Pack** in
Settings to locate it or another compatible pack for which you have the
required rights; the built-in general source remains available.

The v4 WAV bytes come from three independent CC0 libraries:
[VSCO 2 Community Edition](https://github.com/sgossner/VSCO-2-CE),
[Versilian Community Sample Library](https://github.com/sgossner/VCSL), and
[FreePats CC0 instrument banks](https://freepats.zenvoid.org/). The embedded
`manifest.json` records the source library, upstream relative path, and SHA-256
for every slot. The pack contains no Black Desert client audio and is an
approximate editing preview, not game-original or A/B-verified sound. Its
v1.2.1 SHA-256 is
`82cea29f1316b943571663e4150b31e353da4ab9f556141ed65b6598a384db63`.

<!-- section:architecture -->
## Project structure

The repository separates the application, core capabilities, documentation, tests, scripts, and packaging. See the [architecture](../ARCHITECTURE.md) and [extension roadmap](../OPTIMIZATION_EXTENSION_ROADMAP.md).

<!-- section:invariants -->
## Correctness boundary

The current editor state must survive preview, save, and export. The tool does not silently fall back to the original import or report success for unsupported output. See [AGENTS.md](../../AGENTS.md).

<!-- section:testing -->
## Validation

Maintainers run the complete test suite, repository checks, and relevant UI or packaging smoke tests. Routing and minimum gates are in [AI context](../AI_CONTEXT.md) and the [handoff guide](../AGENT_HANDOFF.md).

<!-- section:packaging -->
## Release

Public builds must pass dependency, license, privacy, resource, and startup checks. User projects, identity data, caches, external content, and private keys never enter a release.

<!-- section:privacy -->
## Privacy

The app requires no account login and includes no telemetry or file upload. Scores can contain Owner IDs and character information, so do not commit private scores.

<!-- section:docs -->
## Documentation

Start at the [documentation index](../README.md). Contributors should also read the [architecture](../ARCHITECTURE.md), [AI context](../AI_CONTEXT.md), and [handoff guide](../AGENT_HANDOFF.md).

<!-- section:license -->
## License and credits

Original code is available under the [MIT License](../../LICENSE). Third-party components and references retain their own terms; see [third-party notices](../../THIRD_PARTY_NOTICES.md).
