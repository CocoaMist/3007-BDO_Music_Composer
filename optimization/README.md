# Optimization subsystem

This package owns MIDI optimization independently of the UI and export layers.

## Layout

- `builtin.py` — the production BDO-aware optimization pipeline.
- `registry.py` — the small extension API and algorithm discovery metadata.
- `__init__.py` — the stable public API and default algorithm registration.

`bdo_midi_optimizer.py` remains as a compatibility facade for existing imports.

## Adding an algorithm

An algorithm is a callable with this contract:

```python
def optimize(tracks, bpm, supported_articulations, config=None, time_sig=4):
    ...
    return OptimizationResult(...)
```

Register it during application startup:

```python
from optimization import register_algorithm

register_algorithm(
    "my-optimizer",
    optimize,
    title="My Optimizer",
    description="A concise explanation of its guarantees.",
)
```

Then call the stable dispatcher:

```python
from optimization import optimize_tracks

result = optimize_tracks(
    tracks,
    bpm,
    supported_articulations,
    config,
    algorithm="my-optimizer",
)
```

Extensions must return `OptimizationResult`, remain deterministic for identical inputs, and document whether they preserve the game-safe invariants in `AGENTS.md`. New algorithms need scope, idempotence, note-count/pitch, and manual-articulation tests before they are exposed in the UI.
