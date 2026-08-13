# Localization and regional terminology

The desktop UI has five maintained locales. Simplified Chinese is the exact-source
catalog language; the other catalogs must keep the same key and placeholder set.

| Locale | Intended audience | Game terminology baseline |
|---|---|---|
| `zh_CN` | Simplified Chinese UI | Project source copy; game names remain fixed catalog data |
| `zh_TW` | Traditional Chinese UI | Taiwan desktop terminology; game names remain fixed catalog data |
| `en_US` | NA/EU and the fallback for other regions | Official NA/EU Music Album terminology |
| `ja_JP` | Japan | Official Japanese Music Album terminology |
| `ko_KR` | Korea | Official Korean Music Album terminology |

Automatic selection follows the operating-system UI locale when it is one of the
supported languages. Unknown locales use English. Users can always pin a locale
in Settings; the stored locale codes remain stable.

`zh_TW` is generated from the complete Simplified Chinese source-key set after
all fixed UI and General MIDI names are registered. A deterministic built-in
phrase table applies Taiwan desktop terms before character conversion, so source
and frozen builds do not need a runtime OpenCC dependency.

## Locked product terms

| Concept | English | Japanese | Korean |
|---|---|---|---|
| game composition screen | Music Album | 音楽アルバム | 음악 앨범 |
| game score | Score | 楽譜 | 악보 |
| game note technique (`ntype`) | Musical Technique | 奏法 | 주법 |
| shared master effect | Effector | エフェクター | 이펙터 |
| per-instrument effect send | AuxSend | AuxSend | AuxSend |
| Marnian sound selector | Marnian Timbre | マルニアン音色 | 마르니언 음색 |
| audio-to-note workspace | Transcription | 採譜 | 채보 |
| spectrogram | Spectrogram | スペクトログラム | 스펙트로그램 |
| frame evidence | Frame Activation | フレーム活性度 | 프레임 활성도 |
| onset evidence | Onset Strength | オンセット強度 | 온셋 강도 |
| pitch evidence | Pitch Contour | ピッチ輪郭 | 피치 윤곽 |

“Musical Technique” is used for the game field. “Articulation” remains valid in
MIDI/music-theory explanations where the text is not naming the game control.
AuxSend is not renamed “Reverb Send”: the game control sends an instrument to the
shared Effector, while the individual effect parameters are a separate layer.

Official terminology references:

- [NA/EU Music Album guide](https://www.naeu.playblackdesert.com/en-US/Wiki?wikiNo=147)
- [Japan Music Album guide](https://www.jp.playblackdesert.com/ja-JP/Wiki?wikiNo=272)
- [Korea Music Album guide](https://www.kr.playblackdesert.com/ko-KR/Wiki?wikiNo=173)

## Translation boundary

- Fixed UI copy, official instrument names, Musical Technique labels, validation
  messages, tooltips, accessibility text, actions, menus, and tab labels are
  localized.
- Imported track names, project names, filenames, note names, plugin-provided
  names, game evidence strings, paths, and user text are never translated.
- Unknown instrument IDs use a language-neutral `BDO 0xNN` fallback.
- General MIDI fallback track names, including the Channel 10 drum label, are
  localized when a track is created. They then become project-owned track names
  and are not rewritten by later language switches.
- Third-party plugin output and operating-system error details stay verbatim;
  the surrounding application title and guidance are localized.

`Localizer` stores canonical source text outside Qt dynamic properties so switching
languages repeatedly is deterministic. Widgets containing music- or user-owned
text must opt out of the relevant translated property; fixed combo/list items opt
in explicitly. Use `trv()` for fixed nested enum labels, `trfv()` for nested
templates, and `defer_tr()` for status values that outlive their current widget;
ordinary formatted values remain opaque project or runtime data. Duplicate
rendered labels are reversible only when their English/Japanese/Korean vectors
are equivalent.

## Release checks

Before publishing a build:

1. Verify equal catalog key sets and equal placeholder signatures.
2. Switch a live main window, Settings dialog, note editor, automatic timeline
   validation states, and transcription editor through all five locales.
3. Confirm dynamic names survive every switch byte-for-byte.
4. Check the minimum supported window sizes with the longest English/Japanese/
   Korean labels and confirm tooltips/accessibility names remain available in
   compact toolbar mode.
5. Run `tests.test_i18n_catalog` and the offscreen UI localization smoke tests.
