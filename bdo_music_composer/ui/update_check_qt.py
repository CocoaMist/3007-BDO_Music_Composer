"""Explicit, single-request Qt transport for GitHub update checks.

Construction is network-inert.  A request starts only after :meth:`start`, and
the packaged startup self-test is hard-disabled from network access.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)

from bdo_music_composer.app.application_metadata import (
    APP_VERSION,
    GITHUB_LATEST_RELEASE_API_URL,
)
from bdo_music_composer.app.update_check import (
    MAX_RESPONSE_BYTES,
    UpdateCheckError,
    UpdateErrorCode,
    classify_http_error,
    github_request_headers,
    parse_latest_release_payload,
)


STARTUP_SELF_TEST_ENVIRONMENT = "BDO_STARTUP_SELF_TEST"
DEFAULT_TIMEOUT_MS = 8_000


class UpdateCheckController(QObject):
    """Own one bounded asynchronous GitHub request at a time."""

    started = Signal()
    succeeded = Signal(object)
    failed = Signal(object)
    busy_changed = Signal(bool)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        network_manager: QNetworkAccessManager | None = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
    ) -> None:
        super().__init__(parent)
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        if max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        self._network_manager = network_manager or QNetworkAccessManager(self)
        self._timeout_ms = int(timeout_ms)
        self._max_response_bytes = int(max_response_bytes)
        self._reply: QNetworkReply | None = None
        self._response = bytearray()
        self._current_version = APP_VERSION
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self._on_timeout)

    @property
    def is_busy(self) -> bool:
        return self._reply is not None

    def start(self, current_version: str = APP_VERSION) -> bool:
        """Begin the explicit check, returning ``False`` when none was started."""

        if self.is_busy:
            return False
        if os.environ.get(STARTUP_SELF_TEST_ENVIRONMENT):
            self.failed.emit(
                UpdateCheckError(UpdateErrorCode.SELF_TEST_DISABLED)
            )
            return False
        try:
            headers = github_request_headers(current_version)
        except ValueError:
            self.failed.emit(UpdateCheckError(UpdateErrorCode.INVALID_PAYLOAD))
            return False

        request = QNetworkRequest(QUrl(GITHUB_LATEST_RELEASE_API_URL))
        request.setTransferTimeout(self._timeout_ms)
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.ManualRedirectPolicy,
        )
        for name, value in headers.items():
            request.setRawHeader(name.encode("ascii"), value.encode("ascii"))

        self._current_version = current_version
        self._response.clear()
        try:
            reply = self._network_manager.get(request)
        except Exception:
            self.failed.emit(UpdateCheckError(UpdateErrorCode.NETWORK_ERROR))
            return False

        self._reply = reply
        if hasattr(reply, "setReadBufferSize"):
            reply.setReadBufferSize(self._max_response_bytes + 1)
        reply.readyRead.connect(lambda: self._on_ready_read(reply))
        reply.metaDataChanged.connect(lambda: self._on_metadata_changed(reply))
        reply.sslErrors.connect(lambda _errors: self._on_ssl_errors(reply))
        reply.finished.connect(lambda: self._on_finished(reply))
        self._timeout.start(self._timeout_ms)
        self.busy_changed.emit(True)
        self.started.emit()
        return True

    def cancel(self) -> bool:
        """Cancel the active request and report a typed cancellation."""

        reply = self._reply
        if reply is None:
            return False
        self._finish_error(
            reply,
            UpdateCheckError(UpdateErrorCode.CANCELLED),
            abort=True,
        )
        return True

    def shutdown(self) -> None:
        """Abort transport work without emitting into a closing UI."""

        reply = self._reply
        if reply is None:
            return
        self._release_reply(reply, abort=True)

    def _on_metadata_changed(self, reply: QNetworkReply) -> None:
        if reply is not self._reply:
            return
        content_length = reply.header(
            QNetworkRequest.KnownHeaders.ContentLengthHeader
        )
        try:
            too_large = int(content_length) > self._max_response_bytes
        except (TypeError, ValueError):
            too_large = False
        if too_large:
            self._finish_error(
                reply,
                UpdateCheckError(UpdateErrorCode.PAYLOAD_TOO_LARGE),
                abort=True,
            )

    def _on_ready_read(self, reply: QNetworkReply) -> None:
        if reply is not self._reply:
            return
        chunk = bytes(reply.readAll())
        if len(self._response) + len(chunk) > self._max_response_bytes:
            self._finish_error(
                reply,
                UpdateCheckError(UpdateErrorCode.PAYLOAD_TOO_LARGE),
                abort=True,
            )
            return
        self._response.extend(chunk)

    def _on_ssl_errors(self, reply: QNetworkReply) -> None:
        if reply is not self._reply:
            return
        # Deliberately never call ignoreSslErrors(): a compromised TLS
        # connection cannot supply update text or links.
        self._finish_error(
            reply,
            UpdateCheckError(UpdateErrorCode.TLS_ERROR),
            abort=True,
        )

    def _on_timeout(self) -> None:
        reply = self._reply
        if reply is None:
            return
        self._finish_error(
            reply,
            UpdateCheckError(UpdateErrorCode.TIMEOUT),
            abort=True,
        )

    def _on_finished(self, reply: QNetworkReply) -> None:
        if reply is not self._reply:
            return
        self._on_ready_read(reply)
        if reply is not self._reply:
            return

        status_value = reply.attribute(
            QNetworkRequest.Attribute.HttpStatusCodeAttribute
        )
        try:
            status_code = int(status_value)
        except (TypeError, ValueError):
            status_code = None

        if status_code != 200:
            remaining = bytes(reply.rawHeader("X-RateLimit-Remaining")).decode(
                "ascii",
                errors="ignore",
            )
            if status_code is not None:
                code = classify_http_error(status_code, remaining or None)
                self._finish_error(
                    reply,
                    UpdateCheckError(code, http_status=status_code),
                )
                return
            code = self._network_error_code(reply.error())
            self._finish_error(reply, UpdateCheckError(code))
            return

        if reply.error() != QNetworkReply.NetworkError.NoError:
            code = self._network_error_code(reply.error())
            self._finish_error(reply, UpdateCheckError(code))
            return
        try:
            result = parse_latest_release_payload(
                bytes(self._response),
                self._current_version,
                max_response_bytes=self._max_response_bytes,
            )
        except UpdateCheckError as exc:
            self._finish_error(reply, exc)
            return
        self._finish_success(reply, result)

    @staticmethod
    def _network_error_code(
        error: QNetworkReply.NetworkError,
    ) -> UpdateErrorCode:
        if error == QNetworkReply.NetworkError.TimeoutError:
            return UpdateErrorCode.TIMEOUT
        if error == QNetworkReply.NetworkError.SslHandshakeFailedError:
            return UpdateErrorCode.TLS_ERROR
        if error == QNetworkReply.NetworkError.OperationCanceledError:
            return UpdateErrorCode.CANCELLED
        return UpdateErrorCode.NETWORK_ERROR

    def _release_reply(self, reply: QNetworkReply, *, abort: bool) -> None:
        if reply is not self._reply:
            return
        self._reply = None
        self._timeout.stop()
        self._response.clear()
        if abort:
            try:
                reply.abort()
            except RuntimeError:
                pass
        reply.deleteLater()

    def _finish_success(self, reply: QNetworkReply, result: object) -> None:
        self._release_reply(reply, abort=False)
        self.busy_changed.emit(False)
        self.succeeded.emit(result)

    def _finish_error(
        self,
        reply: QNetworkReply,
        error: UpdateCheckError,
        *,
        abort: bool = False,
    ) -> None:
        self._release_reply(reply, abort=abort)
        self.busy_changed.emit(False)
        self.failed.emit(error)


__all__ = [
    "DEFAULT_TIMEOUT_MS",
    "STARTUP_SELF_TEST_ENVIRONMENT",
    "UpdateCheckController",
]
