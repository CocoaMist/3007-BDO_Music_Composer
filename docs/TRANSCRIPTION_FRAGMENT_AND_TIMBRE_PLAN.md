# Transcription fragment and timbre continuity plan

Status: implemented for display continuity and anonymous timbre grouping;
candidate mutation remains evidence-gated and opt-in.

## Problem

Frame-wise polyphonic transcription can briefly drop below its posterior
threshold inside one sustained note. Treating every dip as a new visual object
makes both analyzed notes and pitch lines look fragmented. Independently,
creating an anonymous colour from every usable short timbre sample produces
too many colours for one instrument.

## Product decision

The small-tool workflow does not add a second heavyweight model or source
separation runtime. It keeps Basic Pitch evidence and the existing bounded
MFCC/spectral/attack profiles, then adds three conservative continuity stages:

1. `preserve` remains the candidate default and never performs balanced NMS or
   false-split mutation. It dry-runs the same evidence gate and marks only the
   lineage that would be affected. The piano roll connects consecutive,
   same-pitch marked candidates with a low-alpha bridge. Separate blocks,
   onset caps, IDs, hit targets, selection, rejection, and draft adoption stay
   intact.
2. Pitch-line rendering uses hysteresis. A ridge starts only above the normal
   denoise threshold; after it starts, a 72%-of-threshold local maximum may
   continue it through a brief dip. Profile-specific bridge windows remain
   bounded, and isolated weak peaks stay hidden.
3. Anonymous instrument grouping selects reliable multi-sample prototypes
   first. Weak groups try an unambiguous prototype assignment using their
   robust group profile plus any candidate profiles. A bounded distinctness
   gate creates at most four weak provisional seeds. Nearby same-role clusters
   may use a lower complete-link floor, but every cross-profile pair must still
   agree, preventing unrestricted chaining.
4. Optional melody guidance treats current-track manual notes as weak,
   display-only supervision. Hits are deduplicated by anonymous group, bounded
   time window, and pitch; ambiguous hits abstain, per-window/total influence
   is capped, and stable emphasis requires three distinct windows. The signal
   propagates across the chosen anonymous group. After the stability gate, the
   current track instrument becomes the highest-priority display assignment
   for both analyzed notes and pitch lines; acoustic confidence and optional
   instrument-family labels remain intact as lower-priority evidence.

## Why candidate auto-merge is not the default

The repository's frozen BabySlakh holdout shows the current balanced profile
inside safety and performance limits, but below the required fragment-reduction
and precision-gain gates. Visual continuity therefore ships without changing
candidate identity. A future automatic merge default still requires a new
untouched holdout pass under the existing benchmark protocol.

The v4 postprocess identity invalidates older decoded annotation reports, but
does not change the v3 balanced/clean automatic-action thresholds evaluated by
that holdout. Its behavioral change is the preserve-mode dry-run sidecar and
display projection only.

## Research basis and scale decision

- Basic Pitch exposes separate onset, frame, and contour posteriors; continuity
  can therefore be judged without rerunning the model:
  <https://github.com/spotify/basic-pitch/blob/main/basic_pitch/note_creation.py>
- pYIN demonstrates the general value of separating frame-wise pitch
  observations from temporal tracking. This implementation uses bounded
  display hysteresis rather than introducing a new HMM decoder:
  <https://www.eecs.qmul.ac.uk/~simond/pub/2014/MauchDixon-PYIN-ICASSP2014.pdf>
- OpenMIC-2018 frames polyphonic instrument recognition as a multi-label
  problem and illustrates why a colour is not proof of a separated source:
  <https://zenodo.org/records/1492445>
- Learned audio embeddings can improve instrument tagging, but Essentia's
  MusicCNN/VGGish route adds TensorFlow graphs and model-distribution review.
  That is disproportionate for this local utility and is not added here:
  <https://essentia.upf.edu/tutorial_tensorflow_auto-tagging_classification_embeddings.html>

## Acceptance gates

- Preserve mode changes no candidate count, timing, pitch, confidence, ID, or
  lineage and performs no formal-note mutation.
- Strong reattacks, regular repeats, chord-supported onsets, pitch flicker, and
  conflicting timbre ownership do not receive a continuity bridge.
- Contour hysteresis connects a weak dip but never starts from weak evidence.
- Continuity and colour projections are built outside `paintEvent`; paint
  queries remain visible-range indexed and evidence images remain worker-owned.
- Timbre output is deterministic, bounded, confidence-labelled, and neutral
  when evidence is missing or ambiguous.
- Guidance excludes notes created from candidate routes, cannot self-confirm a
  candidate, and returns to the identity display when disabled.
