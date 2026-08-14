"""Immutable conversion-setting policy shared by UI, persistence, and export.

This module deliberately has no Qt dependency.  It owns the distinction between
new-score preferences, neutral legacy projects, and imported BDO scores so a
caller never derives missing-field behavior from whichever project happened to
be open previously.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping


DEFAULT_CONVERSION_BPM_OVERRIDE: int | None = None
DEFAULT_CONVERSION_TRANSPOSE = 0
LEGACY_CONVERSION_TRANSPOSE = 0

VELOCITY_MODE_LAYERED = "layered"
VELOCITY_MODE_STEPPED = "stepped"
VELOCITY_MODE_RESCALE = "rescale"
VELOCITY_MODE_FLOOR = "floor"
VELOCITY_MODE_OFF = "off"
VELOCITY_MODE_PRESERVE = "preserve"
VELOCITY_MODES = frozenset(
    {
        VELOCITY_MODE_LAYERED,
        VELOCITY_MODE_STEPPED,
        VELOCITY_MODE_RESCALE,
        VELOCITY_MODE_FLOOR,
        VELOCITY_MODE_OFF,
        VELOCITY_MODE_PRESERVE,
    }
)
MATERIALIZED_VELOCITY_MODES = frozenset(
    {VELOCITY_MODE_OFF, VELOCITY_MODE_PRESERVE}
)

VelocityPair = tuple[int, int]
VelocityStep = VelocityPair | int | None


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    parsed = int(value)
    return parsed or None


def _pair(value: object) -> VelocityPair | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    return int(value[0]), int(value[1])


def _step(value: object) -> VelocityStep:
    pair = _pair(value)
    if pair is not None:
        return pair
    if value is None or value == "":
        return None
    return int(value)


@dataclass(frozen=True, slots=True)
class ConversionSettings:
    """One coherent snapshot of MIDI parsing and BDO export transforms."""

    bpm_override: int | None = DEFAULT_CONVERSION_BPM_OVERRIDE
    transpose: int = DEFAULT_CONVERSION_TRANSPOSE
    apply_sustain: bool = True
    flatten_tempo: bool = False
    velocity_mode: str = VELOCITY_MODE_PRESERVE
    vel_range: VelocityPair | None = None
    vel_floor: int | None = None
    vel_step: VelocityStep = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "bpm_override", _optional_int(self.bpm_override))
        object.__setattr__(self, "transpose", int(self.transpose))
        object.__setattr__(self, "apply_sustain", bool(self.apply_sustain))
        object.__setattr__(self, "flatten_tempo", bool(self.flatten_tempo))
        mode = str(self.velocity_mode or VELOCITY_MODE_PRESERVE)
        if mode not in VELOCITY_MODES:
            raise ValueError(f"unsupported velocity mode: {mode}")
        object.__setattr__(self, "velocity_mode", mode)
        object.__setattr__(self, "vel_range", _pair(self.vel_range))
        object.__setattr__(
            self,
            "vel_floor",
            None if self.vel_floor is None else int(self.vel_floor),
        )
        object.__setattr__(self, "vel_step", _step(self.vel_step))

    @classmethod
    def new_score_defaults(cls) -> "ConversionSettings":
        return cls()

    @classmethod
    def legacy_project_defaults(
        cls,
        source_format: str = "midi",
    ) -> "ConversionSettings":
        """Return neutral defaults for payloads predating explicit transforms."""

        return cls(
            transpose=LEGACY_CONVERSION_TRANSPOSE,
            velocity_mode=VELOCITY_MODE_PRESERVE,
        )

    @classmethod
    def bdo_import_defaults(cls) -> "ConversionSettings":
        return cls.legacy_project_defaults("bdo")

    @classmethod
    def from_preferences(cls, value: object) -> "ConversionSettings":
        """Overlay saved application preferences on current new-score defaults."""

        return cls.overlay(value, cls.new_score_defaults())

    @classmethod
    def from_project_payload(
        cls,
        value: object,
        *,
        source_format: str = "midi",
    ) -> "ConversionSettings":
        """Read project settings without inheriting unrelated runtime state."""

        return cls.overlay(value, cls.legacy_project_defaults(source_format))

    @classmethod
    def from_export_parameters(
        cls,
        params: Mapping[str, Any],
    ) -> "ConversionSettings":
        """Accept the typed boundary or the legacy flattened parameter bag."""

        settings = params.get("conversion_settings")
        if isinstance(settings, cls):
            return settings
        if isinstance(settings, Mapping):
            raw_mode = settings.get(
                "velocity_mode",
                VELOCITY_MODE_PRESERVE,
            )
            mode = str(raw_mode or VELOCITY_MODE_PRESERVE)
            if mode not in VELOCITY_MODES:
                raise ValueError(f"unsupported velocity mode: {mode}")
            return cls.overlay(settings, cls.new_score_defaults())
        if settings is not None:
            raise TypeError(
                "conversion_settings must be a ConversionSettings instance "
                "or mapping"
            )
        if params.get("vel_layered"):
            velocity_mode = VELOCITY_MODE_LAYERED
        elif params.get("vel_range") is not None:
            velocity_mode = VELOCITY_MODE_RESCALE
        elif params.get("vel_step") is not None:
            velocity_mode = VELOCITY_MODE_STEPPED
        elif params.get("vel_floor") is not None:
            velocity_mode = VELOCITY_MODE_FLOOR
        else:
            velocity_mode = VELOCITY_MODE_OFF
        return cls(
            bpm_override=params.get("bpm_override"),
            transpose=int(params.get("transpose", LEGACY_CONVERSION_TRANSPOSE)),
            apply_sustain=bool(params.get("apply_sustain", True)),
            flatten_tempo=bool(params.get("flatten_tempo", False)),
            velocity_mode=velocity_mode,
            vel_range=params.get("vel_range"),
            vel_floor=params.get("vel_floor"),
            vel_step=params.get("vel_step"),
        )

    @classmethod
    def overlay(
        cls,
        value: object,
        base: "ConversionSettings",
    ) -> "ConversionSettings":
        source = _mapping(value)
        mode = str(source.get("velocity_mode", base.velocity_mode) or base.velocity_mode)
        if mode not in VELOCITY_MODES:
            mode = base.velocity_mode
        vel_floor = base.vel_floor
        if "vel_floor" in source:
            raw_vel_floor = source.get("vel_floor")
            vel_floor = None if raw_vel_floor is None else int(raw_vel_floor)
        return cls(
            bpm_override=(
                _optional_int(source.get("bpm_override"))
                if "bpm_override" in source
                else base.bpm_override
            ),
            transpose=int(source.get("transpose", base.transpose)),
            apply_sustain=bool(source.get("apply_sustain", base.apply_sustain)),
            flatten_tempo=bool(source.get("flatten_tempo", base.flatten_tempo)),
            velocity_mode=mode,
            vel_range=(
                _pair(source.get("vel_range"))
                if "vel_range" in source
                else base.vel_range
            ),
            vel_floor=vel_floor,
            vel_step=(
                _step(source.get("vel_step"))
                if "vel_step" in source
                else base.vel_step
            ),
        )

    def with_updates(self, **changes: object) -> "ConversionSettings":
        return replace(self, **changes)

    def to_payload(self) -> dict[str, Any]:
        return {
            "bpm_override": self.bpm_override,
            "transpose": self.transpose,
            "apply_sustain": self.apply_sustain,
            "flatten_tempo": self.flatten_tempo,
            "velocity_mode": self.velocity_mode,
            "vel_range": list(self.vel_range) if self.vel_range else None,
            "vel_floor": self.vel_floor,
            "vel_step": (
                list(self.vel_step)
                if isinstance(self.vel_step, tuple)
                else self.vel_step
            ),
        }

    def midi_parse_parameters(self) -> dict[str, bool]:
        """Project only the settings owned by MIDI parsing."""

        return {
            "apply_sustain": self.apply_sustain,
            "flatten_tempo": self.flatten_tempo,
        }

    def export_transform_parameters(self) -> dict[str, Any]:
        return {
            "bpm_override": self.bpm_override,
            "vel_range": (
                self.vel_range
                if self.velocity_mode == VELOCITY_MODE_RESCALE
                else None
            ),
            "vel_floor": (
                self.vel_floor
                if self.velocity_mode in {VELOCITY_MODE_FLOOR, VELOCITY_MODE_STEPPED}
                else None
            ),
            "vel_step": (
                self.vel_step
                if self.velocity_mode == VELOCITY_MODE_STEPPED
                else None
            ),
            "vel_layered": self.velocity_mode == VELOCITY_MODE_LAYERED,
            "transpose": self.transpose,
        }

    def is_neutral_export_transform(self) -> bool:
        params = self.export_transform_parameters()
        return (
            params["bpm_override"] is None
            and not params["transpose"]
            and params["vel_range"] is None
            and not params["vel_floor"]
            and not params["vel_step"]
            and not params["vel_layered"]
        )


__all__ = [
    "ConversionSettings",
    "DEFAULT_CONVERSION_BPM_OVERRIDE",
    "DEFAULT_CONVERSION_TRANSPOSE",
    "LEGACY_CONVERSION_TRANSPOSE",
    "MATERIALIZED_VELOCITY_MODES",
    "VELOCITY_MODE_OFF",
    "VELOCITY_MODE_PRESERVE",
    "VELOCITY_MODES",
]
