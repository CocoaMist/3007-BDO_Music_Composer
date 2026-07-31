from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

from bdo_music_composer.app.release_notes import (
    RELEASE_NOTES_MAX_BYTES,
    RELEASE_NOTES_MAX_HIGHLIGHTS,
    RELEASE_NOTES_MAX_RELEASES,
    RELEASE_NOTES_MAX_TITLE_CHARS,
    SUPPORTED_RELEASE_NOTE_LOCALES,
    ReleaseNotesError,
    load_release_notes,
    parse_release_notes,
)


def _locale_content(title: str = "标题") -> dict[str, object]:
    return {
        "title": title,
        "summary": "简洁摘要",
        "highlights": ["第一项"],
    }


def _release(
    version: str = "1.0.0",
    *,
    status: str = "stable",
    release_date: str = "2026-07-29",
    locales: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "version": version,
        "date": release_date,
        "status": status,
        "locales": locales or {"zh_CN": _locale_content()},
    }


def _document(
    releases: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "releases": releases or [_release()],
    }


def _synthetic_catalog() -> dict[str, object]:
    stable_locales = {
        locale: _locale_content(f"Stable record {locale}")
        for locale in SUPPORTED_RELEASE_NOTE_LOCALES
    }
    development_locales = {
        locale: _locale_content(f"Development record {locale}")
        for locale in SUPPORTED_RELEASE_NOTE_LOCALES
    }
    payload = _document([_release(locales=stable_locales)])
    payload["development"] = {"locales": development_locales}
    return payload


class ReleaseNotesTests(unittest.TestCase):
    def _load_payload(self, payload: object):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "release_notes.json"
            path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            return load_release_notes(path)

    def _assert_parse_error(self, payload: object, code: str) -> None:
        with self.assertRaises(ReleaseNotesError) as context:
            parse_release_notes(payload)
        self.assertEqual(code, context.exception.code)

    def test_synthetic_catalog_is_complete_immutable_and_localized(self) -> None:
        document = parse_release_notes(_synthetic_catalog())

        self.assertEqual(1, document.schema_version)
        self.assertEqual(("1.0.0",), tuple(item.version for item in document.releases))
        self.assertEqual(date(2026, 7, 29), document.latest.release_date)
        self.assertEqual("stable", document.latest.status)
        self.assertEqual(
            SUPPORTED_RELEASE_NOTE_LOCALES,
            tuple(content.locale for content in document.latest.contents),
        )
        self.assertEqual(
            "Stable record zh_TW",
            document.latest.localized("zh-TW").title,
        )
        self.assertIs(document.latest, document.latest_stable)
        self.assertIsNotNone(document.development)
        assert document.development is not None
        self.assertEqual(
            "Development record en_US",
            document.development.localized("en_US").title,
        )
        self.assertIsInstance(document.latest.contents, tuple)
        self.assertIsInstance(document.latest.contents[0].highlights, tuple)

    def test_synthetic_catalog_stays_concise(self) -> None:
        document = parse_release_notes(_synthetic_catalog())
        entries = list(document.releases)
        if document.development is not None:
            entries.append(document.development)

        for entry in entries:
            for content in entry.contents:
                with self.subTest(entry=str(entry), locale=content.locale):
                    self.assertLessEqual(len(content.highlights), 3)
                    self.assertLessEqual(len(content.summary), 240)
        for release in document.releases:
            version = str(release.version)
            for content in release.contents:
                with self.subTest(version=version, locale=content.locale):
                    self.assertFalse(content.title.strip().startswith(version))
        with self.assertRaises(FrozenInstanceError):
            document.schema_version = 2  # type: ignore[misc]

    def test_locale_fallback_is_requested_then_english_then_chinese(self) -> None:
        locales = {
            "zh_CN": _locale_content("中文"),
            "en_US": _locale_content("English"),
            "ja_JP": _locale_content("日本語"),
        }
        document = self._load_payload(_document([_release(locales=locales)]))

        self.assertEqual("日本語", document.latest.localized("ja-JP").title)
        self.assertEqual("English", document.latest.localized("fr_FR").title)

        chinese_only = self._load_payload(_document())
        self.assertEqual("标题", chinese_only.latest.localized("fr_FR").title)

    def test_semantic_versions_are_sorted_by_precedence(self) -> None:
        document = self._load_payload(
            _document(
                [
                    _release("1.9.0"),
                    _release("1.10.0-rc.2", status="prerelease"),
                    _release("1.10.0"),
                    _release("1.10.0-rc.10", status="prerelease"),
                ]
            )
        )

        self.assertEqual(
            ("1.10.0", "1.10.0-rc.10", "1.10.0-rc.2", "1.9.0"),
            tuple(release.version for release in document.releases),
        )
        self.assertEqual("1.10.0", document.latest_stable.version)

    def test_development_section_is_optional_data_for_the_consumer(self) -> None:
        payload = _document()
        payload["development"] = {
            "locales": {"zh_CN": _locale_content("开发中")}
        }
        with_development = self._load_payload(payload)
        without_development = self._load_payload(_document())

        self.assertEqual(
            "开发中",
            with_development.development.localized("zh_CN").title,
        )
        self.assertIsNone(without_development.development)

    def test_reader_rejects_oversized_invalid_or_missing_resources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            oversized = root / "oversized.json"
            oversized.write_bytes(b"x" * (RELEASE_NOTES_MAX_BYTES + 1))
            with self.assertRaises(ReleaseNotesError) as oversized_error:
                load_release_notes(oversized)
            self.assertEqual("resource_too_large", oversized_error.exception.code)

            invalid_utf8 = root / "invalid-utf8.json"
            invalid_utf8.write_bytes(b"\xff")
            with self.assertRaises(ReleaseNotesError) as utf8_error:
                load_release_notes(invalid_utf8)
            self.assertEqual("invalid_utf8", utf8_error.exception.code)

            invalid_json = root / "invalid.json"
            invalid_json.write_text("{", encoding="utf-8")
            with self.assertRaises(ReleaseNotesError) as json_error:
                load_release_notes(invalid_json)
            self.assertEqual("invalid_json", json_error.exception.code)

            with self.assertRaises(ReleaseNotesError) as missing_error:
                load_release_notes(root / "missing.json")
            self.assertEqual("resource_unavailable", missing_error.exception.code)

    def test_reader_rejects_deeply_nested_json_as_invalid_json(self) -> None:
        depth = 5_000
        payload = "[" * depth + "0" + "]" * depth
        self.assertLess(len(payload.encode("utf-8")), RELEASE_NOTES_MAX_BYTES)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deeply-nested.json"
            path.write_text(payload, encoding="utf-8")

            with self.assertRaises(ReleaseNotesError) as raised:
                load_release_notes(path)

        self.assertEqual("invalid_json", raised.exception.code)
        self.assertIsInstance(raised.exception.__cause__, RecursionError)

    def test_schema_version_and_exact_fields_are_validated(self) -> None:
        invalid_version = _document()
        invalid_version["schema_version"] = True
        self._assert_parse_error(invalid_version, "unsupported_schema")

        unknown_root = _document()
        unknown_root["unexpected"] = True
        self._assert_parse_error(unknown_root, "invalid_schema")

        unknown_release = _document()
        unknown_release["releases"][0]["unexpected"] = True
        self._assert_parse_error(unknown_release, "invalid_schema")

    def test_dates_versions_statuses_and_duplicates_are_validated(self) -> None:
        self._assert_parse_error(
            _document([_release(release_date="2026-02-30")]),
            "invalid_date",
        )
        self._assert_parse_error(
            _document([_release("01.0.0")]),
            "invalid_version",
        )
        self._assert_parse_error(
            _document([_release("1.0.0-01", status="prerelease")]),
            "invalid_version",
        )
        self._assert_parse_error(
            _document([_release("1.0.0-rc.1")]),
            "invalid_status",
        )
        self._assert_parse_error(
            _document(
                [
                    _release("1.0.0+build.1"),
                    _release("1.0.0+build.2"),
                ]
            ),
            "duplicate_version",
        )

    def test_release_highlight_and_text_limits_are_enforced(self) -> None:
        self._assert_parse_error(
            {"schema_version": 1, "releases": []},
            "invalid_count",
        )
        self._assert_parse_error(
            _document(
                [_release(f"1.0.{index}") for index in range(RELEASE_NOTES_MAX_RELEASES + 1)]
            ),
            "invalid_count",
        )

        too_many_highlights = _document()
        too_many_highlights["releases"][0]["locales"]["zh_CN"]["highlights"] = [
            f"项目 {index}"
            for index in range(RELEASE_NOTES_MAX_HIGHLIGHTS + 1)
        ]
        self._assert_parse_error(too_many_highlights, "invalid_count")

        long_title = _document()
        long_title["releases"][0]["locales"]["zh_CN"]["title"] = (
            "长" * (RELEASE_NOTES_MAX_TITLE_CHARS + 1)
        )
        self._assert_parse_error(long_title, "invalid_text")

    def test_locale_set_and_chinese_fallback_are_validated(self) -> None:
        self._assert_parse_error(
            _document([_release(locales={"fr_FR": _locale_content()})]),
            "invalid_locale",
        )
        self._assert_parse_error(
            _document([_release(locales={"en_US": _locale_content()})]),
            "missing_fallback_locale",
        )


if __name__ == "__main__":
    unittest.main()
