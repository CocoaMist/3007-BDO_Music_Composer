from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QByteArray, QUrl, Signal
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QApplication

from bdo_music_composer.app.application_metadata import (
    GITHUB_LATEST_RELEASE_API_URL,
)
from bdo_music_composer.app.update_check import (
    UpdateErrorCode,
    UpdateStatus,
)
from bdo_music_composer.ui.update_check_qt import (
    STARTUP_SELF_TEST_ENVIRONMENT,
    UpdateCheckController,
)


APP = QApplication.instance() or QApplication([])


class FakeReply(QObject):
    readyRead = Signal()
    metaDataChanged = Signal()
    sslErrors = Signal(object)
    finished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.payload = bytearray()
        self.status_code: int | None = 200
        self.network_error = QNetworkReply.NetworkError.NoError
        self.headers: dict[bytes, bytes] = {}
        self.content_length: int | None = None
        self.aborted = False
        self.read_buffer_size = 0

    def setReadBufferSize(self, size: int) -> None:
        self.read_buffer_size = size

    def readAll(self) -> QByteArray:
        value = QByteArray(bytes(self.payload))
        self.payload.clear()
        return value

    def header(self, header: QNetworkRequest.KnownHeaders) -> object:
        if header == QNetworkRequest.KnownHeaders.ContentLengthHeader:
            return self.content_length
        return None

    def attribute(self, attribute: QNetworkRequest.Attribute) -> object:
        if attribute == QNetworkRequest.Attribute.HttpStatusCodeAttribute:
            return self.status_code
        return None

    def rawHeader(self, name: str) -> QByteArray:
        return QByteArray(self.headers.get(name.encode("ascii"), b""))

    def error(self) -> QNetworkReply.NetworkError:
        return self.network_error

    def abort(self) -> None:
        self.aborted = True


class FakeManager:
    def __init__(self, reply: FakeReply) -> None:
        self.reply = reply
        self.requests: list[QNetworkRequest] = []

    def get(self, request: QNetworkRequest) -> FakeReply:
        self.requests.append(request)
        return self.reply


def _release_payload() -> bytes:
    return json.dumps(
        {
            "tag_name": "v1.1.0",
            "name": "v1.1.0",
            "body": "notes",
            "draft": False,
            "prerelease": False,
            "published_at": "2026-07-31T08:00:00Z",
        }
    ).encode()


class UpdateCheckControllerTests(unittest.TestCase):
    def _controller(
        self,
        *,
        max_response_bytes: int = 512 * 1024,
    ) -> tuple[UpdateCheckController, FakeManager, FakeReply]:
        reply = FakeReply()
        manager = FakeManager(reply)
        controller = UpdateCheckController(
            network_manager=manager,  # type: ignore[arg-type]
            timeout_ms=5_000,
            max_response_bytes=max_response_bytes,
        )
        self.addCleanup(controller.shutdown)
        return controller, manager, reply

    def test_constructing_controller_is_network_inert(self) -> None:
        _controller, manager, _reply = self._controller()
        self.assertEqual(manager.requests, [])

    def test_explicit_start_sets_fixed_url_and_public_headers(self) -> None:
        controller, manager, reply = self._controller()
        started: list[bool] = []
        controller.started.connect(lambda: started.append(True))
        self.assertTrue(controller.start())
        self.assertFalse(controller.start())
        self.assertEqual(len(manager.requests), 1)
        request = manager.requests[0]
        self.assertEqual(
            request.url().toString(),
            GITHUB_LATEST_RELEASE_API_URL,
        )
        self.assertEqual(
            bytes(request.rawHeader("X-GitHub-Api-Version")),
            b"2026-03-10",
        )
        self.assertEqual(bytes(request.rawHeader("Authorization")), b"")
        self.assertEqual(started, [True])
        self.assertTrue(controller.is_busy)
        self.assertEqual(reply.read_buffer_size, 512 * 1024 + 1)

    def test_success_emits_validated_result(self) -> None:
        controller, _manager, reply = self._controller()
        results: list[object] = []
        controller.succeeded.connect(results.append)
        self.assertTrue(controller.start())
        reply.payload.extend(_release_payload())
        reply.readyRead.emit()
        reply.finished.emit()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, UpdateStatus.UPDATE)
        self.assertFalse(controller.is_busy)

    def test_http_rate_limit_and_ssl_fail_closed(self) -> None:
        controller, _manager, reply = self._controller()
        failures: list[object] = []
        controller.failed.connect(failures.append)
        controller.start()
        reply.status_code = 403
        reply.headers[b"X-RateLimit-Remaining"] = b"0"
        reply.finished.emit()
        self.assertEqual(failures[-1].code, UpdateErrorCode.RATE_LIMITED)

        tls_controller, _manager, tls_reply = self._controller()
        tls_failures: list[object] = []
        tls_controller.failed.connect(tls_failures.append)
        tls_controller.start()
        tls_reply.sslErrors.emit([])
        self.assertTrue(tls_reply.aborted)
        self.assertEqual(tls_failures[-1].code, UpdateErrorCode.TLS_ERROR)

    def test_declared_and_streamed_oversize_responses_abort(self) -> None:
        declared, _manager, declared_reply = self._controller(
            max_response_bytes=32
        )
        declared_errors: list[object] = []
        declared.failed.connect(declared_errors.append)
        declared.start()
        declared_reply.content_length = 33
        declared_reply.metaDataChanged.emit()
        self.assertTrue(declared_reply.aborted)
        self.assertEqual(
            declared_errors[-1].code,
            UpdateErrorCode.PAYLOAD_TOO_LARGE,
        )

        streamed, _manager, streamed_reply = self._controller(
            max_response_bytes=32
        )
        streamed_errors: list[object] = []
        streamed.failed.connect(streamed_errors.append)
        streamed.start()
        streamed_reply.payload.extend(b"x" * 33)
        streamed_reply.readyRead.emit()
        self.assertTrue(streamed_reply.aborted)
        self.assertEqual(
            streamed_errors[-1].code,
            UpdateErrorCode.PAYLOAD_TOO_LARGE,
        )

    def test_cancel_and_shutdown_release_lifecycle(self) -> None:
        controller, _manager, reply = self._controller()
        failures: list[object] = []
        controller.failed.connect(failures.append)
        controller.start()
        self.assertTrue(controller.cancel())
        self.assertTrue(reply.aborted)
        self.assertFalse(controller.is_busy)
        self.assertEqual(failures[-1].code, UpdateErrorCode.CANCELLED)
        self.assertFalse(controller.cancel())

        closing, _manager, closing_reply = self._controller()
        closing_failures: list[object] = []
        closing.failed.connect(closing_failures.append)
        closing.start()
        closing.shutdown()
        self.assertTrue(closing_reply.aborted)
        self.assertEqual(closing_failures, [])

    def test_startup_self_test_never_starts_network(self) -> None:
        controller, manager, _reply = self._controller()
        failures: list[object] = []
        controller.failed.connect(failures.append)
        with patch.dict(
            os.environ,
            {STARTUP_SELF_TEST_ENVIRONMENT: "1"},
            clear=False,
        ):
            self.assertFalse(controller.start())
        self.assertEqual(manager.requests, [])
        self.assertEqual(
            failures[-1].code,
            UpdateErrorCode.SELF_TEST_DISABLED,
        )


if __name__ == "__main__":
    unittest.main()
