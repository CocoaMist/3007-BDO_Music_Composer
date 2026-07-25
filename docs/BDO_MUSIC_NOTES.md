# Black Desert Music Conversion Notes

Status checked: 2026-07-23.

## Local setup

The conversion path is maintained by three project packages:

```text
bdo_midi   -> MIDI parsing, mappings, and note transforms
bdo_export -> editor/MIDI adaptation
bdo_codec  -> BDO v9 document model, binary encoding, and ICE
```

Install dependencies in the project virtualenv:

```powershell
& .\.venv\Scripts\python.exe -m pip install -r requirements-pyside.txt
```

Run the local wrapper:

```powershell
& .\.venv\Scripts\python.exe scripts\bdo_convert.py path\to\song.mid song_name
```

Default output:

```text
out/bdo/song_name
```

Copy directly to the game music folder:

```powershell
& .\.venv\Scripts\python.exe scripts\bdo_convert.py path\to\song.mid song_name --install
```

Default game folder:

```text
%USERPROFILE%\Documents\Black Desert\music
```

## Edit access in game

To edit an imported score in BDO, create a tiny one-note composition in-game
first, save it, then pass that file as the owner source:

```powershell
& .\.venv\Scripts\python.exe scripts\bdo_convert.py song.mid song_name --owner-file "C:\Users\you\Documents\Black Desert\music\one_note"
```

Owner data is read through the lossless v9 codec. Use only a score belonging to
your own account and never commit or attach that file to a release.

## Important converter behavior

- BDO file format version: 9.
- The broad verified BDO melodic range is MIDI note 12 through 119; individual
  instruments are validated against narrower game-evidence ranges.
- Out-of-range notes are clamped by the conversion adapter after transposition.
- MIDI channel 10, zero-based channel 9, is treated as percussion.
- General MIDI programs are mapped to available BDO instruments.
- Notes are merged by target BDO instrument.
- Each BDO track is split at 730 notes.
- Each instrument is capped at 10,000 notes.
- Sustain pedal CC64 can extend notes unless `--no-sustain` is used.
- Multi-tempo MIDI can use `--flatten-tempo`, which sets the BDO header BPM to
  200 while preserving real-time note positions.
- Output files have no extension.

## Useful options

```powershell
--transpose -12
--bpm 120
--vel 80 127
--vel-floor 90
--vel-step 80 5
--vel-layered
--reverb 30
--delay 20
--chorus 20 30 40
```

## Integration direction

Project code imports `Note` and `parse_midi()` from `bdo_midi`, and imports
`midi_to_bdo()` or `channel_groups_to_bdo()` from `bdo_export`. Binary format
work belongs only in `bdo_codec`; no historical vendor module or path fallback
is supported.
