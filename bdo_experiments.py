"""Privacy-safe metadata records for local game/audio A/B experiments."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Sequence

from bdo_profile import EVIDENCE_STATES


@dataclass(frozen=True, slots=True)
class AbExperimentRecord:
    experiment_id: str
    profile_id: str
    game_version: str
    instrument_id: int
    ntype: int
    test_conditions: str
    conclusion: str
    confidence: str
    input_fingerprint: str
    reference_fingerprint: str = ""
    tested_at: str = ""

    def __post_init__(self) -> None:
        if self.confidence not in EVIDENCE_STATES:
            raise ValueError(f"invalid experiment confidence: {self.confidence}")
        for value in (self.input_fingerprint, self.reference_fingerprint):
            if value and ("/" in value or "\\" in value or ":" in value):
                raise ValueError("experiment records store fingerprints, not local paths")


def write_experiment_records(path: Path, records: Sequence[AbExperimentRecord]) -> None:
    payload = {"schema_version": 1, "experiments": [asdict(item) for item in records]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_experiment_records(path: Path) -> tuple[AbExperimentRecord, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if int(payload.get("schema_version", 0)) != 1:
        raise ValueError("unsupported A/B experiment schema")
    return tuple(AbExperimentRecord(**item) for item in payload.get("experiments", ()))


__all__ = ["AbExperimentRecord", "read_experiment_records", "write_experiment_records"]
