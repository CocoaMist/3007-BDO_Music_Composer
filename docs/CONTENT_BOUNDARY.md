# 内容红线：不碰客户端音频

状态：**产品硬约束**。程序不列出、提取、转换、打包、下载或传播客户端音频。
这不是法律意见，也不表示 Pearl Abyss 对本程序作出授权或背书。

## Decision source

Before publishing a game-audio pack, the maintainer asked Pearl Abyss's fan
content contact whether client instrument audio could be extracted, converted
to WAV or a separate optional pack, distributed for free, or prepared locally
by an end user. The written reply said that these uses are not within the
currently permitted fan-content scope and asked that user-side extraction or
conversion support not be provided. The reply cited possible Pearl Abyss and
third-party rights and licence obligations.

The private correspondence is retained by the maintainer. This repository
records only the operational conclusion needed to keep contributors and builds
inside the same boundary.

## Product contract

The public application and repository must not:

- list or browse PAZ contents for the purpose of locating client audio;
- extract client instrument audio, SoundBanks, WEM payloads, or BGM;
- convert client audio to WAV or another separately usable format;
- build, download, bundle, publish, or help users build a pack from client
  audio, even when the pack is free and separate from the application;
- describe the Composer itself as endorsed, approved, or licensed by Pearl
  Abyss.

The project may continue to provide:

- MIDI/project editing, deterministic optimization, local transcription, and
  BDO v9 score interoperability;
- original procedural preview;
- adapters for independently licensed, user-selected third-party preview
  sources, provided the application neither acquires those sources nor assumes
  that the user has redistribution rights;
- a narrow local artwork import that reads exactly two allow-listed composition
  UI resources into a local cache. It is not a general PAZ browser, exposes no
  audio path, and is not evidence of authorization for other client resources.

## Extension gate

Every future audio backend or sample-pack integration must answer four
questions before it can enter production:

1. What is the independent source and licence of every audio asset?
2. Does any step require reading, locating, decoding, or converting client
   audio? If yes, reject the integration.
3. Can the backend remain optional, replaceable, and outside project/export
   serialization?
4. Do packaging inventory, acknowledgements, and offline tests prove that no
   audio asset or acquisition helper is shipped?

`src/bdo_music_composer/core/content_boundary.py` owns the short wording displayed
in the application. `tools/check_repository_hygiene.py` rejects the retired
client-audio extraction/conversion filenames so the boundary is executable,
not merely documentary.

## Structural consequence

The production dependency direction remains compact:

```text
UI -> app workflows -> editor/audio/project/export domains
                    -> independent bdo_midi / bdo_codec / bdo_export
```

Production UI no longer imports an application feature from `tools/`. The
allow-listed local artwork workflow belongs to the Qt-free
`src/bdo_music_composer/app/local_game_art.py`; image decoding is injected by
`src/bdo_music_composer/ui/local_game_art_qt.py`, and the bounded path-table
primitive is isolated in `src/bdo_music_composer/core/paz_readonly.py`. General
developer tools remain audits, benchmarks, and validators only.
