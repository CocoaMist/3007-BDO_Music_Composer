"""Versioned, evidence-labelled game constraints for score experiments."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


EVIDENCE_STATES = frozenset({"verified", "inferred", "approximate"})


@dataclass(frozen=True, slots=True)
class Evidence:
    status: str
    source: str
    verified_at: str | None = None

    def __post_init__(self) -> None:
        if self.status not in EVIDENCE_STATES:
            raise ValueError(f"unknown evidence status: {self.status}")


@dataclass(frozen=True, slots=True)
class InstrumentRule:
    instrument_id: int
    pitch_min: int | None
    pitch_max: int | None
    allowed_pitches: frozenset[int] = frozenset()
    articulations: frozenset[int] = frozenset({0})
    evidence: Evidence = field(default_factory=lambda: Evidence("inferred", "legacy editor map"))

    def supports_pitch(self, pitch: int) -> bool | None:
        if self.allowed_pitches:
            return pitch in self.allowed_pitches
        if self.pitch_min is None or self.pitch_max is None:
            return None
        return self.pitch_min <= pitch <= self.pitch_max


@dataclass(frozen=True, slots=True)
class BdoProfile:
    profile_id: str
    format_version: int
    region: str
    game_version: str
    note_limit_per_track: int
    note_limit_per_instrument: int
    drum_instrument_id: int
    drum_pitch_min: int
    drum_pitch_max: int
    marnian_mode_offsets: Mapping[str, int]
    instruments: Mapping[int, InstrumentRule]
    evidence: Evidence


def _evidence(payload: Mapping[str, Any], fallback_source: str) -> Evidence:
    return Evidence(
        str(payload.get("status", "inferred")),
        str(payload.get("source", fallback_source)),
        str(payload["verified_at"]) if payload.get("verified_at") else None,
    )


def load_bdo_profile(
    path: Path,
    *,
    articulation_map: Mapping[int, Sequence[tuple[int, str]]] | None = None,
    supported_pitch_map: Mapping[int, frozenset[int]] | None = None,
) -> BdoProfile:
    payload = json.loads(path.read_text(encoding="utf-8"))
    instruments: dict[int, InstrumentRule] = {}
    for raw_id, raw_rule in payload.get("instruments", {}).items():
        instrument_id = int(raw_id, 0) if isinstance(raw_id, str) else int(raw_id)
        rule = dict(raw_rule)
        pitches = frozenset(int(item) for item in rule.get("allowed_pitches", ()))
        if supported_pitch_map is not None and supported_pitch_map.get(instrument_id):
            pitches = frozenset(int(item) for item in supported_pitch_map[instrument_id])
        articulations = frozenset(
            int(item) for item in rule.get("articulations", (0,))
        )
        if articulation_map is not None and instrument_id in articulation_map:
            articulations = frozenset(int(item[0]) for item in articulation_map[instrument_id]) | {0}
        instruments[instrument_id] = InstrumentRule(
            instrument_id,
            int(rule["pitch_min"]) if rule.get("pitch_min") is not None else None,
            int(rule["pitch_max"]) if rule.get("pitch_max") is not None else None,
            pitches,
            articulations,
            _evidence(rule.get("evidence", {}), f"{path.name}:instruments.{raw_id}"),
        )
    limits = payload["limits"]
    drum = payload["drum_set"]
    return BdoProfile(
        profile_id=str(payload["profile_id"]),
        format_version=int(payload["format_version"]),
        region=str(payload.get("region", "global")),
        game_version=str(payload.get("game_version", "unknown")),
        note_limit_per_track=int(limits["notes_per_track"]),
        note_limit_per_instrument=int(limits["notes_per_instrument"]),
        drum_instrument_id=int(drum["instrument_id"]),
        drum_pitch_min=int(drum["pitch_min"]),
        drum_pitch_max=int(drum["pitch_max"]),
        marnian_mode_offsets={str(key): int(value) for key, value in payload["marnian_mode_offsets"].items()},
        instruments=instruments,
        evidence=_evidence(payload.get("evidence", {}), path.name),
    )


__all__ = ["BdoProfile", "Evidence", "InstrumentRule", "load_bdo_profile"]
