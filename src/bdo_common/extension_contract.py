"""Qt-free version and capability negotiation for extension boundaries."""

from __future__ import annotations

from dataclasses import dataclass
import re


_CAPABILITY_PATTERN = re.compile(r"^[a-z][a-z0-9.-]{0,63}$")
VALID_EXTENSION_TRANSPORTS = frozenset({
    "python-in-process-trusted",
    "python-api",
    "native-c-abi",
    "ndjson-stdio",
})


class ExtensionContractError(ValueError):
    """An extension cannot safely run against this host contract."""


def _capabilities(values: frozenset[str]) -> frozenset[str]:
    normalized = frozenset(str(value).strip().lower() for value in values)
    if any(not _CAPABILITY_PATTERN.fullmatch(value) for value in normalized):
        raise ExtensionContractError("extension capability identifiers are invalid")
    return normalized


@dataclass(frozen=True, slots=True)
class HostExtensionContract:
    api_name: str
    api_version: int
    capabilities: frozenset[str]
    transports: frozenset[str]

    def __post_init__(self) -> None:
        if not self.api_name.strip() or self.api_version <= 0:
            raise ExtensionContractError("host extension API identity is invalid")
        object.__setattr__(self, "capabilities", _capabilities(self.capabilities))
        if not self.transports or not self.transports.issubset(VALID_EXTENSION_TRANSPORTS):
            raise ExtensionContractError("host extension transports are invalid")


@dataclass(frozen=True, slots=True)
class ExtensionRequirement:
    api_name: str
    minimum_api_version: int
    maximum_api_version: int
    required_capabilities: frozenset[str] = frozenset()
    optional_capabilities: frozenset[str] = frozenset()
    transport: str = "ndjson-stdio"

    def __post_init__(self) -> None:
        if (
            not self.api_name.strip()
            or self.minimum_api_version <= 0
            or self.maximum_api_version < self.minimum_api_version
        ):
            raise ExtensionContractError("extension API version range is invalid")
        object.__setattr__(
            self,
            "required_capabilities",
            _capabilities(self.required_capabilities),
        )
        object.__setattr__(
            self,
            "optional_capabilities",
            _capabilities(self.optional_capabilities),
        )
        if self.transport not in VALID_EXTENSION_TRANSPORTS:
            raise ExtensionContractError("extension transport is invalid")


@dataclass(frozen=True, slots=True)
class NegotiatedExtension:
    api_name: str
    api_version: int
    capabilities: frozenset[str]
    transport: str


def negotiate_extension(
    host: HostExtensionContract,
    requirement: ExtensionRequirement,
) -> NegotiatedExtension:
    if host.api_name != requirement.api_name:
        raise ExtensionContractError("extension API identity mismatch")
    if not (
        requirement.minimum_api_version
        <= host.api_version
        <= requirement.maximum_api_version
    ):
        raise ExtensionContractError("extension API version is incompatible")
    if requirement.transport not in host.transports:
        raise ExtensionContractError("extension transport is not supported")
    missing = requirement.required_capabilities - host.capabilities
    if missing:
        raise ExtensionContractError(
            "extension requires unsupported capabilities: "
            + ", ".join(sorted(missing))
        )
    enabled = requirement.required_capabilities | (
        requirement.optional_capabilities & host.capabilities
    )
    return NegotiatedExtension(
        host.api_name,
        host.api_version,
        enabled,
        requirement.transport,
    )


__all__ = [
    "ExtensionContractError",
    "ExtensionRequirement",
    "HostExtensionContract",
    "NegotiatedExtension",
    "VALID_EXTENSION_TRANSPORTS",
    "negotiate_extension",
]
