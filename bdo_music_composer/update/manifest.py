"""Strict signed update-channel parsing with no network or Qt dependency."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from enum import Enum
import hashlib
import hmac
import json
import re
from urllib.parse import urlsplit

from bdo_music_composer.app.application_metadata import (
    UPDATE_APP_ID,
    UPDATE_CHANNEL,
    UPDATE_PROTOCOL_VERSION,
    UPDATE_SIGNING_RSA_EXPONENT,
    UPDATE_SIGNING_RSA_MODULUS_HEX,
)
from bdo_music_composer.app.update_check import SemanticVersion


MAX_MANIFEST_BYTES = 128 * 1024
MAX_SIGNATURE_BYTES = 1024
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024 * 1024
EXPECTED_EXECUTABLE_NAME = "BDO-Music-Composer.exe"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$",
    re.ASCII,
)
_ALLOWED_DOWNLOAD_HOSTS = frozenset({
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "gitee.com",
    "giteeusercontent.com",
})
_SHA256_DIGEST_INFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


class ManifestErrorCode(str, Enum):
    TOO_LARGE = "too_large"
    INVALID_JSON = "invalid_json"
    INVALID_SCHEMA = "invalid_schema"
    INVALID_SIGNATURE = "invalid_signature"
    UNSUPPORTED_PROTOCOL = "unsupported_protocol"
    NO_WINDOWS_ARTIFACT = "no_windows_artifact"


class ManifestError(ValueError):
    def __init__(self, code: ManifestErrorCode) -> None:
        self.code = ManifestErrorCode(code)
        super().__init__(self.code.value)


@dataclass(frozen=True, slots=True)
class UpdateArtifact:
    filename: str
    size: int
    sha256: str
    urls: tuple[tuple[str, str], ...]

    def url_for(self, source: str) -> str | None:
        return dict(self.urls).get(str(source))


@dataclass(frozen=True, slots=True)
class UpdateManifest:
    version: SemanticVersion
    published_at: str
    mandatory: bool
    release_notes: tuple[tuple[str, str], ...]
    artifact: UpdateArtifact
    protocol: int

    def localized_notes(self, locale: str) -> str:
        notes = dict(self.release_notes)
        exact = notes.get(locale)
        if exact:
            return exact
        if str(locale).startswith("zh"):
            return notes.get("zh_CN") or notes.get("en_US") or ""
        return notes.get("en_US") or notes.get("zh_CN") or ""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _require_exact_keys(
    value: object,
    required: set[str],
    optional: set[str] = set(),
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != required | (set(value) & optional):
        raise ManifestError(ManifestErrorCode.INVALID_SCHEMA)
    if not required.issubset(value):
        raise ManifestError(ManifestErrorCode.INVALID_SCHEMA)
    return value


def _safe_download_url(value: object) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise ManifestError(ManifestErrorCode.INVALID_SCHEMA)
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.hostname not in _ALLOWED_DOWNLOAD_HOSTS
        or not parsed.path
        or parsed.fragment
    ):
        raise ManifestError(ManifestErrorCode.INVALID_SCHEMA)
    return value


def verify_manifest_signature(payload: bytes, signature_text: bytes | str) -> None:
    """Verify an exact-byte RSA-3072/SHA-256 PKCS#1 v1.5 signature."""

    if len(payload) > MAX_MANIFEST_BYTES:
        raise ManifestError(ManifestErrorCode.TOO_LARGE)
    if isinstance(signature_text, bytes):
        encoded = signature_text.strip()
    elif isinstance(signature_text, str):
        encoded = signature_text.strip().encode("ascii", errors="strict")
    else:
        raise ManifestError(ManifestErrorCode.INVALID_SIGNATURE)
    if not encoded or len(encoded) > MAX_SIGNATURE_BYTES:
        raise ManifestError(ManifestErrorCode.INVALID_SIGNATURE)
    try:
        signature = base64.b64decode(encoded, validate=True)
    except (ValueError, UnicodeError) as exc:
        raise ManifestError(ManifestErrorCode.INVALID_SIGNATURE) from exc

    modulus = int(UPDATE_SIGNING_RSA_MODULUS_HEX, 16)
    width = (modulus.bit_length() + 7) // 8
    if len(signature) != width:
        raise ManifestError(ManifestErrorCode.INVALID_SIGNATURE)
    signature_value = int.from_bytes(signature, "big")
    if signature_value >= modulus:
        raise ManifestError(ManifestErrorCode.INVALID_SIGNATURE)
    encoded_message = pow(
        signature_value,
        int(UPDATE_SIGNING_RSA_EXPONENT),
        modulus,
    ).to_bytes(width, "big")
    digest_info = _SHA256_DIGEST_INFO_PREFIX + hashlib.sha256(payload).digest()
    padding_length = width - len(digest_info) - 3
    expected = b"\x00\x01" + b"\xff" * padding_length + b"\x00" + digest_info
    if padding_length < 8 or not hmac.compare_digest(encoded_message, expected):
        raise ManifestError(ManifestErrorCode.INVALID_SIGNATURE)


def parse_signed_manifest(
    payload: bytes | bytearray | memoryview,
    signature_text: bytes | str,
) -> UpdateManifest:
    raw = bytes(payload)
    verify_manifest_signature(raw, signature_text)
    return _parse_manifest_payload(raw)


def _parse_manifest_payload(raw: bytes) -> UpdateManifest:
    """Parse already-authenticated bytes; kept separate for schema tests."""

    if len(raw) > MAX_MANIFEST_BYTES:
        raise ManifestError(ManifestErrorCode.TOO_LARGE)
    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ManifestError(ManifestErrorCode.INVALID_JSON) from exc

    root = _require_exact_keys(parsed, {
        "schema_version", "app_id", "channel", "version", "published_at",
        "update_protocol", "mandatory", "release_notes", "artifacts",
    })
    if (
        root["schema_version"] != 1
        or root["app_id"] != UPDATE_APP_ID
        or root["channel"] != UPDATE_CHANNEL
        or isinstance(root["update_protocol"], bool)
        or not isinstance(root["update_protocol"], int)
    ):
        raise ManifestError(ManifestErrorCode.INVALID_SCHEMA)
    protocol = int(root["update_protocol"])
    if protocol != UPDATE_PROTOCOL_VERSION:
        raise ManifestError(ManifestErrorCode.UNSUPPORTED_PROTOCOL)
    try:
        version = SemanticVersion.parse(root["version"])  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ManifestError(ManifestErrorCode.INVALID_SCHEMA) from exc
    if version.prerelease:
        raise ManifestError(ManifestErrorCode.INVALID_SCHEMA)
    published_at = root["published_at"]
    if not isinstance(published_at, str) or not _TIMESTAMP_RE.fullmatch(published_at):
        raise ManifestError(ManifestErrorCode.INVALID_SCHEMA)
    if not isinstance(root["mandatory"], bool):
        raise ManifestError(ManifestErrorCode.INVALID_SCHEMA)

    raw_notes = root["release_notes"]
    if not isinstance(raw_notes, dict) or not 1 <= len(raw_notes) <= 8:
        raise ManifestError(ManifestErrorCode.INVALID_SCHEMA)
    notes: list[tuple[str, str]] = []
    for locale, text in raw_notes.items():
        if (
            not isinstance(locale, str)
            or not re.fullmatch(r"[a-z]{2}_[A-Z]{2}", locale)
            or not isinstance(text, str)
            or len(text) > 32_000
        ):
            raise ManifestError(ManifestErrorCode.INVALID_SCHEMA)
        notes.append((locale, text))

    raw_artifacts = root["artifacts"]
    if not isinstance(raw_artifacts, list) or not 1 <= len(raw_artifacts) <= 8:
        raise ManifestError(ManifestErrorCode.INVALID_SCHEMA)
    selected: UpdateArtifact | None = None
    for raw_artifact in raw_artifacts:
        item = _require_exact_keys(raw_artifact, {
            "platform", "architecture", "type", "filename", "size", "sha256", "urls",
        })
        if (
            item["platform"] != "windows"
            or item["architecture"] != "x86_64"
            or item["type"] != "pyinstaller-onefile"
        ):
            continue
        size = item["size"]
        digest = item["sha256"]
        urls = item["urls"]
        if (
            item["filename"] != EXPECTED_EXECUTABLE_NAME
            or isinstance(size, bool)
            or not isinstance(size, int)
            or not 1 <= size <= MAX_ARTIFACT_BYTES
            or not isinstance(digest, str)
            or not _SHA256_RE.fullmatch(digest)
            or not isinstance(urls, dict)
            or not 1 <= len(urls) <= 2
            or not set(urls).issubset({"github", "gitee"})
        ):
            raise ManifestError(ManifestErrorCode.INVALID_SCHEMA)
        normalized_urls = tuple(
            (source, _safe_download_url(url))
            for source, url in sorted(urls.items())
        )
        selected = UpdateArtifact(
            filename=EXPECTED_EXECUTABLE_NAME,
            size=int(size),
            sha256=digest,
            urls=normalized_urls,
        )
        break
    if selected is None:
        raise ManifestError(ManifestErrorCode.NO_WINDOWS_ARTIFACT)
    return UpdateManifest(
        version=version,
        published_at=published_at,
        mandatory=bool(root["mandatory"]),
        release_notes=tuple(sorted(notes)),
        artifact=selected,
        protocol=protocol,
    )


__all__ = [
    "EXPECTED_EXECUTABLE_NAME",
    "MAX_MANIFEST_BYTES",
    "MAX_SIGNATURE_BYTES",
    "ManifestError",
    "ManifestErrorCode",
    "UpdateArtifact",
    "UpdateManifest",
    "parse_signed_manifest",
    "verify_manifest_signature",
]
