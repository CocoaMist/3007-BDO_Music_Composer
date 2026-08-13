from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest

import mido

from bdo_codec import (
    BdoDocument, BdoHeader, BdoInstrumentGroup, BdoNote, BdoTrack, BdoTrackSettings,
    encode_score,
)


_TOOL_PATH = Path(__file__).resolve().parents[1] / "tools" / "bdo_to_midi.py"
_SPEC = importlib.util.spec_from_file_location("bdo_to_midi_tool", _TOOL_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_TOOL = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_TOOL)


class BdoToMidiToolTests(unittest.TestCase):
    def _document(self) -> BdoDocument:
        settings = BdoTrackSettings((9, 8, 7, 6, 5, 4, 3, 2))
        piano = BdoTrack(0x11, 101, settings, (
            BdoNote(60, 17, 91, 72, 1.25, 300.5),
            BdoNote(64, 0, 63, 61, 1_000.125, 249.875),
        ))
        # Empty trailing physical BDO tracks are meaningful and must also survive.
        trailing = BdoTrack(0x11, 101, settings, ())
        drums = BdoTrack(0x0D, 70, BdoTrackSettings(), (
            BdoNote(48, 99, 100, 54, 500.0, 120.0),
        ))
        return BdoDocument(
            9, BdoHeader(123, b"\0" * 4, "Private", "Private", 137, 4, ""),
            (BdoInstrumentGroup((piano, trailing)), BdoInstrumentGroup((drums,))),
        )

    def test_projection_embeds_exact_note_records_and_playable_events(self) -> None:
        document = self._document()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "score.mid"
            _TOOL.convert_bdo_to_midi(document, output)
            self.assertEqual(_TOOL.lossless_metadata_from_midi(output), _TOOL._document_metadata(document))
            _TOOL.verify_lossless_metadata(document, output)

            midi = mido.MidiFile(output)
            note_on = [message for track in midi.tracks for message in track if message.type == "note_on"]
            self.assertEqual([(item.note, item.velocity) for item in note_on], [(60, 91), (64, 63), (48, 100)])
            drum_messages = [message for message in midi.tracks[3] if not message.is_meta]
            self.assertTrue(all(message.channel == 9 for message in drum_messages))

    def test_cli_refuses_overwrite_and_can_verify(self) -> None:
        document = self._document()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "score.bdo"
            output = root / "score.mid"
            source.write_bytes(encode_score(document, mode="canonical"))
            self.assertEqual(_TOOL.main([str(source), str(output), "--verify"]), 0)
            self.assertEqual(_TOOL.main([str(source), str(output)]), 2)
            self.assertEqual(_TOOL.main([str(source), str(output), "--force", "--verify"]), 0)
