# Basic Pitch 0.4.0 license evidence

Reviewed on 2026-07-27 for the exact Basic Pitch release used by BDO Music
Composer. This is an engineering redistribution record, not legal advice.

## Finding

Basic Pitch 0.4.0 is published by Spotify under **Apache-2.0**. The tagged
official repository contains all of the following in the same release tree:

- [`LICENSE`](https://github.com/spotify/basic-pitch/blob/v0.4.0/LICENSE),
  identifying Spotify AB and Apache License 2.0;
- [`NOTICE`](https://github.com/spotify/basic-pitch/blob/v0.4.0/NOTICE), with
  Spotify and upstream attribution notices; and
- the packaged
  [`basic_pitch/saved_models/icassp_2022/nmp.onnx`](https://github.com/spotify/basic-pitch/blob/v0.4.0/basic_pitch/saved_models/icassp_2022/nmp.onnx)
  model used by this application.

The installed `basic-pitch==0.4.0` wheel has the same layout: its distribution
metadata includes `LICENSE` and `NOTICE`, and the wheel contains `nmp.onnx`.
No separate model-specific license or additional restriction was found in the
tagged model directory or installed wheel.

On that evidence, BDO Music Composer treats the unmodified `nmp.onnx` as part
of the Apache-2.0 Basic Pitch distribution. Apache-2.0 permits redistribution
in source or object form subject to its conditions, including providing the
license and retaining applicable attribution/NOTICE material. The build does
not rename or modify the model.

## How the release preserves the terms

Every Windows build runs `scripts/audit_transcription_licenses.py`. For the
exact build environment it:

1. copies the Basic Pitch `LICENSE` and `NOTICE` from installed wheel metadata;
2. hashes the bundled `nmp.onnx` model;
3. embeds the copied notices and generated inventory under
   `licenses/transcription` in the frozen executable; and
4. fails a `-PublicRelease` build when the checked-in policy does not approve
   the exact inventory digest.

Basic Pitch model evidence is therefore available and consistent with
Apache-2.0 redistribution. This finding did **not** by itself clear the whole
Windows executable. The separate v1.0.0 review of ONNX Runtime, Qt/PySide6,
libsndfile, libsoxr, LLVM-derived components, and other native/transitive
artifacts is recorded in `packaging/transcription_release_policy.json`; any
changed inventory requires a new review.

## Academic citation

Spotify asks research users to cite both the paper and the code version used:

> Bittner, Rachel M.; Bosch, Juan José; Rubinstein, David;
> Meseguer-Brocal, Gabriel; Ewert, Sebastian. “A Lightweight
> Instrument-Agnostic Model for Polyphonic Note Transcription and Multipitch
> Estimation.” ICASSP 2022.

- [Basic Pitch GitHub repository](https://github.com/spotify/basic-pitch)
- [Paper record](https://arxiv.org/abs/2203.09893)
