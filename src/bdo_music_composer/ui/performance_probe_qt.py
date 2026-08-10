"""Opt-in Qt adapter for bounded, content-free UI performance metrics."""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import QApplication, QWidget

from bdo_music_composer.ui.performance_metrics import UiPerformanceRecorder


_INPUT_EVENTS = frozenset({
    QEvent.Type.KeyPress,
    QEvent.Type.MouseButtonPress,
    QEvent.Type.MouseButtonRelease,
    QEvent.Type.MouseMove,
    QEvent.Type.Wheel,
    QEvent.Type.TouchBegin,
    QEvent.Type.TouchUpdate,
})


class UiPerformanceProbe(QObject):
    """Measure first visual response and event-loop stalls for registered roots."""

    def __init__(
        self,
        application: QApplication,
        root: QWidget,
        *,
        heartbeat_ms: int = 16,
    ) -> None:
        super().__init__(application)
        self.recorder = UiPerformanceRecorder(
            stall_threshold_ms=max(32.0, float(heartbeat_ms) * 2.0),
        )
        self._roots: list[QWidget] = [root]
        self._application = application
        self._closed = False
        application.installEventFilter(self)
        self._heartbeat = QTimer(self)
        self._heartbeat.setInterval(max(8, int(heartbeat_ms)))
        self._heartbeat.setTimerType(Qt.TimerType.PreciseTimer)
        self._heartbeat.timeout.connect(self.recorder.heartbeat)
        self._heartbeat.start()
        self.recorder.heartbeat()
        root.destroyed.connect(self.shutdown)

    def register_root(self, root: QWidget) -> None:
        if root not in self._roots:
            self._roots.append(root)

    def begin_interaction_window(self) -> None:
        self.recorder.reset_interaction_window()

    def note_synthetic_input(self) -> None:
        """Allow deterministic qualification tools to mark an input boundary."""

        self.recorder.note_input()

    def _belongs_to_registered_root(self, watched: QObject) -> bool:
        if self._closed or not isinstance(watched, QWidget):
            return False
        try:
            window = watched.window()
            for root in tuple(self._roots):
                try:
                    if window is root or root.isAncestorOf(watched):
                        return True
                except RuntimeError:
                    continue
            return False
        except RuntimeError:
            return False

    def shutdown(self, *_args: object) -> None:
        if self._closed:
            return
        self._closed = True
        self._heartbeat.stop()
        self._application.removeEventFilter(self)
        self._roots = []

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if not self._closed and self._belongs_to_registered_root(watched):
            event_type = event.type()
            if event_type in _INPUT_EVENTS:
                self.recorder.note_input()
            elif event_type == QEvent.Type.Paint:
                # Record entry into the next paint dispatch.  A zero-delay
                # Python callback can outlive Qt widgets during Windows
                # process teardown and has caused intermittent heap failures
                # in benchmark subprocesses.
                self.recorder.note_paint_complete()
        return False


def install_ui_performance_probe(
    root: QWidget,
) -> UiPerformanceProbe | None:
    """Install diagnostics only after an explicit local opt-in."""

    if os.environ.get("BDO_UI_PERF_DIAGNOSTICS", "").strip() != "1":
        return None
    application = QApplication.instance()
    if application is None:
        return None
    return UiPerformanceProbe(application, root)


__all__ = ["UiPerformanceProbe", "install_ui_performance_probe"]
