"""Qt-free ownership of project requests and lifecycle state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping

from .project_persistence import new_project_id, normalize_project_id
from .project_schema import resolve_project_file_reference


class ProjectSourceFormat(str, Enum):
    MIDI = "midi"
    BDO = "bdo"
    PROJECT = "project"


class ProjectOpenErrorCode(str, Enum):
    MISSING_SOURCE = "missing_source"


class ProjectOpenError(ValueError):
    """A typed project-open failure that the UI can localize."""

    def __init__(self, code: ProjectOpenErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class ProjectOpenRequest:
    """Normalized routing facts for opening one migrated project payload."""

    project_path: Path
    project_id: str
    source_format: ProjectSourceFormat
    source_path: Path | None
    source_copy_path: Path | None
    allow_legacy_absolute_paths: bool
    output_name: str

    @classmethod
    def from_payload(
        cls,
        project_path: Path,
        payload: Mapping[str, object],
        *,
        file_exists: Callable[[Path], bool] | None = None,
    ) -> "ProjectOpenRequest":
        path = Path(project_path)
        is_file = file_exists or (lambda candidate: candidate.is_file())
        raw_format = str(
            payload.get("source_format") or ProjectSourceFormat.MIDI.value
        )
        try:
            source_format = ProjectSourceFormat(raw_format)
        except ValueError:
            source_format = ProjectSourceFormat.MIDI

        allow_legacy = (
            str(payload.get("path_policy") or "") != "project-relative-v1"
        )
        recovery_copy = resolve_project_file_reference(
            path.parent,
            payload.get("source_midi_path"),
            allow_legacy_absolute=allow_legacy,
        )
        original_source = resolve_project_file_reference(
            path.parent,
            payload.get("original_midi_path"),
            allow_legacy_absolute=allow_legacy,
        )
        source_copy_path = (
            recovery_copy
            if recovery_copy is not None and is_file(recovery_copy)
            else None
        )
        active_source = (
            source_copy_path
            if source_copy_path is not None
            else original_source
        )
        if source_format is ProjectSourceFormat.PROJECT:
            active_source = None
        elif (
            (active_source is None or not is_file(active_source))
            # Current project snapshots own their complete track/note model.
            # A missing provenance file must not make those edits inaccessible.
            and not isinstance(payload.get("tracks"), list)
        ):
            raise ProjectOpenError(ProjectOpenErrorCode.MISSING_SOURCE)
        elif active_source is not None and not is_file(active_source):
            active_source = None

        return cls(
            project_path=path,
            project_id=(
                normalize_project_id(payload.get("project_id"))
                or new_project_id()
            ),
            source_format=source_format,
            source_path=active_source,
            source_copy_path=source_copy_path,
            allow_legacy_absolute_paths=allow_legacy,
            output_name=str(payload.get("output_name") or path.parent.name),
        )


@dataclass(slots=True)
class ProjectLifecycleController:
    """Gate autosave/UI reactions while one project transition is active."""

    loading: bool = False
    generation: int = 0
    reason: str = ""

    def begin_loading(self, reason: str) -> int:
        self.generation += 1
        self.loading = True
        self.reason = str(reason or "project loading")
        return self.generation

    def finish_loading(self, generation: int) -> bool:
        if int(generation) != self.generation:
            return False
        self.loading = False
        self.reason = ""
        return True

    def set_loading(self, loading: bool, reason: str = "") -> None:
        if loading:
            self.begin_loading(reason)
        else:
            self.loading = False
            self.reason = ""


__all__ = [
    "ProjectLifecycleController",
    "ProjectOpenError",
    "ProjectOpenErrorCode",
    "ProjectOpenRequest",
    "ProjectSourceFormat",
]
