# 参考音频音色分组：只帮你看，不替你编曲

状态：已实现、实验性、只影响显示。

## Product boundary

参考音频可以按匿名音色组给识别候选着色。Analyzed Notes 用来审阅和采纳草稿，
Pitch Line 用来看滑音、颤音和音准；两者互不冒充。它们不会分离音轨、增加 Track、
选择 BDO 乐器或修改 `TranscriptionCandidate` / `Note`。

Two layers are available:

1. Built-in anonymous grouping is enabled by default. It extracts bounded
   MFCC, spectral, and attack/decay summaries only from low-overlap candidate
   passages that also have usable Basic Pitch frame evidence. Initial
   monophonic voices are refined for stable timbre changes, then reliable
   voice prototypes are selected before weak single-segment evidence.
   Short or low-sample groups first try to inherit the nearest unambiguous
   prototype; only a bounded number of sufficiently distinct provisional
   timbres may create new colours. Prototypes are merged with deterministic
   complete-link clustering.
   Complete-link is deliberately conservative: every cross-pair must agree,
   so one ambiguous phrase cannot chain unrelated colours together. One
   quality-acceptable low-overlap segment can establish a low-confidence
   provisional colour rather than being discarded solely for having one
   sample. Moderately similar groups in the same musical role may merge across
   a nearby temporal boundary, but the complete-link floor still prevents a
   weak similarity chain. A short voice with one usable candidate profile may
   also inherit an existing prototype only when its best similarity is strong
   and clearly separated from the runner-up.
   The compact detail panel leads with group count, coverage, and candidate-
   weighted average confidence. It shows at most six highest-value group rows
   plus an overflow count; external-backend diagnostics stay in the tooltip
   instead of crowding the primary result.
2. Generic instrument labels are optional and disabled by default. If a
   separately installed `muscriptor` command is available, the small model can
   produce standard-MIDI program labels. The adapter matches those events back
   to the existing candidates by pitch, onset, and duration overlap. A group
   receives a “likely …” label only when at least two notes agree and coverage,
   dominance, and alignment confidence all pass their thresholds.

Hue means anonymous timbre cluster. Saturation means confidence in that group
assignment, and local opacity means the amount of audio evidence supporting the
specific candidate or contour span. The user's Pitch Line opacity setting is a
separate master multiplier. Grey means insufficient evidence. A colour or
generic label is never proof of the real recording source.

Before acoustic profiling finishes, the UI may show a bounded structural
prediction derived from the already available time/pitch voice groups. This
provisional result covers candidates immediately, is confidence-capped, and is
labelled as a few-shot prediction while the background worker verifies it from
audio. Adjacent non-overlapping fragments merge only when musical role, time
gap, and pitch proximity all agree. Overlapping voices and role changes remain
separate, reducing colour churn without collapsing simultaneous instruments.
Acoustic results replace the prediction only when they match the active
cache key and candidate set. Acoustic groups remain authoritative, but their
under-evidenced unknown candidates retain provisional structural groups. This
hybrid projection keeps Melody Guidance operable instead of turning its target
back into one undifferentiated unknown group.

## Instrument-aware pitch line

Status: implemented, experimental, display-only.

The raw Pitch Line layer reuses the anonymous timbre colours, but
only where one rendered contour segment has one unambiguous candidate-group
owner. The visual grammar is:

- the contour inside a grouped candidate uses the same stable hue as that
  candidate;
- an unknown or multiply claimed contour stays neutral blue-grey instead of
  guessing an instrument;
- hue encodes group identity, saturation encodes group-classification
  confidence, and local opacity encodes candidate-level acoustic evidence;
- line opacity is controlled independently from Frame/Onset/spectrogram
  evidence. Existing v8 projects migrate their prior effective contour
  strength, while new projects start at 82%;
- adjacent ridge samples use a constrained cubic Bézier path with at most
  0.08 semitone of control-point overshoot, plus a quiet dark halo and a thin
  coloured core. Gaps and colour-owner changes remain separate paths;
- the compact legend names groups as `Timbre A`, `Timbre B`, and so on, with a
  generic family name only when the optional label gate passes;
- semantic Voice Hints keep their existing role colours. Instrument hue and
  musical role are separate meanings and must not compete on one stroke;
- a two-threshold hysteresis rule lets an established ridge survive a short
  posterior dip, but a weak isolated peak cannot start a new line;
- a display-only bridge spans an evidence-backed weak same-pitch split while
  retaining separate onset markers, candidate IDs, selection and draft actions.

This follows three reusable patterns: Melodyne overlays a thin pitch curve on
the corresponding note blob, Sonic Visualiser treats curves, notes, and
spectrograms as independently switchable layers, and accessible chart guidance
requires a legend or another non-colour cue rather than hue alone:

- <https://helpcenter.celemony.com/M5/doc/melodyneStudio5/en/M5tour_ViewOptions-stand-alone?env=standAlone>
- <https://sonicvisualiser.org/doc/reference/1.9/en/index.html>
- <https://www.w3.org/WAI/WCAG22/Understanding/use-of-color>

The implementation extends the evidence-tile worker and never recolours tiles
inside `paintEvent`. A compact immutable sidecar carries visible-range
candidate ownership spans and a colour revision in the contour tile key.
While building ridge paths, the worker resolves each path segment to zero, one,
or multiple groups and writes neutral, group-coloured, or neutral-conflict
pixels respectively. This keeps disk access, matrix scans, QImage allocation,
and colour arbitration outside the GUI paint path. The existing byte-bounded
tile cache remains the memory owner and a timbre-result revision invalidates
only contour tiles.

## Melody guidance

Status: implemented, opt-in, weak evidence, display-only.

When Melody Guidance is enabled, editable notes on the current track can
gradually emphasize the anonymous timbre group whose pitch and timing they
match. Notes already materialized from transcription routes are excluded so a
candidate cannot validate itself. The evidence unit is one
`(group, time window, pitch)` tuple: recognition fragments with the same pitch
inside one window count once. A window is two bars at the project tempo,
clamped to 2–6 seconds; at most three pitches contribute per window, one
window contributes at most 4%, and the total guidance influence is capped at
15%. Ambiguous top-two matches cast no vote. One unambiguous window may expose
a deliberately weak, confidence-capped prediction. Strong focus requires at
least two distinct windows and a clear margin over the runner-up.

Guidance propagates one unified display assignment to every analyzed note and
pitch-line span owned by the same anonymous group. Once the two-window focus
gate passes, the current track's instrument is the highest-priority display label;
optional external labels and acoustic confidence remain lower-priority
evidence and cannot overwrite it. Other groups retain their independent
colours and a visible floor (42% after stable focus, 72% while evidence is
accumulating), so guidance does not collapse every source into the current
instrument. A gold top rail gives guided analyzed notes a non-colour cue. The
UI reports windows and deduplicated hits separately from acoustic
classification and optional generic-label confidence. This display override
never mutates candidates/notes, routes a track, rewrites the underlying
acoustic label, or affects export.

Regression gates:

- deterministic colours and neutral conflict handling for overlapping notes;
- no colour when grouping is disabled, unavailable, stale, or below its
  evidence threshold;
- visible-range tile generation and unchanged paint-query bounds;
- keyboard-accessible legend text and explicit confidence text;
- offscreen dark-theme layout checks;
- no changes to candidates, formal notes, routing, export, or project data.

## Accuracy and failure behaviour

- Reference audio is decoded once per grouping worker. At most eight clean
  segments are selected for one initial voice. At most twelve reliable colour
  groups are exposed; weaker prototypes remain neutral instead of expanding
  the UI or reusing an unrelated colour.
- One clean segment above the reliability floor may establish a provisional
  low-confidence colour, and a short voice may inherit a strong, unambiguous
  prototype. Dense overlaps, missing or below-floor profiles, and close
  first/second matches still fail into the neutral group instead of receiving
  a confident colour.
- Cluster and colour assignment are deterministic for the same candidates and
  features. Results are accepted only if the cache key and complete candidate
  ID set still match the active transcription session.
- Reanalysis, reference-audio replacement, project replacement, and relevant
  BPM changes cancel or invalidate stale work.
- Optional-backend failure does not discard built-in colours. It changes only
  the label status, and command output/local paths are not stored in project
  data or shown as diagnostics.

## Optional MuScriptor backend

The application does not bundle MuScriptor, its Python dependencies, or model
weights. Discovery checks an explicit
`config["transcription_ui"]["muscriptor_executable"]` first and otherwise the
`muscriptor` command on `PATH`. Enabling labels invokes:

```text
muscriptor transcribe --model small <audio> -o <temporary-midi>
```

The temporary MIDI is deleted after parsing. MuScriptor may fetch its gated
model on first use according to its own configuration. Users must separately
accept the model terms and have the necessary rights to transcribe the input.
The upstream code is MIT; the published model weights are CC BY-NC 4.0 and are
not part of this repository or release package. See the
[official model card](https://huggingface.co/MuScriptor/muscriptor-small) and
[upstream repository](https://github.com/muscriptor/muscriptor).

The small model uses about 100M parameters, five-second chunks, and a bounded
36-group instrument taxonomy. It does not output velocity and is less reliable
on dense mixtures, unusual timbres, rare instruments, and underrepresented
genres. Those constraints are why the feature labels families, never routes
notes automatically, and retains an unknown state.

## Out of scope

There is no third-stage BDO-instrument matching, source separation, stem
export, automatic track creation, or automatic candidate acceptance in this
feature.
