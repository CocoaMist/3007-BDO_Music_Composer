# Developer SDK：只承诺这几个入口

SDK 给扩展作者和嵌入式调用者使用。只有列在这里的接口算稳定 API；能 import 到的
内部模块不等于公开承诺。

## API layers

`bdo_music_composer.sdk.core_api` is the stable Qt-free entry point. It exposes:

- BDO v9 document types, lossless/canonical codec operations, validation, and
  document comparison;
- immutable MIDI notes, parsing, instrument mapping, and pure note transforms;
- editor `TrackState`, track/master effect values, volume preview mapping, and
  editor-to-document export helpers;
- read-only BDO authoring diagnostics, readiness scoring, and semantic note
  diffs that never apply changes to `TrackState`;
- `APP_VERSION`, `SDK_API_VERSION`, `SDK_CAPABILITIES`, and
  `negotiate_sdk_extension()` for fail-closed compatibility gates.

Importing this module must never initialize PySide6, the audio engine, user
configuration, or the desktop application.

`bdo_music_composer.sdk.ui_api` is optional. Its module import remains Qt-free;
PySide6 loads only when a helper is called. It provides:

- `create_application()` for the shared palette, theme, metadata, and runtime
  localization setup;
- `create_timeline_canvas()` for a standalone multitrack overview widget;
- `load_ui_components()` for advanced classes that retain their original
  constructor contracts;
- `run_desktop_app()` for launching the complete application.

Install the UI layer with `pip install -e ".[ui]"` from the extracted SDK.

## Minimal core use

```python
from bdo_music_composer.sdk.core_api import Note, build_score_document, encode_score

notes = [[Note(60, 100, 0.0, 500.0, 0)]]
document = build_score_document(
    bpm=120,
    time_sig_num=4,
    instrument_groups=[(0, notes)],
    char_name="SDK",
    owner_id=0,
)
wire_bytes = encode_score(document)
```

An Owner ID of zero is useful only for in-memory codec development. Production
game export must use the application export workflow and a valid locally read
Owner ID; never hard-code or publish someone else's identity.

## Stability contract

- SDK API level `1` covers the names listed in `core_api.__all__` and
  `ui_api.__all__`.
- SDK consumers negotiate an explicit version range, capability set, and
  `python-api` transport before enabling optional behavior.
- `Note(pitch, vel, start, dur, ntype)` and `TrackState` preserve the editor
  wire model. Changing either requires migration and regression coverage.
- Advanced classes returned by `load_ui_components()` are reusable but not a
  frozen ABI. Their constructor contracts can evolve with the desktop UI.
- Internal modules remain available as source for extensions, but callers that
  import them directly own the upgrade cost.
- Binary score changes are high risk: delegate writes to `bdo_codec` and keep
  validation plus round-trip tests.

## Extension boundaries

Prefer the pure `optimization.registry` extension boundary for new optimizers.
Trusted optimizer bundles use the explicitly labelled in-process contract;
non-trusted Windows extensions use the bounded NDJSON stdio envelope in
`bdo_common.extension_protocol` and do not enter the GUI process.
Keep new domain logic out of `ui/main_window.py`; add a focused package owner
and let the UI orchestrate it. UI paint paths must remain visible-range indexed,
and package initializers under `bdo_music_composer` remain inert.

## Build and verify

```powershell
.\.venv\Scripts\python.exe packaging\developer_sdk\build_sdk.py
.\.venv\Scripts\python.exe -m unittest tests.test_developer_sdk -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -q
```

The ZIP has deterministic timestamps and a `SDK_MANIFEST.json` SHA-256
inventory. The allowlist excludes scores, MIDI/audio, game banks, autosaves,
local settings, release history, executables, and previously built archives.
See `examples/sdk/` for a privacy-conscious score inspector and a reusable
timeline example.
