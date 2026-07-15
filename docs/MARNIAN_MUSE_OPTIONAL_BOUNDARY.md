# Marnian Muse optimizer-package boundary

Marnian Muse is an independent headless engine distributed to Music Composer
as a standard `.bdoopt` optimizer package. Music Composer owns only optimizer
API v1, bundle discovery, validation, preview application, and BDO constraints.
It does not own the Marnian algorithms, profile development, datasets, reports,
audio references, or future model weights.

The standalone project builds the package with:

```powershell
marnian-build-bdoopt path\to\marnian-muse.bdoopt
```

The generated archive contains the runtime engine, default profile, package
entry adapter, and README. It must not contain corpus MIDI, downloaded audio,
research reports, local paths, or training data.

Copy the archive to the directory opened by the optimizer panel's
`算法包目录` button. Discovery reads only `manifest.json`; engine code is
extracted and imported only after the user selects Marnian Muse and explicitly
starts analysis. Its manifest requests the built-in game-safe prepass and
global scope. All preview changes are validated and applied by the host.

Removing the `.bdoopt` file removes Marnian Muse from the next refreshed
algorithm list without affecting Music Composer's built-in safe optimizer.
