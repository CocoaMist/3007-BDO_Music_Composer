# Documentation

Use this page as the routing index for current product contracts, engineering
guides, and historical evidence. User-facing guides live in
[`locales/`](locales/). Current code and tests override historical records.

## Choose by task

| Task | Read first | Continue with |
|---|---|---|
| Use the application | [Localized guides](locales/) | [Composition authoring](BDO_COMPOSITION_AUTHORING.md) |
| Take over development | [Agent handoff](AGENT_HANDOFF.md) | [AI context](AI_CONTEXT.md), [editing guide](AI_EDITING_GUIDE.md) |
| Understand the system | [Architecture](ARCHITECTURE.md) | [Project structure](PROJECT_STRUCTURE.md) |
| Use the developer API | [Developer SDK](DEVELOPER_SDK.md) | [Extension roadmap](OPTIMIZATION_EXTENSION_ROADMAP.md) |
| Package or publish | [Windows packaging](WINDOWS_PACKAGING.md) | [Localization](LOCALIZATION.md), [content boundary](CONTENT_BOUNDARY.md) |
| Investigate performance | [Native core plan](PERFORMANCE_NATIVE_CORE_PLAN.md) | [Benchmarks](benchmarks/) |
| Review product UI | [Creative language and UI audit](CREATIVE_LANGUAGE_AND_UI_AUDIT.md) | [Professional desktop gates](PROFESSIONAL_DESKTOP_PHASE6_10.md) |

## Current contracts by domain

| Domain | Canonical references |
|---|---|
| Format and export | [BDO v9 codec](BDO_V9_CODEC.md), [music notes](BDO_MUSIC_NOTES.md), [conversion settings](CONVERSION_SETTINGS.md), [articulation and transpose lock](NOTE_ARTICULATION_TRANSPOSE_ALGORITHM_LOCK.md) |
| Editor and game evidence | [Composition authoring](BDO_COMPOSITION_AUTHORING.md), [mixer effects](BDO_MIXER_EFFECTS.md), [instrument editor adaptation](INSTRUMENT_EDITOR_ADAPTATION.md), [percussion roll evaluation](PERCUSSION_ROLL_EVALUATION.md) |
| Music semantics | [Articulation rules](BDO_ARTICULATION_RULES.md), [instrument articulation](INSTRUMENT_ARTICULATION_GUIDE.md), [MIDI technique model](MIDI_TECHNIQUE_MODEL.md), [music theory](MUSIC_THEORY_KNOWLEDGE_BASE.md) |
| Transcription | [Voice guides](TRANSCRIPTION_VOICE_GUIDES.md), [fragment and timbre plan](TRANSCRIPTION_FRAGMENT_AND_TIMBRE_PLAN.md), [reference timbre grouping](REFERENCE_TIMBRE_GROUPING.md), [Marnian Muse boundary](MARNIAN_MUSE_OPTIONAL_BOUNDARY.md), [Basic Pitch license review](BASIC_PITCH_LICENSE_REVIEW.md) |
| Audio and samples | [Audio source strategy](AUDIO_SOURCE_STRATEGY.md), [sample mapping status](BDO_SAMPLE_MAPPING_STATUS.md), [content boundary](CONTENT_BOUNDARY.md) |
| Product operations | [Localization](LOCALIZATION.md), [Windows packaging](WINDOWS_PACKAGING.md) |
| Rehearsal tools | [Multiplayer synchronizer](MULTIPLAYER_SYNCHRONIZER.md) |

## Evidence and history

- [`releases/`](releases/) contains versioned release scope and verification
  records. The latest packaged sample-preview record is
  [v1.2.1](releases/RELEASE_NOTES_V1.2.1.md); the source application is currently
  v1.3.0.
- [`benchmarks/`](benchmarks/) contains reproducible performance protocols and
  result snapshots.
- [`history/`](history/) contains dated implementation and audit records.
- [`reference/game-ui/`](reference/game-ui/) indexes private-source-safe game UI
  evidence.

Historical documents describe the state at the date recorded. Do not use them
as a substitute for the current contracts above, `AGENTS.md`, or regression
tests.
