"""Embed the reusable timeline widget with a small in-memory score."""

from __future__ import annotations

from bdo_music_composer.sdk.core_api import Note, TrackState
from bdo_music_composer.sdk.ui_api import create_application, create_timeline_canvas


def main() -> int:
    app = create_application(language="auto")
    track = TrackState(
        track_id=1,
        notes=[
            Note(60, 80, 0.0, 480.0, 0),
            Note(64, 90, 500.0, 480.0, 0),
            Note(67, 100, 1000.0, 700.0, 0),
        ],
        gm_program=0,
        is_percussion=False,
        display_name="SDK Piano",
        bdo_instrument_id=0,
    )
    timeline = create_timeline_canvas([track])
    timeline.resize(1000, 520)
    timeline.setWindowTitle("BDO Music Composer SDK - Timeline")
    timeline.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
