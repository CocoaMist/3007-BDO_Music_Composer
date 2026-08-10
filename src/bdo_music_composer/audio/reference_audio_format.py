"""Bounded container checks for user-selected reference audio."""

from __future__ import annotations

from pathlib import Path


SUPPORTED_REFERENCE_AUDIO_SUFFIXES = frozenset({".mp3", ".wav"})
_PROBE_BYTES = 65_536

INVALID_REFERENCE_AUDIO_SOURCE = (
    "无法识别有效的 WAV/MP3 音频头；文件可能已损坏，"
    "或实际是 M4A/AAC/网页文件。请重新导出为 WAV 或标准 MP3。"
)
MISMATCHED_REFERENCE_AUDIO_SOURCE = (
    "参考音频的扩展名与实际格式不一致；"
    "请用音频软件重新导出为 WAV 或标准 MP3。"
)
UNSUPPORTED_REFERENCE_AUDIO_SOURCE = (
    "当前仅支持 WAV 和标准 MP3 参考音频；请先转换后再载入。"
)
MISSING_REFERENCE_AUDIO_SOURCE = "参考音频文件不存在或无法读取。"


class ReferenceAudioFormatError(ValueError):
    """A stable, user-safe reason a reference file cannot be decoded."""


def _mpeg_layer_three_frame_length(header: bytes) -> int | None:
    """Return one MPEG Layer III frame length for a plausible header."""

    if len(header) < 4 or header[0] != 0xFF or header[1] & 0xE0 != 0xE0:
        return None
    version = (header[1] >> 3) & 0x03
    layer = (header[1] >> 1) & 0x03
    bitrate_index = (header[2] >> 4) & 0x0F
    sample_rate_index = (header[2] >> 2) & 0x03
    if (
        version == 0x01
        or layer != 0x01
        or bitrate_index in {0x00, 0x0F}
        or sample_rate_index == 0x03
    ):
        return None

    if version == 0x03:
        bitrates = (
            0,
            32,
            40,
            48,
            56,
            64,
            80,
            96,
            112,
            128,
            160,
            192,
            224,
            256,
            320,
        )
        sample_rates = (44_100, 48_000, 32_000)
        coefficient = 144
    elif version == 0x02:
        bitrates = (
            0,
            8,
            16,
            24,
            32,
            40,
            48,
            56,
            64,
            80,
            96,
            112,
            128,
            144,
            160,
        )
        sample_rates = (22_050, 24_000, 16_000)
        coefficient = 72
    else:
        bitrates = (
            0,
            8,
            16,
            24,
            32,
            40,
            48,
            56,
            64,
            80,
            96,
            112,
            128,
            144,
            160,
        )
        sample_rates = (11_025, 12_000, 8_000)
        coefficient = 72
    bitrate = bitrates[bitrate_index] * 1_000
    sample_rate = sample_rates[sample_rate_index]
    padding = (header[2] >> 1) & 0x01
    frame_length = coefficient * bitrate // sample_rate + padding
    return frame_length if frame_length >= 24 else None


def _contains_consecutive_mp3_frames(payload: bytes) -> bool:
    """Reject coincidental sync bits by requiring two correctly spaced frames."""

    limit = max(0, len(payload) - 4)
    for offset in range(limit):
        frame_length = _mpeg_layer_three_frame_length(
            payload[offset : offset + 4]
        )
        if frame_length is None:
            continue
        next_offset = offset + frame_length
        if next_offset + 4 > len(payload):
            continue
        if _mpeg_layer_three_frame_length(
            payload[next_offset : next_offset + 4]
        ) is not None:
            return True
    return False


def _mp3_probe_offset(header: bytes, file_size: int) -> int | None:
    """Return the first byte after a valid ID3v2 tag, or zero without one."""

    if not header.startswith(b"ID3"):
        return 0
    if len(header) < 10 or any(byte & 0x80 for byte in header[6:10]):
        return None
    tag_size = (
        (header[6] << 21)
        | (header[7] << 14)
        | (header[8] << 7)
        | header[9]
    )
    offset = 10 + tag_size
    return offset if offset < file_size else None


def detect_reference_audio_format(path: Path | str) -> str | None:
    """Return ``wav``/``mp3`` from bounded content inspection."""

    candidate = Path(path)
    try:
        file_size = candidate.stat().st_size
        with candidate.open("rb") as stream:
            header = stream.read(12)
            if (
                len(header) >= 12
                and header[:4] in {b"RIFF", b"RF64", b"RIFX"}
                and header[8:12] == b"WAVE"
            ):
                return "wav"
            probe_offset = _mp3_probe_offset(header, file_size)
            if probe_offset is None:
                return None
            stream.seek(probe_offset)
            payload = stream.read(_PROBE_BYTES)
    except OSError:
        return None
    return "mp3" if _contains_consecutive_mp3_frames(payload) else None


def validate_reference_audio_file(path: Path | str) -> str:
    """Validate the supported suffix and real container before native decode."""

    candidate = Path(path)
    if not candidate.is_file():
        raise ReferenceAudioFormatError(MISSING_REFERENCE_AUDIO_SOURCE)
    suffix = candidate.suffix.lower()
    if suffix not in SUPPORTED_REFERENCE_AUDIO_SUFFIXES:
        raise ReferenceAudioFormatError(UNSUPPORTED_REFERENCE_AUDIO_SOURCE)
    detected = detect_reference_audio_format(candidate)
    if detected is None:
        raise ReferenceAudioFormatError(INVALID_REFERENCE_AUDIO_SOURCE)
    if suffix != f".{detected}":
        raise ReferenceAudioFormatError(MISMATCHED_REFERENCE_AUDIO_SOURCE)
    return detected


__all__ = [
    "INVALID_REFERENCE_AUDIO_SOURCE",
    "MISMATCHED_REFERENCE_AUDIO_SOURCE",
    "MISSING_REFERENCE_AUDIO_SOURCE",
    "ReferenceAudioFormatError",
    "SUPPORTED_REFERENCE_AUDIO_SUFFIXES",
    "UNSUPPORTED_REFERENCE_AUDIO_SOURCE",
    "detect_reference_audio_format",
    "validate_reference_audio_file",
]
