"""Offline preview renderer backed by extracted BDO Wwise samples."""

from __future__ import annotations

import json
import math
import os
import wave
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

import numpy as np

from bdo_music_composer.audio.bdo_audio_mixing import (
    apply_articulation_preview_in_place,
    prepare_sample_pcm,
    preview_chord_intervals,
)
from bdo_music_composer.audio.bdo_audio_lifecycle import (
    INSTANCE_LIMIT_RELEASE_MS,
    InstanceTimelineItem,
    VoiceLifecycle,
    detect_active_signal_frames,
    plan_instance_timeline,
    sample_output_frames,
    voice_lifecycle,
)
from bdo_music_composer.audio.bdo_instrument_samples import (
    BDO_BANK_BY_ID,
    WwiseContainerRotation,
    bank_for_instrument,
    preview_has_native_articulation,
    preview_pitch_offset_semitones,
    preview_route_ntype,
    resolve_bdo_pitch,
    row_instance_limit,
    row_loop_points,
    row_release_ms,
    row_routes_ntype,
    row_volume_gain,
    sample_pitch_ratio,
    select_zone_row,
    select_zone_variants,
    velocity_zone_boundaries,
)
from bdo_midi import _GM_TO_BDO_DRUM as GM_TO_BDO_DRUM
from bdo_common.bdo_track_effects import DEFAULT_TRACK_VOLUME, track_volume_preview_gain


SAMPLE_RATE = 36000


@dataclass(frozen=True)
class RenderResult:
    duration_ms: float
    notes_rendered: int
    missing_instruments: tuple[int, ...]


@dataclass(frozen=True)
class _RenderRequest:
    start_ms: float
    track_order: int
    note_order: int
    track: object
    note: object
    synth_mode: str


@dataclass(frozen=True)
class _PreparedVoice:
    relative_start: int
    velocity: int
    playback_ratio: float
    sample: np.ndarray
    row: dict
    lifecycle: VoiceLifecycle
    loop_points: tuple[int, int] | None
    instrument_id: int
    ntype: int
    native_articulation: bool
    track_volume_gain: float
    gain_scale: float = 1.0
    count_note: bool = True


@dataclass(frozen=True)
class _PreparedEvent:
    relative_start: int
    audible_frames: int
    voice_indices: tuple[int, ...]
    instance_group_id: int = -1
    instance_scope_id: int = -1
    max_instances: int = 0
    kill_newest: bool = False


@lru_cache(maxsize=128)
def _read_wav(path_string: str) -> np.ndarray:
    path = Path(path_string)
    with wave.open(str(path), "rb") as source:
        if source.getsampwidth() != 2:
            raise ValueError(f"Unsupported sample width: {path}")
        data = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
        channels = source.getnchannels()
        rate = source.getframerate()
    if channels == 1:
        data = np.column_stack((data, data))
    else:
        data = data.reshape(-1, channels)[:, :2]
        if data.shape[1] == 1:
            data = np.column_stack((data[:, 0], data[:, 0]))
    if rate != SAMPLE_RATE:
        length = max(1, round(len(data) * SAMPLE_RATE / rate))
        positions = np.linspace(0, len(data) - 1, length)
        data = np.column_stack((
            np.interp(positions, np.arange(len(data)), data[:, 0]),
            np.interp(positions, np.arange(len(data)), data[:, 1]),
        )).astype(np.float32)
    prepared, _gain = prepare_sample_pcm(data)
    return prepared


@lru_cache(maxsize=128)
def _wav_sample_rate(path_string: str) -> int:
    with wave.open(str(Path(path_string)), "rb") as source:
        return max(1, int(source.getframerate()))


@lru_cache(maxsize=128)
def _active_signal_frames(path_string: str) -> int:
    return detect_active_signal_frames(_read_wav(path_string), SAMPLE_RATE)


class BdoSampleMap:
    def __init__(
        self,
        map_path: str | Path,
        audio_root: str | Path | None = None,
    ) -> None:
        mapping_path = Path(map_path)
        payload = json.loads(mapping_path.read_text(encoding="utf-8"))
        configured_root = (
            Path(audio_root)
            if audio_root
            else Path(os.environ["BDO_AUDIO_ROOT"])
            if os.environ.get("BDO_AUDIO_ROOT")
            else None
        )
        self.by_bank = {
            bank: [
                self._resolve_row_path(
                    row,
                    mapping_path,
                    configured_root,
                )
                for row in rows
                if row.get("wav_exists")
            ]
            for bank, rows in payload.get("banks", {}).items()
        }

    @staticmethod
    def _resolve_row_path(
        row: dict,
        mapping_path: Path,
        audio_root: Path | None,
    ) -> dict:
        raw_path = Path(str(row.get("wav_path", "") or ""))
        if raw_path.is_absolute() or not raw_path.parts:
            return row
        candidates: list[Path] = []
        if audio_root is not None:
            candidates.extend((
                audio_root / "乐器_WAV" / raw_path,
                audio_root / raw_path,
            ))
        candidates.extend((
            mapping_path.parent / raw_path,
            Path.cwd() / raw_path,
        ))
        selected = next(
            (candidate for candidate in candidates if candidate.is_file()),
            candidates[0] if candidates else raw_path,
        )
        resolved = dict(row)
        resolved["wav_path"] = str(selected)
        return resolved

    def has_instrument(
        self, instrument_id: int, synth_mode: str = "basic"
    ) -> bool:
        bank = bank_for_instrument(instrument_id, synth_mode)
        return bool(bank and self.by_bank.get(bank))

    def has_complete_media(
        self,
        instrument_id: int,
        synth_mode: str = "basic",
    ) -> bool:
        """Whether every mapped WAV required by one bank exists locally.

        Mapping metadata describes structural coverage; it must not be used as
        proof that a configured external sample directory is complete.
        """

        bank = bank_for_instrument(instrument_id, synth_mode)
        rows = self.by_bank.get(bank or "", [])
        return bool(rows) and all(
            Path(str(row.get("wav_path", ""))).is_file()
            for row in rows
        )

    def supported_pitches(
        self, instrument_id: int, synth_mode: str = "basic"
    ) -> frozenset[int]:
        bank = bank_for_instrument(instrument_id, synth_mode)
        return frozenset(
            pitch
            for row in self.by_bank.get(bank or "", [])
            for pitch in range(int(row["key_min"]), int(row["key_max"]) + 1)
        )

    def choose(
        self,
        instrument_id: int,
        pitch: int,
        velocity: int,
        ntype: int = 0,
        synth_mode: str = "basic",
        variant_index: int = 0,
    ) -> dict | None:
        bank = bank_for_instrument(instrument_id, synth_mode)
        route_ntype = preview_route_ntype(instrument_id, ntype)
        resolved_pitch = resolve_bdo_pitch(
            instrument_id,
            pitch,
            ntype,
        )
        return self.choose_bank(
            bank or "",
            resolved_pitch,
            velocity,
            route_ntype,
            variant_index,
        )

    def choose_variants(
        self,
        instrument_id: int,
        pitch: int,
        velocity: int,
        ntype: int = 0,
        synth_mode: str = "basic",
    ) -> tuple[dict, ...]:
        bank = bank_for_instrument(instrument_id, synth_mode)
        route_ntype = preview_route_ntype(instrument_id, ntype)
        resolved_pitch = resolve_bdo_pitch(
            instrument_id,
            pitch,
            ntype,
        )
        return select_zone_variants(
            self.by_bank.get(bank or "", []),
            resolved_pitch,
            velocity,
            route_ntype,
            bank=bank,
        )

    def velocity_boundaries(
        self,
        instrument_id: int,
        pitch: int,
        ntype: int = 0,
        synth_mode: str = "basic",
    ) -> tuple[int, ...]:
        """Return mapping-authored velocity transitions for one editor note."""
        bank = bank_for_instrument(instrument_id, synth_mode)
        route_ntype = preview_route_ntype(instrument_id, ntype)
        resolved_pitch = resolve_bdo_pitch(instrument_id, pitch, ntype)
        return velocity_zone_boundaries(
            self.by_bank.get(bank or "", []),
            resolved_pitch,
            route_ntype,
            bank=bank,
        )

    def choose_bank(
        self,
        bank: str,
        pitch: int,
        velocity: int,
        ntype: int = 0,
        variant_index: int = 0,
    ) -> dict | None:
        rows = self.by_bank.get(bank, [])
        return select_zone_row(
            rows,
            pitch,
            velocity,
            ntype,
            variant_index,
            bank=bank,
        )


@lru_cache(maxsize=4)
def _cached_sample_map(map_path: str) -> BdoSampleMap:
    return BdoSampleMap(map_path)


@lru_cache(maxsize=4)
def _cached_mapping_banks(map_path: str) -> dict[str, tuple[dict, ...]]:
    """Load routing metadata without probing thousands of local WAV paths."""
    payload = json.loads(Path(map_path).read_text(encoding="utf-8"))
    return {
        str(bank): tuple(rows)
        for bank, rows in payload.get("banks", {}).items()
    }


def sample_map_covers(
    map_path: str | Path,
    instrument_ids: tuple[int, ...] | list[int],
) -> bool:
    sample_map = _cached_sample_map(str(map_path))
    return all(sample_map.has_instrument(instrument_id) for instrument_id in instrument_ids)


def sample_map_velocity_boundaries(
    map_path: str | Path,
    instrument_id: int,
    pitch: int,
    ntype: int = 0,
    synth_mode: str = "basic",
) -> tuple[int, ...]:
    """Cached metadata-only query for editor-side game mapping hints."""
    bank = bank_for_instrument(instrument_id, synth_mode)
    route_ntype = preview_route_ntype(instrument_id, ntype)
    resolved_pitch = resolve_bdo_pitch(instrument_id, pitch, ntype)
    return velocity_zone_boundaries(
        _cached_mapping_banks(str(map_path)).get(bank or "", ()),
        resolved_pitch,
        route_ntype,
        bank=bank,
    )


def sample_map_supported_pitches(
    map_path: str | Path,
    instrument_id: int,
    synth_mode: str = "basic",
) -> frozenset[int]:
    """Return the exact MIDI keys with a Wwise source zone for an instrument."""
    return _cached_sample_map(str(map_path)).supported_pitches(
        instrument_id, synth_mode
    )


def sample_map_supports_note(
    map_path: str | Path,
    instrument_id: int,
    pitch: int,
    velocity: int,
    ntype: int = 0,
    synth_mode: str = "basic",
) -> bool:
    """Whether Wwise has an exact key-and-velocity zone for this note."""
    return (
        _cached_sample_map(str(map_path)).choose(
            instrument_id,
            pitch,
            velocity,
            ntype,
            synth_mode,
        )
        is not None
    )


def _resample_for_note(
    sample: np.ndarray,
    playback_ratio: float,
    max_frames: int,
    start_output_frame: int = 0,
    *,
    loop_points: tuple[int, int] | None = None,
) -> np.ndarray:
    ratio = max(1.0e-9, float(playback_ratio))
    start_frame = max(0, int(start_output_frame))
    if loop_points is None:
        available_frames = max(
            0,
            math.ceil(len(sample) / ratio) - start_frame,
        )
        output_frames = min(max(0, int(max_frames)), available_frames)
    else:
        output_frames = max(0, int(max_frames))
    if output_frames <= 0:
        return np.empty((0, 2), dtype=np.float32)
    positions = (
        np.arange(output_frames, dtype=np.float32)
        + start_frame
    ) * ratio
    loop_start = loop_end = 0
    if loop_points is None:
        np.clip(
            positions,
            0.0,
            max(0, len(sample) - 1),
            out=positions,
        )
    else:
        loop_start, loop_end = loop_points
        loop_length = loop_end - loop_start
        looping = positions >= loop_end
        positions[looping] = loop_start + np.mod(
            positions[looping] - loop_start,
            loop_length,
        )
    indices = positions.astype(np.intp)
    fractions = positions - indices
    following = np.minimum(indices + 1, len(sample) - 1)
    if loop_points is not None:
        at_loop_boundary = (
            (positions >= loop_start)
            & (following >= loop_end)
        )
        following[at_loop_boundary] = loop_start
    rendered = np.asarray(sample[indices], dtype=np.float32).copy()
    rendered += (sample[following] - rendered) * fractions[:, None]
    return rendered


def render_preview(
    tracks: list,
    map_path: str | Path,
    output_path: str | Path,
    start_ms: float = 0.0,
    audio_root: str | Path | None = None,
) -> RenderResult:
    sample_map = BdoSampleMap(map_path, audio_root)
    missing: set[int] = set()
    requests: list[_RenderRequest] = []
    prepared: list[_PreparedVoice] = []
    prepared_events: list[_PreparedEvent] = []
    container_rotation = WwiseContainerRotation()

    for track_order, track in enumerate(tracks):
        synth_mode = str(
            getattr(track, "marnian_synth_mode", "basic") or "basic"
        )
        if not sample_map.has_instrument(
            track.bdo_instrument_id, synth_mode
        ):
            missing.add(track.bdo_instrument_id)
            continue
        for note_order, note in enumerate(track.notes):
            requests.append(_RenderRequest(
                float(note.start),
                track_order,
                note_order,
                track,
                note,
                synth_mode,
            ))

    requests.sort(
        key=lambda request: (
            request.start_ms,
            request.track_order,
            request.note_order,
        )
    )
    for request in requests:
        track = request.track
        note = request.note
        synth_mode = request.synth_mode
        # Per-note velocity is already the game-native value.  The retired
        # ``volume_scale`` field is migration-only and must never create a
        # hidden preview/export difference.
        velocity = max(0, min(127, round(note.vel)))
        ntype = int(
            getattr(note, "ntype", 0)
            or getattr(track, "articulation_type", 0)
            or 0
        )
        variants = sample_map.choose_variants(
            track.bdo_instrument_id,
            note.pitch,
            velocity,
            ntype,
            synth_mode,
        )
        if not variants:
            missing.add(track.bdo_instrument_id)
            continue
        bank = bank_for_instrument(
            track.bdo_instrument_id,
            synth_mode,
        ) or ""
        selected = container_rotation.choose(bank, variants)
        if selected is None:
            missing.add(track.bdo_instrument_id)
            continue
        note_frames = max(
            1,
            round(
                note.dur
                * track.duration_scale
                * SAMPLE_RATE
                / 1000.0
            )
        )
        wav_path = str(selected["wav_path"])
        sample = _read_wav(wav_path)
        route_ntype = preview_route_ntype(
            track.bdo_instrument_id,
            ntype,
        )
        target_pitch = resolve_bdo_pitch(
            track.bdo_instrument_id,
            note.pitch,
            ntype,
        )
        native_sample_route = row_routes_ntype(
            selected,
            route_ntype,
        )
        native_articulation = preview_has_native_articulation(
            track.bdo_instrument_id,
            selected,
            route_ntype,
        )
        resample_pitch = target_pitch + (
            preview_pitch_offset_semitones(
                ntype,
                native_sample_route,
            )
        )
        ratio = sample_pitch_ratio(
            selected,
            resample_pitch,
            bank=bank,
        )
        loop_points = row_loop_points(
            selected,
            len(sample),
            source_sample_rate=_wav_sample_rate(wav_path),
            output_sample_rate=SAMPLE_RATE,
        )
        lifecycle = voice_lifecycle(
            track.bdo_instrument_id,
            ntype,
            note_frames,
            sample_output_frames(
                _active_signal_frames(wav_path),
                ratio,
            ),
            SAMPLE_RATE,
            native_articulation=native_sample_route,
            sample_loops=loop_points is not None,
            release_ms=row_release_ms(selected),
        )
        instance_limit = row_instance_limit(selected)
        relative_start = round(
            (note.start - start_ms) * SAMPLE_RATE / 1000.0
        )
        if relative_start + lifecycle.audible_frames <= 0:
            continue
        layer_specs = [(ratio, ntype, native_articulation, 1.0, True)]
        layer_specs.extend(
            (
                ratio * (2.0 ** (semitones / 12.0)),
                0,
                False,
                0.52,
                False,
            )
            for semitones in preview_chord_intervals(
                ntype,
                native_articulation=native_articulation,
            )
        )
        first_voice_index = len(prepared)
        prepared.extend(
            _PreparedVoice(
                relative_start=relative_start,
                velocity=velocity,
                playback_ratio=layer_ratio,
                sample=sample,
                row=selected,
                lifecycle=lifecycle,
                loop_points=loop_points,
                instrument_id=track.bdo_instrument_id,
                ntype=layer_ntype,
                native_articulation=layer_native,
                track_volume_gain=track_volume_preview_gain(
                    getattr(track, "bdo_track_volume", DEFAULT_TRACK_VOLUME)
                ),
                gain_scale=gain_scale,
                count_note=count_note,
            )
            for (
                layer_ratio,
                layer_ntype,
                layer_native,
                gain_scale,
                count_note,
            ) in layer_specs
        )
        prepared_events.append(_PreparedEvent(
            relative_start=relative_start,
            audible_frames=lifecycle.audible_frames,
            voice_indices=tuple(
                range(first_voice_index, len(prepared))
            ),
            instance_group_id=(
                instance_limit.group_id
                if instance_limit.enforceable
                else -1
            ),
            instance_scope_id=(
                -1
                if instance_limit.global_scope
                else int(
                    getattr(track, "track_id", request.track_order)
                )
            ),
            max_instances=(
                instance_limit.max_instances
                if instance_limit.enforceable
                else 0
            ),
            kill_newest=instance_limit.kill_newest,
        ))

    instance_release_frames = max(
        1,
        round(SAMPLE_RATE * INSTANCE_LIMIT_RELEASE_MS / 1000.0),
    )
    instance_plan = plan_instance_timeline(
        [
            InstanceTimelineItem(
                start_frame=event.relative_start,
                audible_frames=event.audible_frames,
                group_id=event.instance_group_id,
                scope_id=event.instance_scope_id,
                max_instances=event.max_instances,
                kill_newest=event.kill_newest,
            )
            for event in prepared_events
        ],
        instance_release_frames,
    )
    planned_voices: list[_PreparedVoice] = []
    for event_index, event in enumerate(prepared_events):
        if not instance_plan.accepted[event_index]:
            continue
        planned_lifecycle: VoiceLifecycle | None = None
        if instance_plan.forced_release[event_index]:
            planned_audible = instance_plan.audible_frames[event_index]
            planned_lifecycle = VoiceLifecycle(
                note_frames=(
                    prepared[event.voice_indices[0]].lifecycle.note_frames
                ),
                audible_frames=planned_audible,
                fade_out_frames=min(
                    planned_audible,
                    instance_release_frames,
                ),
            )
        for voice_index in event.voice_indices:
            voice = prepared[voice_index]
            planned_voices.append(
                replace(voice, lifecycle=planned_lifecycle)
                if planned_lifecycle is not None
                else voice
            )
    prepared = planned_voices
    end_frame = max(
        (
            voice.relative_start + voice.lifecycle.audible_frames
            for voice in prepared
        ),
        default=0,
    )
    frames = max(1, end_frame)
    mix = np.zeros((frames, 2), dtype=np.float32)
    rendered = 0
    for voice in prepared:
        start_frame = max(0, voice.relative_start)
        age_frames = max(0, -voice.relative_start)
        audible_remaining = max(
            0,
            voice.lifecycle.audible_frames - age_frames,
        )
        rendered_sample = _resample_for_note(
            voice.sample,
            voice.playback_ratio,
            audible_remaining,
            age_frames,
            loop_points=voice.loop_points,
        )
        if rendered_sample.size == 0:
            continue
        sample_end = min(len(mix), start_frame + len(rendered_sample))
        rendered_sample = rendered_sample[:sample_end - start_frame]
        rendered_sample *= (
            (voice.velocity / 127.0)
            * voice.track_volume_gain
            * row_volume_gain(voice.row)
            * voice.gain_scale
        )
        ages = age_frames + np.arange(
            len(rendered_sample), dtype=np.float32
        )
        apply_articulation_preview_in_place(
            rendered_sample,
            voice.instrument_id,
            voice.ntype,
            ages,
            voice.lifecycle.note_frames,
            SAMPLE_RATE,
            native_articulation=voice.native_articulation,
        )
        if voice.lifecycle.fade_out_frames > 0:
            fade = np.clip(
                (
                    voice.lifecycle.audible_frames
                    - ages
                    - 1.0
                )
                / voice.lifecycle.fade_out_frames,
                0.0,
                1.0,
            )
            rendered_sample *= fade[:, None]
        mix[start_frame:sample_end] += rendered_sample
        rendered += int(voice.count_note)

    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    if peak > 0.98:
        mix *= 0.98 / peak
    pcm = np.clip(mix * 32767.0, -32768, 32767).astype("<i2")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as target:
        target.setnchannels(2)
        target.setsampwidth(2)
        target.setframerate(SAMPLE_RATE)
        target.writeframes(pcm.tobytes())
    return RenderResult((len(mix) / SAMPLE_RATE) * 1000.0, rendered, tuple(sorted(missing)))
