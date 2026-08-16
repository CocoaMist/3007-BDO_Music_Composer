# Packaging: build it, then prove it

This directory owns the release and SDK build entry points. Build outputs stay
local and never belong in Git.

## Windows application

Use `windows/build.ps1` for the single-file Windows application. Signing,
update publication, and release evidence remain explicit operator actions.

## Developer SDK

Run the deterministic, privacy-filtered SDK builder from the repository root:

```powershell
.\.venv\Scripts\python.exe packaging\developer_sdk\build_sdk.py
```

Use `--output <path>` to choose the destination. The builder uses an explicit
source allow-list, rejects private and generated inputs, writes a SHA-256
inventory, and fixes archive timestamps.

## Optional native audio qualification

The original-project native audio experiment is built with:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\native_audio\build.ps1
```

Generated binaries remain ignored. They enter a public application only after
parity, device, memory-safety, inventory, and maintainer release gates pass.
