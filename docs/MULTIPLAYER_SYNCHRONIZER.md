# 多人同步器：界面先占位，网络暂不开

## Product decision

工具栏只展示 **多人同步** 房间预览。协议、安全和延迟验证没完成前，不启用任何网络
传输；旧的本地节拍器和硬件选项也不会回来冒充多人同步。

The reserved room contains:

- host/join role, IP address or host name, port and six-digit PIN;
- Beijing-time display and a user-selected countdown duration;
- the read-only project Global BPM and meter;
- connection/clock-quality status;
- Team A / Team B leaders plus future member readiness and latency rows.

The disabled create/join buttons are intentional. A PIN authenticates a room
but is not encryption, NAT traversal is not designed yet, and the tool does not
send game input.

## Game-informed interaction

The current Black Desert Music Album guide says ensemble play is available to
players in the same party. The FFXIV official Ensemble Mode uses a party ready
check and metronome to coordinate performance. The external room therefore
coordinates people—especially two party leaders—around one future start time;
it does not bypass either game's party rules or automate performance actions.

Research references:

- Black Desert official Music Album guide:
  <https://www.jp.playblackdesert.com/ja-JP/Wiki?wikiNo=272>
- FFXIV official Ensemble Mode overview:
  <https://na.finalfantasyxiv.com/blog/002867.html>
- Qt asynchronous TCP client/server APIs:
  <https://doc.qt.io/qt-6/qtnetwork-programming.html>
- NTP delay/offset model (RFC 5905):
  <https://datatracker.ietf.org/doc/html/rfc5905>

## Future protocol

`NetworkRoomDraft` is the immutable UI-to-transport hand-off. A later network
owner should use asynchronous sockets and a versioned bounded message format.
Joining should require a nonce-backed PIN challenge; Internet use requires an
authenticated encrypted transport rather than sending the PIN as plaintext.

Clock sync should exchange four timestamps repeatedly, reject high-jitter
samples, estimate round-trip delay and clock offset, then broadcast a future
absolute start epoch. Each client maps that epoch to a local monotonic clock
for the final countdown. Beijing time is display-only and must never replace
the monotonic deadline. Room state should expose ready/not-ready, last sample,
delay, offset, jitter and disconnect reason.

## Global BPM and reference music

`WorkspaceTempoHostMixin` owns the single project BPM. A direct edit disables
automatic reference following and updates timeline, preview, analysis,
autosave, conversion validation and BDO export together.

New projects default to **Follow reference BPM**. Attaching a reference file
starts a bounded background tempo estimate over at most three minutes. Strong
regular-onset evidence updates Global BPM; weak evidence preserves the current
value. Full transcription then performs a second pass from its cached onset
evidence. Manual edits always win until the user explicitly enables following
again.

```text
reference file -> bounded tempo estimate -> confidence gate
                                     strong -> Global BPM
full analysis -> cached onset estimate -----^

Global BPM -> ConversionSettings.bpm_override -> ExportRequest
           -> bdo_export -> BDO v9 header.bpm -> export verification
```

The binary/export compatibility range remains `1..200`; the current official
Black Desert composing guide documents `180` as the in-game authoring maximum.
The workspace explains that distinction instead of claiming every current
client accepts the binary compatibility maximum.

## Verification

- `tests/test_reference_tempo.py` covers bounded deterministic tempo evidence.
- `tests/test_workspace_tempo_ui.py` covers manual override, automatic follow,
  room fields, disabled network actions and BDO-header propagation.
- layout, localization, project-schema, export round-trip and full regression
  suites remain required.
