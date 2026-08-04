from __future__ import annotations

import json
import unittest

from bdo_music_composer.app.application_metadata import (
    APP_VERSION,
    GITHUB_LATEST_RELEASE_API_URL,
    GITHUB_RELEASES_URL,
    RELEASE_NOTES_UI_ENABLED,
    WINDOWS_APP_USER_MODEL_ID,
)
from bdo_music_composer.app.update_check import (
    MAX_RELEASE_BODY_CHARS,
    MAX_RESPONSE_BYTES,
    SemanticVersion,
    UpdateCheckError,
    UpdateErrorCode,
    UpdateStatus,
    classify_http_error,
    github_request_headers,
    parse_latest_release_payload,
    safe_release_url,
)


def _payload(
    tag: str = "v1.1.0",
    *,
    draft: bool = False,
    prerelease: bool = False,
    body: str = "release notes",
) -> bytes:
    return json.dumps(
        {
            "tag_name": tag,
            "name": f"Release {tag}",
            "body": body,
            "draft": draft,
            "prerelease": prerelease,
            "published_at": "2026-07-31T08:00:00Z",
            # This must never become the presented release URL.
            "html_url": "https://attacker.invalid/download",
        }
    ).encode()


class SemanticVersionTests(unittest.TestCase):
    def test_strict_semver_rejects_noncanonical_values(self) -> None:
        invalid = (
            "v1.2.3",
            "1.2",
            "01.2.3",
            "1.02.3",
            "1.2.03",
            "1.2.3-01",
            "1.2.3-",
            "1.2.3+",
            " 1.2.3",
            "１.２.３",
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    SemanticVersion.parse(value)

    def test_semver_precedence_matches_semver_2(self) -> None:
        ordered = [
            "1.0.0-alpha",
            "1.0.0-alpha.1",
            "1.0.0-alpha.beta",
            "1.0.0-beta",
            "1.0.0-beta.2",
            "1.0.0-beta.11",
            "1.0.0-rc.1",
            "1.0.0",
        ]
        parsed = [SemanticVersion.parse(value) for value in ordered]
        self.assertEqual(parsed, sorted(reversed(parsed)))
        self.assertEqual(
            SemanticVersion.parse("1.0.0+build.1"),
            SemanticVersion.parse("1.0.0+build.2"),
        )


class UpdatePayloadTests(unittest.TestCase):
    def test_metadata_is_fixed_to_public_project(self) -> None:
        self.assertEqual(APP_VERSION, "1.1.0")
        self.assertFalse(RELEASE_NOTES_UI_ENABLED)
        self.assertEqual(
            WINDOWS_APP_USER_MODEL_ID,
            "CocoaMist.BDOMusicComposer.1",
        )
        self.assertEqual(
            GITHUB_LATEST_RELEASE_API_URL,
            "https://api.github.com/repos/"
            "CocoaMist/3007-BDO_Music_Composer/releases/latest",
        )
        self.assertEqual(
            GITHUB_RELEASES_URL,
            "https://github.com/CocoaMist/3007-BDO_Music_Composer/releases",
        )

    def test_parses_stable_release_and_ignores_untrusted_url(self) -> None:
        result = parse_latest_release_payload(_payload(), "1.0.0")
        self.assertEqual(result.status, UpdateStatus.UPDATE)
        self.assertEqual(str(result.release.version), "1.1.0")
        self.assertEqual(
            result.release.release_url,
            f"{GITHUB_RELEASES_URL}/tag/v1.1.0",
        )
        self.assertNotIn("attacker", result.release.release_url)

    def test_reports_current_and_local_ahead(self) -> None:
        current = parse_latest_release_payload(_payload("v1.0.0"), "1.0.0")
        ahead = parse_latest_release_payload(_payload("v1.0.0"), "1.1.0")
        self.assertEqual(current.status, UpdateStatus.CURRENT)
        self.assertEqual(ahead.status, UpdateStatus.LOCAL_AHEAD)

    def test_rejects_draft_prerelease_and_prerelease_tag(self) -> None:
        samples = (
            _payload(draft=True),
            _payload(prerelease=True),
            _payload("v1.1.0-rc.1"),
        )
        for sample in samples:
            with self.subTest(sample=sample):
                with self.assertRaises(UpdateCheckError) as raised:
                    parse_latest_release_payload(sample)
                self.assertEqual(
                    raised.exception.code,
                    UpdateErrorCode.NO_STABLE_RELEASE,
                )

    def test_rejects_oversize_invalid_and_duplicate_key_payloads(self) -> None:
        with self.assertRaises(UpdateCheckError) as raised:
            parse_latest_release_payload(b" " * (MAX_RESPONSE_BYTES + 1))
        self.assertEqual(
            raised.exception.code,
            UpdateErrorCode.PAYLOAD_TOO_LARGE,
        )
        invalid_samples = (
            b"[]",
            b"{",
            b'{"tag_name":"v1.0.0","tag_name":"v2.0.0"}',
            json.dumps(
                {
                    "tag_name": "v1.0.0",
                    "draft": False,
                    "prerelease": False,
                    "published_at": "not-a-date",
                }
            ).encode(),
        )
        for sample in invalid_samples:
            with self.subTest(sample=sample):
                with self.assertRaises(UpdateCheckError) as invalid:
                    parse_latest_release_payload(sample)
                self.assertEqual(
                    invalid.exception.code,
                    UpdateErrorCode.INVALID_PAYLOAD,
                )

    def test_rejects_deeply_nested_json_as_invalid_payload(self) -> None:
        depth = 5_000
        payload = ("[" * depth + "0" + "]" * depth).encode("ascii")
        self.assertLess(len(payload), MAX_RESPONSE_BYTES)

        with self.assertRaises(UpdateCheckError) as raised:
            parse_latest_release_payload(payload)

        self.assertEqual(
            raised.exception.code,
            UpdateErrorCode.INVALID_PAYLOAD,
        )
        self.assertIsInstance(raised.exception.__cause__, RecursionError)

    def test_release_body_is_bounded_after_bounded_json_parse(self) -> None:
        result = parse_latest_release_payload(
            _payload(body="x" * (MAX_RELEASE_BODY_CHARS + 100))
        )
        self.assertEqual(len(result.release.body), MAX_RELEASE_BODY_CHARS)

    def test_request_headers_are_public_and_versioned(self) -> None:
        headers = github_request_headers()
        self.assertEqual(headers["Accept"], "application/vnd.github+json")
        self.assertEqual(headers["X-GitHub-Api-Version"], "2026-03-10")
        self.assertEqual(headers["User-Agent"], "BDO-Music-Composer/1.1.0")
        self.assertNotIn("Authorization", headers)
        self.assertNotIn("Owner", " ".join(headers))

    def test_safe_url_and_http_error_classification(self) -> None:
        self.assertEqual(
            safe_release_url("v2.3.4"),
            f"{GITHUB_RELEASES_URL}/tag/v2.3.4",
        )
        self.assertEqual(
            classify_http_error(403, "0"),
            UpdateErrorCode.RATE_LIMITED,
        )
        self.assertEqual(
            classify_http_error(429),
            UpdateErrorCode.RATE_LIMITED,
        )
        self.assertEqual(
            classify_http_error(404),
            UpdateErrorCode.NOT_FOUND,
        )
        self.assertEqual(
            classify_http_error(410),
            UpdateErrorCode.API_VERSION_UNSUPPORTED,
        )
        self.assertEqual(
            classify_http_error(500),
            UpdateErrorCode.HTTP_ERROR,
        )


if __name__ == "__main__":
    unittest.main()
