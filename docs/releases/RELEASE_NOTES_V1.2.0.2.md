# BDO Music Composer v1.2.0.2

> Status: test release record. Current architecture and compatibility
> documentation remain authoritative for later development.

v1.2.0.2 unifies percussion editing with the ordinary piano roll and aligns
game percussion names across the key rail and note blocks.

## Highlights

- Removed the separate diamond-marker percussion roll. Drum-set, hand-drum,
  cymbal, and handpan notes now use the same duration-aware rectangular blocks,
  velocity display, selection, move, and resize interactions as melodic notes.
- Preserved game-native key identities: the drum set uses its 17 verified BDO
  labels, the hand drum uses the verified `Bng*`/`Cng*` labels, and beginner
  cymbal lanes use `HIT`. Handpan remains a pitched roll because its complete
  game range is not yet verified.
- Synchronized note-block labels with the corresponding game key row while
  retaining localized explanations on the wider key rail.
- Kept canonical type-99 drum identity even when a draft contains an invalid
  pitch, so one validation error cannot relabel the entire track as GM drums.
- Changed low-level GM drum conversion to reject unmapped keys instead of
  silently exporting them as the BDO kick lane.

## Verification

The source release must pass the complete unit/UI/codec/audio suite, focused
percussion editor and export round trips, repository hygiene, source startup,
the public dependency-inventory gate, frozen Basic Pitch ONNX/CPU inference,
and the frozen ten-second GUI startup self-test. The GitHub update chain must
also pass detached manifest-signature, asset size/hash, anonymous raw-channel,
download, staging, and frozen apply/health-handshake checks.

## Important notes

- This is a positive fourth-component test revision after v1.2.0.1.
- This is an unofficial community tool and is not affiliated with Pearl Abyss.
- Update-manifest signatures protect the update chain but do not replace
  Windows Authenticode publisher signing; SmartScreen may still warn.
- Projects, Owner IDs, character names, reference audio, local game samples,
  autosaves, exports, private caches, and signing keys remain local.
