# To AI agents

Read [`AGENTS.md`](AGENTS.md) first, then [`docs/AI_CONTEXT.md`](docs/AI_CONTEXT.md).

Fast facts:

- Entry point: `main.py`; desktop implementation: `pyside_bdo_gui.py`.
- Core model: `TrackState` plus `midi2bdo.Note(pitch, vel, start, dur, ntype)`.
- Export must use the current editor model, never silently re-read the original MIDI.
- High-risk areas: BDO v9 binary layout, Owner ID privacy, audio-thread I/O, drum `ntype=99`, and Marnian mode IDs.
- Run `.\.venv\Scripts\python.exe -m unittest discover -s tests -q` before handoff.
- Do not publish generated scores, game assets, local paths, autosaves, or build artifacts.
