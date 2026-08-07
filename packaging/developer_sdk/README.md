# Developer SDK packaging

Build the source SDK from the repository root:

```powershell
.\.venv\Scripts\python.exe packaging\developer_sdk\build_sdk.py
```

Use `--output <path>` to choose the ZIP destination. The builder uses an
explicit source allowlist, rejects private/binary extensions, excludes local
settings and generated output, writes a SHA-256 inventory, and fixes ZIP entry
timestamps so identical source trees produce identical archives.

The generated archive is a release artifact and must not be committed.
