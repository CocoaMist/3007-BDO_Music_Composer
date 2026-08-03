"""Bounded, Qt-free loading for the packaged release-notes catalog."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import re
from typing import Any, NoReturn

from bdo_music_composer.core.project_paths import RELEASE_NOTES_PATH


RELEASE_NOTES_SCHEMA_VERSION = 1
RELEASE_NOTES_MAX_BYTES = 256 * 1024
RELEASE_NOTES_MAX_RELEASES = 64
RELEASE_NOTES_MAX_LOCALES = 5
RELEASE_NOTES_MAX_HIGHLIGHTS = 12
RELEASE_NOTES_MAX_TITLE_CHARS = 120
RELEASE_NOTES_MAX_SUMMARY_CHARS = 800
RELEASE_NOTES_MAX_HIGHLIGHT_CHARS = 300
RELEASE_NOTES_MAX_VERSION_CHARS = 64

SUPPORTED_RELEASE_NOTE_LOCALES = (
    "zh_CN",
    "zh_TW",
    "en_US",
    "ja_JP",
    "ko_KR",
)

_SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


class ReleaseNotesError(ValueError):
    """Raised when the local release-notes resource violates its contract."""

    def __init__(self, code: str, message: str, *, location: str = "$") -> None:
        self.code = code
        self.location = location
        super().__init__(f"{code} at {location}: {message}")


@dataclass(frozen=True, slots=True)
class LocalizedReleaseNotes:
    """One immutable, presentation-ready locale variant."""

    locale: str
    title: str
    summary: str
    highlights: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReleaseNotesSection:
    """A localized section without a published version or date."""

    contents: tuple[LocalizedReleaseNotes, ...]

    def localized(self, locale: str) -> LocalizedReleaseNotes:
        return _select_localized(self.contents, locale)


@dataclass(frozen=True, slots=True)
class ReleaseNotesEntry:
    """One published release, ordered by semantic-version precedence."""

    version: str
    release_date: date
    status: str
    contents: tuple[LocalizedReleaseNotes, ...]

    @property
    def is_prerelease(self) -> bool:
        return self.status == "prerelease"

    def localized(self, locale: str) -> LocalizedReleaseNotes:
        return _select_localized(self.contents, locale)


@dataclass(frozen=True, slots=True)
class ReleaseNotesDocument:
    """Validated release history plus optional source-development notes."""

    schema_version: int
    releases: tuple[ReleaseNotesEntry, ...]
    development: ReleaseNotesSection | None = None

    @property
    def latest(self) -> ReleaseNotesEntry:
        return self.releases[0]

    @property
    def latest_stable(self) -> ReleaseNotesEntry | None:
        return next(
            (release for release in self.releases if not release.is_prerelease),
            None,
        )


def _fail(code: str, message: str, *, location: str) -> NoReturn:
    raise ReleaseNotesError(code, message, location=location)


def _expect_object(value: object, *, location: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        _fail("invalid_schema", "expected an object", location=location)
    if any(not isinstance(key, str) for key in value):
        _fail("invalid_schema", "object keys must be strings", location=location)
    return value


def _expect_exact_keys(
    value: Mapping[str, object],
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
    location: str,
) -> None:
    keys = frozenset(value)
    missing = required - keys
    unknown = keys - required - optional
    if missing:
        _fail(
            "invalid_schema",
            f"missing fields: {', '.join(sorted(missing))}",
            location=location,
        )
    if unknown:
        _fail(
            "invalid_schema",
            f"unknown fields: {', '.join(sorted(unknown))}",
            location=location,
        )


def _expect_text(
    value: object,
    *,
    maximum: int,
    location: str,
) -> str:
    if not isinstance(value, str):
        _fail("invalid_text", "expected a string", location=location)
    if not value or value != value.strip():
        _fail(
            "invalid_text",
            "text must be non-empty without surrounding whitespace",
            location=location,
        )
    if len(value) > maximum:
        _fail(
            "invalid_text",
            f"text exceeds {maximum} characters",
            location=location,
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        _fail("invalid_text", "control characters are not allowed", location=location)
    return value


def _normalize_locale(locale: str) -> str:
    normalized = str(locale or "").replace("-", "_")
    parts = normalized.split("_", 1)
    if len(parts) == 2 and parts[0] and parts[1]:
        return f"{parts[0].lower()}_{parts[1].upper()}"
    return normalized


def _select_localized(
    contents: tuple[LocalizedReleaseNotes, ...],
    requested_locale: str,
) -> LocalizedReleaseNotes:
    by_locale = {content.locale: content for content in contents}
    candidates = (_normalize_locale(requested_locale), "en_US", "zh_CN")
    for locale in dict.fromkeys(candidates):
        content = by_locale.get(locale)
        if content is not None:
            return content
    # The loader requires zh_CN, so this protects manually constructed objects.
    raise ReleaseNotesError(
        "missing_fallback_locale",
        "no requested, English, or Simplified Chinese content is available",
        location="locales",
    )


def _parse_localized_content(
    locale: str,
    value: object,
    *,
    location: str,
) -> LocalizedReleaseNotes:
    content = _expect_object(value, location=location)
    _expect_exact_keys(
        content,
        required=frozenset(("title", "summary", "highlights")),
        location=location,
    )
    highlights_value = content["highlights"]
    if not isinstance(highlights_value, list):
        _fail("invalid_schema", "highlights must be an array", location=location)
    if not 1 <= len(highlights_value) <= RELEASE_NOTES_MAX_HIGHLIGHTS:
        _fail(
            "invalid_count",
            "highlight count is outside the supported range",
            location=f"{location}.highlights",
        )
    highlights = tuple(
        _expect_text(
            item,
            maximum=RELEASE_NOTES_MAX_HIGHLIGHT_CHARS,
            location=f"{location}.highlights[{index}]",
        )
        for index, item in enumerate(highlights_value)
    )
    return LocalizedReleaseNotes(
        locale=locale,
        title=_expect_text(
            content["title"],
            maximum=RELEASE_NOTES_MAX_TITLE_CHARS,
            location=f"{location}.title",
        ),
        summary=_expect_text(
            content["summary"],
            maximum=RELEASE_NOTES_MAX_SUMMARY_CHARS,
            location=f"{location}.summary",
        ),
        highlights=highlights,
    )


def _parse_locales(value: object, *, location: str) -> tuple[LocalizedReleaseNotes, ...]:
    locales = _expect_object(value, location=location)
    if not 1 <= len(locales) <= RELEASE_NOTES_MAX_LOCALES:
        _fail(
            "invalid_count",
            "locale count is outside the supported range",
            location=location,
        )

    parsed: dict[str, LocalizedReleaseNotes] = {}
    for raw_locale, raw_content in locales.items():
        locale = _normalize_locale(raw_locale)
        if locale not in SUPPORTED_RELEASE_NOTE_LOCALES:
            _fail(
                "invalid_locale",
                f"unsupported locale {raw_locale!r}",
                location=location,
            )
        if locale in parsed:
            _fail(
                "duplicate_locale",
                f"duplicate normalized locale {locale}",
                location=location,
            )
        parsed[locale] = _parse_localized_content(
            locale,
            raw_content,
            location=f"{location}.{raw_locale}",
        )
    if "zh_CN" not in parsed:
        _fail(
            "missing_fallback_locale",
            "zh_CN content is required",
            location=location,
        )
    return tuple(
        parsed[locale]
        for locale in SUPPORTED_RELEASE_NOTE_LOCALES
        if locale in parsed
    )


def _parse_semver(
    value: object,
    *,
    location: str,
) -> tuple[
    tuple[int, int, int, int, tuple[tuple[int, int | str], ...]],
    tuple[int, int, int, tuple[str, ...]],
    bool,
]:
    version = _expect_text(
        value,
        maximum=RELEASE_NOTES_MAX_VERSION_CHARS,
        location=location,
    )
    match = _SEMVER_PATTERN.fullmatch(version)
    if match is None:
        _fail("invalid_version", "expected a semantic version", location=location)
    major, minor, patch = (int(match.group(index)) for index in range(1, 4))
    prerelease_text = match.group(4)
    prerelease = tuple(prerelease_text.split(".")) if prerelease_text else ()
    if any(
        identifier.isdigit()
        and len(identifier) > 1
        and identifier.startswith("0")
        for identifier in prerelease
    ):
        _fail(
            "invalid_version",
            "numeric prerelease identifiers cannot contain leading zeroes",
            location=location,
        )
    prerelease_key = tuple(
        (0, int(identifier)) if identifier.isdigit() else (1, identifier)
        for identifier in prerelease
    )
    sort_key = (
        major,
        minor,
        patch,
        0 if prerelease else 1,
        prerelease_key,
    )
    identity = (major, minor, patch, prerelease)
    return sort_key, identity, bool(prerelease)


def _parse_release(value: object, *, index: int) -> tuple[
    ReleaseNotesEntry,
    tuple[int, int, int, int, tuple[tuple[int, int | str], ...]],
    tuple[int, int, int, tuple[str, ...]],
]:
    location = f"$.releases[{index}]"
    release = _expect_object(value, location=location)
    _expect_exact_keys(
        release,
        required=frozenset(("version", "date", "status", "locales")),
        location=location,
    )
    version = _expect_text(
        release["version"],
        maximum=RELEASE_NOTES_MAX_VERSION_CHARS,
        location=f"{location}.version",
    )
    sort_key, identity, has_prerelease = _parse_semver(
        version,
        location=f"{location}.version",
    )
    date_text = _expect_text(
        release["date"],
        maximum=10,
        location=f"{location}.date",
    )
    try:
        release_date = date.fromisoformat(date_text)
    except ValueError:
        _fail("invalid_date", "expected an ISO calendar date", location=f"{location}.date")
    if release_date.isoformat() != date_text:
        _fail("invalid_date", "expected YYYY-MM-DD", location=f"{location}.date")

    status = _expect_text(
        release["status"],
        maximum=16,
        location=f"{location}.status",
    )
    if status not in {"stable", "prerelease"}:
        _fail(
            "invalid_status",
            "status must be stable or prerelease",
            location=f"{location}.status",
        )
    if has_prerelease != (status == "prerelease"):
        _fail(
            "invalid_status",
            "status must agree with semantic-version prerelease metadata",
            location=f"{location}.status",
        )

    return (
        ReleaseNotesEntry(
            version=version,
            release_date=release_date,
            status=status,
            contents=_parse_locales(
                release["locales"],
                location=f"{location}.locales",
            ),
        ),
        sort_key,
        identity,
    )


def parse_release_notes(value: object) -> ReleaseNotesDocument:
    """Validate decoded JSON data and return a deeply immutable document."""

    document = _expect_object(value, location="$")
    _expect_exact_keys(
        document,
        required=frozenset(("schema_version", "releases")),
        optional=frozenset(("development",)),
        location="$",
    )
    schema_version = document["schema_version"]
    if type(schema_version) is not int or schema_version != RELEASE_NOTES_SCHEMA_VERSION:
        _fail(
            "unsupported_schema",
            f"expected schema {RELEASE_NOTES_SCHEMA_VERSION}",
            location="$.schema_version",
        )

    releases_value = document["releases"]
    if not isinstance(releases_value, list):
        _fail("invalid_schema", "releases must be an array", location="$.releases")
    if not 1 <= len(releases_value) <= RELEASE_NOTES_MAX_RELEASES:
        _fail(
            "invalid_count",
            "release count is outside the supported range",
            location="$.releases",
        )

    parsed_releases = [
        _parse_release(value, index=index)
        for index, value in enumerate(releases_value)
    ]
    identities: set[tuple[int, int, int, tuple[str, ...]]] = set()
    for _release, _sort_key, identity in parsed_releases:
        if identity in identities:
            _fail(
                "duplicate_version",
                "release versions must have unique semantic precedence",
                location="$.releases",
            )
        identities.add(identity)
    parsed_releases.sort(key=lambda item: item[1], reverse=True)

    development_value = document.get("development")
    development: ReleaseNotesSection | None = None
    if development_value is not None:
        development_object = _expect_object(
            development_value,
            location="$.development",
        )
        _expect_exact_keys(
            development_object,
            required=frozenset(("locales",)),
            location="$.development",
        )
        development = ReleaseNotesSection(
            contents=_parse_locales(
                development_object["locales"],
                location="$.development.locales",
            )
        )

    return ReleaseNotesDocument(
        schema_version=schema_version,
        releases=tuple(item[0] for item in parsed_releases),
        development=development,
    )


def load_release_notes(
    path: str | Path = RELEASE_NOTES_PATH,
) -> ReleaseNotesDocument:
    """Load one bounded UTF-8 JSON catalog from a source or frozen resource."""

    resource_path = Path(path)
    try:
        if resource_path.stat().st_size > RELEASE_NOTES_MAX_BYTES:
            _fail(
                "resource_too_large",
                f"resource exceeds {RELEASE_NOTES_MAX_BYTES} bytes",
                location=str(resource_path),
            )
        with resource_path.open("rb") as stream:
            payload = stream.read(RELEASE_NOTES_MAX_BYTES + 1)
    except ReleaseNotesError:
        raise
    except OSError as exc:
        raise ReleaseNotesError(
            "resource_unavailable",
            "release-notes resource could not be read",
            location=str(resource_path),
        ) from exc
    if len(payload) > RELEASE_NOTES_MAX_BYTES:
        _fail(
            "resource_too_large",
            f"resource exceeds {RELEASE_NOTES_MAX_BYTES} bytes",
            location=str(resource_path),
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseNotesError(
            "invalid_utf8",
            "release-notes resource must be UTF-8",
            location=str(resource_path),
        ) from exc
    try:
        decoded: Any = json.loads(text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ReleaseNotesError(
            "invalid_json",
            "release-notes resource is not valid JSON",
            location=str(resource_path),
        ) from exc
    return parse_release_notes(decoded)
