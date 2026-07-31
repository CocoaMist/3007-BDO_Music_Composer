"""Lazy packaged access to the immutable Black Desert rule profile."""

from __future__ import annotations

from functools import lru_cache

from bdo_instrument_adaptation import articulation_pairs_by_instrument
from bdo_profile import BdoProfile, load_bdo_profile
from project_paths import PROFILES_DIR


@lru_cache(maxsize=1)
def get_bdo_profile() -> BdoProfile:
    """Load and validate the bundled profile once, on first domain use."""

    return load_bdo_profile(
        PROFILES_DIR / "bdo_global_v9.json",
        articulation_map=articulation_pairs_by_instrument(),
    )


__all__ = ["get_bdo_profile"]
