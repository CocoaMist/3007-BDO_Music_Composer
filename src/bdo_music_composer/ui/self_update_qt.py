"""Background signed-channel check, download, and exit-time update handoff."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import ssl
import sys
import threading
import time
from typing import Callable, Mapping, MutableMapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PySide6.QtCore import QObject, QThread, Signal

from bdo_music_composer.app.application_metadata import (
    APP_NAME,
    APP_VERSION,
    GITHUB_UPDATE_CHANNEL_URL,
    GITEE_UPDATE_CHANNEL_URL,
)
from bdo_music_composer.app.update_check import SemanticVersion
from bdo_music_composer.update.install import (
    UPDATE_ROOT,
    file_sha256,
    record_ready_update,
)
from bdo_music_composer.update.manifest import (
    MAX_MANIFEST_BYTES,
    MAX_SIGNATURE_BYTES,
    ManifestError,
    UpdateManifest,
    parse_signed_manifest,
)
from bdo_music_composer.update.preferences import update_preferences


CHECK_INTERVAL_SECONDS = 24 * 60 * 60
NETWORK_TIMEOUT_SECONDS = 8.0
_ALLOWED_NETWORK_HOSTS = frozenset({
    "raw.githubusercontent.com",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "gitee.com",
    "giteeusercontent.com",
})


class UpdateNetworkError(RuntimeError):
    pass


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != "https" or urlsplit(newurl).hostname not in _ALLOWED_NETWORK_HOSTS:
            raise UpdateNetworkError("unsafe update redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _validate_network_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _ALLOWED_NETWORK_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.fragment
    ):
        raise UpdateNetworkError("unsafe update URL")


def _opener():
    return build_opener(_SafeRedirectHandler())


def _request(url: str) -> Request:
    _validate_network_url(url)
    return Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": f"{APP_NAME.replace(' ', '-')}/{APP_VERSION}",
        },
        method="GET",
    )


def _fetch_bounded(url: str, limit: int, cancelled: threading.Event) -> bytes:
    try:
        with _opener().open(_request(url), timeout=NETWORK_TIMEOUT_SECONDS) as response:
            _validate_network_url(response.geturl())
            length = response.headers.get("Content-Length")
            if length is not None and int(length) > limit:
                raise UpdateNetworkError("update response is too large")
            payload = bytearray()
            while not cancelled.is_set():
                reader = getattr(response, "read1", response.read)
                chunk = reader(min(64 * 1024, limit + 1 - len(payload)))
                if not chunk:
                    return bytes(payload)
                payload.extend(chunk)
                if len(payload) > limit:
                    raise UpdateNetworkError("update response is too large")
    except (HTTPError, URLError, OSError, ssl.SSLError, ValueError) as exc:
        raise UpdateNetworkError("update request failed") from exc
    raise UpdateNetworkError("update request cancelled")


@dataclass(frozen=True, slots=True)
class PreparedUpdate:
    manifest: UpdateManifest
    executable: Path
    source: str


class UpdateDownloadWorker(QThread):
    checking = Signal()
    available = Signal(object, str)
    progress = Signal(int, int)
    ready = Signal(object)
    current = Signal()
    failed = Signal(str)

    def __init__(self, preferences: Mapping[str, object], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.preferences = dict(preferences)
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def _source_order(self) -> list[tuple[str, str]]:
        sources = {
            "github": GITHUB_UPDATE_CHANNEL_URL,
            "gitee": GITEE_UPDATE_CHANNEL_URL,
        }
        selected = str(self.preferences.get("source", "auto"))
        if selected in sources:
            return [(selected, sources[selected])]
        last = str(self.preferences.get("last_source", ""))
        order = [last] if last in sources else []
        order.extend(name for name in ("gitee", "github") if name not in order)
        return [(name, sources[name]) for name in order]

    def _discover(self) -> tuple[UpdateManifest, str]:
        errors: list[str] = []
        candidates: list[tuple[UpdateManifest, str]] = []
        for source, manifest_url in self._source_order():
            if self._cancelled.is_set():
                break
            try:
                payload = _fetch_bounded(manifest_url, MAX_MANIFEST_BYTES, self._cancelled)
                signature = _fetch_bounded(
                    f"{manifest_url}.sig",
                    MAX_SIGNATURE_BYTES,
                    self._cancelled,
                )
                candidates.append((parse_signed_manifest(payload, signature), source))
            except (ManifestError, UpdateNetworkError) as exc:
                errors.append(f"{source}:{type(exc).__name__}")
        if candidates:
            # A lagging mirror is normal. Select the highest signed SemVer,
            # preserving source preference when both mirrors agree.
            return max(candidates, key=lambda item: item[0].version)
        raise UpdateNetworkError(",".join(errors) or "no update source available")

    def _download(self, manifest: UpdateManifest, first_source: str) -> PreparedUpdate:
        artifact = manifest.artifact
        sources = [first_source] + [name for name in ("gitee", "github") if name != first_source]
        target_dir = UPDATE_ROOT / str(manifest.version)
        target_dir.mkdir(parents=True, exist_ok=True)
        final_path = target_dir / artifact.filename
        if final_path.is_file() and final_path.stat().st_size == artifact.size:
            if file_sha256(final_path) == artifact.sha256:
                return PreparedUpdate(manifest, final_path, first_source)
        partial = target_dir / f".{artifact.filename}.part"
        errors: list[str] = []
        for source in sources:
            url = artifact.url_for(source)
            if url is None or self._cancelled.is_set():
                continue
            partial.unlink(missing_ok=True)
            try:
                with _opener().open(_request(url), timeout=NETWORK_TIMEOUT_SECONDS) as response:
                    _validate_network_url(response.geturl())
                    length = response.headers.get("Content-Length")
                    if length is not None and int(length) != artifact.size:
                        raise UpdateNetworkError("artifact size header mismatch")
                    downloaded = 0
                    with partial.open("wb") as stream:
                        while not self._cancelled.is_set():
                            reader = getattr(response, "read1", response.read)
                            chunk = reader(64 * 1024)
                            if not chunk:
                                break
                            downloaded += len(chunk)
                            if downloaded > artifact.size:
                                raise UpdateNetworkError("artifact is too large")
                            stream.write(chunk)
                            self.progress.emit(downloaded, artifact.size)
                        stream.flush()
                        os.fsync(stream.fileno())
                if self._cancelled.is_set():
                    raise UpdateNetworkError("update download cancelled")
                if partial.stat().st_size != artifact.size or file_sha256(partial) != artifact.sha256:
                    raise UpdateNetworkError("artifact integrity check failed")
                os.replace(partial, final_path)
                return PreparedUpdate(manifest, final_path, source)
            except (HTTPError, URLError, OSError, ssl.SSLError, ValueError, UpdateNetworkError) as exc:
                errors.append(f"{source}:{type(exc).__name__}")
                partial.unlink(missing_ok=True)
        raise UpdateNetworkError(",".join(errors) or "no artifact mirror available")

    def run(self) -> None:
        self.checking.emit()
        try:
            manifest, source = self._discover()
            local = SemanticVersion.parse(APP_VERSION)
            highest_text = str(self.preferences.get("highest_version", ""))
            highest = SemanticVersion.parse(highest_text) if highest_text else local
            if manifest.version < highest:
                raise UpdateNetworkError("signed channel attempted a version rollback")
            if manifest.version <= local:
                self.current.emit()
                return
            self.available.emit(manifest, source)
            if not bool(self.preferences.get("auto_download", True)):
                return
            self.ready.emit(self._download(manifest, source))
        except (UpdateNetworkError, ManifestError, ValueError) as exc:
            if not self._cancelled.is_set():
                self.failed.emit(str(exc))


class SelfUpdateController(QObject):
    checking = Signal()
    available = Signal(object, str)
    progress = Signal(int, int)
    ready = Signal(object)
    current = Signal()
    failed = Signal(str)

    def __init__(
        self,
        config: MutableMapping[str, object],
        save_config: Callable[[], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self._save_config = save_config
        self.worker: UpdateDownloadWorker | None = None
        self.prepared: PreparedUpdate | None = None

    @property
    def supported(self) -> bool:
        return sys.platform == "win32" and bool(getattr(sys, "frozen", False))

    def start(self, *, manual: bool = False) -> bool:
        if self.worker is not None and self.worker.isRunning():
            return False
        preferences = update_preferences(self.config)
        if not self.supported:
            if manual:
                self.failed.emit("self-update is available only in the packaged Windows application")
            return False
        if os.environ.get("BDO_STARTUP_SELF_TEST"):
            return False
        if not manual:
            if not preferences["enabled"]:
                return False
            if int(time.time()) - int(preferences["last_check"]) < CHECK_INTERVAL_SECONDS:
                return False
        worker = UpdateDownloadWorker(preferences, self)
        self.worker = worker
        worker.checking.connect(self.checking)
        worker.available.connect(self._on_available)
        worker.available.connect(self.available)
        worker.progress.connect(self.progress)
        worker.ready.connect(self._on_ready)
        worker.ready.connect(self.ready)
        worker.current.connect(self._on_current)
        worker.current.connect(self.current)
        worker.failed.connect(self._on_failed)
        worker.failed.connect(self.failed)
        worker.finished.connect(self._worker_finished)
        worker.start()
        return True

    def _record_check(self, *, source: str = "", version: str = "") -> None:
        preferences = update_preferences(self.config)
        preferences["last_check"] = int(time.time())
        if source:
            preferences["last_source"] = source
        if version:
            preferences["highest_version"] = version
        self.config["updates"] = preferences
        self._save_config()

    def _on_available(self, manifest: UpdateManifest, source: str) -> None:
        self._record_check(source=source, version=str(manifest.version))

    def _on_ready(self, prepared: PreparedUpdate) -> None:
        self.prepared = prepared
        record_ready_update(
            prepared.executable,
            version=str(prepared.manifest.version),
            sha256=prepared.manifest.artifact.sha256,
        )
        self._record_check(source=prepared.source, version=str(prepared.manifest.version))

    def _on_current(self) -> None:
        self._record_check()

    def _on_failed(self, _message: str) -> None:
        self._record_check()

    def _worker_finished(self) -> None:
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.deleteLater()

    def shutdown(self) -> None:
        worker = self.worker
        if worker is None or not worker.isRunning():
            return
        worker.cancel()
        worker.wait(int((NETWORK_TIMEOUT_SECONDS + 2.0) * 1000))


__all__ = [
    "CHECK_INTERVAL_SECONDS",
    "PreparedUpdate",
    "SelfUpdateController",
    "UpdateDownloadWorker",
]
