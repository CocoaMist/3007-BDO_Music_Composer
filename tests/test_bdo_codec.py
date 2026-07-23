from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

from bdo_codec import (
    BdoDocument, BdoHeader, BdoInstrumentGroup, BdoNote, BdoTrack,
    BdoTrackSettings, UnsafeOpaqueDataError, decode_score, document_from_dict,
    document_matches_logical_tracks, document_to_dict, encode_score, validate_score,
)
from bdo_codec.ice import decrypt, encrypt
from pyside_bdo_gui import Note, channel_groups_to_bdo


def document_with(notes: tuple[BdoNote, ...], *, extra: bytes = b"") -> BdoDocument:
    settings = BdoTrackSettings(tuple(range(8)))
    tracks = (
        BdoTrack(0x11, 100, settings, notes, extra_data=extra),
        BdoTrack(0x11, 100, settings, ()),
    )
    return BdoDocument(
        version=9,
        header=BdoHeader(12345, b"\x01\x02\x03\x04", "Name", "Name", 120, 4, ""),
        groups=(BdoInstrumentGroup(tracks),),
    )


class IceCodecTests(unittest.TestCase):
    def test_fixed_vectors_and_inverse(self) -> None:
        vectors = {
            "0000000000000000": "41ef586af7ca4f0e",
            "0001020304050607": "c3bdf28b3c7dde63",
            "0011223344556677": "ad82068a1a7a89a9",
            "000102030405060708090a0b0c0d0e0f": "c3bdf28b3c7dde63bccdf2d6ce3ace8e",
        }
        for plaintext, ciphertext in vectors.items():
            with self.subTest(plaintext=plaintext):
                self.assertEqual(encrypt(bytes.fromhex(plaintext)).hex(), ciphertext)
                self.assertEqual(decrypt(bytes.fromhex(ciphertext)).hex(), plaintext)

    def test_rejects_unaligned_payload(self) -> None:
        with self.assertRaises(ValueError):
            encrypt(b"unaligned")


class ScoreCodecTests(unittest.TestCase):
    def test_all_note_types_and_wire_fields_roundtrip(self) -> None:
        notes = tuple(
            BdoNote(index % 128, index, index % 128, (127 - index) % 128,
                    index * 0.125, 0.001 + index / 7.0)
            for index in range(256)
        )
        encoded = encode_score(document_with(notes), mode="canonical")
        decoded = decode_score(encoded)
        track = decoded.groups[0].tracks[0]
        self.assertEqual([note.ntype for note in track.notes], list(range(256)))
        self.assertEqual(track.volume, 100)
        self.assertEqual(track.settings.values, tuple(range(8)))
        self.assertEqual(track.notes[1].velocity_b, 126)
        self.assertEqual(encode_score(decoded, mode="lossless"), encoded)

    def test_json_document_is_semantically_reversible(self) -> None:
        original = document_with((BdoNote(60, 11, 90, 73, 0.25, 123.456789),))
        payload = document_to_dict(original)
        rebuilt = document_from_dict(json.loads(json.dumps(payload)))
        decoded = decode_score(encode_score(rebuilt, mode="canonical"))
        self.assertEqual(decoded.groups[0].tracks[0].notes, original.groups[0].tracks[0].notes)
        self.assertEqual(decoded.groups[0].tracks[0].settings, original.groups[0].tracks[0].settings)
        self.assertEqual(decoded.groups[0].tracks[0].volume, original.groups[0].tracks[0].volume)

    def test_opaque_track_data_is_preserved_and_blocks_note_count_change(self) -> None:
        encoded = encode_score(
            document_with((BdoNote(60, 0, 90, 90, 0.0, 100.0),), extra=b"\x12\x34"),
            mode="canonical",
        )
        decoded = decode_score(encoded)
        self.assertEqual(decoded.groups[0].tracks[0].extra_data, b"\x12\x34")
        self.assertTrue(any(issue.code == "tracks.opaque_data" for issue in validate_score(decoded)))
        changed_track = replace(
            decoded.groups[0].tracks[0],
            notes=decoded.groups[0].tracks[0].notes + (BdoNote(61, 0, 90, 90, 200.0, 100.0),),
        )
        changed_group = replace(decoded.groups[0], tracks=(changed_track, decoded.groups[0].tracks[1]))
        with self.assertRaises(UnsafeOpaqueDataError):
            encode_score(replace(decoded, groups=(changed_group,)), mode="lossless")

    def test_legacy_facade_preserves_volume_settings_and_second_velocity(self) -> None:
        settings = (9, 10, 11, 12, 13, 14, 15, 16)
        source = [Note(60, 91, 1.25, 300.5, 11)]
        encoded, _summary = channel_groups_to_bdo(
            120, 4, [(source, 0, False)], instrument_map={0: 0x11},
            preserve_note_types=True, track_volumes={0: 101},
            track_settings_map={0: settings},
            velocity_b_maps={0: [(60, 91, 1.25, 300.5, 11, 72)]},
        )
        track = decode_score(encoded).groups[0].tracks[0]
        self.assertEqual(track.volume, 101)
        self.assertEqual(track.settings.values, settings)
        self.assertEqual(track.notes[0].velocity_b, 72)

    def test_editor_adapter_recognizes_an_untouched_projection(self) -> None:
        encoded = encode_score(
            document_with((BdoNote(60, 11, 91, 72, 1.25, 300.5),)),
            mode="canonical",
        )
        document = decode_score(encoded)
        logical_track = SimpleNamespace(
            bdo_source_group_index=0,
            bdo_track_volume=100,
            duration_scale=1.0,
            volume_scale=1.0,
            notes=[Note(60, 91, 1.25, 300.5, 11)],
        )
        self.assertTrue(document_matches_logical_tracks(
            document,
            [logical_track],
            instrument_ids=[0x11],
            track_settings=[tuple(range(8))],
            owner_id=12345,
            character_name="Name",
            bpm=120,
            time_signature=4,
        ))
        logical_track.notes[0] = logical_track.notes[0]._replace(vel=92)
        self.assertFalse(document_matches_logical_tracks(
            document,
            [logical_track],
            instrument_ids=[0x11],
            track_settings=[tuple(range(8))],
            owner_id=12345,
            character_name="Name",
            bpm=120,
            time_signature=4,
        ))

    def test_split_at_730_and_empty_trailing_track(self) -> None:
        source = [Note(60, 90, index * 10.0, 5.0, 0) for index in range(731)]
        encoded, _summary = channel_groups_to_bdo(
            120, 4, [(source, 0, False)], instrument_map={0: 0x11}, preserve_note_types=True,
        )
        group = decode_score(encoded).groups[0]
        self.assertEqual([len(track.notes) for track in group.tracks], [730, 1, 0])

    def test_cli_roundtrip_and_private_redaction(self) -> None:
        encoded = encode_score(document_with((BdoNote(60, 0, 90, 90, 0.0, 100.0),)), mode="canonical")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "score"
            path.write_bytes(encoded)
            result = subprocess.run(
                [sys.executable, "-m", "bdo_codec", "roundtrip", str(path), "--verify-bytes"],
                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            inspect = subprocess.run(
                [sys.executable, "-m", "bdo_codec", "inspect", str(path)],
                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
            )
            self.assertEqual(inspect.returncode, 0, inspect.stderr)
            self.assertNotIn("Name", inspect.stdout)
            self.assertIn("<redacted>", inspect.stdout)


if __name__ == "__main__":
    unittest.main()
