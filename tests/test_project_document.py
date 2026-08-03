from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from bdo_music_composer.editor.editor_import import TrackImportPresentation
from bdo_music_composer.app.project_document import (
    ProjectLoadError,
    ProjectLoadErrorCode,
    prepare_project_load,
)


PRESENTATION = TrackImportPresentation(
    colors=("#111111", "#222222"),
    bdo_instrument_name=lambda value: f"BDO {value}",
    gm_program_name=lambda value: f"GM {value}",
    drum_track_name=lambda: "Drums",
    new_track_name=lambda value: f"Track {value}",
)


def _payload(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 11,
        "path_policy": "project-relative-v1",
        "source_format": "project",
        "output_name": "Typed project",
        "owner_id": 123,
        "char_name": "Shai",
        "bpm": 137,
        "time_sig": 3,
        "time_sig_denominator": 4,
        "tempo_changes": 2,
        "conversion_settings": {
            "velocity_mode": "preserve",
            "transpose": 0,
            "reverb": 201,
            "delay": 202,
            "chorus": [203, 204, 205],
        },
        "pitch_transform": {
            "version": 1,
            "global_semitones": 0,
            "track_overrides": [],
        },
        "lyric_events": [
            {"time": 125.0, "kind": "lyrics", "text": "hello"}
        ],
        "reference_audio_attached": True,
        "reference_audio_volume": 65,
        "reference_audio_offset_ms": -125.5,
        "beat_origin_ms": 250.0,
        "reference_audio_path": "",
        "research": {
            "profile_id": "profile-test",
            "ab_experiments": [{"id": "experiment-1"}],
        },
        "transcription_review": {},
        "transcription_assist_review": {},
        "tracks": [
            {
                "track_id": 7,
                "display_name": "edited",
                "gm_program": 0,
                "is_percussion": False,
                "bdo_instrument_id": 11,
                "bdo_track_volume": 91,
                "bdo_track_settings": [8, 7, 6, 5, 4, 3, 2, 1],
                "volume_scale": 1.0,
                "duration_scale": 1.0,
                "notes": [[72, 0, 123.0, 456.0, 11]],
            }
        ],
    }
    value.update(updates)
    return value


def _prepare(
    project_path: Path,
    payload: object,
    *,
    file_exists=lambda _path: False,
    meter_reader=lambda _path: 4,
):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return prepare_project_load(
        project_path,
        text,
        PRESENTATION,
        file_exists=file_exists,
        midi_meter_reader=meter_reader,
    )


class ProjectDocumentTests(unittest.TestCase):
    def test_complete_document_becomes_one_typed_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "project.json"
            plan = _prepare(path, _payload())

        self.assertEqual(plan.open_request.output_name, "Typed project")
        self.assertEqual(plan.owner_id, 123)
        self.assertEqual(plan.character_name, "Shai")
        self.assertEqual(
            (plan.bpm, plan.time_signature, plan.time_signature_denominator),
            (137, 3, 4),
        )
        self.assertEqual(plan.master_effects.legacy_values(), (
            201,
            202,
            (203, 204, 205),
        ))
        self.assertEqual(len(plan.tracks), 1)
        self.assertEqual(plan.tracks[0].track_id, 7)
        self.assertEqual(plan.tracks[0].notes[0].vel, 0)
        self.assertEqual(plan.tracks[0].notes[0].ntype, 11)
        self.assertEqual(plan.research.profile_id, "profile-test")
        self.assertEqual(
            plan.research.experiments_payload(),
            [{"id": "experiment-1"}],
        )
        self.assertEqual(plan.lyric_payload()[0]["text"], "hello")
        self.assertTrue(plan.reference.was_attached)
        self.assertEqual(plan.reference.volume_percent, 65)

    def test_document_errors_have_stable_codes_and_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "project.json"
            cases = (
                ("{", ProjectLoadErrorCode.INVALID_JSON, "$"),
                ([], ProjectLoadErrorCode.INVALID_ROOT, "$"),
                (
                    {"schema_version": 999},
                    ProjectLoadErrorCode.UNSUPPORTED_SCHEMA,
                    "schema_version",
                ),
                (
                    _payload(owner_id="invalid"),
                    ProjectLoadErrorCode.INVALID_FIELD,
                    "owner_id",
                ),
                (
                    _payload(reference_audio_volume=101),
                    ProjectLoadErrorCode.INVALID_FIELD,
                    "reference_audio_volume",
                ),
            )
            for payload, code, error_path in cases:
                with self.subTest(code=code):
                    with self.assertRaises(ProjectLoadError) as caught:
                        _prepare(path, payload)
                    self.assertIs(caught.exception.code, code)
                    self.assertEqual(caught.exception.path, error_path)

    def test_invalid_track_retains_the_editor_import_path(self) -> None:
        payload = _payload()
        payload["tracks"][0]["notes"][0][1] = "invalid"  # type: ignore[index]
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ProjectLoadError) as caught:
                _prepare(Path(temp) / "project.json", payload)

        self.assertIs(
            caught.exception.code,
            ProjectLoadErrorCode.INVALID_TRACKS,
        )
        self.assertEqual(caught.exception.path, "tracks[0].notes[0][1]")

    def test_invalid_reference_is_distinct_from_missing_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "project.json"
            for reference in ("../outside.mid", str(Path(temp).resolve())):
                payload = _payload(
                    source_format="midi",
                    source_midi_path=reference,
                    tracks=None,
                )
                with self.subTest(reference=reference):
                    with self.assertRaises(ProjectLoadError) as caught:
                        _prepare(path, payload)
                    self.assertIs(
                        caught.exception.code,
                        ProjectLoadErrorCode.INVALID_SOURCE_REFERENCE,
                    )
                    self.assertEqual(
                        caught.exception.path,
                        "source_midi_path",
                    )

            with self.assertRaises(ProjectLoadError) as caught:
                _prepare(
                    path,
                    _payload(
                        source_format="midi",
                        source_midi_path="missing.mid",
                        tracks=None,
                    ),
                )
            self.assertIs(
                caught.exception.code,
                ProjectLoadErrorCode.MISSING_SOURCE,
            )

    def test_strict_empty_snapshot_can_open_without_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            plan = _prepare(
                Path(temp) / "project.json",
                _payload(
                    source_format="midi",
                    source_midi_path="missing.mid",
                    tracks=[],
                ),
            )

        self.assertEqual(plan.tracks, ())
        self.assertIsNone(plan.open_request.source_path)

    def test_missing_identity_never_inherits_caller_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            plan = _prepare(
                Path(temp) / "project.json",
                _payload(owner_id=None, char_name=None),
            )

        self.assertEqual(plan.owner_id, 0)
        self.assertEqual(plan.character_name, "")

    def test_midi_meter_and_reference_existence_use_explicit_ports(self) -> None:
        seen: list[Path] = []

        def exists(path: Path) -> bool:
            return path.name in {"source.mid", "reference.wav"}

        def meter(path: Path) -> int:
            seen.append(path)
            return 8

        with tempfile.TemporaryDirectory() as temp:
            plan = _prepare(
                Path(temp) / "project.json",
                _payload(
                    source_format="midi",
                    source_midi_path="source.mid",
                    time_sig_denominator=None,
                    reference_audio_path="reference.wav",
                ),
                file_exists=exists,
                meter_reader=meter,
            )

        self.assertEqual(plan.time_signature_denominator, 8)
        self.assertEqual([path.name for path in seen], ["source.mid"])
        self.assertEqual(plan.reference.candidate_path.name, "reference.wav")


if __name__ == "__main__":
    unittest.main()
