"""Conservative validation-state rules for BDO sample preview evidence."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from typing import Iterable, Mapping


VALIDATION_MATRIX_FORMAT = 2
_MEASUREMENT_FIELDS = frozenset({
    "capture_path",
    "onset_frames",
    "pitch_cents",
    "loudness_lufs",
    "spectral_distance",
    "listener_pass",
    "verification",
})


def validation_matrix_definition_sha256(
    payload: Mapping[str, object],
) -> str:
    """Hash immutable probe identities while excluding measurement results."""

    cells = payload.get("cells", ())
    unmapped = payload.get("unmapped", ())
    if not isinstance(cells, Iterable) or isinstance(cells, (str, bytes)):
        return ""
    if not isinstance(unmapped, Iterable) or isinstance(unmapped, (str, bytes)):
        return ""
    try:
        definition = {
            "format": int(payload.get("format", 0) or 0),
            "mapping_evidence_sha256": str(
                payload.get("mapping_evidence_sha256", "")
            ),
            "cells": sorted(
                [
                    {
                        str(key): value
                        for key, value in cell.items()
                        if str(key) not in _MEASUREMENT_FIELDS
                    }
                    for cell in cells
                    if isinstance(cell, Mapping)
                ],
                key=lambda item: str(item.get("cell_id", "")),
            ),
            "unmapped": sorted(
                (
                    {
                        str(key): value
                        for key, value in item.items()
                    }
                    for item in unmapped
                    if isinstance(item, Mapping)
                ),
                key=lambda item: json.dumps(
                    item,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        }
        encoded = json.dumps(
            definition,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    except (KeyError, TypeError, ValueError, OverflowError):
        return ""
    return hashlib.sha256(encoded).hexdigest()


def verified_instrument_articulations(
    payload: Mapping[str, object],
    mapping_evidence_sha256: str | None,
) -> frozenset[tuple[int, int]]:
    """Return pairs whose complete current-evidence probe set is verified.

    Format-1 matrices identified cells too loosely and could exercise a
    different source than the one named in the record.  They intentionally
    fail closed.  A format-2 pair is verified only when every generated probe
    for every bank/mode is current, selection-valid, and listener-verified.
    """

    expected_hash = str(mapping_evidence_sha256 or "").strip()
    if (
        int(payload.get("format", 0) or 0) != VALIDATION_MATRIX_FORMAT
        or not expected_hash
        or str(payload.get("mapping_evidence_sha256", "")) != expected_hash
        or str(payload.get("matrix_definition_sha256", ""))
        != validation_matrix_definition_sha256(payload)
    ):
        return frozenset()

    grouped: dict[tuple[int, int], list[Mapping[str, object]]] = defaultdict(list)
    raw_cells = payload.get("cells", ())
    if not isinstance(raw_cells, Iterable) or isinstance(raw_cells, (str, bytes)):
        return frozenset()
    try:
        for cell in raw_cells:
            if not isinstance(cell, Mapping):
                return frozenset()
            pair = (
                int(cell["instrument_id"]),
                int(cell.get("requested_ntype", cell.get("ntype", 0))),
            )
            grouped[pair].append(cell)
    except (KeyError, TypeError, ValueError, OverflowError):
        return frozenset()

    invalid_pairs: set[tuple[int, int]] = set()
    raw_unmapped = payload.get("unmapped", ())
    if isinstance(raw_unmapped, Iterable) and not isinstance(
        raw_unmapped,
        (str, bytes),
    ):
        try:
            invalid_pairs = {
                (
                    int(item["instrument_id"]),
                    int(item["requested_ntype"]),
                )
                for item in raw_unmapped
                if isinstance(item, Mapping)
                and "requested_ntype" in item
            }
        except (KeyError, TypeError, ValueError, OverflowError):
            return frozenset()

    return frozenset(
        pair
        for pair, cells in grouped.items()
        if pair not in invalid_pairs
        and cells
        and all(
            bool(cell.get("selection_valid", False))
            and cell.get("verification") == "verified"
            and str(cell.get("mapping_evidence_sha256", "")) == expected_hash
            for cell in cells
        )
    )
