"""Backward-compatible optimizer imports.

New code should import from :mod:`optimization`. This facade keeps existing
integrations and saved automation scripts working after the package split.
"""

from optimization import *  # noqa: F401,F403
