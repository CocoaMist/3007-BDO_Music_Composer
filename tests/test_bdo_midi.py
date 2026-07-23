from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import mido

from bdo_midi import (
    BDO_INSTRUMENTS,
    Note,
    gm_program_name,
    gm_to_bdo_instrument,
    map_drum_notes,
    parse_midi,
)


class MidiParserTests(unittest.TestCase):
    def _save(self, tracks: list[list[mido.Message | mido.MetaMessage]]) -> Path:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "fixture.mid"
        midi = mido.MidiFile(type=1 if len(tracks) > 1 else 0, ticks_per_beat=480)
        for messages in tracks:
            track = mido.MidiTrack()
            track.extend(messages)
            midi.tracks.append(track)
        midi.save(path)
        return path

    def test_default_tempo_and_note_on_zero(self) -> None:
        path = self._save([[
            mido.Message("note_on", channel=0, note=60, velocity=90, time=0),
            mido.Message("note_on", channel=0, note=60, velocity=0, time=480),
        ]])
        bpm, meter, groups, tempo_count = parse_midi(path)
        self.assertEqual((bpm, meter, tempo_count), (120, 4, 1))
        self.assertAlmostEqual(groups[0][0][0].dur, 500.0)

    def test_program_changes_split_groups_and_channel_ten_is_percussion(self) -> None:
        path = self._save([[
            mido.Message("program_change", channel=0, program=40, time=0),
            mido.Message("note_on", channel=0, note=60, velocity=90, time=0),
            mido.Message("note_off", channel=0, note=60, velocity=0, time=120),
            mido.Message("program_change", channel=0, program=24, time=0),
            mido.Message("note_on", channel=0, note=64, velocity=90, time=0),
            mido.Message("note_off", channel=0, note=64, velocity=0, time=120),
            mido.Message("program_change", channel=9, program=99, time=0),
            mido.Message("note_on", channel=9, note=36, velocity=100, time=0),
            mido.Message("note_off", channel=9, note=36, velocity=0, time=120),
        ]])
        groups = parse_midi(path)[2]
        self.assertEqual([(program, drums) for _notes, program, drums in groups], [
            (24, False), (40, False), (0, True),
        ])

    def test_repeated_note_closes_previous_voice(self) -> None:
        path = self._save([[
            mido.Message("note_on", channel=0, note=60, velocity=70, time=0),
            mido.Message("note_on", channel=0, note=60, velocity=90, time=240),
            mido.Message("note_off", channel=0, note=60, velocity=0, time=240),
        ]])
        notes = parse_midi(path)[2][0][0]
        self.assertEqual([note.vel for note in notes], [70, 90])
        self.assertEqual([round(note.dur) for note in notes], [250, 250])

    def test_sustain_extends_note_and_control_is_aligned(self) -> None:
        path = self._save([[
            mido.Message("control_change", channel=0, control=64, value=127, time=0),
            mido.Message("note_on", channel=0, note=60, velocity=90, time=0),
            mido.Message("note_off", channel=0, note=60, velocity=0, time=240),
            mido.Message("control_change", channel=0, control=64, value=0, time=240),
        ]])
        parsed = parse_midi(path, include_controls=True)
        self.assertAlmostEqual(parsed[2][0][0][0].dur, 500.0)
        self.assertEqual([event["value"] for event in parsed[4][0]], [127, 0])

    def test_controls_text_and_dangling_note_are_preserved(self) -> None:
        path = self._save([[
            mido.MetaMessage("lyrics", text="hello", time=0),
            mido.Message("pitchwheel", channel=0, pitch=1000, time=0),
            mido.Message("aftertouch", channel=0, value=60, time=0),
            mido.Message("polytouch", channel=0, note=62, value=50, time=0),
            mido.Message("note_on", channel=0, note=62, velocity=80, time=0),
        ]])
        parsed = parse_midi(path, include_controls=True, include_lyrics=True)
        self.assertEqual(parsed[2][0][0][0].dur, 100.0)
        self.assertEqual({event["kind"] for event in parsed[4][0]}, {
            "pitchwheel", "aftertouch", "polytouch",
        })
        self.assertEqual(parsed[5][0]["text"], "hello")

    def test_duplicate_tempo_tick_uses_last_event_and_flatten_mode(self) -> None:
        path = self._save([[
            mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(90), time=0),
            mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(100), time=0),
            mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(140), time=480),
            mido.Message("note_on", channel=0, note=60, velocity=90, time=0),
            mido.Message("note_off", channel=0, note=60, velocity=0, time=480),
        ]])
        self.assertEqual(parse_midi(path)[:2], (100, 4))
        self.assertEqual(parse_midi(path, flatten_tempo=True)[0], 200)
        self.assertEqual(parse_midi(path)[3], 2)

    def test_non_quarter_denominator_is_rejected(self) -> None:
        path = self._save([[
            mido.MetaMessage("time_signature", numerator=6, denominator=8, time=0),
        ]])
        with self.assertRaisesRegex(ValueError, "only supports a /4 meter"):
            parse_midi(path)

    def test_asynchronous_type_two_file_is_rejected(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "type2.mid"
        midi = mido.MidiFile(type=2, ticks_per_beat=480)
        midi.tracks.append(mido.MidiTrack())
        midi.tracks.append(mido.MidiTrack())
        midi.save(path)
        with self.assertRaisesRegex(ValueError, "asynchronous tracks"):
            parse_midi(path)


class MidiMappingTests(unittest.TestCase):
    def test_every_gm_program_has_a_name_and_deterministic_mapping(self) -> None:
        for program in range(128):
            self.assertNotEqual(gm_program_name(program), f"Program {program}")
            self.assertEqual(
                gm_to_bdo_instrument(program),
                gm_to_bdo_instrument(program),
            )
            self.assertIn(gm_to_bdo_instrument(program), BDO_INSTRUMENTS.values())

    def test_canonical_drum_is_not_remapped(self) -> None:
        mapped = map_drum_notes([Note(48, 90, 0.0, 120.0, 99)])
        self.assertEqual((mapped[0].pitch, mapped[0].ntype), (48, 99))


if __name__ == "__main__":
    unittest.main()
