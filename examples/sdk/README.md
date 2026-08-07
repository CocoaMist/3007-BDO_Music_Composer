# SDK examples

Run these commands from an editable SDK checkout:

```powershell
python examples/sdk/inspect_score.py path/to/score.bdo
python examples/sdk/timeline_widget.py
```

`inspect_score.py` intentionally omits Owner ID and character names from its
output. `timeline_widget.py` demonstrates the optional `ui` dependency group.
The complete application and advanced widgets keep their original constructor
contracts; use `bdo_music_composer.sdk.ui_api.load_ui_components()` when you
need them.
