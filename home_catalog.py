"""Bounded, privacy-preserving home-page filesystem discovery."""

from __future__ import annotations

from dataclasses import dataclass, replace
import heapq
import json
import os
from pathlib import Path
import re
import time
from typing import Callable, Iterator

from bdo_codec import score_instrument_ids
from bdo_midi import BDO_ENSEMBLE_PLAYER_LIMIT, unique_performance_instrument_ids
from bdo_music_composer.project.project_persistence import (
    PROJECT_INDEX_NAME,
    normalize_project_id,
)


PROJECT_LABEL_PREFIX_BYTES = 256 * 1024
GAME_SCORE_METADATA_MAX_BYTES = 2 * 1024 * 1024
_OUTPUT_NAME = re.compile(r'"output_name"\s*:\s*("(?:\\.|[^"\\])*")')
_PROJECT_ID = re.compile(r'"project_id"\s*:\s*("(?:\\.|[^"\\])*")')


@dataclass(frozen=True)
class HomeEntry:
    kind: str
    label: str
    path: Path
    detail: str
    modified_at: float
    version_count: int = 1
    project_id: str = ""
    version_index: int = 1
    instrument_ids: tuple[int, ...] = ()

    @property
    def performance_instrument_ids(self) -> tuple[int, ...]:
        """Return physical game instruments after folding Marnian sound modes."""

        return unique_performance_instrument_ids(self.instrument_ids)

    @property
    def instrument_count(self) -> int:
        return len(self.performance_instrument_ids)

    @property
    def required_players(self) -> int:
        """Return the simultaneous ensemble size allowed by the game."""

        return min(self.instrument_count, BDO_ENSEMBLE_PLAYER_LIMIT)

    @property
    def exceeds_ensemble_limit(self) -> bool:
        return self.instrument_count > BDO_ENSEMBLE_PLAYER_LIMIT


def _normalized_instrument_ids(value: object) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result: list[int] = []
    seen: set[int] = set()
    for raw in value:
        try:
            instrument_id = int(raw)
        except (TypeError, ValueError):
            continue
        if 0 <= instrument_id <= 0xFF and instrument_id not in seen:
            seen.add(instrument_id)
            result.append(instrument_id)
    return tuple(result)


def game_score_instrument_ids(path: Path) -> tuple[int, ...]:
    """Return a bounded, identity-blind instrument summary for one score."""

    try:
        # Bound the read itself rather than trusting a preceding stat: a file
        # can be replaced or grow between those calls while the home scan is
        # yielding across event-loop turns.
        with path.open("rb") as stream:
            data = stream.read(GAME_SCORE_METADATA_MAX_BYTES + 1)
        if len(data) > GAME_SCORE_METADATA_MAX_BYTES:
            return ()
        return score_instrument_ids(data)
    except (OSError, ValueError):
        return ()


def home_timestamp(timestamp: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))


def scan_example_projects(
    directory: Path,
    limit: int = 8,
    *,
    unknown_source: str = "Unknown source",
    format_detail: Callable[[str], str] | None = None,
) -> list[HomeEntry]:
    """Read bounded local-example manifests without loading full projects."""

    if not directory.is_dir() or limit <= 0:
        return []
    detail_formatter = format_detail or (
        lambda source: f"Example · source: {source}"
    )
    entries: list[HomeEntry] = []
    for manifest_path in directory.glob("*/example.json"):
        try:
            if manifest_path.stat().st_size > 64 * 1024:
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            project_name = str(manifest.get("project") or "project.json")
            if (
                Path(project_name).is_absolute()
                or Path(project_name).name != project_name
            ):
                continue
            project_path = manifest_path.parent / project_name
            stat = project_path.stat()
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        if not project_path.is_file():
            continue
        title = str(
            manifest.get("title") or manifest_path.parent.name
        ).strip()
        manifest_source = str(manifest.get("source") or "").strip()
        source = manifest_source if manifest_source else unknown_source
        entries.append(HomeEntry(
            "example",
            title,
            project_path,
            detail_formatter(source),
            stat.st_mtime,
        ))
    entries.sort(
        key=lambda item: (item.label.casefold(), str(item.path).casefold())
    )
    return entries[:limit]


def merge_home_project_entries(
    entries: list[HomeEntry],
    limit: int = 80,
    *,
    timestamp: Callable[[float], str] = home_timestamp,
    format_version: Callable[[str, int, int], str] | None = None,
) -> list[HomeEntry]:
    """Deduplicate paths and annotate only explicit project-ID versions."""

    if limit <= 0:
        return []
    version_formatter = format_version or (
        lambda value, index, count: f"{value} · version {index}/{count}"
    )
    by_path: dict[str, HomeEntry] = {}
    for entry in entries:
        try:
            path_key = str(entry.path.resolve()).casefold()
        except OSError:
            path_key = str(entry.path).casefold()
        existing = by_path.get(path_key)
        if existing is None or entry.modified_at >= existing.modified_at:
            by_path[path_key] = entry

    groups: dict[str, list[HomeEntry]] = {}
    for entry in by_path.values():
        key = (
            f"project:{entry.project_id}"
            if entry.kind == "project" and entry.project_id
            else f"path:{str(entry.path).casefold()}"
        )
        groups.setdefault(key, []).append(entry)

    merged: list[HomeEntry] = []
    for members in groups.values():
        members.sort(key=lambda item: item.modified_at, reverse=True)
        version_count = len(members)
        for offset, member in enumerate(members):
            version_index = version_count - offset
            detail = timestamp(member.modified_at)
            if version_count > 1:
                detail = version_formatter(
                    detail,
                    version_index,
                    version_count,
                )
            merged.append(replace(
                member,
                detail=detail,
                version_count=version_count,
                version_index=version_index,
            ))
    merged.sort(key=lambda item: item.modified_at, reverse=True)
    return merged[:limit]


def scan_game_scores(directory: Path, limit: int = 80) -> list[HomeEntry]:
    if not directory.is_dir() or limit <= 0:
        return []
    candidates: list[tuple[float, Path]] = []
    try:
        paths = directory.iterdir()
        for path in paths:
            if not path.is_file() or path.name.startswith("."):
                continue
            try:
                candidates.append((path.stat().st_mtime, path))
            except OSError:
                continue
    except OSError:
        return []
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [
        HomeEntry(
            "game",
            path.stem or path.name,
            path,
            home_timestamp(modified_at),
            modified_at,
            instrument_ids=game_score_instrument_ids(path),
        )
        for modified_at, path in candidates[:limit]
    ]


def _project_metadata(
    project_path: Path,
) -> tuple[str, str, tuple[int, ...]]:
    index_path = project_path.parent / PROJECT_INDEX_NAME
    try:
        if index_path.is_file() and index_path.stat().st_size <= 64 * 1024:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
            label = str(payload.get("output_name") or "").strip()
            if label:
                return (
                    label,
                    normalize_project_id(payload.get("project_id")),
                    _normalized_instrument_ids(payload.get("instrument_ids")),
                )
    except (OSError, ValueError, TypeError):
        pass

    project_id = ""
    try:
        with project_path.open("rb") as stream:
            prefix = stream.read(PROJECT_LABEL_PREFIX_BYTES).decode(
                "utf-8", errors="ignore"
            )
        id_match = _PROJECT_ID.search(prefix)
        if id_match:
            project_id = normalize_project_id(json.loads(id_match.group(1)))
        match = _OUTPUT_NAME.search(prefix)
        if match:
            label = str(json.loads(match.group(1))).strip()
            if label:
                return label, project_id, ()
    except (OSError, ValueError, TypeError):
        pass
    return project_path.parent.name, project_id, ()


def _project_entry(modified_at: float, path: Path) -> HomeEntry:
    label, project_id, instrument_ids = _project_metadata(path)
    return HomeEntry(
        "project",
        label,
        path,
        home_timestamp(modified_at),
        modified_at,
        project_id=project_id,
        instrument_ids=instrument_ids,
    )


def scan_local_projects(directory: Path, limit: int = 80) -> list[HomeEntry]:
    """Stat all projects but parse metadata only for the newest bounded set."""

    if not directory.is_dir() or limit <= 0:
        return []
    candidates: list[tuple[float, Path]] = []
    for path in directory.glob("*/project.json"):
        try:
            candidates.append((path.stat().st_mtime, path))
        except OSError:
            continue
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [_project_entry(modified_at, path) for modified_at, path in candidates[:limit]]


class IncrementalHomeScan:
    """Bounded home discovery that yields between small directory batches.

    Directory enumeration and ``stat`` calls are split across GUI event-loop
    turns. Project metadata is read only after the newest bounded paths are
    known, so a large autosave tree never causes full project JSON parsing.
    """

    def __init__(
        self,
        game_directory: Path,
        project_directory: Path,
        *,
        game_limit: int = 80,
        project_limit: int = 400,
    ) -> None:
        self.game_limit = max(0, int(game_limit))
        self.project_limit = max(0, int(project_limit))
        self._game_iter = self._directory_iter(Path(game_directory))
        self._project_iter = self._directory_iter(Path(project_directory))
        self._game_done = self._game_iter is None
        self._project_done = self._project_iter is None
        self._game_heap: list[tuple[float, str, Path]] = []
        self._project_heap: list[tuple[float, str, Path]] = []
        self._pending_project_metadata: Iterator[tuple[float, str, Path]] | None = None
        self._pending_game_metadata: Iterator[tuple[float, str, Path]] | None = None
        self._game_entries: list[HomeEntry] = []
        self._project_entries: list[HomeEntry] = []
        self._turn = 0
        self._metadata_turn = 0
        self._game_metadata_done = False
        self._project_metadata_done = False

    @staticmethod
    def _directory_iter(directory: Path) -> os.ScandirIterator[str] | None:
        try:
            return os.scandir(directory)
        except OSError:
            return None

    @staticmethod
    def _retain_newest(
        heap: list[tuple[float, str, Path]],
        item: tuple[float, str, Path],
        limit: int,
    ) -> None:
        if limit <= 0:
            return
        if len(heap) < limit:
            heapq.heappush(heap, item)
        elif item[:2] > heap[0][:2]:
            heapq.heapreplace(heap, item)

    def cancel(self) -> None:
        for iterator in (self._game_iter, self._project_iter):
            if iterator is not None:
                iterator.close()
        self._game_iter = None
        self._project_iter = None
        self._game_done = True
        self._project_done = True
        self._game_metadata_done = True
        self._project_metadata_done = True

    def _scan_game_one(self) -> None:
        iterator = self._game_iter
        if iterator is None:
            self._game_done = True
            return
        try:
            item = next(iterator)
        except (StopIteration, OSError):
            iterator.close()
            self._game_iter = None
            self._game_done = True
            return
        try:
            if not item.name.startswith(".") and item.is_file(follow_symlinks=False):
                modified_at = item.stat(follow_symlinks=False).st_mtime
                path = Path(item.path)
                self._retain_newest(
                    self._game_heap,
                    (modified_at, str(path).casefold(), path),
                    self.game_limit,
                )
        except OSError:
            return

    def _scan_project_one(self) -> None:
        iterator = self._project_iter
        if iterator is None:
            self._project_done = True
            return
        try:
            item = next(iterator)
        except (StopIteration, OSError):
            iterator.close()
            self._project_iter = None
            self._project_done = True
            return
        try:
            if not item.is_dir(follow_symlinks=False):
                return
            path = Path(item.path) / "project.json"
            modified_at = path.stat().st_mtime
            if not path.is_file():
                return
            self._retain_newest(
                self._project_heap,
                (modified_at, str(path).casefold(), path),
                self.project_limit,
            )
        except OSError:
            return

    def _prepare_results(self) -> None:
        if self._pending_project_metadata is not None:
            return
        self._pending_game_metadata = iter(
            sorted(self._game_heap, reverse=True)
        )
        self._pending_project_metadata = iter(
            sorted(self._project_heap, reverse=True)
        )

    def _scan_game_metadata_one(self) -> None:
        assert self._pending_game_metadata is not None
        try:
            modified_at, _key, path = next(self._pending_game_metadata)
        except StopIteration:
            self._game_metadata_done = True
            return
        self._game_entries.append(HomeEntry(
            "game",
            path.stem or path.name,
            path,
            home_timestamp(modified_at),
            modified_at,
            instrument_ids=game_score_instrument_ids(path),
        ))

    def _scan_project_metadata_one(self) -> None:
        assert self._pending_project_metadata is not None
        try:
            modified_at, _key, path = next(self._pending_project_metadata)
        except StopIteration:
            self._project_metadata_done = True
            return
        self._project_entries.append(_project_entry(modified_at, path))

    def step(self, max_items: int = 64) -> bool:
        """Process at most ``max_items`` facts; return ``True`` when done."""

        budget = max(1, int(max_items))
        while budget and not (self._game_done and self._project_done):
            if (self._turn % 2 == 0 and not self._game_done) or self._project_done:
                self._scan_game_one()
            else:
                self._scan_project_one()
            self._turn += 1
            budget -= 1

        if not (self._game_done and self._project_done):
            return False
        self._prepare_results()
        assert self._pending_game_metadata is not None
        assert self._pending_project_metadata is not None
        metadata_budget = max(1, budget // 8)
        while metadata_budget and not (
            self._game_metadata_done and self._project_metadata_done
        ):
            scan_game = (
                self._metadata_turn % 2 == 0
                and not self._game_metadata_done
            ) or self._project_metadata_done
            if scan_game:
                self._scan_game_metadata_one()
            else:
                self._scan_project_metadata_one()
            self._metadata_turn += 1
            metadata_budget -= 1
        return self._game_metadata_done and self._project_metadata_done

    def results(self) -> tuple[list[HomeEntry], list[HomeEntry]]:
        return list(self._game_entries), list(self._project_entries)


__all__ = [
    "HomeEntry",
    "IncrementalHomeScan",
    "game_score_instrument_ids",
    "home_timestamp",
    "merge_home_project_entries",
    "scan_example_projects",
    "scan_game_scores",
    "scan_local_projects",
]
