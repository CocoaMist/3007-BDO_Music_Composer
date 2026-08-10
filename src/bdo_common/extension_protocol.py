"""Bounded NDJSON envelope for isolated Windows extension processes."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Mapping


EXTENSION_PROTOCOL_VERSION = 1
MAX_EXTENSION_MESSAGE_BYTES = 1024 * 1024
_METHOD_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_FIELDS = frozenset({"protocol_version", "request_id", "method", "payload"})


class ExtensionProtocolError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ExtensionEnvelope:
    request_id: str
    method: str
    payload: Mapping[str, Any]
    protocol_version: int = EXTENSION_PROTOCOL_VERSION


def encode_extension_envelope(envelope: ExtensionEnvelope) -> bytes:
    if envelope.protocol_version != EXTENSION_PROTOCOL_VERSION:
        raise ExtensionProtocolError("unsupported extension protocol version")
    if not envelope.request_id or len(envelope.request_id) > 128:
        raise ExtensionProtocolError("extension request ID is invalid")
    if not _METHOD_PATTERN.fullmatch(envelope.method):
        raise ExtensionProtocolError("extension method is invalid")
    if not isinstance(envelope.payload, Mapping):
        raise ExtensionProtocolError("extension payload must be an object")
    try:
        encoded = json.dumps(
            {
                "protocol_version": envelope.protocol_version,
                "request_id": envelope.request_id,
                "method": envelope.method,
                "payload": dict(envelope.payload),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8") + b"\n"
    except (TypeError, ValueError) as exc:
        raise ExtensionProtocolError("extension payload is not JSON-safe") from exc
    if len(encoded) > MAX_EXTENSION_MESSAGE_BYTES:
        raise ExtensionProtocolError("extension message exceeds the size limit")
    return encoded


def decode_extension_envelope(data: bytes) -> ExtensionEnvelope:
    if not data or len(data) > MAX_EXTENSION_MESSAGE_BYTES or not data.endswith(b"\n"):
        raise ExtensionProtocolError("extension message framing is invalid")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ExtensionProtocolError("extension message is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict) or set(payload) != _FIELDS:
        raise ExtensionProtocolError("extension message fields are invalid")
    envelope = ExtensionEnvelope(
        request_id=str(payload["request_id"]),
        method=str(payload["method"]),
        payload=payload["payload"],
        protocol_version=int(payload["protocol_version"]),
    )
    encode_extension_envelope(envelope)
    return envelope


__all__ = [
    "EXTENSION_PROTOCOL_VERSION",
    "MAX_EXTENSION_MESSAGE_BYTES",
    "ExtensionEnvelope",
    "ExtensionProtocolError",
    "decode_extension_envelope",
    "encode_extension_envelope",
]
