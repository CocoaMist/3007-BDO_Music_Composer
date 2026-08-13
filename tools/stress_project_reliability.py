"""Bounded adversarial stress for undo and autosave recovery contracts.

All files are created below a fresh temporary directory.  This is not a
security scanner or malware generator; it attacks model and persistence
boundaries with deterministic hostile inputs and injected I/O failures.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import tempfile
from unittest.mock import patch

from bdo_midi import Note
from bdo_music_composer.editor.editor_commands import (
    ProjectCommandStack,
    ProjectSnapshot,
)
from bdo_music_composer.editor.editor_models import TrackState
from bdo_music_composer.project.project_persistence import (
    AutosaveRequest,
    PROJECT_INDEX_NAME,
    ProjectMetadataSnapshot,
    freeze_project_tracks,
    write_autosave,
)


def _tracks() -> list[TrackState]:
    return [
        TrackState(
            track_id=index,
            notes=[Note(48 + index, 80, index * 100.0, 120.0, 0)],
            gm_program=0,
            is_percussion=False,
            display_name=f"track-{index}",
            bdo_instrument_id=0x12,
        )
        for index in range(1, 5)
    ]


def _snapshot(tracks: list[TrackState], markers: list[dict]) -> ProjectSnapshot:
    return ProjectSnapshot.capture(
        tracks, 0, 0, None, timeline_markers=markers
    )


def _fingerprint(snapshot: ProjectSnapshot) -> tuple[object, ...]:
    return (
        tuple(
            (
                track.track_id, track.display_name, track.muted, track.solo,
                tuple(track.notes), track.arrangement_group_id,
            )
            for track in snapshot.restored_tracks()
        ),
        json.dumps(
            snapshot.restored_timeline_markers(),
            ensure_ascii=False,
            sort_keys=True,
        ),
    )


def _mutate(
    rng: random.Random, tracks: list[TrackState], markers: list[dict], serial: int
) -> None:
    track = rng.choice(tracks)
    operation = rng.randrange(5)
    if operation == 0:
        track.muted = not track.muted
    elif operation == 1:
        track.solo = not track.solo
    elif operation == 2:
        track.display_name = f"hostile-\0-{serial}-" + "界" * (serial % 31)
    elif operation == 3:
        track.notes.append(Note(
            rng.randrange(0, 128), rng.randrange(1, 128),
            float(serial * 17), float(1 + rng.randrange(1000)),
            rng.randrange(0, 100),
        ))
        del track.notes[:-96]
    else:
        markers.append({
            "id": f"m-{serial}", "label": "攻击\0标记" + "x" * 120,
            "time_ms": float(serial * 13),
        })
        del markers[:-512]


def attack_undo(seed: int, iterations: int) -> dict[str, int]:
    rng = random.Random(seed)
    tracks, markers = _tracks(), []
    stack = ProjectCommandStack(limit=64)
    oracle_undo: list[ProjectSnapshot] = []
    oracle_redo: list[ProjectSnapshot] = []
    counts = {"mutations": 0, "undos": 0, "redos": 0}
    for serial in range(iterations):
        roll = rng.random()
        current = _snapshot(tracks, markers)
        if roll < 0.62 or not oracle_undo:
            stack.push(current)
            oracle_undo.append(current)
            del oracle_undo[:-64]
            oracle_redo.clear()
            _mutate(rng, tracks, markers, serial)
            counts["mutations"] += 1
        elif roll < 0.84:
            restored = stack.undo(current)
            expected = oracle_undo.pop()
            oracle_redo.append(current)
            if restored is None or _fingerprint(restored) != _fingerprint(expected):
                raise AssertionError("undo diverged from the independent oracle")
            tracks = restored.restored_tracks()
            markers = list(restored.restored_timeline_markers() or [])
            counts["undos"] += 1
        elif oracle_redo:
            restored = stack.redo(current)
            expected = oracle_redo.pop()
            oracle_undo.append(current)
            if restored is None or _fingerprint(restored) != _fingerprint(expected):
                raise AssertionError("redo diverged from the independent oracle")
            tracks = restored.restored_tracks()
            markers = list(restored.restored_timeline_markers() or [])
            counts["redos"] += 1
        if len(stack._undo) > 64:
            raise AssertionError("undo history exceeded its configured bound")
    return counts


def _request(
    project_dir: Path, tracks: list[TrackState], serial: int
) -> AutosaveRequest:
    return AutosaveRequest(
        project_dir=project_dir,
        metadata=ProjectMetadataSnapshot.capture(
            schema_version=13,
            saved_at=f"sequence-{serial}",
            reason=f"adversarial-{serial}",
            output_name=f"Reliability {serial}",
            research={
                "timeline_markers": [{
                    "id": f"m-{serial}", "label": "边界" * 20,
                    "time_ms": float(serial),
                }],
            },
        ),
        tracks=freeze_project_tracks(tracks),
    )


def _assert_saved_pair(project_dir: Path, serial: int) -> None:
    project = json.loads((project_dir / "project.json").read_text("utf-8"))
    index = json.loads((project_dir / PROJECT_INDEX_NAME).read_text("utf-8"))
    if project["reason"] != f"adversarial-{serial}":
        raise AssertionError("autosave exposed a stale project payload")
    if project["project_id"] != index["project_id"]:
        raise AssertionError("project and safe index identities diverged")
    if list(project_dir.glob(".*.tmp")):
        raise AssertionError("atomic-write temporary files leaked")


def attack_autosave(seed: int, iterations: int) -> dict[str, int]:
    rng = random.Random(seed ^ 0xA5705A)
    with tempfile.TemporaryDirectory(prefix="bdo-reliability-") as folder:
        project_dir = Path(folder) / "project"
        tracks = _tracks()
        for serial in range(iterations):
            _mutate(rng, tracks, [], serial)
            write_autosave(_request(project_dir, tracks, serial))
            _assert_saved_pair(project_dir, serial)

        baseline = (project_dir / "project.json").read_bytes()
        failed_request = _request(project_dir, tracks, iterations)
        with patch("bdo_common.atomic_io.os.replace", side_effect=OSError("injected replace failure")):
            try:
                write_autosave(failed_request)
            except OSError:
                pass
            else:
                raise AssertionError("injected atomic replacement failure escaped")
        if (project_dir / "project.json").read_bytes() != baseline:
            raise AssertionError("failed atomic save damaged the previous project")
        if list(project_dir.glob(".*.tmp")):
            raise AssertionError("failed save leaked temporary files")

        write_autosave(failed_request)
        _assert_saved_pair(project_dir, iterations)

        log_path = project_dir / "autosave.log"
        log_path.unlink(missing_ok=True)
        log_path.mkdir()
        final_serial = iterations + 1
        write_autosave(_request(project_dir, tracks, final_serial))
        _assert_saved_pair(project_dir, final_serial)

    rejected = 0
    for build in (
        lambda: ProjectMetadataSnapshot.capture(schema_version=13, research={"x": float("nan")}),
        lambda: ProjectMetadataSnapshot.capture(schema_version=13, source_reference="../escape.mid"),
        lambda: freeze_project_tracks((TrackState(1, [Note(60, 90, float("nan"), 1, 0)], 0, False, "bad", 0x12),)),
    ):
        try:
            build()
        except (TypeError, ValueError):
            rejected += 1
        else:
            raise AssertionError("malformed autosave input was accepted")
    return {"writes": iterations + 2, "faults_injected": 2, "malformed_rejected": rejected}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20260813)
    parser.add_argument("--iterations", type=int, default=120)
    args = parser.parse_args()
    iterations = max(10, min(10_000, int(args.iterations)))
    result = {
        "seed": int(args.seed),
        "iterations": iterations,
        "undo": attack_undo(int(args.seed), iterations * 4),
        "autosave": attack_autosave(int(args.seed), iterations),
        "status": "ok",
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
