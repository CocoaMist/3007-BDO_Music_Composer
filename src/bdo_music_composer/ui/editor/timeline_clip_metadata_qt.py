"""Late Clip metadata overlay for the multitrack timeline."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter

from bdo_music_composer.ui.i18n import tr, trf


def paint_track_clip_metadata(
    canvas, painter: QPainter, track, region_rect: QRectF,
    visible_start: float, visible_duration: float, *, active: bool,
) -> None:
    """Paint unobtrusive Clip identity last so notes cannot cover it."""

    painter.save()
    font = painter.font()
    font.setPointSize(max(7, font.pointSize() - 2))
    painter.setFont(font)
    for clip in canvas._visible_track_clips(
        track, visible_start, visible_start + visible_duration
    ):
        clip_x = region_rect.left() + (
            (clip.start_ms - visible_start) / visible_duration
        ) * region_rect.width()
        clip_width = max(
            8.0, (clip.end_ms - clip.start_ms)
            / visible_duration * region_rect.width(),
        )
        clip_rect = QRectF(
            clip_x, region_rect.top() + 2.0, clip_width,
            region_rect.height() - 4.0,
        ).intersected(region_rect)
        if clip_rect.width() < 28.0 or clip_rect.isEmpty():
            continue
        name = str(getattr(clip, "display_name", "") or "").strip()
        percent = int(getattr(clip, "velocity_percent", 100))
        index = canvas._track_note_indexes.get(id(track))
        count = (
            sum(
                1 for note in index.intervals.query_closed(
                    clip.start_ms, clip.end_ms
                ).items
                if clip.start_ms <= float(note.start) < clip.end_ms
            )
            if index is not None else 0
        )
        full = trf(
            "{name} · {count} 音块 · {percent}%",
            name=name or tr("音块"), count=count, percent=percent,
        )
        medium = trf(
            "{name} · {percent}%",
            name=name or tr("音块"), percent=percent,
        )
        available = max(1, int(clip_rect.width() - 12.0))
        text = full
        if painter.fontMetrics().horizontalAdvance(text) > available:
            text = medium
        if painter.fontMetrics().horizontalAdvance(text) > available:
            text = f"{percent}%"
        text = painter.fontMetrics().elidedText(text, Qt.ElideRight, available)
        text_rect = QRectF(
            clip_rect.left() + 5.0, clip_rect.bottom() - 17.0,
            max(1.0, clip_rect.width() - 10.0), 14.0,
        )
        backing = QColor("#181719")
        backing.setAlpha(142 if active else 104)
        painter.fillRect(text_rect.adjusted(-2.0, 0.0, 2.0, 0.0), backing)
        painter.setPen(QColor("#f2eee7" if active else "#c0bbb2"))
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, text)
    painter.restore()


__all__ = ["paint_track_clip_metadata"]
