"""Immutable application identity and release-surface policy.

Keeping these values outside the GUI prevents widgets from inventing repository
URLs or reading machine-local configuration when they only need public
application metadata.
"""

from __future__ import annotations


APP_NAME = "BDO Music Composer"
APP_VERSION = "1.1.0"
WINDOWS_APP_USER_MODEL_ID = "CocoaMist.BDOMusicComposer.1"

# The implementation and catalog remain available for internal validation.
# Enabling a public entry is a deliberate release-policy change, not a user
# setting or an environment-dependent behavior.
RELEASE_NOTES_UI_ENABLED = False

GITHUB_OWNER = "CocoaMist"
GITHUB_REPOSITORY = "3007-BDO_Music_Composer"
GITHUB_API_VERSION = "2026-03-10"

GITHUB_REPOSITORY_URL = (
    f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPOSITORY}"
)
GITHUB_RELEASES_URL = f"{GITHUB_REPOSITORY_URL}/releases"
GITHUB_LATEST_RELEASE_API_URL = (
    "https://api.github.com/repos/"
    f"{GITHUB_OWNER}/{GITHUB_REPOSITORY}/releases/latest"
)


__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "GITHUB_API_VERSION",
    "GITHUB_LATEST_RELEASE_API_URL",
    "GITHUB_OWNER",
    "GITHUB_RELEASES_URL",
    "GITHUB_REPOSITORY",
    "GITHUB_REPOSITORY_URL",
    "RELEASE_NOTES_UI_ENABLED",
    "WINDOWS_APP_USER_MODEL_ID",
]
