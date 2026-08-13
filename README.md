# BDO Music Composer

Unofficial desktop music editor and Black Desert score workbench. Arrange
multitrack clips, edit MIDI notes, preview locally, and export the current
project state as a BDO v9 score.

[简体中文](docs/locales/zh-CN.md) · [English](docs/locales/en.md) ·
[日本語](docs/locales/ja.md) · [한국어](docs/locales/ko.md)

![BDO Music Composer v1.3.0 multitrack arrangement](docs/images/readme-timeline.png)

Screenshots use the English interface. Track and instrument names are project
data and remain in their original language.

## Highlights

- Arrange and merge clips across a multitrack timeline with select, razor, and
  stateful snapping tools. Snap priority is time marker, clips, then grid.
- Edit notes, velocity, rhythm, articulations, and track instruments in the
  piano roll while keeping operations undoable.
- Open MIDI or existing BDO scores, autosave locally, preview the edited model,
  and export that same current model without falling back to the original MIDI.
- Use local optimization and transcription assistance as reviewable editing
  aids rather than destructive one-click replacements.

## Get started

Most users should download the Windows build from
[GitHub Releases](https://github.com/CocoaMist/3007-BDO_Music_Composer/releases).
Source development requires Python 3.12 and the environment described in
[`CONTRIBUTING.md`](CONTRIBUTING.md). The application entry point is `main.py`.

1. Create a project, import MIDI, or open a BDO score.
2. Arrange clips on the timeline and edit notes in the piano roll.
3. Preview the result and review automatic export validation.
4. Export with a valid Owner ID, then verify the score in game.

## Note editor

![BDO Music Composer v1.3.0 piano-roll note editor](docs/images/readme-piano-roll.png)

## Documentation

| Need | Start here |
|---|---|
| Use the application | [中文](docs/locales/zh-CN.md) · [English](docs/locales/en.md) · [日本語](docs/locales/ja.md) · [한국어](docs/locales/ko.md) |
| Browse technical documentation | [Documentation index](docs/README.md) |
| Understand architecture and data flow | [Architecture](docs/ARCHITECTURE.md) |
| Contribute code | [Contributing guide](CONTRIBUTING.md) |
| Continue work as an agent or maintainer | [`AGENTS.md`](AGENTS.md), then [Agent handoff](docs/AGENT_HANDOFF.md) |
| Build a Windows release | [Windows packaging](docs/WINDOWS_PACKAGING.md) |

## Local content and preview audio

Projects, settings, Owner IDs, caches, and external content remain local. The
application has no account login, telemetry, or file upload, and it does not
acquire or distribute restricted content. See the governing
[content boundary](docs/CONTENT_BOUNDARY.md).

Releases may separately provide the optional
`BDO-Approximate-CC0-Full-Coverage-v4-Compact.bdosamples` pack. It contains
independently licensed CC0 material for approximate editing preview, not Black
Desert client audio or game-original sound. Provenance, configuration, and the
v1.2.1 pack checksum are documented in
[Audio source strategy](docs/AUDIO_SOURCE_STRATEGY.md).

## Status and license

Core editing, autosave, optimization, preview, transcription assistance, and
score export have automated regression coverage. Hardware, audio-device, and
game-version compatibility can still vary. This community project is not
affiliated with Pearl Abyss.

Original project code is available under the [MIT License](LICENSE).
Third-party components and references retain their own terms; see
[Third-party notices](THIRD_PARTY_NOTICES.md).
