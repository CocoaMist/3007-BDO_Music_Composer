from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bdo_codec import decode_score, encode_score
from bdo_codec.ice import decrypt as decrypt_ice, encrypt as encrypt_ice
from bdo_export import channel_groups_to_bdo
from bdo_midi import Note
from bdo_music_composer.core.conversion_settings import ConversionSettings
from bdo_music_composer.export.export_verification import (
    ExportVerificationIssue,
    ExportVerificationReport,
    build_export_expectation,
    verify_export_bytes,
    verify_published_export,
)
from bdo_music_composer.export.export_workflow import (
    ExportRequest,
    execute_export,
    freeze_export_tracks,
    prepare_export,
)
from bdo_music_composer.editor.pitch_transform import PitchTransformPlan


@dataclass
class MutableTrack:
    notes: list[Note]
    track_id: int = 0
    gm_program: int = 0
    is_percussion: bool = False
    bdo_instrument_id: int = 0x0B
    marnian_synth_mode: str = "basic"
    duration_scale: float = 1.0
    volume_scale: float = 1.0
    articulation_type: int | None = None
    bdo_track_volume: int = 70
    bdo_track_settings: tuple[int, ...] = (0,) * 8
    bdo_source_group_index: int | None = None
    bdo_source_note_records: tuple[tuple, ...] = ()


def make_request(
    root: Path,
    tracks: list[MutableTrack],
    *,
    source_document: object | None = None,
    character_name: str = "MIDI",
) -> ExportRequest:
    snapshots = freeze_export_tracks(tracks)
    return ExportRequest(
        direct_tracks=snapshots,
        bpm=120,
        time_signature=4,
        out_path=root / "out" / "score.bdo",
        character_name=character_name,
        owner_id=123,
        conversion=ConversionSettings(),
        pitch_plan=PitchTransformPlan(0),
        reverb=0,
        delay=0,
        chorus=None,
        game_dir=root / "game",
        articulation_map=tuple(
            (index, int(track.articulation_type))
            for index, track in enumerate(snapshots)
            if track.articulation_type is not None
        ),
        track_volumes=tuple(
            (index, track.bdo_track_volume)
            for index, track in enumerate(snapshots)
        ),
        track_settings=tuple(
            (index, track.bdo_track_settings)
            for index, track in enumerate(snapshots)
        ),
        velocity_b_maps=tuple(
            (index, track.bdo_source_note_records)
            for index, track in enumerate(snapshots)
            if track.bdo_source_note_records
        ),
        source_document=source_document,
    )


class ExportVerificationTests(unittest.TestCase):
    def test_canonical_projection_checks_730_split_and_all_note_fields(self) -> None:
        notes = [
            Note(60 + index % 5, index % 128, index * 2.0, 0.0, index % 3)
            for index in range(731)
        ]
        track = MutableTrack(
            notes,
            duration_scale=0.0,
            bdo_track_volume=83,
            bdo_track_settings=(10, 1, 20, 2, 30, 3, 4, 5),
        )
        with tempfile.TemporaryDirectory() as temp:
            request = make_request(Path(temp), [track])
            expectation = build_export_expectation(request)
            prepared = prepare_export(request)
            report = verify_export_bytes(expectation, prepared.data)

        self.assertTrue(report.matches, report.issues)
        self.assertEqual(
            expectation.instruments[0].physical_note_counts,
            (730, 1, 0),
        )
        self.assertTrue(all(
            note.dur == 1.0 for note in expectation.instruments[0].notes
        ))

    def test_same_note_count_with_changed_pitch_is_not_a_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            request = make_request(Path(temp), [
                MutableTrack([Note(60, 91, 0.0, 250.0, 11)])
            ])
            expectation = build_export_expectation(request)
            document = decode_score(prepare_export(request).data)
            group = document.groups[0]
            active = group.tracks[0]
            changed_note = replace(active.notes[0], pitch=61)
            changed_track = replace(active, notes=(changed_note,))
            changed_group = replace(
                group,
                tracks=(changed_track, *group.tracks[1:]),
            )
            changed_data = encode_score(
                replace(document, groups=(changed_group,)),
                mode="canonical",
            )

        report = verify_export_bytes(expectation, changed_data)
        self.assertFalse(report.matches)
        self.assertIn(
            "notes.identity_count_mismatch",
            {issue.code for issue in report.issues},
        )

    def test_group_order_and_physical_layout_are_not_aggregated_away(self) -> None:
        tracks = [
            MutableTrack(
                [Note(60, 90, 0.0, 100.0, 0)],
                track_id=1,
                bdo_instrument_id=0x0B,
            ),
            MutableTrack(
                [Note(64, 80, 200.0, 100.0, 0)],
                track_id=2,
                bdo_instrument_id=0x0C,
            ),
        ]
        with tempfile.TemporaryDirectory() as temp:
            request = make_request(Path(temp), tracks)
            expectation = build_export_expectation(request)
            document = decode_score(prepare_export(request).data)
            reversed_data = encode_score(
                replace(document, groups=tuple(reversed(document.groups))),
                mode="canonical",
            )

        reversed_report = verify_export_bytes(expectation, reversed_data)
        self.assertFalse(reversed_report.matches)
        self.assertIn(
            "groups.instrument_mismatch",
            {issue.code for issue in reversed_report.issues},
        )

        with tempfile.TemporaryDirectory() as temp:
            request = make_request(Path(temp), [MutableTrack([
                Note(60 + index, 90, index * 100.0, 80.0, 0)
                for index in range(3)
            ])])
            expectation = build_export_expectation(request)
            document = decode_score(prepare_export(request).data)
            group = document.groups[0]
            active, trailing = group.tracks
            split_group = replace(group, tracks=(
                replace(active, notes=active.notes[:1]),
                replace(active, notes=active.notes[1:]),
                trailing,
            ))
            split_data = encode_score(
                replace(document, groups=(split_group,)),
                mode="canonical",
            )

        split_report = verify_export_bytes(expectation, split_data)
        self.assertFalse(split_report.matches)
        self.assertIn(
            "groups.physical_layout_mismatch",
            {issue.code for issue in split_report.issues},
        )

    def test_time_tolerance_pairs_notes_by_discrete_identity(self) -> None:
        notes = [
            Note(60, 90, 0.0, 100.0, 0),
            Note(60, 90, 0.0009, 200.0, 0),
        ]
        with tempfile.TemporaryDirectory() as temp:
            request = make_request(Path(temp), [MutableTrack(notes)])
            expectation = build_export_expectation(request)
            document = decode_score(prepare_export(request).data)
            group = document.groups[0]
            active = group.tracks[0]
            moved = (
                replace(active.notes[0], start_ms=0.0009),
                replace(active.notes[1], start_ms=0.0),
            )
            moved_group = replace(
                group,
                tracks=(replace(active, notes=moved), *group.tracks[1:]),
            )
            moved_data = encode_score(
                replace(document, groups=(moved_group,)),
                mode="canonical",
            )

        self.assertTrue(
            verify_export_bytes(expectation, moved_data).matches
        )

    def test_dual_velocity_survives_identity_changing_projection(self) -> None:
        source_record = (60, 91, 1.25, 300.5, 0, 72)
        track = MutableTrack(
            [Note(60, 91, 1.25, 300.5, 0)],
            duration_scale=0.5,
            articulation_type=44,
            bdo_source_note_records=(source_record,),
        )
        with tempfile.TemporaryDirectory() as temp:
            request = make_request(Path(temp), [track])
            request = replace(
                request,
                conversion=request.conversion.with_updates(transpose=12),
                pitch_plan=PitchTransformPlan(12),
            )
            expectation = build_export_expectation(request)
            prepared = prepare_export(request)
            document = decode_score(prepared.data)

        note = document.groups[0].tracks[0].notes[0]
        self.assertEqual(
            (
                note.pitch,
                note.velocity_a,
                note.velocity_b,
                note.duration_ms,
                note.ntype,
            ),
            (72, 91, 72, 150.25, 44),
        )
        self.assertTrue(
            verify_export_bytes(expectation, prepared.data).matches
        )

    def test_dual_velocity_survives_drum_mapping(self) -> None:
        source_record = (36, 91, 0.0, 300.0, 0, 72)
        track = MutableTrack(
            [Note(36, 91, 0.0, 300.0, 0)],
            is_percussion=True,
            bdo_instrument_id=0x0D,
            bdo_source_note_records=(source_record,),
        )
        with tempfile.TemporaryDirectory() as temp:
            request = make_request(Path(temp), [track])
            expectation = build_export_expectation(request)
            prepared = prepare_export(request)
            note = decode_score(prepared.data).groups[0].tracks[0].notes[0]

        self.assertEqual((note.velocity_a, note.velocity_b), (91, 72))
        self.assertEqual(note.ntype, 99)
        self.assertTrue(
            verify_export_bytes(expectation, prepared.data).matches
        )

    def test_source_reuse_honors_requested_volume_and_velocity_b(self) -> None:
        source_record = (60, 91, 1.25, 300.5, 11, 72)
        source_data, _summary = channel_groups_to_bdo(
            120,
            4,
            [([Note(60, 91, 1.25, 300.5, 11)], 0, False)],
            char_name="MIDI",
            owner_id=123,
            instrument_map={0: 0x0B},
            preserve_note_types=True,
            track_volumes={0: 70},
            track_settings_map={0: (0,) * 8},
            velocity_b_maps={0: (source_record,)},
        )
        source_track = MutableTrack(
            [Note(60, 91, 1.25, 300.5, 11)],
            bdo_source_group_index=0,
            bdo_source_note_records=(source_record,),
        )
        with tempfile.TemporaryDirectory() as temp:
            request = make_request(
                Path(temp),
                [source_track],
                source_document=decode_score(source_data),
            )
            volume_request = replace(request, track_volumes=((0, 99),))
            volume_expectation = build_export_expectation(volume_request)
            volume_data = prepare_export(volume_request).data
            changed_record = (*source_record[:5], 99)
            velocity_request = replace(
                request,
                velocity_b_maps=((0, (changed_record,)),),
            )
            velocity_expectation = build_export_expectation(velocity_request)
            velocity_data = prepare_export(velocity_request).data

        self.assertFalse(volume_expectation.preserves_source_groups)
        self.assertEqual(
            decode_score(volume_data).groups[0].tracks[0].volume,
            99,
        )
        self.assertTrue(
            verify_export_bytes(volume_expectation, volume_data).matches
        )
        self.assertFalse(velocity_expectation.preserves_source_groups)
        self.assertEqual(
            decode_score(velocity_data).groups[0].tracks[0].notes[0].velocity_b,
            99,
        )
        self.assertTrue(
            verify_export_bytes(velocity_expectation, velocity_data).matches
        )

    def test_snapshot_mix_fields_are_fallbacks_for_compat_requests(self) -> None:
        source_record = (60, 91, 1.25, 300.5, 11, 72)
        track = MutableTrack(
            [Note(60, 91, 1.25, 300.5, 11)],
            bdo_track_volume=83,
            bdo_source_note_records=(source_record,),
        )
        with tempfile.TemporaryDirectory() as temp:
            request = make_request(Path(temp), [track])
            compatibility_request = replace(
                request,
                track_volumes=(),
                velocity_b_maps=(),
            )
            expectation = build_export_expectation(compatibility_request)
            prepared = prepare_export(compatibility_request)
            active = decode_score(prepared.data).groups[0].tracks[0]

        self.assertEqual(active.volume, 83)
        self.assertEqual(active.notes[0].velocity_b, 72)
        self.assertTrue(
            verify_export_bytes(expectation, prepared.data).matches
        )

    def test_source_reuse_is_note_container_order_independent(self) -> None:
        source_notes = [
            Note(60, 91, 0.0, 100.0, 0),
            Note(64, 82, 200.0, 150.0, 11),
        ]
        source_data, _summary = channel_groups_to_bdo(
            120,
            4,
            [(source_notes, 0, False)],
            char_name="MIDI",
            owner_id=123,
            instrument_map={0: 0x0B},
            preserve_note_types=True,
            track_volumes={0: 70},
            track_settings_map={0: (0,) * 8},
        )
        with tempfile.TemporaryDirectory() as temp:
            request = make_request(
                Path(temp),
                [MutableTrack(
                    list(reversed(source_notes)),
                    bdo_source_group_index=0,
                )],
                source_document=decode_score(source_data),
            )
            expectation = build_export_expectation(request)
            prepared = prepare_export(request)

        self.assertTrue(expectation.preserves_source_groups)
        self.assertEqual(prepared.data, source_data)
        self.assertTrue(verify_export_bytes(expectation, prepared.data).matches)

    def test_percussion_semantic_change_disables_source_reuse(self) -> None:
        source_note = Note(60, 90, 0.0, 200.0, 0)
        source_data, _summary = channel_groups_to_bdo(
            120,
            4,
            [([source_note], 0, False)],
            char_name="MIDI",
            owner_id=123,
            instrument_map={0: 0x0B},
            preserve_note_types=True,
            track_volumes={0: 70},
            track_settings_map={0: (0,) * 8},
        )
        with tempfile.TemporaryDirectory() as temp:
            request = make_request(
                Path(temp),
                [MutableTrack(
                    [source_note],
                    is_percussion=True,
                    bdo_instrument_id=0x0B,
                    bdo_source_group_index=0,
                )],
                source_document=decode_score(source_data),
            )
            expectation = build_export_expectation(request)
            prepared = prepare_export(request)
            note = decode_score(prepared.data).groups[0].tracks[0].notes[0]

        self.assertFalse(expectation.preserves_source_groups)
        self.assertEqual(note.ntype, 99)
        self.assertTrue(verify_export_bytes(expectation, prepared.data).matches)

    def test_any_authored_duration_scale_disables_source_reuse(self) -> None:
        source_note = Note(60, 90, 0.0, 10_000_000.0, 0)
        source_data, _summary = channel_groups_to_bdo(
            120,
            4,
            [([source_note], 0, False)],
            char_name="MIDI",
            owner_id=123,
            instrument_map={0: 0x0B},
            preserve_note_types=True,
            track_volumes={0: 70},
            track_settings_map={0: (0,) * 8},
        )
        with tempfile.TemporaryDirectory() as temp:
            request = make_request(
                Path(temp),
                [MutableTrack(
                    [source_note],
                    duration_scale=1.0000000005,
                    bdo_source_group_index=0,
                )],
                source_document=decode_score(source_data),
            )
            expectation = build_export_expectation(request)
            prepared = prepare_export(request)
            duration = decode_score(
                prepared.data
            ).groups[0].tracks[0].notes[0].duration_ms

        self.assertFalse(expectation.preserves_source_groups)
        self.assertAlmostEqual(duration, 10_000_000.005, places=6)
        self.assertTrue(verify_export_bytes(expectation, prepared.data).matches)

    def test_canonical_note_order_and_padding_are_verified(self) -> None:
        notes = [
            Note(60, 90, 0.0, 100.0, 0),
            Note(60, 90, 200.0, 100.0, 0),
        ]
        with tempfile.TemporaryDirectory() as temp:
            request = make_request(Path(temp), [MutableTrack(notes)])
            expectation = build_export_expectation(request)
            prepared = prepare_export(request)
            document = decode_score(prepared.data)
            group = document.groups[0]
            active = group.tracks[0]
            reversed_group = replace(group, tracks=(
                replace(active, notes=tuple(reversed(active.notes))),
                *group.tracks[1:],
            ))
            reversed_data = encode_score(
                replace(document, groups=(reversed_group,)),
                mode="canonical",
            )
            plaintext = decrypt_ice(prepared.data[4:])
            padded_data = prepared.data[:4] + encrypt_ice(
                plaintext + b"\x00" * 8
            )

        order_report = verify_export_bytes(expectation, reversed_data)
        self.assertFalse(order_report.matches)
        self.assertIn(
            "wire.note_order_invalid",
            {issue.code for issue in order_report.issues},
        )
        padding_report = verify_export_bytes(expectation, padded_data)
        self.assertFalse(padding_report.matches)
        self.assertIn(
            "wire.trailing_data",
            {issue.code for issue in padding_report.issues},
        )

    def test_lossless_source_reuse_accepts_encoded_legacy_note_times(self) -> None:
        legacy_times = ((-1.0, 100.0), (0.0, 0.0), (0.0, -1.0))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = make_request(root, [
                MutableTrack([Note(60, 90, 0.0, 100.0, 0)])
            ])
            document = decode_score(prepare_export(base).data)
            group = document.groups[0]
            active = group.tracks[0]
            for start, duration in legacy_times:
                source_note = replace(
                    active.notes[0],
                    start_ms=start,
                    duration_ms=duration,
                )
                source_group = replace(group, tracks=(
                    replace(active, notes=(source_note,)),
                    *group.tracks[1:],
                ))
                source_data = encode_score(
                    replace(document, groups=(source_group,)),
                    mode="canonical",
                )
                source_document = decode_score(source_data)
                editor_track = MutableTrack(
                    [Note(60, 90, start, duration, 0)],
                    bdo_source_group_index=0,
                )
                request = make_request(
                    root,
                    [editor_track],
                    source_document=source_document,
                )
                expectation = build_export_expectation(request)

                self.assertTrue(expectation.preserves_source_groups)
                self.assertEqual(prepare_export(request).data, source_data)
                self.assertTrue(
                    verify_export_bytes(expectation, source_data).matches
                )

    def test_lossless_source_reuse_requires_original_bytes_and_layout(self) -> None:
        source_record = (60, 91, 1.25, 300.5, 11, 72)
        canonical_data, _summary = channel_groups_to_bdo(
            120,
            4,
            [([Note(60, 91, 1.25, 300.5, 11)], 0, False)],
            char_name="MIDI",
            owner_id=123,
            instrument_map={0: 0x0B},
            preserve_note_types=True,
            track_volumes={0: 70},
            track_settings_map={0: (0,) * 8},
            velocity_b_maps={0: (source_record,)},
        )
        canonical_document = decode_score(canonical_data)
        legacy_header = replace(
            canonical_document.header,
            instrument_tag="legacy-tag",
        )
        source_data = encode_score(
            replace(canonical_document, header=legacy_header),
            mode="lossless",
        )
        source_document = decode_score(source_data)
        source_track = MutableTrack(
            [Note(60, 91, 1.25, 300.5, 11)],
            bdo_source_group_index=0,
            bdo_source_note_records=(source_record,),
        )
        with tempfile.TemporaryDirectory() as temp:
            request = make_request(
                Path(temp),
                [source_track],
                source_document=source_document,
            )
            expectation = build_export_expectation(request)
            prepared = prepare_export(request)

        self.assertTrue(expectation.preserves_source_groups)
        self.assertEqual(prepared.data, source_data)
        self.assertTrue(verify_export_bytes(expectation, source_data).matches)
        canonical_rewrite = encode_score(source_document, mode="canonical")
        rewrite_report = verify_export_bytes(expectation, canonical_rewrite)
        self.assertFalse(rewrite_report.matches)
        self.assertIn(
            "wire.source_bytes_mismatch",
            {issue.code for issue in rewrite_report.issues},
        )

    def test_empty_score_uses_the_two_track_canonical_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            request = make_request(Path(temp), [MutableTrack([])])
            expectation = build_export_expectation(request)
            prepared = prepare_export(request)

        self.assertEqual(
            expectation.instruments[0].physical_note_counts,
            (0, 0),
        )
        self.assertTrue(verify_export_bytes(expectation, prepared.data).matches)

    def test_character_name_truncation_is_rejected_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request = make_request(
                root,
                [MutableTrack([Note(60, 90, 0.0, 250.0, 0)])],
                character_name="X" * 40,
            )
            with self.assertRaisesRegex(ValueError, "losslessly"):
                execute_export(request)
            self.assertFalse(request.out_path.exists())
            self.assertFalse(request.game_dir.exists())

    def test_publication_report_detects_tampered_game_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request = make_request(root, [
                MutableTrack([Note(60, 90, 0.0, 250.0, 0)])
            ])
            expectation = build_export_expectation(request)
            prepared = prepare_export(request)
            request.out_path.parent.mkdir(parents=True)
            request.out_path.write_bytes(prepared.data)
            game_copy = root / "game" / "score.bdo"
            game_copy.parent.mkdir(parents=True)
            game_copy.write_bytes(b"not a score")
            report = verify_published_export(
                expectation,
                prepared.data,
                request.out_path,
                game_copy,
            )

        self.assertFalse(report.matches)
        self.assertTrue(report.stage_matches("primary"))
        self.assertFalse(report.stage_matches("game_copy"))

    def test_execute_export_attaches_all_successful_verification_stages(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            request = make_request(Path(temp), [
                MutableTrack([Note(60, 90, 0.0, 250.0, 0)])
            ])
            result = execute_export(request)

        report = result[2]["verification_report"]
        self.assertTrue(report.matches)
        self.assertEqual(
            report.checked_stages,
            ("prepared", "primary", "game_copy"),
        )

    def test_failed_prepared_verification_never_writes_or_installs(self) -> None:
        failed_report = ExportVerificationReport(
            issues=(ExportVerificationIssue(
                "prepared", "test.failure", "wire", "good", "bad"
            ),),
            omitted_issue_count=0,
            expected_note_count=1,
            actual_note_count=1,
            expected_instrument_count=1,
            actual_instrument_count=1,
            checked_stages=("prepared",),
        )
        with tempfile.TemporaryDirectory() as temp:
            request = make_request(Path(temp), [
                MutableTrack([Note(60, 90, 0.0, 250.0, 0)])
            ])
            with patch(
                "bdo_music_composer.export.export_workflow.verify_export_bytes",
                return_value=failed_report,
            ):
                with self.assertRaisesRegex(RuntimeError, "test.failure"):
                    execute_export(request)
            self.assertFalse(request.out_path.exists())
            self.assertFalse(request.game_dir.exists())

    def test_private_header_differences_are_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            request = make_request(Path(temp), [
                MutableTrack([Note(60, 90, 0.0, 250.0, 0)])
            ])
            expectation = build_export_expectation(request)
            document = decode_score(prepare_export(request).data)
            changed_data = encode_score(
                replace(
                    document,
                    header=replace(document.header, owner_id=456),
                ),
                mode="canonical",
            )

        report = verify_export_bytes(expectation, changed_data)
        owner_issue = next(
            issue for issue in report.issues
            if issue.path == "header.owner_id"
        )
        self.assertEqual(owner_issue.expected, "<redacted>")
        self.assertEqual(owner_issue.actual, "<redacted>")

    def test_omitted_issues_make_stage_success_conservative(self) -> None:
        report = ExportVerificationReport(
            issues=(),
            omitted_issue_count=1,
            expected_note_count=0,
            actual_note_count=0,
            expected_instrument_count=1,
            actual_instrument_count=1,
            checked_stages=("game_copy",),
        )
        self.assertFalse(report.stage_matches("game_copy"))


if __name__ == "__main__":
    unittest.main()
