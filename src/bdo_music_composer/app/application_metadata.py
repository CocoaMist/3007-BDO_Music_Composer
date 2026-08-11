"""Immutable application identity and release-surface policy.

Keeping these values outside the GUI prevents widgets from inventing repository
URLs or reading machine-local configuration when they only need public
application metadata.
"""

from __future__ import annotations


APP_NAME = "BDO Music Composer"
APP_VERSION = "1.2.1"
WINDOWS_APP_USER_MODEL_ID = "CocoaMist.BDOMusicComposer.1"

# The implementation and catalog remain available for internal validation.
# Enabling a public entry is a deliberate release-policy change, not a user
# setting or an environment-dependent behavior.
RELEASE_NOTES_UI_ENABLED = False

# Self-update release identity.  GitHub and Gitee are mirrors of the same
# signed channel document; neither hosting provider is itself a trust root.
UPDATE_APP_ID = "CocoaMist.BDOMusicComposer"
UPDATE_PROTOCOL_VERSION = 1
UPDATE_CHANNEL = "stable"

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

GITEE_OWNER = "raionnyan"
GITEE_REPOSITORY = GITHUB_REPOSITORY
GITEE_REPOSITORY_URL = (
    f"https://gitee.com/{GITEE_OWNER}/{GITEE_REPOSITORY}"
)

GITHUB_UPDATE_CHANNEL_URL = (
    "https://raw.githubusercontent.com/"
    f"{GITHUB_OWNER}/{GITHUB_REPOSITORY}/master/updates/{UPDATE_CHANNEL}/"
    "update-manifest-v1.json"
)
GITEE_UPDATE_CHANNEL_URL = (
    f"{GITEE_REPOSITORY_URL}/raw/master/updates/{UPDATE_CHANNEL}/"
    "update-manifest-v1.json"
)

# RSA-3072 public key used only to verify detached SHA-256/PKCS#1 v1.5
# signatures over the exact update-manifest bytes.  The matching private key
# is release-operator material and must never enter this repository or a build.
UPDATE_SIGNING_RSA_EXPONENT = 65537
UPDATE_SIGNING_RSA_MODULUS_HEX = (
    "f5524b85a821cddfc738d43c304866af3e41a9caae3258721c3a64fca3c0da27"
    "88d42f8a47b6fc9db24437ab6d802173b9fb80343f222c0f5ffb783f12363f55"
    "43617e9f372031c7120150035a5beae27e6d749ea4a62f5015972f32dabb06c7"
    "ebffb0c3b98acce178567ca4b9af684829b49886e54cdf6299390110025e56bb"
    "b8a94cdbf2eb266831aaf5d47dc91f1a12c6c7c919637266ebb3cee2a5e562d0"
    "7631937ea445d25c76b0fe2319ec3ce2570a39c77fd1f4e560afa2119f7b9867"
    "b48497e2aca6a45b8ebeb696795faeb2aa1e4438f7171a0b95a742598513baa7"
    "a1aeade23d3fefccdcd27c3282de4d6a1147c669443cec1f6dc48e9cf32b6427"
    "16664f35d57764479cc436f3faf030faf793d5e792cc7a8d660c92b9a67c60a5"
    "245dcb5a3fa220971110a0614a4c29e1a5aa6d1949cd68c75fb6338506a3d69f"
    "42d72e246ea6daa17e3ce66a76da30689a241c687740122990f5e8e5619ef759"
    "2863055a9b643daa824ebcbf3054ac5eded e19c46b73dfe480bcd46f72157d3b"
    .replace(" ", "")
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
    "GITHUB_UPDATE_CHANNEL_URL",
    "GITEE_OWNER",
    "GITEE_REPOSITORY",
    "GITEE_REPOSITORY_URL",
    "GITEE_UPDATE_CHANNEL_URL",
    "RELEASE_NOTES_UI_ENABLED",
    "UPDATE_APP_ID",
    "UPDATE_CHANNEL",
    "UPDATE_PROTOCOL_VERSION",
    "UPDATE_SIGNING_RSA_EXPONENT",
    "UPDATE_SIGNING_RSA_MODULUS_HEX",
    "WINDOWS_APP_USER_MODEL_ID",
]
