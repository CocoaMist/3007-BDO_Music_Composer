# Fragment-cleanup benchmark protocol

This protocol evaluates transcription fragment cleanup independently from the
Basic Pitch evidence cache and the mixed-audio fusion search. The existing
`babyslakh_transcription_v2.json` report predates cleanup and must not be cited
as evidence that a cleanup profile passed.

The benchmark consumes the same frame-index raw events, `frame` evidence, and
`onset` evidence used by the application. It never reconstructs frame time from
a nominal frame rate. Production conversion still uses the persisted
`times_ms.npy` axis after cleanup.

The current application postprocessor is
`fragment-cleanup-v3-explicit-opt-in`. `preserve` is the safe default. An
explicit `balanced` or `clean` profile selection directly executes that
profile's deterministic actions; there is no independent runtime enable flag
that can disagree with the selected profile. Both action profiles are labelled
experimental and remain unverified until a new holdout passes every applicable
gate below. `preview_frame_event_cleanup()` is the separate API for inspecting
potential actions without applying them.

## Metrics

Exact MIDI pitch is required for all note matches. Onsets use a four-frame
tolerance. Offset-aware matches additionally use the larger of four frames or
20% of the reference-note duration.

Short-note strata are reported as:

- `short_le_6`: severe fragments and true notes spanning at most six frames;
- `short_le_8`: the cumulative review population spanning at most eight
  frames;
- `short_9_11`: the disjoint density-only population spanning nine through
  eleven frames.

Each stratum reports reference, estimate, and matched counts plus precision and
recall. Duration is a measurement feature only; it is never sufficient grounds
for automatic deletion.

The fragment metrics have these fixed meanings:

- `fragment_count`: extra same-pitch estimates assigned by overlap to one
  reference note;
- `split_rate`: reference notes with two or more assigned estimates divided by
  the reference-note count;
- `unsupported_fragment_boundary_count`: extra fragment onsets with no
  same-pitch reference onset within four frames;
- `false_merge_count`: additional true onsets collapsed into a processed event
  whose lineage contains multiple raw events;
- `pitch_flicker_count`: notes of at most eight frames within one frame of a
  note at least two frames longer and one or two semitones away;
- `candidate_inflation_ratio`: candidate count divided by reference-note
  count;
- `candidate_count_change_rate`: processed candidate-count growth relative to
  the raw decoder output (negative values mean cleanup reduced candidates).

Per-song note precision, note recall, onset F1, and onset-plus-offset F1 are
macro-averaged across the holdout. Short-note counts and rates are pooled so a
song with no short notes cannot dominate the result. The report also retains
every per-song result and identifies the worst precision, recall, onset-F1,
onset-plus-offset-F1, and short-note-recall deltas.

Postprocessing time is divided by the complete evidence-to-candidate decode
time for the same songs: the one shared raw-event decode plus that
configuration's postprocessing time. Stream decode, HPSS, and ONNX evidence
generation are timed separately and do not dilute the 5% postprocessing gate.

## Closed parameter search

`fragment_cleanup_grid()` enumerates exactly 108 configurations in this fixed
order:

1. merge gap: `0`, `1`, `2` frames;
2. NMS overlap ratio: `0.80`, `0.85`, `0.90`;
3. NMS onset distance: `1`, `2` frames;
4. weak-onset prominence: `0.05`, `0.10`, `0.15`;
5. clean-profile confidence ceiling: `0.25`, `0.30`.

`evaluate_fragment_cleanup_grid()` applies both `balanced` and `clean` to every
requested grid member using the same raw events and evidence. Thus the
clean-confidence ceiling is measured rather than treated as a duplicate
tie-break value. `select_fragment_cleanup_config()` first requires the
balanced release gate and the separate clean safety gate. It ranks survivors
by balanced fragment reduction, balanced precision, balanced
onset-plus-offset F1, clean precision, clean onset-plus-offset F1, and finally
the enumeration order above. An off-grid configuration is rejected.

The benchmark uses `preserve` as the baseline, then calls the same production
postprocessor with `balanced` and `clean`; selecting either profile is itself
the action request. It must not pass a second automatic-action boolean. A
non-applying inspection uses `preview_frame_event_cleanup()` and is not valid
quality evidence because it leaves the candidate stream unchanged.

The checked-in report-schema-v3 historical report records
`production_release_mode` as
`annotation_only` and `automatic_actions_evaluated` as `true`, reflecting the
older `fragment-cleanup-v2-annotation-only` release policy. Those fields do not
describe or validate the current explicit-opt-in runtime contract.

## Balanced-profile release gates

All checks are mandatory:

| Check | Threshold |
|---|---:|
| Fragment-count reduction | at least 20% |
| Note-precision gain | at least 0.005 |
| Onset-F1 degradation | no more than 0.003 |
| Onset-plus-offset-F1 degradation | no more than 0.002 |
| Note-recall degradation | no more than 0.005 |
| True-note recall for notes at most eight frames | no more than 0.01 |
| False merges / reference notes | no more than 0.5% |
| Worst per-song onset-F1 degradation | no more than 0.02 |
| Postprocessing share of full decode | below 5% |

## Clean-profile safety gates

Clean output never contributes to the balanced release measurements. It is
evaluated separately, relative to the same preserve baseline, and must satisfy:

| Check | Threshold |
|---|---:|
| Onset-F1 degradation | no more than 0.003 |
| Onset-plus-offset-F1 degradation | no more than 0.002 |
| Note-recall degradation | no more than 0.005 |
| True-note recall for notes at most eight frames | no more than 0.01 |
| False merges / reference notes | no more than 0.5% |
| Worst per-song onset-F1 degradation | no more than 0.02 |
| Candidate count | no greater than balanced |
| Clean postprocessing share of full decode | below 5% |

These recall, short-note, false-merge, and per-song limits are not weaker than
the balanced profile. A configuration is selectable only when both profiles
pass their respective gates.

If no configuration passes, the benchmark selector returns no configuration.
That profile must remain non-default, explicitly labelled experimental, and
must not be described as verified or recommended. The application may expose
its reversible actions only through deliberate profile selection while keeping
`preserve` as the default; benchmark failure must not be implemented as a
second hidden switch that contradicts the selected profile. No cleanup result
is checked into this repository unless it was produced from the fixed
tuning/holdout split without exposing dataset paths or audio.

## Completed report-schema-v3 holdout (historical algorithm)

The formal Track00013–Track00020 run evaluated all 108 closed-grid
configurations under `fragment-cleanup-v2-annotation-only`. Balanced passed
0/108 release gates, clean passed 104/108 safety gates, and 0/108 passed joint
selection. The selected configuration is
therefore `null` and `annotation_only` is `true`. Clean safety alone did not
authorize a default/verified automatic suppression mode.

For the frozen fixed parameters, balanced produced zero fragmentation
reduction and zero precision gain. Its total decode time was
`20.657526400056668` seconds, postprocessing took
`0.39931660002912395` seconds, and the resulting share was
`0.01933032020852354`. Clean suppressed 18 of 28,215 candidates, changed
precision by `+0.00010135017009060832` and onset F1 by
`+0.00011290366145133568`, left note recall and ≤8-frame recall unchanged, and
used `0.4125146000296809` of `20.670724400057225` seconds for a
`0.01995646558127101` share. Clean passed its safety gate, but the balanced
gate and joint selection failed.

This report predates `fragment-cleanup-v3-explicit-opt-in`. It is evidence that
balanced/clean must remain experimental and non-default, not evidence that the
current v3 implementation passed a new grid. Its compact JSON remains checked
in as historical evidence.

The repository stores a path-free, 6 KiB
[compact v3 result](babyslakh_transcription_v3_cleanup.json) with the dataset
MD5, public holdout IDs, closed grid, fixed thresholds, decisive metrics, and
gate outcomes. The 929 KiB full grid report remains a local benchmark artifact
and is intentionally not copied into the repository.

## Completed report-schema-v4 holdout (current algorithm)

The current Track00013–Track00020 run evaluated all 108 configurations using
the real `fragment-cleanup-v3-explicit-opt-in` actions. Balanced passed 0/108
release gates, clean passed 91/108 safety gates, and joint selection passed
0/108. `annotation_only` is `false`: deliberate balanced/clean selections do
execute, independently of the failed recommendation gate.

With the fixed V1 parameters, balanced reduced the candidate count from 28,215
to 28,083, the fragment count from 8,105 to 8,024, and split references from
3,540 to 3,508. Fragmentation fell by `0.00999383096853794`, precision changed
by `+0.0006365278082392234`, recall by `+0.00006268647414309214`, onset F1 by
`-0.0002454484666918888`, and onset-plus-offset F1 by
`+0.0003237214719195858`. False merges were 48/30,289 references
(`0.0015847337317177854`). Postprocessing used
`0.574420499993721` of `17.01416049999534` seconds, a
`0.03376131899037148` share.

Clean reduced the count to 28,065 by suppressing another 18 candidates. It
changed precision by `+0.0007390327710278533`, onset F1 by
`-0.00013227775854035562`, retained the balanced recall result, and used a
`0.035894649699020724` timing share. Its safety gate passed. Balanced passed
every recall, onset, false-merge, per-song, and timing check, but missed both
release-effectiveness requirements: 20% fragment reduction and 0.005 precision
gain. The selector therefore returned `null`; this keeps both action profiles
experimental and leaves `preserve` as the safe default without disabling a
profile that the user explicitly selected.

The repository stores the path-free
[compact v4 result](babyslakh_transcription_v4_cleanup.json). The full grid
report remains a local benchmark artifact because it contains redundant
per-configuration and per-track detail.

## Cleanup-only holdout command

After the default BabySlakh download has completed, run only the frozen v2
mixed-enhanced evidence path and the cleanup grid with:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_babyslakh_transcription.py `
  --cleanup-holdout `
  --cleanup-output "$env:LOCALAPPDATA\BDO Music Composer\benchmarks\BabySlakh\babyslakh_transcription_v4_cleanup.json"
```

This mode does not execute the older 243-member fusion search. It loads and
prewarms ONNX at most once, generates evidence once for each fixed holdout
track, and evaluates all cleanup configurations before releasing that track's
memory maps. `--cleanup-output` has no default and is required, so an ordinary
benchmark invocation cannot accidentally publish a v3 cleanup report.

Each successfully generated `frame`, `onset`, and exact frame-time array is
published under the cleanup benchmark's Local AppData work directory with a
manifest written last. The manifest is bound to the public track ID, audio
fingerprint, backend/fusion cache key, frozen v2 parameters, shapes, dtypes,
sizes, and SHA-256 hashes. A restarted run validates that checkpoint and skips
the completed track's ONNX inference; if every track is valid, model creation
and prewarming are also skipped. Truncated, modified, symlinked, or incompatible
checkpoints fail closed and only the affected track is regenerated.

Grid configurations that produce the same
reference/raw/balanced/clean-note signature share the expensive matching and
fragment-metric calculation.
Configuration-specific postprocessing timings remain separate, so this reuse
cannot hide a timing-gate failure. The final report records only reuse and
checkpoint counts plus `checkpoint`/`onnx` source labels, never checkpoint
directories.

The JSON contains only the dataset identity, public track IDs, frozen
parameters, aggregate/per-song metrics, and timings. It never contains the
dataset directory, audio/MIDI paths, cache path, or output path. When every
configuration fails at least one release gate, `selected_config` is `null`.
That outcome keeps the profile experimental and non-default; it does not create
a runtime flag that silently converts a user's explicit `balanced` or `clean`
selection into `preserve`.
