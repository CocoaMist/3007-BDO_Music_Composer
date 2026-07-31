"""Reference-audio transport, waveform decode and alignment controller."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import (
    QAudioDecoder,
    QAudioFormat,
    QAudioOutput,
    QMediaPlayer,
)
from PySide6.QtWidgets import QFileDialog, QWidget

from i18n import tr, trf
from bdo_music_composer.ui.ui_notifications import show_global_toast


class ReferenceAudioController(QObject):
    """Local MP3/WAV playback plus bounded waveform-envelope extraction."""

    file_changed = Signal(str)
    volume_changed = Signal(int)
    offset_changed = Signal(float)
    changed = Signal()
    timeline_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._audio_path: Path | None = None
        self._project_offset_ms = 0.0
        self.waveform: list[tuple[float, float, float]] = []
        self.waveform_starts: list[float] = []
        self.waveform_loading = False
        self._waveform_deferred_for_playback = False
        self._pending_project_position_ms: float | None = None

        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.5)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.positionChanged.connect(lambda _position: self.changed.emit())
        self.player.durationChanged.connect(self._duration_changed)
        self.player.playbackStateChanged.connect(self._playback_state_changed)
        self.player.errorOccurred.connect(self._playback_error)

        self.decoder = QAudioDecoder(self)
        self.decoder.bufferReady.connect(self._read_waveform_buffer)
        self.decoder.finished.connect(self._waveform_finished)
        self.decoder.error.connect(self._waveform_error)

    @property
    def audio_path(self) -> str:
        return str(self._audio_path or "")

    @property
    def display_name(self) -> str:
        return self._audio_path.name if self._audio_path else tr("未载入参考音频")

    @property
    def duration_ms(self) -> float:
        waveform_end = self.waveform[-1][1] if self.waveform else 0.0
        return max(float(self.player.duration()), waveform_end)

    @property
    def project_offset_ms(self) -> float:
        """Project time occupied by audio frame zero."""
        return self._project_offset_ms

    @property
    def project_start_ms(self) -> float:
        return self._project_offset_ms

    @property
    def project_end_ms(self) -> float:
        return self._project_offset_ms + self.duration_ms

    @property
    def project_position_ms(self) -> float:
        return self.audio_to_project(float(self.player.position()))

    @property
    def is_playing(self) -> bool:
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    @property
    def volume_percent(self) -> int:
        return round(self.audio_output.volume() * 100)

    def choose_audio(self, parent: QWidget) -> None:
        start = self._audio_path.parent if self._audio_path else Path.home()
        selected, _filter = QFileDialog.getOpenFileName(
            parent,
            tr("选择参考音频"),
            str(start),
            tr("音频文件 (*.mp3 *.wav);;所有文件 (*.*)"),
        )
        if selected:
            self.set_audio_path(Path(selected))

    def set_audio_path(self, path: str | Path | None, *, notify: bool = True) -> bool:
        candidate = Path(path) if path else None
        if candidate is None or not candidate.is_file() or candidate.suffix.lower() not in {".mp3", ".wav"}:
            if path:
                return False
            self.stop()
            self.decoder.stop()
            self.decoder.setSource(QUrl())
            self.player.setSource(QUrl())
            self._audio_path = None
            self._pending_project_position_ms = None
            self.waveform = []
            self.waveform_starts = []
            self.waveform_loading = False
            self._waveform_deferred_for_playback = False
            if notify:
                self.file_changed.emit("")
            self.timeline_changed.emit()
            self.changed.emit()
            return True

        self.stop()
        self.decoder.stop()
        self._audio_path = candidate.resolve()
        self._pending_project_position_ms = None
        source = QUrl.fromLocalFile(str(self._audio_path))
        self.player.setSource(source)
        self.waveform = []
        self.waveform_starts = []
        self.waveform_loading = True
        self._waveform_deferred_for_playback = False
        self.decoder.setSource(source)
        self.decoder.start()
        if notify:
            self.file_changed.emit(str(self._audio_path))
        self.timeline_changed.emit()
        self.changed.emit()
        return True

    def play(self) -> None:
        if self._audio_path is not None:
            # A second full-file decoder can starve the audible Media
            # Foundation stream on long files. Resume waveform work only after
            # playback pauses or stops.
            if self.waveform_loading and self.decoder.isDecoding():
                self.decoder.stop()
                self.waveform = []
                self.waveform_starts = []
                self._waveform_deferred_for_playback = True
            self.player.play()

    def pause(self) -> None:
        self.player.pause()

    def stop(self) -> None:
        self._pending_project_position_ms = None
        self.player.stop()

    def shutdown(self) -> None:
        """Release multimedia backends before the owning window is destroyed."""

        self.set_audio_path(None, notify=False)
        # A source-less QMediaPlayer can still retain the platform audio backend.
        # Detach it explicitly so headless/no-device Windows processes can exit.
        self.player.setAudioOutput(None)

    def project_to_audio(self, project_ms: float) -> float:
        return float(project_ms) - self._project_offset_ms

    def audio_to_project(self, audio_ms: float) -> float:
        return float(audio_ms) + self._project_offset_ms

    def set_project_offset_ms(self, milliseconds: float, *, notify: bool = True) -> None:
        normalized = float(milliseconds)
        if not math.isfinite(normalized):
            return
        if math.isclose(normalized, self._project_offset_ms, abs_tol=0.001):
            return
        self._project_offset_ms = normalized
        if notify:
            self.offset_changed.emit(normalized)
        self.timeline_changed.emit()
        self.changed.emit()

    def set_position(self, milliseconds: float) -> None:
        """Seek with a project-time position.

        All UI callers operate on the shared project timeline. The underlying
        media player remains in source-audio time.
        """
        project_ms = float(milliseconds)
        if not math.isfinite(project_ms):
            return
        audio_ms = self.project_to_audio(project_ms)
        if not math.isfinite(audio_ms) or audio_ms < 0.0:
            self._pending_project_position_ms = None
            self.player.setPosition(0)
            return
        media_duration_ms = float(self.player.duration())
        if media_duration_ms <= 0.0:
            # QMediaPlayer may ignore seeks issued before metadata arrives.
            # Retain the project-clock request and reapply it on durationChanged.
            self._pending_project_position_ms = project_ms
            self.player.setPosition(max(0, round(audio_ms)))
            return
        self._pending_project_position_ms = None
        self.player.setPosition(
            max(0, min(round(audio_ms), round(media_duration_ms)))
        )

    def _apply_pending_position(self) -> None:
        pending = self._pending_project_position_ms
        if pending is None or float(self.player.duration()) <= 0.0:
            return
        self._pending_project_position_ms = None
        self.set_position(pending)

    def _duration_changed(self, _duration: int) -> None:
        self._apply_pending_position()
        self.timeline_changed.emit()

    def set_volume_percent(self, percent: int, *, notify: bool = True) -> None:
        normalized = max(0, min(100, int(percent)))
        if normalized == self.volume_percent:
            return
        self.audio_output.setVolume(normalized / 100.0)
        if notify:
            self.volume_changed.emit(normalized)
        self.changed.emit()

    def _read_waveform_buffer(self) -> None:
        buffer = self.decoder.read()
        if not buffer.isValid() or buffer.frameCount() <= 0:
            return
        audio_format = buffer.format()
        channels = max(1, audio_format.channelCount())
        sample_rate = max(1, audio_format.sampleRate())
        sample_format = audio_format.sampleFormat()
        raw = buffer.constData().cast("B")
        try:
            if sample_format == QAudioFormat.SampleFormat.UInt8:
                samples = np.frombuffer(raw, dtype=np.uint8)
                amplitudes = np.abs(samples.astype(np.float32) - 128.0) / 128.0
            elif sample_format == QAudioFormat.SampleFormat.Int16:
                samples = np.frombuffer(raw, dtype=np.int16)
                amplitudes = np.abs(samples.astype(np.float32)) / 32768.0
            elif sample_format == QAudioFormat.SampleFormat.Int32:
                samples = np.frombuffer(raw, dtype=np.int32)
                amplitudes = np.abs(samples.astype(np.float64)) / 2147483648.0
            elif sample_format == QAudioFormat.SampleFormat.Float:
                samples = np.frombuffer(raw, dtype=np.float32)
                amplitudes = np.abs(samples)
            else:
                return
        except (BufferError, TypeError, ValueError):
            return

        frame_count = len(amplitudes) // channels
        if frame_count <= 0:
            return
        frame_peaks = amplitudes[:frame_count * channels].reshape(frame_count, channels).max(axis=1)
        frames_per_bucket = max(1, sample_rate // 20)  # 50 ms envelope
        start_ms = max(0.0, float(buffer.startTime()) / 1000.0)
        offsets = np.arange(0, frame_count, frames_per_bucket, dtype=np.int64)
        bucket_peaks = np.maximum.reduceat(frame_peaks, offsets)
        ends = np.minimum(offsets + frames_per_bucket, frame_count)
        self.waveform.extend(
            (
                start_ms + float(offset) / sample_rate * 1000.0,
                start_ms + float(end) / sample_rate * 1000.0,
                min(1.0, float(peak)),
            )
            for offset, end, peak in zip(offsets, ends, bucket_peaks)
        )

    def _waveform_finished(self) -> None:
        self.waveform.sort(key=lambda item: item[0])
        self.waveform_starts = [item[0] for item in self.waveform]
        self.waveform_loading = False
        self._apply_pending_position()
        self.timeline_changed.emit()
        self.changed.emit()

    def _playback_state_changed(
        self, state: QMediaPlayer.PlaybackState,
    ) -> None:
        self.changed.emit()
        if (
            state != QMediaPlayer.PlaybackState.PlayingState
            and self._waveform_deferred_for_playback
            and self._audio_path is not None
        ):
            self._waveform_deferred_for_playback = False
            self.waveform_loading = True
            self.decoder.setSource(QUrl.fromLocalFile(str(self._audio_path)))
            self.decoder.start()
            self.changed.emit()

    def _waveform_error(self, _error: QAudioDecoder.Error) -> None:
        self.waveform_loading = False
        self.timeline_changed.emit()
        self.changed.emit()

    def _playback_error(self, _error: QMediaPlayer.Error, error_string: str) -> None:
        if error_string and isinstance(self.parent(), QWidget):
            show_global_toast(
                self.parent(),
                trf("参考音频无法播放：{error}", error=error_string),
                kind="warning",
                duration_ms=4200,
            )
