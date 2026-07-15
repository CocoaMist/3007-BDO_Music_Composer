"""Small, explicit migrations for autosaved BDO Music Composer projects."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


CURRENT_PROJECT_SCHEMA = 2


def migrate_project(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(payload))
    version = int(result.get("schema_version", result.get("version", 1)))
    if version < 1 or version > CURRENT_PROJECT_SCHEMA:
        raise ValueError(f"unsupported project schema version: {version}")
    if version == 1:
        result["schema_version"] = 2
        result.setdefault("research", {"profile_id": "bdo-global-v9-2026.07", "ab_experiments": []})
        version = 2
    result["schema_version"] = version
    result.pop("version", None)
    return result


__all__ = ["CURRENT_PROJECT_SCHEMA", "migrate_project"]
