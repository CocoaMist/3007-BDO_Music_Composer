"""Pure, bounded parsing for the latest stable GitHub release.

This module intentionally has no Qt, filesystem, authentication, download, or
process-execution dependencies.  The transport supplies one bounded response;
this layer validates it and constructs links only from the fixed repository
identity in :mod:`application_metadata`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import total_ordering
import json
import re
from typing import Mapping
from urllib.parse import quote

from bdo_music_composer.app.application_metadata import (
    APP_NAME,
    APP_VERSION,
    GITHUB_API_VERSION,
    GITHUB_RELEASES_URL,
)


MAX_RESPONSE_BYTES = 512 * 1024
MAX_RELEASE_BODY_CHARS = 32_000
MAX_RELEASE_NAME_CHARS = 240
MAX_TAG_CHARS = 96

_SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$",
    re.ASCII,
)
_PUBLISHED_AT_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z$",
    re.ASCII,
)


class UpdateStatus(str, Enum):
    """Relationship between the local build and GitHub's stable release."""

    UPDATE = "update"
    CURRENT = "current"
    LOCAL_AHEAD = "local_ahead"


class UpdateErrorCode(str, Enum):
    """Stable error categories suitable for localized presentation."""

    PAYLOAD_TOO_LARGE = "payload_too_large"
    INVALID_PAYLOAD = "invalid_payload"
    NO_STABLE_RELEASE = "no_stable_release"
    RATE_LIMITED = "rate_limited"
    NOT_FOUND = "not_found"
    API_VERSION_UNSUPPORTED = "api_version_unsupported"
    TIMEOUT = "timeout"
    TLS_ERROR = "tls_error"
    NETWORK_ERROR = "network_error"
    HTTP_ERROR = "http_error"
    CANCELLED = "cancelled"
    SELF_TEST_DISABLED = "self_test_disabled"


class UpdateCheckError(ValueError):
    """Typed update-check failure without retaining response contents."""

    def __init__(
        self,
        code: UpdateErrorCode,
        message: str = "",
        *,
        http_status: int | None = None,
    ) -> None:
        self.code = UpdateErrorCode(code)
        self.http_status = http_status
        super().__init__(message or self.code.value)


@total_ordering
@dataclass(frozen=True, slots=True, eq=False)
class SemanticVersion:
    """Strict SemVer 2.0.0 value with precedence-aware comparisons."""

    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()
    build: tuple[str, ...] = ()

    @classmethod
    def parse(cls, value: str) -> "SemanticVersion":
        if not isinstance(value, str):
            raise ValueError("semantic version must be text")
        matched = _SEMVER_RE.fullmatch(value)
        if matched is None:
            raise ValueError("invalid semantic version")
        prerelease = tuple((matched.group(4) or "").split("."))
        if prerelease == ("",):
            prerelease = ()
        if any(
            identifier.isascii()
            and identifier.isdigit()
            and len(identifier) > 1
            and identifier.startswith("0")
            for identifier in prerelease
        ):
            raise ValueError("numeric prerelease identifiers cannot have leading zeroes")
        build = tuple((matched.group(5) or "").split("."))
        if build == ("",):
            build = ()
        return cls(
            major=int(matched.group(1)),
            minor=int(matched.group(2)),
            patch=int(matched.group(3)),
            prerelease=prerelease,
            build=build,
        )

    def compare_precedence(self, other: "SemanticVersion") -> int:
        if not isinstance(other, SemanticVersion):
            raise TypeError("version comparison requires SemanticVersion")
        local_core = (self.major, self.minor, self.patch)
        remote_core = (other.major, other.minor, other.patch)
        if local_core != remote_core:
            return 1 if local_core > remote_core else -1
        if not self.prerelease and not other.prerelease:
            return 0
        if not self.prerelease:
            return 1
        if not other.prerelease:
            return -1
        for local_identifier, remote_identifier in zip(
            self.prerelease,
            other.prerelease,
        ):
            if local_identifier == remote_identifier:
                continue
            local_numeric = local_identifier.isdigit()
            remote_numeric = remote_identifier.isdigit()
            if local_numeric and remote_numeric:
                return 1 if int(local_identifier) > int(remote_identifier) else -1
            if local_numeric != remote_numeric:
                return -1 if local_numeric else 1
            return 1 if local_identifier > remote_identifier else -1
        if len(self.prerelease) == len(other.prerelease):
            return 0
        return 1 if len(self.prerelease) > len(other.prerelease) else -1

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, SemanticVersion)
            and self.compare_precedence(other) == 0
        )

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemanticVersion):
            return NotImplemented
        return self.compare_precedence(other) < 0

    def __hash__(self) -> int:
        return hash((self.major, self.minor, self.patch, self.prerelease))

    def __str__(self) -> str:
        value = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            value += f"-{'.'.join(self.prerelease)}"
        if self.build:
            value += f"+{'.'.join(self.build)}"
        return value


@dataclass(frozen=True, slots=True)
class ReleaseInfo:
    """Validated metadata for one stable GitHub release."""

    version: SemanticVersion
    tag_name: str
    name: str
    body: str
    published_at: str | None
    release_url: str


@dataclass(frozen=True, slots=True)
class UpdateResult:
    """One deterministic comparison against the current application version."""

    status: UpdateStatus
    current_version: SemanticVersion
    release: ReleaseInfo


def _stable_version_from_tag(tag_name: str) -> SemanticVersion:
    if not isinstance(tag_name, str) or not tag_name or len(tag_name) > MAX_TAG_CHARS:
        raise UpdateCheckError(UpdateErrorCode.INVALID_PAYLOAD)
    semantic_text = tag_name[1:] if tag_name.startswith("v") else tag_name
    try:
        version = SemanticVersion.parse(semantic_text)
    except ValueError as exc:
        raise UpdateCheckError(UpdateErrorCode.INVALID_PAYLOAD) from exc
    if version.prerelease:
        raise UpdateCheckError(UpdateErrorCode.NO_STABLE_RELEASE)
    return version


def safe_release_url(tag_name: str) -> str:
    """Build a release URL from the fixed repository and a validated tag."""

    _stable_version_from_tag(tag_name)
    return f"{GITHUB_RELEASES_URL}/tag/{quote(tag_name, safe='')}"


def github_request_headers(
    current_version: str = APP_VERSION,
) -> dict[str, str]:
    """Return public GitHub API headers; authentication is never added."""

    SemanticVersion.parse(current_version)
    user_agent_name = APP_NAME.replace(" ", "-")
    return {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{user_agent_name}/{current_version}",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }


def classify_http_error(
    status_code: int,
    rate_limit_remaining: str | int | None = None,
) -> UpdateErrorCode:
    """Map transport details to a stable, non-sensitive presentation code."""

    try:
        remaining = int(rate_limit_remaining)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        remaining = None
    if status_code == 429 or status_code == 403 and remaining in {None, 0}:
        return UpdateErrorCode.RATE_LIMITED
    if status_code == 404:
        return UpdateErrorCode.NOT_FOUND
    if status_code == 410:
        return UpdateErrorCode.API_VERSION_UNSUPPORTED
    return UpdateErrorCode.HTTP_ERROR


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _decode_payload(
    payload: bytes | bytearray | memoryview | str,
    *,
    max_response_bytes: int,
) -> dict[str, object]:
    if max_response_bytes <= 0:
        raise ValueError("max_response_bytes must be positive")
    if isinstance(payload, str):
        try:
            encoded = payload.encode("utf-8")
        except UnicodeError as exc:
            raise UpdateCheckError(UpdateErrorCode.INVALID_PAYLOAD) from exc
    elif isinstance(payload, (bytes, bytearray, memoryview)):
        encoded = bytes(payload)
    else:
        raise UpdateCheckError(UpdateErrorCode.INVALID_PAYLOAD)
    if len(encoded) > max_response_bytes:
        raise UpdateCheckError(UpdateErrorCode.PAYLOAD_TOO_LARGE)
    try:
        decoded = encoded.decode("utf-8")
        parsed = json.loads(decoded, object_pairs_hook=_unique_object)
    except (
        UnicodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as exc:
        raise UpdateCheckError(UpdateErrorCode.INVALID_PAYLOAD) from exc
    if not isinstance(parsed, dict):
        raise UpdateCheckError(UpdateErrorCode.INVALID_PAYLOAD)
    return parsed


def parse_latest_release_payload(
    payload: bytes | bytearray | memoryview | str,
    current_version: str = APP_VERSION,
    *,
    max_response_bytes: int = MAX_RESPONSE_BYTES,
) -> UpdateResult:
    """Validate one HTTP-200 ``releases/latest`` payload and compare versions."""

    parsed = _decode_payload(payload, max_response_bytes=max_response_bytes)
    if parsed.get("draft") is not False or parsed.get("prerelease") is not False:
        raise UpdateCheckError(UpdateErrorCode.NO_STABLE_RELEASE)

    tag_name = parsed.get("tag_name")
    version = _stable_version_from_tag(tag_name)  # type: ignore[arg-type]
    try:
        local_version = SemanticVersion.parse(current_version)
    except ValueError as exc:
        raise UpdateCheckError(UpdateErrorCode.INVALID_PAYLOAD) from exc

    name = parsed.get("name")
    if name is None or name == "":
        name = tag_name
    if not isinstance(name, str) or len(name) > MAX_RELEASE_NAME_CHARS:
        raise UpdateCheckError(UpdateErrorCode.INVALID_PAYLOAD)

    body = parsed.get("body")
    if body is None:
        body = ""
    if not isinstance(body, str):
        raise UpdateCheckError(UpdateErrorCode.INVALID_PAYLOAD)
    body = body[:MAX_RELEASE_BODY_CHARS]

    published_at = parsed.get("published_at")
    if published_at is not None and (
        not isinstance(published_at, str)
        or _PUBLISHED_AT_RE.fullmatch(published_at) is None
    ):
        raise UpdateCheckError(UpdateErrorCode.INVALID_PAYLOAD)

    release = ReleaseInfo(
        version=version,
        tag_name=tag_name,  # type: ignore[arg-type]
        name=name,
        body=body,
        published_at=published_at,
        release_url=safe_release_url(tag_name),  # type: ignore[arg-type]
    )
    precedence = version.compare_precedence(local_version)
    if precedence > 0:
        status = UpdateStatus.UPDATE
    elif precedence == 0:
        status = UpdateStatus.CURRENT
    else:
        status = UpdateStatus.LOCAL_AHEAD
    return UpdateResult(
        status=status,
        current_version=local_version,
        release=release,
    )


__all__ = [
    "MAX_RELEASE_BODY_CHARS",
    "MAX_RESPONSE_BYTES",
    "ReleaseInfo",
    "SemanticVersion",
    "UpdateCheckError",
    "UpdateErrorCode",
    "UpdateResult",
    "UpdateStatus",
    "classify_http_error",
    "github_request_headers",
    "parse_latest_release_payload",
    "safe_release_url",
]
