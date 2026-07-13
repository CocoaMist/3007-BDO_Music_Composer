# Contributing

Thanks for helping improve BDO Music Composer.

## Before opening a change

- Read `AGENTS.md` and `docs/ARCHITECTURE.md`.
- Keep game assets, personal scores, Owner IDs, and extracted audio out of the repository.
- For format or articulation claims, describe the evidence and whether it is verified in-game or inferred.

## Development

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-pyside.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

Add focused regression tests for behavior changes. UI changes should also receive an offscreen smoke test when practical.

## Pull requests

Include:

- the user-visible outcome;
- affected invariants or file-format fields;
- tests run and their result;
- screenshots for visual changes;
- game A/B evidence for claims marked verified.

Do not include generated EXEs, ZIP archives, scores, autosaves, crash logs, or game audio.

## Licensing

Original project code is licensed under MIT. Vendored dependency review remains pending; contributions must not introduce code with incompatible or unknown licensing.
