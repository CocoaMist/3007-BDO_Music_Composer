# Black Desert Music Conversion Notes

Status checked: 2026-07-07.

## Local setup

The converter is vendored at:

```text
tools/midi-to-bdo
```

Install dependencies in the project virtualenv:

```powershell
& .\.venv\Scripts\python.exe -m pip install -r tools\midi-to-bdo\requirements.txt
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

The upstream tool intentionally only extracts owner data from very small
single-note files.

## Important converter behavior

- BDO file format version: 9.
- BDO melodic pitch range is MIDI note 24 through 108.
- Out-of-range notes are octave-shifted into range, then clamped.
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

Treat `tools/midi-to-bdo/midi2bdo.py` as the low-level encoder. Project code
should generate or clean MIDI, then call `scripts/bdo_convert.py` or import
`midi_to_bdo()` directly.
