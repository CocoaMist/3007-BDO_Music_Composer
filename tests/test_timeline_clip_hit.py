"""Focused tests for timeline Clip hit-testing and marquee geometry."""

from __future__ import annotations

import unittest

from PySide6.QtCore import QPointF, QRectF

from bdo_music_composer.editor.editor_models import TrackState
from bdo_music_composer.ui.editor.timeline_clip_hit import (
    clip_action_at,
    clip_keys_intersecting,
    marquee_rect,
)


def _track(track_id: int) -> TrackState:
    return TrackState(track_id, [], 0, False, f"track-{track_id}", 0x0B)


class TimelineClipHitTests(unittest.TestCase):
    def test_marquee_rect_normalizes_and_clips_to_grid(self) -> None:
        grid = QRectF(100.0, 50.0, 400.0, 300.0)
        self.assertEqual(
            marquee_rect(QPointF(300.0, 200.0), QPointF(120.0, 90.0), grid),
            QRectF(120.0, 90.0, 180.0, 110.0),
        )
        # dragging entirely outside the grid clips back to the grid bounds
        self.assertEqual(
            marquee_rect(QPointF(80.0, 40.0), QPointF(600.0, 400.0), grid),
            grid,
        )

    def test_marquee_rect_without_press_is_empty(self) -> None:
        self.assertTrue(
            marquee_rect(None, QPointF(10.0, 10.0), QRectF(0.0, 0.0, 100.0, 100.0)).isEmpty()
        )

    def test_clip_keys_intersecting_returns_only_body_clips(self) -> None:
        t1 = _track(1)
        t2 = _track(2)
        regions = [
            (QRectF(0.0, 0.0, 100.0, 20.0), "clip_body|a", t1),
            (QRectF(200.0, 0.0, 100.0, 20.0), "clip_body|b", t2),
            (QRectF(0.0, 30.0, 100.0, 20.0), "lane", t1),
        ]
        self.assertEqual(
            clip_keys_intersecting(regions, QRectF(0.0, 0.0, 110.0, 20.0)),
            {(1, "a")},
        )
        self.assertEqual(
            clip_keys_intersecting(regions, QRectF(0.0, 0.0, 310.0, 20.0)),
            {(1, "a"), (2, "b")},
        )
        self.assertEqual(clip_keys_intersecting(regions, QRectF()), set())

    def test_clip_action_at_degrades_handle_to_body_when_not_selected(self) -> None:
        t1 = _track(1)
        regions = [(QRectF(0.0, 0.0, 7.0, 20.0), "clip_start|a", t1)]
        action = clip_action_at(
            regions,
            QPointF(3.0, 10.0),
            arrangement_tool="select",
            selected_clip_keys=set(),
        )
        self.assertEqual(action, (t1, "a", "clip_body"))

    def test_clip_action_at_keeps_handle_when_selected(self) -> None:
        t1 = _track(1)
        regions = [(QRectF(0.0, 0.0, 7.0, 20.0), "clip_start|a", t1)]
        action = clip_action_at(
            regions,
            QPointF(3.0, 10.0),
            arrangement_tool="select",
            selected_clip_keys={(1, "a")},
        )
        self.assertEqual(action, (t1, "a", "clip_start"))

    def test_clip_action_at_razor_tool_never_uses_handles(self) -> None:
        t1 = _track(1)
        regions = [(QRectF(0.0, 0.0, 7.0, 20.0), "clip_end|a", t1)]
        action = clip_action_at(
            regions,
            QPointF(3.0, 10.0),
            arrangement_tool="razor",
            selected_clip_keys={(1, "a")},
        )
        self.assertEqual(action, (t1, "a", "clip_body"))

    def test_clip_action_at_ignores_non_clip_regions(self) -> None:
        t1 = _track(1)
        regions = [(QRectF(0.0, 0.0, 100.0, 20.0), "lane", t1)]
        self.assertIsNone(
            clip_action_at(regions, QPointF(50.0, 10.0), arrangement_tool="select")
        )

if __name__ == "__main__":
    unittest.main()
