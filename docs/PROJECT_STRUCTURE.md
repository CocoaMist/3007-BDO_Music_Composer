# Project structure

- `main.py` — unified GUI/CLI entry point.
- `pyside_bdo_gui.py` — PySide6 desktop editor and conversion workflow.
- `i18n.py` — Chinese, English, Japanese, and Korean UI catalogs.
- `optimization/` — extensible optimizer package with built-in pipeline and registry.
- `bdo_midi_optimizer.py` — compatibility facade for the historical optimizer import path.
- Other `bdo_*.py` files — analysis, articulation, lyrics, preview, and rendering modules.
- `assets/` — application-owned UI resources and Windows icon sources.
- `data/mappings/` — runtime BDO/Wwise mappings; manifests are research inputs and are not packaged.
- `tools/midi-to-bdo/` — vendored BDO v9 serializer and ICE implementation.
- `scripts/` — command-line conversion and research utilities.
- `tests/` — automated regression tests.
- `docs/` — architecture, format knowledge, algorithms, validation notes, and UI references.
- `packaging/windows/` — reproducible PyInstaller configuration.
- `build/`, `dist/`, `out/`, `auto_save/` — generated artifacts; not source-controlled.

The Windows one-file build embeds only required runtime resources. External game audio remains user-configured and is never copied into the executable.
