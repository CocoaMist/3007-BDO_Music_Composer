# BDO v9 lossless codec

`bdo_codec` is the project's independent reader/writer for Black Desert music
score version 9. It owns the binary layout and ICE block transform. The
independent `bdo_midi` package owns MIDI parsing and mappings, while
`bdo_export` adapts editor tracks into codec documents. Binary-format logic
belongs only in `bdo_codec`.

## Public API

```python
from bdo_codec import decode_score, encode_score, read_score, write_score

document = decode_score(score_bytes)
same_bytes = encode_score(document, mode="lossless")
canonical_bytes = encode_score(document, mode="canonical")
```

The document tree contains `BdoHeader`, `BdoInstrumentGroup`, `BdoTrack`,
`BdoNote`, and `BdoTrackSettings`. It retains both velocity bytes, physical
track order, raw track volume, all eight settings bytes, declared lengths,
opaque track extensions, header padding, and trailing aligned data.

`lossless` returns the original encrypted bytes when the decoded document is
unchanged. After an edit it reuses unchanged raw records and rebuilds dirty
records. A non-zero opaque region is retained only while its association is
stable; an edit that could change that association raises
`UnsafeOpaqueDataError` with a field path and byte offset.

`canonical` validates values, recalculates sizes/counts/alignment, splits tracks
at 730 notes, and ensures the required empty final physical track exists for
each instrument group. It intentionally does not promise byte identity.

The editor-facing five-field `Note(pitch, vel, start, dur, ntype)` shape is not
changed. Project schema v3 stores the source note binding separately so an
unchanged imported note keeps `velocity_b`; a new note, or one whose velocity
was edited, writes `velocity_b == velocity_a`. Game track volume and the
editor's note-velocity `volume_scale` are separate fields.

## Binary structure enforced by the codec

- four-byte little-endian version `9`, followed by ICE-encrypted data;
- encrypted/plain payload length divisible by eight;
- fixed `0x150`-byte plaintext header, including Owner ID and two UTF-16LE names;
- instrument groups and physical tracks in source order;
- track prefix `<HH8sH>` and 20-byte note records `<BBBBdd>`;
- explicit bounds for every count, declared length, offset, and note value;
- no guessing: a version other than 9 is rejected.

## CLI

```powershell
python -m bdo_codec inspect <score>
python -m bdo_codec inspect <score> --include-private
python -m bdo_codec decode <score> <document.json>
python -m bdo_codec encode <document.json> <score>
python -m bdo_codec validate <score>
python -m bdo_codec roundtrip <score> --verify-bytes
```

`inspect` redacts the Owner ID and character names by default. Reversible JSON
uses schema `bdo-score-document/v1` and contains those private fields; keep it
outside Git just like a real score.

## Evidence and private validation

The repository contains only the status registry
`data/codec/bdo_v9_evidence.json`, artificial fixtures, and validation tools.
It contains no real score, Owner ID, local game path, PAZ, BNK, WEM, WAV, or
other game asset.

Run byte-level validation against a private local corpus:

```powershell
python scripts/verify_private_bdo_corpus.py "F:\private\Music"
```

Generate controlled one-variable probes using a score saved by the tester's
own account:

```powershell
python scripts/generate_bdo_codec_probes.py <owner-score> <private-output-dir>
```

The output embeds private identity and must not be committed. A semantic
mapping is marked verified only after all three checks succeed: an in-game save
difference isolates the field, the generated score imports successfully, and
the game re-save preserves the intended meaning. Therefore arbitrary `ntype`
bytes and settings already round-trip losslessly, but untested audible meanings
remain explicitly pending in the evidence registry.
