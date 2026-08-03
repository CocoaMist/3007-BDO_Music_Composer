"""Application-owned revision-scoped conversion validation snapshots.

This module is Qt-free.  It caches only one immutable result and relies on the
editor's explicit :class:`bdo_music_composer.editor.model_revision.ModelRevision`
boundary for safe
invalidation; it never fingerprints or retains mutable note containers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from bdo_music_composer.core.bdo_profile import BdoProfile
from bdo_music_composer.export.bdo_validation import ValidationContext, ValidationIssue


Validator = Callable[
    [Sequence[object], BdoProfile, ValidationContext],
    tuple[ValidationIssue, ...],
]


@dataclass(frozen=True, slots=True)
class ValidationSnapshot:
    revision: int
    scope_key: str
    issues: tuple[ValidationIssue, ...]


class ConversionValidationController:
    """Build and reuse the last validation result for one model revision."""

    def __init__(self, validator: Validator) -> None:
        self._validator = validator
        self._snapshot: ValidationSnapshot | None = None

    @property
    def cached_snapshot(self) -> ValidationSnapshot | None:
        return self._snapshot

    def invalidate(self) -> None:
        self._snapshot = None

    def snapshot(
        self,
        *,
        revision: int,
        scope_key: str,
        tracks: Sequence[object],
        profile: BdoProfile,
        context: ValidationContext,
    ) -> ValidationSnapshot:
        key = (int(revision), str(scope_key))
        current = self._snapshot
        if current is not None and (current.revision, current.scope_key) == key:
            return current
        snapshot = ValidationSnapshot(
            revision=key[0],
            scope_key=key[1],
            issues=tuple(self._validator(tracks, profile, context)),
        )
        self._snapshot = snapshot
        return snapshot


__all__ = ["ConversionValidationController", "ValidationSnapshot"]
