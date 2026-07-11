"""Registration and discovery for interchangeable MIDI optimization algorithms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable


@runtime_checkable
class OptimizerAlgorithm(Protocol):
    """Callable contract shared by built-in and third-party optimizers."""

    def __call__(
        self,
        tracks: list,
        bpm: int,
        supported_articulations: dict[int, list[tuple[int, str]]],
        config: object | None = None,
        time_sig: int = 4,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class AlgorithmDescriptor:
    """Human-readable metadata for an optimizer registered in this process."""

    name: str
    title: str
    description: str
    runner: OptimizerAlgorithm


_ALGORITHMS: dict[str, AlgorithmDescriptor] = {}


def register_algorithm(
    name: str,
    runner: OptimizerAlgorithm,
    *,
    title: str,
    description: str = "",
    replace: bool = False,
) -> AlgorithmDescriptor:
    """Register an optimizer without coupling it to the desktop UI."""
    key = name.strip().lower()
    if not key:
        raise ValueError("algorithm name must not be empty")
    if not callable(runner):
        raise TypeError("algorithm runner must be callable")
    if key in _ALGORITHMS and not replace:
        raise ValueError(f"optimization algorithm already registered: {key}")
    descriptor = AlgorithmDescriptor(key, title.strip() or key, description.strip(), runner)
    _ALGORITHMS[key] = descriptor
    return descriptor


def get_algorithm(name: str) -> AlgorithmDescriptor:
    """Return a registered algorithm or raise a useful lookup error."""
    key = name.strip().lower()
    try:
        return _ALGORITHMS[key]
    except KeyError as exc:
        choices = ", ".join(sorted(_ALGORITHMS)) or "<none>"
        raise KeyError(f"unknown optimization algorithm {name!r}; available: {choices}") from exc


def list_algorithms() -> tuple[AlgorithmDescriptor, ...]:
    """Return a deterministic snapshot suitable for a future UI selector."""
    return tuple(_ALGORITHMS[key] for key in sorted(_ALGORITHMS))


def unregister_algorithm(name: str) -> None:
    """Remove an extension algorithm, primarily for tests and plugin teardown."""
    del _ALGORITHMS[name.strip().lower()]
