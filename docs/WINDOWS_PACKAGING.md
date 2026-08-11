# Windows packaging

BDO Music Composer has one Windows one-file package:
`dist\BDO-Music-Composer.exe`. The package uses
`packaging/windows/BDOMusicComposer.spec` and includes Basic Pitch `nmp.onnx`,
ONNX Runtime CPU, SoundFile/libsndfile, soxr/libsoxr, and the scientific
dependencies required by the embedded transcription mode. There is no
dependency-light edition, separately named transcription executable, or
alternate build spec.

The executable uses the same UI, project schema, editor model, export path, and
user cache location as a source checkout. It never contains reference audio,
extracted game audio, Owner IDs, autosaves, exported scores, or transcription
evidence caches.

A user can explicitly export a bounded, path-redacted local diagnostic bundle
without opening a project:

```powershell
.\BDO-Music-Composer.exe --export-support-bundle <destination.zip>
```

The command performs no upload and never includes projects, scores, Owner IDs,
audio, configuration, or local paths.

## Signed seamless updates

The distributed shape remains one `BDO-Music-Composer.exe`. A frozen Windows
build checks the RSA-signed stable channel after startup, can fetch identical
assets from Gitee or GitHub, and stages a verified new EXE under Local AppData.
It does not interrupt the current session: the next user-initiated launch hands
off to the staged EXE, which replaces the installed copy and retains the old
copy until the real new GUI reports healthy. Source launches and
`--self-test-startup` never start update networking.

After the ordinary public build gates pass and the same EXE has been uploaded
to both mirrors, generate the exact channel document with the private key kept
outside the repository:

```powershell
.\.venv\Scripts\python.exe scripts\generate_update_manifest.py `
  dist\BDO-Music-Composer.exe `
  --version 1.2.0.1 `
  --github-url <exact-github-release-asset-url> `
  --gitee-url <exact-gitee-release-asset-url> `
  --private-key <outside-repository-private-key.pem> `
  --output-dir <release-channel-output>
```

Publish the resulting `update-manifest-v1.json` and
`update-manifest-v1.json.sig` byte-for-byte to both configured stable-channel
paths. Never rebuild separately per mirror and never publish the private key.
Ordinary releases use `major.minor.patch`. A positive fourth component is a
test revision ordered after its three-part base and before the next patch; a
zero or leading-zero fourth component is rejected to avoid version aliases.

## Build

Use CPython 3.12.10 and install the build/runtime dependencies into the
repository virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install --constraint requirements\windows-py312.txt -r requirements\build.txt
powershell -ExecutionPolicy Bypass -File scripts\install_transcription.ps1
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
```

Every build also emits `dist\release-evidence\BDO-Music-Composer.exe.sha256`
and an SPDX 2.3 JSON document. A reviewed public release enables the checked-in
exact-inventory license gate:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1 `
  -PublicRelease
```

Authenticode publisher signing is optional. When a protected certificate-store
identity is available, append
`-SigningCertificateThumbprint <certificate-store-thumbprint>`; signing and
verification then fail closed. The publisher private key must not be passed as
a file, environment variable, or repository secret. Unsigned releases may
trigger a Windows SmartScreen warning.

The output is always `dist\BDO-Music-Composer.exe`. Loading a reference audio
file and entering transcription mode exposes its bundled analysis capability.
Alternate TensorFlow, TFLite, and Core ML backends/models are excluded. ONNX
Runtime's CPU provider is validated before PyInstaller starts.
After packaging, the build runs two frozen-process checks: a synthetic Basic
Pitch ONNX/CPU inference and the real PySide main window offscreen for at least
ten seconds. The GUI check uses a disposable `BDO_USER_DATA_DIR`, so it cannot
read or overwrite the maintainer's projects, autosaves, caches, or settings.
The directory is created before launch, and both GUI-subsystem processes use
explicit wait/exit-code handling; ordinary PowerShell invocation is not
accepted because it can return before a windowed executable exits.

## Reproducible dependency set

`requirements/desktop.txt`, `requirements/transcription.txt`, and
`requirements/build.txt` describe the direct dependency groups.
`requirements/windows-py312.txt` pins their complete Windows/CPython 3.12.10
version closure, including PySide6, the ONNX/scientific stack, and PyInstaller.
The source setup command and `scripts/install_transcription.ps1` both apply the
same constraints. Update the constraint file only as one reviewed dependency
change: run the full suite and frozen self-tests, regenerate the license
inventory, and record its newly approved digest before creating another public
build. Version equality alone is not clearance because the inventory also
hashes notice files, the ONNX model, and native libraries.

## License inventory

Before every build, `scripts/audit_transcription_licenses.py` walks the installed
runtime dependency closure starting from the pinned transcription stack. It:

1. records exact distribution names and versions;
2. records active runtime dependencies while excluding the deliberately unused
   non-ONNX Basic Pitch backends;
3. copies license, copyright, copying, and notice files available in installed
   wheel metadata;
4. hashes the bundled ONNX model and ONNX Runtime native libraries; and
5. produces a canonical inventory digest.

The generated report is temporary build input and is embedded under
`licenses/transcription`; it is not committed as a machine-specific artifact.
Missing metadata stays visible as unresolved instead of being guessed.

Basic Pitch 0.4.0 publishes its Apache-2.0 `LICENSE`, Spotify `NOTICE`, and
packaged `nmp.onnx` in the same tagged GitHub tree, and the installed wheel
contains the same three artifacts. The model-specific finding and academic
citation are recorded in
[Basic Pitch license evidence](BASIC_PITCH_LICENSE_REVIEW.md). This resolves
the Basic Pitch model evidence item; it does not approve the notices for every
native library in the complete executable.

## Public-release gate

The v1.0.0 exact-artifact review is recorded in the checked-in policy. Passing
`-PublicRelease` to the same `build.ps1` requires all of the following:

- `public_release_cleared` is explicitly true in
  `packaging/transcription_release_policy.json`;
- the generated inventory schema matches the schema recorded by that approval;
- the policy contains the digest of the exact dependency inventory being
  built;
- the inventory has no unresolved package license metadata; and
- reviewer identity and UTC review time are recorded.

The policy must only be changed after reviewing the actual model, Python wheels,
native libraries, and all required notice texts. Any dependency change produces
a different digest and blocks a public build until it is reviewed again. A
successful build without `-PublicRelease` is local evaluation only and is not
evidence that redistribution is cleared.

The published v0.3.0 artifact retains its historical schema-1 approval record.
Schema 1 could include `*.py` and environment-generated `*.pyc` files from
importable packages whose directory happened to be named `licenses`, making a
rebuild digest depend on bytecode state. Audit schema 2 excludes those runtime
modules. The v1.0.0 policy approves the resulting deterministic schema-2
inventory only; the old digest remains historical release evidence rather than
being silently rewritten.

After clearance, a public candidate still requires the normal clean-build,
artifact inspection, full test suite, and playback smoke test; the build itself
enforces the frozen ten-second startup check. Generated `build/`, `dist/`, and
audit output must remain outside Git.
The frozen executable writes runtime config, autosaves, logs, and default
exports under `%LOCALAPPDATA%\BDO Music Composer` (or `BDO_USER_DATA_DIR`);
those files must never appear in the inspected `dist` artifact.
