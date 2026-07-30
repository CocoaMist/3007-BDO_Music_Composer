# Conversion settings boundary

## Purpose

Conversion settings used to be seven parallel mutable attributes owned by
`MidiToBdoWindow`. Startup, blank-project creation, raw MIDI import, BDO import,
project recovery, application preferences, autosave, and export each rebuilt a
slightly different subset. The result was temporal coupling: a missing field
could inherit the value of the score opened immediately before it.

`conversion_settings.py` is now the Qt-free source of truth. Its immutable
`ConversionSettings` value owns:

- optional BPM override;
- global transpose;
- sustain and tempo-flattening MIDI parse policy;
- velocity mode and its optional range/floor/step parameters.

Character identity and master effects deliberately remain outside this model.
They have different ownership and compatibility rules: identity is a local
export preference, while master effects belong to the open score.

## Source policies

| Entry path | BPM | Transpose | Velocity | Reason |
|---|---:|---:|---|---|
| New installation / new authored score | MIDI | `-8` | layered | Current product default |
| Saved application preference | saved value | saved value | saved value | Explicit user choice wins |
| Legacy MIDI/blank project missing fields | MIDI | `0` | layered | Preserve historical output |
| Raw or legacy BDO score | score BPM | `0` | off | Preserve score and lossless path |
| Current project with fields | saved value | saved value | saved value | Project is authoritative |

These policies are constructors on the immutable model rather than branches in
widgets. Opening another score cannot change the fallback used by a subsequent
new score or legacy project.

## Data flow

```mermaid
flowchart LR
    Config["Application preferences"] --> Policy["ConversionSettings source policy"]
    Project["Project payload"] --> Policy
    BDO["BDO import"] --> Policy
    Policy --> State["Immutable ConversionSettings"]
    State --> UI["Window compatibility properties"]
    State --> Save["Stable JSON payload"]
    State --> Parse["MIDI parse projection"]
    State --> Pitch["PitchTransformPlan global fallback"]
    Pitch --> Validate["Validation"]
    Pitch --> Preview["Preview"]
    Pitch --> Export["Typed ExportRequest"]
    Export --> Prepare["Pure prepare_export"]
    Prepare --> Publish["Atomic publish_export"]
    Legacy["Legacy flat-parameter adapter"] --> Export
```

`to_payload()` is the single JSON projection.
`midi_parse_parameters()` and `export_transform_parameters()` expose only the
fields each consumer owns. `export_workflow` accepts the immutable value first
and retains a legacy flat-dictionary adapter for older callers.

## Compatibility rules

- A project missing `transpose` means historical neutral transpose, not the
  current `-8` new-score default.
- BDO import always starts with a neutral transform so unchanged documents can
  remain byte-for-byte lossless.
- Inactive velocity parameters may be retained in memory/payload, but only the
  selected velocity mode is projected into export arguments.
- The PySide window exposes compatibility properties such as `transpose` and
  `velocity_mode`; lifecycle transitions replace the complete immutable state
  rather than assigning those properties one by one.
- Project command snapshots include the immutable conversion state, so an
  automatic conversion-check transpose fix is fully undoable together with
  any track repairs from the same action.
- Master-effect compatibility fields remain in the project conversion payload
  for old projects, but are parsed and authored by `MasterEffects`, not by
  `ConversionSettings`.

## Per-track octave adaptation

`pitch_transform.py` implements the immutable extension seam. A
`PitchTransformPlan` combines the global transpose with optional overrides
keyed by stable editor `track_id`:

```text
effective semitones = global semitones + track octave override
```

- Track overrides authored by the current UI are octave-only (`12k`). An
  arbitrary semitone override has a separate explicit mode so it cannot be
  confused with automatic voice-range adaptation.
- Percussion is always resolved to zero. The shared
  `track_uses_percussion_pitch_semantics()` boundary classifies both a
  percussion MIDI source and any track currently assigned to the BDO drum-set
  target (`0x0D`) as percussion. Consumers must use
  `PitchTransformPlan.effective_track_semitones()` and the same classification
  for serialization so preview, validation, PySide export, and WPF export
  cannot disagree after an instrument remap. Source `Note.pitch` values and
  the source-facing `is_percussion` flag remain unchanged; preview and export
  receive detached projected notes.
- Timeline range hints, structured validation, the piano-roll preview, the
  main preview, PySide export, and the WPF sidecar all use the same plan.
- Right-clicking a melodic track opens **Track Octave**. The operation is
  project-undoable and does not write track state into application preferences.
- Schema v10 persists the plan and migrates v9 projects to an empty override
  list with `ConversionSettings.transpose` as the global fallback. Stale
  overrides are pruned by stable track identity on load/save/delete.
- `bdo_codec` remains policy-free. `prepare_export()` resolves note pitches
  before delegating to `bdo_export`, and passes zero to the legacy scalar
  transpose argument so a transform can never be applied twice.

`ExportRequest` is the typed immutable worker boundary. `prepare_export()` is
filesystem-free, while `publish_export()` owns atomic output and the
best-effort game-directory copy. `execute_export()` retains a mapping adapter
for existing integrations.

## Validation

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_conversion_settings -v
.\.venv\Scripts\python.exe -m unittest tests.test_pitch_transform tests.test_export_workflow -v
.\.venv\Scripts\python.exe -m unittest tests.test_conversion_defaults_ui tests.test_pitch_transform_ui tests.test_wpf_sidecar -v
```

The full repository suite remains required because settings affect MIDI parse,
preview validation, autosave recovery, and BDO lossless-export eligibility.
