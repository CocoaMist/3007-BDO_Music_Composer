"""Background Qt workers for transcription analysis and sample-pack preparation."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
import threading
import traceback

from PySide6.QtCore import QObject, QThread, Signal

from bdo_music_composer.audio.bdo_sample_pack import (
    SamplePackCancelled,
    SamplePackError,
    extract_sample_pack,
)
from bdo_music_composer.transcription.bdo_transcription import (
    DEFAULT_TRANSCRIPTION_ANALYSIS_MODE,
    DEFAULT_TRANSCRIPTION_CLEANUP_PROFILE,
    POSTPROCESS_VERSION,
    TranscriptionCancelled,
    TranscriptionError,
    load_cached_transcription_result,
    load_transcription_evidence,
    load_transcription_evidence_descriptor,
    load_transcription_frame_times,
    redecode_transcription_full,
    redecode_transcription_interval,
    transcription_audio_fingerprint,
    transcribe_reference_audio,
)
from bdo_music_composer.transcription.bdo_transcription_assist import (
    ManualVoiceGroupReview,
    TranscriptionAssistReviewState,
    recover_assist_review,
)
from bdo_music_composer.transcription.bdo_transcription_harmony import (
    HarmonyAnalysis,
    HarmonyAnalysisCancelled,
    analyse_harmony,
    harmony_cache_key,
)
from bdo_music_composer.transcription.bdo_transcription_instruments import (
    BdoInstrumentDescriptor,
    InstrumentAnalysisCancelled,
    InstrumentMatchAnalysis,
    group_voice_candidates,
    match_bdo_instruments,
    overlay_manual_voice_groups,
    refine_voice_groups_by_timbre,
)
from bdo_music_composer.transcription.bdo_transcription_timbre import (
    FramePitchEvidence,
    TimbreProfileError,
    extract_group_timbre_profiles,
    load_or_build_timbre_profile_index,
    remap_group_timbre_profiles,
)
from bdo_music_composer.app.crash_logging import append_crash_log
from bdo_music_composer.transcription.rhythm_cleanup import (
    RhythmDiagnosticCancelled,
    RhythmDiagnosticSidecar,
    analyse_project_rhythm_diagnostics,
)
from bdo_music_composer.transcription.rhythm_grid import (
    ProjectRhythmSettings,
    build_project_rhythm_grid,
)
from bdo_music_composer.transcription.rhythm_alignment import (
    RhythmAlignmentCancelled,
    RhythmAlignmentConfig,
    analyse_rhythm_alignment,
)
from bdo_music_composer.ui.i18n import tr


@dataclass(frozen=True, slots=True)
class TranscriptionAssistAnalysisBundle:
    harmony: HarmonyAnalysis
    instrument_matches: InstrumentMatchAnalysis
    recovered_review: TranscriptionAssistReviewState | None = None
    timbre_profile_index: object | None = None
    group_timbre_profiles: object | None = None
    group_timbre_revision: str = ""

def _semantic_revision(values: tuple[object, ...], fields: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for value in values:
        for field_name in fields:
            field_value = getattr(value, field_name, "")
            if isinstance(field_value, float):
                field_value = round(field_value, 6)
            digest.update(str(field_value).encode("utf-8"))
            digest.update(b"\x1f")
        digest.update(b"\n")
    return digest.hexdigest()[:24]

def _close_mapped_array(value: object | None) -> None:
    mmap = getattr(value, "_mmap", None)
    if mmap is not None:
        try:
            mmap.close()
        except (OSError, ValueError):
            pass


class TranscriptionRhythmDiagnosticWorker(QThread):
    """Read cached evidence once for an explicit, diagnostic-only request."""

    succeeded = Signal(int, object)
    failed = Signal(int, str)
    cancelled = Signal(int)

    def __init__(
        self,
        *,
        generation: int,
        cache_key: str,
        candidates: tuple[object, ...],
        settings: ProjectRhythmSettings,
        alignment_config: RhythmAlignmentConfig | None = None,
        cache_root: str | Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.generation = int(generation)
        self.cache_key = str(cache_key)
        self.candidates = tuple(candidates)
        self.settings = settings
        self.alignment_config = alignment_config or RhythmAlignmentConfig()
        self.cache_root = None if cache_root is None else Path(cache_root)
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def _cache_kwargs(self) -> dict[str, Path]:
        return {} if self.cache_root is None else {"cache_root": self.cache_root}

    def run(self) -> None:
        mapped_arrays: list[object] = []
        try:
            if self._cancelled.is_set():
                raise RhythmDiagnosticCancelled()
            grid = build_project_rhythm_grid(self.settings)
            if grid is None:
                raise ValueError(
                    "project rhythm diagnostics require explicit enablement"
                )
            cache_kwargs = self._cache_kwargs()
            descriptor = load_transcription_evidence_descriptor(
                self.cache_key,
                cancelled=self._cancelled.is_set,
                **cache_kwargs,
            )
            if descriptor is None:
                raise ValueError("transcription evidence cache is unavailable")
            times = load_transcription_frame_times(
                self.cache_key,
                cancelled=self._cancelled.is_set,
                **cache_kwargs,
            )
            frame = load_transcription_evidence(
                self.cache_key,
                "frame",
                cancelled=self._cancelled.is_set,
                **cache_kwargs,
            )
            onset = load_transcription_evidence(
                self.cache_key,
                "onset",
                cancelled=self._cancelled.is_set,
                **cache_kwargs,
            )
            contour = load_transcription_evidence(
                self.cache_key,
                "contour",
                cancelled=self._cancelled.is_set,
                **cache_kwargs,
            )
            mapped_arrays.extend((times, frame, onset, contour))
            if times is None or frame is None or onset is None:
                raise ValueError("required transcription evidence is unavailable")
            frame_layer = descriptor.layer("frame")
            contour_layer = descriptor.layer("contour")
            if frame_layer is None:
                raise ValueError("frame evidence descriptor is unavailable")
            result = analyse_project_rhythm_diagnostics(
                evidence_cache_key=self.cache_key,
                candidates=self.candidates,
                grid=grid,
                frame_times_ms=times,
                frame_evidence=frame,
                onset_evidence=onset,
                contour_evidence=contour,
                frame_midi_min=frame_layer.midi_min,
                contour_midi_min=(
                    descriptor.midi_min
                    if contour_layer is None
                    else contour_layer.midi_min
                ),
                contour_bins_per_semitone=(
                    3
                    if contour_layer is None
                    else contour_layer.bins_per_semitone
                ),
                cancelled=self._cancelled.is_set,
            )
            alignment = analyse_rhythm_alignment(
                evidence_cache_key=self.cache_key,
                candidates=self.candidates,
                settings=self.settings,
                frame_times_ms=times,
                onset_evidence=onset,
                frame_midi_min=frame_layer.midi_min,
                config=self.alignment_config,
                cancelled=self._cancelled.is_set,
            )
            result = replace(result, alignment=alignment)
        except (
            RhythmAlignmentCancelled,
            RhythmDiagnosticCancelled,
            TranscriptionCancelled,
        ):
            self.cancelled.emit(self.generation)
        except (OSError, ValueError) as exc:
            self.failed.emit(self.generation, str(exc))
        except Exception as exc:
            append_crash_log(
                "Transcription rhythm diagnostic failed",
                traceback.format_exc(),
            )
            self.failed.emit(
                self.generation,
                str(exc) or type(exc).__name__,
            )
        else:
            if self._cancelled.is_set():
                self.cancelled.emit(self.generation)
            else:
                self.succeeded.emit(self.generation, result)
        finally:
            for value in mapped_arrays:
                _close_mapped_array(value)


class TranscriptionRhythmDiagnosticRunner(QObject):
    """Single-slot explicit runner with cancellation and stale rejection."""

    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    busy_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._generation = 0
        self._worker: TranscriptionRhythmDiagnosticWorker | None = None
        self._expected_grid = None
        self._expected_cache_key = ""
        self._expected_candidates: tuple[object, ...] = ()

    @property
    def busy(self) -> bool:
        return self._worker is not None

    def start_diagnostic(
        self,
        *,
        cache_key: str,
        candidates: tuple[object, ...],
        settings: ProjectRhythmSettings,
        alignment_config: RhythmAlignmentConfig | None = None,
        cache_root: str | Path | None = None,
    ) -> bool:
        """Start only from an explicit caller; never queue concurrent work."""

        if self.busy or not settings.enabled or not str(cache_key):
            return False
        grid = build_project_rhythm_grid(settings)
        if grid is None:
            return False
        self._generation += 1
        generation = self._generation
        worker = TranscriptionRhythmDiagnosticWorker(
            generation=generation,
            cache_key=str(cache_key),
            candidates=tuple(candidates),
            settings=settings,
            alignment_config=alignment_config,
            cache_root=cache_root,
            parent=self,
        )
        self._worker = worker
        self._expected_grid = grid
        self._expected_cache_key = str(cache_key)
        self._expected_candidates = tuple(candidates)
        worker.succeeded.connect(self._succeeded)
        worker.failed.connect(self._failed)
        worker.cancelled.connect(self._cancelled)
        worker.finished.connect(self._finished)
        self.busy_changed.emit(True)
        worker.start()
        return True

    def cancel(self) -> None:
        worker = self._worker
        if worker is not None:
            worker.cancel()

    def invalidate(self) -> None:
        """Cancel and reject any result bound to an older editor revision."""

        self._generation += 1
        self._expected_grid = None
        self._expected_cache_key = ""
        self._expected_candidates = ()
        self.cancel()

    def _succeeded(
        self,
        generation: int,
        sidecar: RhythmDiagnosticSidecar,
    ) -> None:
        if generation != self._generation or self._expected_grid is None:
            return
        if not sidecar.is_current(
            evidence_cache_key=self._expected_cache_key,
            candidates=self._expected_candidates,
            grid=self._expected_grid,
        ):
            return
        self.succeeded.emit(sidecar)

    def _failed(self, generation: int, message: str) -> None:
        if generation == self._generation:
            self.failed.emit(str(message))

    def _cancelled(self, generation: int) -> None:
        if generation == self._generation:
            self.cancelled.emit()

    def _finished(self) -> None:
        worker = self.sender()
        if worker is not self._worker:
            return
        self._worker = None
        self._expected_grid = None
        self._expected_cache_key = ""
        self._expected_candidates = ()
        if isinstance(worker, QThread):
            worker.deleteLater()
        self.busy_changed.emit(False)

class TranscriptionAssistAnalysisWorker(QThread):
    """Derive harmony and voice/instrument suggestions off the GUI thread."""

    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        *,
        cache_key: str,
        candidates: tuple[object, ...],
        audio_time_notes: tuple[object, ...],
        descriptors: tuple[BdoInstrumentDescriptor, ...],
        bpm: float,
        time_signature: int,
        beat_origin_audio_ms: float,
        duration_ms: float | None,
        midi_min: int,
        reference_audio_path: str = "",
        sample_map_path: str | Path = "",
        audio_root: str | Path = "",
        manual_voice_groups: tuple[ManualVoiceGroupReview, ...] = (),
        audio_fingerprint: str = "",
        pitch_offset: int = 0,
        review_state: TranscriptionAssistReviewState | None = None,
        previous_candidates: tuple[object, ...] = (),
        reuse_instrument_matches: InstrumentMatchAnalysis | None = None,
        reuse_timbre_profile_index: object | None = None,
        reuse_group_timbre_profiles: object | None = None,
        reuse_group_timbre_revision: str = "",
        allow_review_recovery: bool = True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.cache_key = str(cache_key)
        self.candidates = tuple(candidates)
        self.audio_time_notes = tuple(audio_time_notes)
        self.descriptors = tuple(descriptors)
        self.bpm = float(bpm)
        self.time_signature = int(time_signature)
        self.beat_origin_audio_ms = float(beat_origin_audio_ms)
        self.duration_ms = (
            None if duration_ms is None else float(duration_ms)
        )
        self.midi_min = int(midi_min)
        self.reference_audio_path = str(reference_audio_path or "")
        self.sample_map_path = Path(sample_map_path) if sample_map_path else None
        self.audio_root = Path(audio_root) if audio_root else None
        self.manual_voice_groups = tuple(manual_voice_groups)
        self.audio_fingerprint = str(audio_fingerprint or "")
        self.pitch_offset = int(pitch_offset)
        self.review_state = (
            review_state
            if isinstance(review_state, TranscriptionAssistReviewState)
            else TranscriptionAssistReviewState()
        )
        self.previous_candidates = tuple(previous_candidates)
        self.reuse_instrument_matches = reuse_instrument_matches
        self.reuse_timbre_profile_index = reuse_timbre_profile_index
        self.reuse_group_timbre_profiles = reuse_group_timbre_profiles
        self.reuse_group_timbre_revision = str(
            reuse_group_timbre_revision or ""
        )
        self.allow_review_recovery = bool(allow_review_recovery)
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        frame = None
        times = None
        try:
            frame = load_transcription_evidence(self.cache_key, "frame")
            times = load_transcription_frame_times(self.cache_key)
            if frame is None or times is None:
                raise TranscriptionError(
                    "扒谱证据缓存缺失或校验失败，无法生成和声建议。"
                )
            if self._cancelled.is_set():
                self.cancelled.emit()
                return
            candidate_revision = _semantic_revision(
                self.candidates,
                (
                    "candidate_id",
                    "pitch",
                    "start_ms",
                    "duration_ms",
                    "confidence",
                ),
            )
            note_revision = _semantic_revision(
                self.audio_time_notes,
                ("pitch", "start", "dur", "vel", "ntype"),
            )
            derived_cache_key = harmony_cache_key(
                self.cache_key,
                bpm=self.bpm,
                time_signature=self.time_signature,
                beat_origin_audio_ms=self.beat_origin_audio_ms,
                candidate_revision=candidate_revision,
                note_revision=note_revision,
            )
            harmony = analyse_harmony(
                frame,
                times,
                cache_key=derived_cache_key,
                bpm=self.bpm,
                beat_origin_audio_ms=self.beat_origin_audio_ms,
                midi_min=self.midi_min,
                duration_ms=self.duration_ms,
                symbolic_candidates=self.candidates,
                symbolic_notes=self.audio_time_notes,
                cancelled=self._cancelled.is_set,
            )
            if self._cancelled.is_set():
                self.cancelled.emit()
                return
            profile_index = self.reuse_timbre_profile_index
            group_profiles = self.reuse_group_timbre_profiles
            group_profile_revision = self.reuse_group_timbre_revision
            instrument_matches = self.reuse_instrument_matches
            if instrument_matches is None:
                groups = group_voice_candidates(
                    self.candidates,
                    beat_ms=60_000.0 / max(1.0, self.bpm),
                    cancelled=self._cancelled.is_set,
                )
                if self.manual_voice_groups:
                    groups = overlay_manual_voice_groups(
                        groups,
                        self.candidates,
                        self.manual_voice_groups,
                        cancelled=self._cancelled.is_set,
                    )
                wanted_group_revision = _semantic_revision(
                    tuple(groups),
                    (
                        "group_id",
                        "candidate_ids",
                        "start_audio_ms",
                        "end_audio_ms",
                        "role",
                    ),
                )
                wanted_group_revision = hashlib.sha256(
                    (
                        f"{self.audio_fingerprint}|"
                        f"{candidate_revision}|"
                        f"{wanted_group_revision}"
                    ).encode("utf-8")
                ).hexdigest()[:24]
                instrument_profiles = {}
                sample_profile_key = ""
                if (
                    self.reference_audio_path
                    and self.sample_map_path is not None
                    and self.sample_map_path.is_file()
                    and self.audio_root is not None
                    and self.audio_root.is_dir()
                    and not self._cancelled.is_set()
                ):
                    try:
                        if profile_index is None:
                            profile_index = (
                                load_or_build_timbre_profile_index(
                                    self.sample_map_path,
                                    self.audio_root,
                                    cancelled=self._cancelled.is_set,
                                )
                            )
                        instrument_profiles = profile_index.as_mapping()
                        sample_profile_key = (
                            profile_index.sample_profile_key
                        )
                        if (
                            group_profiles is None
                            or group_profile_revision
                            != wanted_group_revision
                        ):
                            group_profiles = (
                                extract_group_timbre_profiles(
                                    self.reference_audio_path,
                                    self.candidates,
                                    groups,
                                    frame_evidence=FramePitchEvidence(
                                        times,
                                        frame,
                                        self.midi_min,
                                        1,
                                    ),
                                    cancelled=self._cancelled.is_set,
                                )
                            )
                            group_profile_revision = (
                                wanted_group_revision
                            )
                    except (
                        OSError,
                        TypeError,
                        ValueError,
                        TimbreProfileError,
                    ):
                        # Local sample evidence is optional.  The deterministic
                        # range/role fallback remains available and visibly
                        # capped.
                        instrument_profiles = {}
                        group_profiles = {}
                        group_profile_revision = wanted_group_revision
                        sample_profile_key = ""
                else:
                    group_profiles = {}
                    group_profile_revision = wanted_group_revision
                candidate_timbres = getattr(
                    group_profiles,
                    "candidate_profiles",
                    {},
                )
                if candidate_timbres:
                    manual_group_ids = {
                        str(review.group_id)
                        for review in self.manual_voice_groups
                        if not bool(getattr(review, "orphaned", False))
                    }
                    fixed_groups = tuple(
                        group
                        for group in groups
                        if group.group_id in manual_group_ids
                    )
                    refinable_groups = tuple(
                        group
                        for group in groups
                        if group.group_id not in manual_group_ids
                    )
                    refined_groups = refine_voice_groups_by_timbre(
                        refinable_groups,
                        self.candidates,
                        candidate_timbres,
                        cancelled=self._cancelled.is_set,
                    )
                    if refined_groups != refinable_groups:
                        groups = tuple(
                            sorted(
                                (*fixed_groups, *refined_groups),
                                key=lambda group: (
                                    group.start_audio_ms,
                                    group.end_audio_ms,
                                    group.group_id,
                                ),
                            )
                        )
                        group_profiles = remap_group_timbre_profiles(
                            group_profiles,
                            self.candidates,
                            groups,
                            cancelled=self._cancelled.is_set,
                        )
                instrument_matches = match_bdo_instruments(
                    groups,
                    self.candidates,
                    self.descriptors,
                    group_timbre_profiles=group_profiles or {},
                    instrument_timbre_profiles=instrument_profiles,
                    sample_profile_key=sample_profile_key,
                    pitch_offset=self.pitch_offset,
                    beat_ms=60_000.0 / max(1.0, self.bpm),
                    top_k=3,
                    cancelled=self._cancelled.is_set,
                )
            previous_revision = _semantic_revision(
                self.previous_candidates,
                (
                    "candidate_id",
                    "pitch",
                    "start_ms",
                    "duration_ms",
                    "confidence",
                ),
            )
            candidate_revision_changed = bool(
                self.previous_candidates
            ) and previous_revision != candidate_revision
            current_group_ids = {
                group.group_id for group in instrument_matches.groups
            }
            review_group_ids = {
                item.group_id
                for item in self.review_state.active_voice_groups
            }
            needs_recovery = (
                self.audio_fingerprint
                != self.review_state.audio_fingerprint
                or self.review_state.has_orphaned_reviews
                or candidate_revision_changed
                or not review_group_ids.issubset(current_group_ids)
            )
            recovered_review = None
            if needs_recovery and self.allow_review_recovery:
                recovered_review = recover_assist_review(
                    self.review_state,
                    audio_fingerprint=self.audio_fingerprint,
                    old_candidates=self.previous_candidates,
                    new_candidates=self.candidates,
                    chord_segments=harmony.chord_segments,
                    voice_groups=instrument_matches.groups,
                    force_reanchor=(
                        candidate_revision_changed
                        and self.audio_fingerprint
                        == self.review_state.audio_fingerprint
                    ),
                    cancelled=self._cancelled.is_set,
                ).state
        except (HarmonyAnalysisCancelled, InstrumentAnalysisCancelled):
            self.cancelled.emit()
        except RuntimeError:
            if self._cancelled.is_set():
                self.cancelled.emit()
            else:
                self.failed.emit(
                    "语义分析失败；缓存或本地音色证据不可用。"
                )
        except TranscriptionError as exc:
            self.failed.emit(str(exc))
        except (OSError, TypeError, ValueError):
            # Do not surface cache/sample paths in UI state, logs, project
            # payloads, or packaged diagnostics.
            self.failed.emit(
                "语义分析失败；缓存或本地音色证据不可用。"
            )
        except Exception:
            self.failed.emit("语义分析失败；请重新分析整首。")
        else:
            if self._cancelled.is_set():
                self.cancelled.emit()
            else:
                self.succeeded.emit(
                    TranscriptionAssistAnalysisBundle(
                        harmony,
                        instrument_matches,
                        recovered_review,
                        profile_index,
                        group_profiles,
                        group_profile_revision,
                    )
                )
        finally:
            _close_mapped_array(frame)
            _close_mapped_array(times)

class TranscriptionAnalysisWorker(QThread):
    """Run bundled Basic Pitch inference away from the GUI/audio threads."""

    progress_changed = Signal(int)
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        audio_path: str | Path,
        parent: QObject | None = None,
        *,
        analysis_mode: str = DEFAULT_TRANSCRIPTION_ANALYSIS_MODE,
        sensitivity: str = "balanced",
        cleanup_profile: str = DEFAULT_TRANSCRIPTION_CLEANUP_PROFILE,
    ) -> None:
        super().__init__(parent)
        self.audio_path = Path(audio_path)
        self.analysis_mode = str(analysis_mode)
        self.sensitivity = str(sensitivity)
        self.cleanup_profile = str(cleanup_profile)
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        try:
            result = transcribe_reference_audio(
                self.audio_path,
                self.progress_changed.emit,
                self._cancelled.is_set,
                analysis_mode=self.analysis_mode,
                sensitivity=self.sensitivity,
                cleanup_profile=self.cleanup_profile,
            )
        except TranscriptionCancelled:
            self.cancelled.emit()
        except TranscriptionError as exc:
            append_crash_log(
                "Transcription analysis failed",
                traceback.format_exc(),
            )
            self.failed.emit(str(exc))
        except Exception:
            append_crash_log(
                "Transcription analysis failed",
                traceback.format_exc(),
            )
            self.failed.emit(tr("扒谱分析失败。"))
        else:
            if self._cancelled.is_set():
                self.cancelled.emit()
            else:
                self.succeeded.emit(result)

class TranscriptionRedecodeWorker(QThread):
    """Decode one A–B range from cached evidence without running ONNX."""

    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        cache_key: str,
        start_ms: float,
        end_ms: float,
        sensitivity: str,
        parent: QObject | None = None,
        *,
        cleanup_profile: str = DEFAULT_TRANSCRIPTION_CLEANUP_PROFILE,
    ) -> None:
        super().__init__(parent)
        self.cache_key = str(cache_key)
        self.start_ms = float(start_ms)
        self.end_ms = float(end_ms)
        self.sensitivity = str(sensitivity)
        self.cleanup_profile = str(cleanup_profile)
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        try:
            result = redecode_transcription_interval(
                self.cache_key,
                self.start_ms,
                self.end_ms,
                sensitivity=self.sensitivity,
                cleanup_profile=self.cleanup_profile,
                context_ms=500.0,
                cancelled=self._cancelled.is_set,
            )
        except TranscriptionCancelled:
            self.cancelled.emit()
        except TranscriptionError as exc:
            append_crash_log(
                "Transcription range decode failed",
                traceback.format_exc(),
            )
            self.failed.emit(str(exc))
        except Exception:
            append_crash_log(
                "Transcription range decode failed",
                traceback.format_exc(),
            )
            self.failed.emit(tr("区间重解码失败。"))
        else:
            if self._cancelled.is_set():
                self.cancelled.emit()
            else:
                self.succeeded.emit(result)

class TranscriptionCacheLoadWorker(QThread):
    """Validate and restore a cached analysis away from the GUI thread."""

    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        cache_key: str,
        parent: QObject | None = None,
        *,
        audio_path: str | Path = "",
        expected_audio_fingerprint: str = "",
        analysis_mode: str = DEFAULT_TRANSCRIPTION_ANALYSIS_MODE,
        sensitivity: str = "balanced",
        cleanup_profile: str = DEFAULT_TRANSCRIPTION_CLEANUP_PROFILE,
    ) -> None:
        super().__init__(parent)
        self.cache_key = str(cache_key)
        self.audio_path = Path(audio_path) if audio_path else None
        self.expected_audio_fingerprint = str(
            expected_audio_fingerprint or ""
        )
        self.analysis_mode = str(analysis_mode)
        self.sensitivity = str(sensitivity)
        self.cleanup_profile = str(cleanup_profile)
        self.current_audio_fingerprint = ""
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        try:
            initial_audio_fingerprint = ""
            if self.audio_path is not None:
                try:
                    initial_audio_fingerprint = (
                        transcription_audio_fingerprint(
                            self.audio_path,
                            cancelled=self._cancelled.is_set,
                        )
                    )
                except OSError:
                    self.succeeded.emit(None)
                    return
                self.current_audio_fingerprint = initial_audio_fingerprint
                if (
                    self.expected_audio_fingerprint
                    and initial_audio_fingerprint
                    != self.expected_audio_fingerprint
                ):
                    self.succeeded.emit(None)
                    return
            expected = (
                initial_audio_fingerprint
                or self.expected_audio_fingerprint
                or None
            )
            result = load_cached_transcription_result(
                self.cache_key,
                expected_audio_fingerprint=expected,
                cancelled=self._cancelled.is_set,
            )
            if result is not None:
                descriptor = getattr(
                    result, "evidence_descriptor", None
                )
                if (
                    descriptor is not None
                    and descriptor.analysis_mode != self.analysis_mode
                ):
                    result = None
                elif (
                    descriptor is not None
                    and (
                        descriptor.decode_sensitivity != self.sensitivity
                        or descriptor.cleanup_profile
                        != self.cleanup_profile
                        or descriptor.postprocess_version
                        != POSTPROCESS_VERSION
                        or result.postprocess_report is None
                    )
                ):
                    result = redecode_transcription_full(
                        self.cache_key,
                        sensitivity=self.sensitivity,
                        cleanup_profile=self.cleanup_profile,
                        cancelled=self._cancelled.is_set,
                    )
            if self.audio_path is not None:
                try:
                    self.current_audio_fingerprint = (
                        transcription_audio_fingerprint(
                            self.audio_path,
                            cancelled=self._cancelled.is_set,
                        )
                    )
                except OSError:
                    self.succeeded.emit(None)
                    return
                if (
                    self.current_audio_fingerprint
                    != initial_audio_fingerprint
                ):
                    self.succeeded.emit(None)
                    return
        except TranscriptionCancelled:
            self.cancelled.emit()
            return
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            if self._cancelled.is_set():
                self.cancelled.emit()
            else:
                self.succeeded.emit(result)

class SamplePackPrepareWorker(QThread):
    """Hash, validate, and extract one local sample pack off the GUI thread."""

    progress_changed = Signal(int)
    succeeded = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        pack_path: str | Path,
        cache_root: str | Path,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.pack_path = Path(pack_path)
        self.cache_root = Path(cache_root)
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self) -> None:
        try:
            audio_root = extract_sample_pack(
                self.pack_path,
                self.cache_root,
                progress=self.progress_changed.emit,
                cancelled=self._cancelled.is_set,
            )
        except SamplePackCancelled:
            self.cancelled.emit()
        except (OSError, SamplePackError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc) or type(exc).__name__)
        else:
            if self._cancelled.is_set():
                self.cancelled.emit()
            else:
                self.succeeded.emit(str(audio_root))
