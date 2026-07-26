# Changelog

## Unreleased

- 多轨时间轴把游戏轨道音量直接放入每一行并统一写入
  `bdo_track_volume`；新编辑范围与游戏一致为 0–100/default 70，实时与
  离线试听共用该增益。输出目录迁入设置，底边栏只保留性能指标。
- 按游戏作曲界面拆分每轨 Reverb/Delay/Chorus Send 与五项 Master FX；
  两层编辑互不覆盖，导入的 101–255 wire byte 在未编辑时无损保留。同一
  游戏乐器的音量或发送量冲突会在导出检查中阻止，不再静默择一。本地试听
  明确标记这些尚未 A/B 校准的 DSP 为未模拟。
- 统一实时试听、Seek、单音试听和离线渲染的声部生命周期：优先使用 Wwise
  Note-Off Release 与 WEM 循环证据，旧映射才回退到乐器族尾音；暂停真正挂起
  `QAudioSink` 并保留缓冲，继续不重触发，停止和定位丢弃旧 PCM。
- 统一乐器到 Wwise 音色库的路由和 GM→BDO 架子鼓映射；实时试听、离线
  渲染、转换检查与音域校验现在使用相同的键位/力度区间，并支持玛勒尼斯
  合成器四种音源模式。新增私有音源目录只读审计，可核对各乐器音块区间
  及本地 WEM/WAV 完整性。
- 从 Event→ActionPlay 自动恢复 102 个奏法路由，修正专业吉他 type 0/3
  对调，并接入父链 Volume、容器播放顺序/实例限制及 2193 条采样循环。
  8 个非零父链实例组由实时/离线共用的时间线规划器只执行一次。实时输出
  优先 36 kHz，以 1024 帧低/高水位批量补给；128 个活跃声部起在既有
  96 ms 缓冲内自适应到最多 2048 帧。同块多起音只遍历每个存活声部一次，
  同时间点复用压力清理，结束释放不再执行无声插值，并报告相对音频预算的
  P95 渲染负载。主时间轴与音符编辑器 Stop 均保留共享音频线程和解码缓存。
- 进一步优化多轨混音：预载期把不超过 192 MiB 的解码样本整理为只读 PCM
  arena，使固定 8 路插值瓦片可跨不同 Wwise 源聚合；fallback 奏法复用
  预分配 scratch，状态统计移出 transport 锁。真实 153 峰值声部对照中
  P95 从 12.577 ms 降至 9.919 ms（约 21.1%）；CPU/RAM、音频负载、XRUN
  与活跃声部数显示在时间轴下方。
- 新增本地游戏图导入：只解密用户 PAZ 中白名单作曲 CSS 与乐器 sprite，
  校验版本、路径、解压边界、裁切和缓存哈希后生成 26 张本地瓦片；游戏
  资源不进入工程、仓库或安装包。游戏注册表证据同时修正 ID 39 为单簧管，
  并把 10,000 音符改为工具软警戒线；730 只表示 v9 物理轨道容量。
- 主页支持置顶经过隐私清理且带来源标注的本地示例；当前维护者安装的
  “淘金小镇 · 示例”标注来源 MidiShow，但未经再分发许可的 MIDI 不随程序发布。
- 旋律声部骨架升级为缩放 LOD：远景半拍轮廓、中景音符/连接、近景弱分支，
  增加连续性主旋律 beam、低音/和声筛选、和弦支撑带和只读点击定位。

- Embed audio-assisted transcription in the existing note editor instead of a
  separate central page. Evidence, candidates, formal draft notes, and the
  aligned waveform share one piano roll, transport, playhead, zoom domain, and
  A–B loop.
- Add independent reference-audio offset and first-beat anchors, schema-v5
  lightweight candidate/assist review persistence, deterministic candidate
  routing, and atomic batch application to formal BDO tracks.
- Separate full-song Basic Pitch inference from cached interval re-decoding;
  validate exact frame-time evidence manifests and render pitch evidence through
  a bounded asynchronous tile cache.
- Add a versioned standard/mixed-enhanced analysis boundary, cache-v4 isolation,
  streamed SoundFile/soxr decoding, fast blockwise HPSS, sequential per-window
  evidence fusion, float16 single-timeline publication, sensitivity-consistent
  cache-only re-decoding, and a reproducible BabySlakh tuning/holdout
  benchmark. Runtime and resident-memory gates are measured in an independent
  pre-warmed process over the complete decode/infer/decode/cache pipeline. The
  v2 holdout improved onset+offset F1 by 0.02222, ran at 1.9668x standard, and
  peaked at 414.22 MiB, passing every fixed gate. New projects therefore
  default to mixed-enhanced analysis; migrated projects remain standard.
- Route initial inference, full-cache re-decode, and A–B re-decode through one
  frame-index candidate decoder over the exact persisted float16 evidence.
  Add deterministic `preserve`, `balanced`, and `clean` fragment handling with
  audit flags, source lineage, evidence-gated same-pitch NMS/merge, and
  reversible weak-fragment suppression. `preserve` is the safe default;
  selecting the experimental `balanced` or `clean` profile is the sole,
  explicit opt-in that executes its real actions. A separate preview API shows
  potential actions without applying them. Cleanup changes reuse the existing
  v4 evidence cache and never rerun ONNX/HPSS. Profile changes commit only
  after cache re-decoding succeeds and roll back the session, combo, and
  candidate projection on failure or cancellation. The analysis worker no
  longer has a legacy retry that can silently discard explicit decode options.
- Upgrade projects to schema v8 and transcription review payload v4. New
  projects and schemas through v7/review payloads through v3 migrate to
  `preserve`, so a formerly inert profile value cannot silently begin editing
  candidates. Current v8/review-v4 projects persist an explicit experimental
  `balanced` or `clean` selection. Lineage-aware candidate replacement
  protects rejected and pending/applied review from derived-candidate
  overwrite without changing the immutable transcription candidate model.
- Add the report-schema-v3 BabySlakh cleanup-only benchmark protocol and its
  closed-grid release gates; the existing v2 report is not cleanup evidence.
  Preserve the checkpoint-resumed
  `fragment-cleanup-v2-annotation-only` eight-track holdout: balanced passed
  0/108 configurations, clean safety passed 104/108, and joint selection
  passed 0/108. The frozen fixed configuration's balanced branch produced zero
  fragment/precision improvement at 1.933% postprocessing share; its clean
  branch hid 18/28,215 candidates with tiny precision/onset-F1 gains, unchanged
  recall, and 1.996% share. The checked-in compact report therefore records
  `selected_config=null` and `annotation_only=true`. That historical report
  does not authorize either profile as a verified/default cleanup mode. The
  current `fragment-cleanup-v3-explicit-opt-in` implementation exposes real
  balanced/clean actions only after the user selects an option labelled
  experimental. Its report-schema-v4 holdout also selected 0/108: the fixed
  balanced branch reduced 28,215 candidates to 28,083, reduced fragmentation
  by 0.999%, gained 0.000637 precision, and used 3.376% of decode time; clean
  suppressed another 18 candidates and passed its safety gate at 3.589%.
  Recall, per-song, false-merge, and timing limits passed, but balanced missed
  the 20% fragmentation and 0.005 precision gates. `preserve` therefore remains
  the safe default while the two explicit action profiles remain unverified.
- Keep recognition output non-authoritative: no automatic stem separation,
  instrument assignment, percussion transcription, or whole-song write
  fallback.
- Replace the default continuous pitch heat map with semantic candidate blocks:
  phrase/voice hue, confidence opacity, chord-role strips, independent review
  borders, overlap folding, and three visible-time LOD levels. Frame, onset, and
  contour tiles remain available as opt-in diagnostic evidence.
- Add conservative key/chord analysis from the cached Basic Pitch frame matrix,
  including alternatives, inversions, conflict markers, editable chord
  segments, and manual key/chord locks that survive ordinary reanalysis.
- Add deterministic phrase/voice grouping, previous/next phrase navigation,
  current-phrase A–B looping, and an ordered review queue that locates issues
  without selecting or writing candidates.
- Add explainable BDO Top-3 suggestions per voice group. Local user-supplied
  BDO samples contribute bounded background timbre features; missing or
  contaminated timbre evidence falls back to range/role/articulation ranking
  with a 45% confidence cap.
- Keep every Top-3 result advisory and manually confirmed. Confirmation alone
  does not identify a source instrument, create a track, reroute notes, or
  bypass the existing staging and atomic Apply/OK boundary.
- Persist only lightweight human assist decisions. Automatic harmony, voice and
  match results remain disposable; sample/reference paths, audio clips, and
  feature matrices never enter project files, logs, or release artifacts.
- Stage current-track drafts and explicit cross-track copies inside the editor;
  Apply/OK commits all affected tracks and review state as one undoable project
  operation, while Cancel leaves the formal project unchanged.
- Consolidate Windows packaging into one `BDO-Music-Composer.exe` with Basic
  Pitch ONNX CPU inference enabled inside transcription mode. Every build
  embeds its generated dependency/license inventory, runs synthetic
  transcription inference against the frozen executable, and then runs a
  10-second frozen GUI startup check. Both GUI-subsystem processes are awaited
  explicitly and checked by their real exit codes; the disposable user-data
  directory is created before launch, and config persistence also creates a
  missing parent directory. Public distribution remains gated until that exact
  inventory and complete notice set are reviewed.
- Remove transcription-mode UI stalls by separating the lightweight backend
  probe from cached full validation, batching candidate paint, caching the
  piano-roll background, and limiting playhead/waveform updates to dirty slices.
- Use one Qt-free candidate projection/matching policy for editor preview,
  staging, cross-track copies, and project Apply, and expose a public editor
  facade so the main window no longer manipulates its panel or canvas directly.
- Cancel obsolete evidence/WAV work cooperatively, clear stale tile bookkeeping,
  and reuse bounded audio-mixing scratch buffers so dense playback no longer
  allocates `voices × frames` matrices on every block.
- Bind transcription caches and assist review to the reference audio's content
  hash rather than its path. Inference, restore, snapshot Undo, and cache
  validation now fail closed across source replacement and remain cancellable.
- Prepare local `.bdosamples` archives on a cancellable worker and publish
  validated caches atomically, so large packs and concurrent app instances do
  not block or corrupt the editor.
- Reject negative-time, rejected-candidate, orphaned, and track-ID-conflicting
  routes at both staging and Apply. Track IDs referenced by review history are
  not silently reused.
- Keep frozen-build config, autosaves, logs, caches, and default exports under
  Local AppData; redact absolute drive and UNC paths from persistent failure
  logs and keep the distributable directory free of runtime user data.
- Index transcription review ordering, A-B duplicate checks, and visible
  candidate spans so explicit review actions, region replacement, and
  pathological long-note viewports do not rescan the full candidate set.
  Reuse frame-event time projections and candidate hashes across raw
  accounting, cleanup, and report construction.
- Compact the embedded transcription controls around short action labels and a
  distinct `◇/◆ 碎音` profile cue while preserving independent sensitivity,
  cleanup, staging, and Apply boundaries; full descriptions remain accessible
  through tooltips and accessibility names. Reduce the main workspace chrome
  and note-editor header/inspector height so the timeline and piano roll retain
  more vertical space without removing commands.
- Document a privacy-gated, review-only DeepSeek provider direction without
  adding an LLM or network dependency to deterministic editor pipelines.

## 0.3.0 - 2026-07-23

- Replace the vendored MIDI-to-BDO runtime with independent `bdo_midi`,
  `bdo_export`, and `bdo_codec` packages.
- Preserve the editor's five-field note model while covering MIDI tempo,
  program, sustain, performance-control, lyric, and percussion behavior.
- Keep dual velocities, game track volume, eight-byte settings, articulations,
  physical 730-note tracks, and empty trailing tracks through canonical export.
- Remove historical `midi2bdo` and `_ice` imports from the application,
  developer tools, tests, and Windows packaging.

## 0.2.0 - 2026-07-15

- Reposition the project as a BDO score research and editing lab.
- Add versioned BDO profiles, unified validation issues, score snapshots, and structural diffing.
- Add versioned project schema migration, project-level editor commands, and optimizer plugin hosting.
- Redesign the piano roll around a full-width canvas with integrated ruler seeking and sample preload feedback.
- Add note audition, draw gestures, articulation shortcuts, ghost notes, and a practical velocity lane.
- Improve asynchronous real-time sample loading, cancellation, caching, and editor playback behavior.
- Coordinate the main timeline, settings, editor layout, localization, and scrollbars across light and dark themes.

## 0.1.0 - 2026-07-14

- Initial Windows release.
