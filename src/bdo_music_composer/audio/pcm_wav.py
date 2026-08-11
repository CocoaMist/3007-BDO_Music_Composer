"""PCM WAV decoding primitives shared by preview and offline rendering."""

from __future__ import annotations

import numpy as np


def pcm_bytes_to_float32(
    payload: bytes | bytearray,
    sample_width: int,
    channels: int,
) -> np.ndarray:
    """Decode interleaved little-endian 16/24-bit PCM into frame rows."""

    width = int(sample_width)
    channel_count = int(channels)
    if width not in {2, 3}:
        raise ValueError(f"unsupported PCM sample width: {width * 8}-bit")
    if channel_count < 1:
        raise ValueError("PCM channel count must be positive")
    frame_width = width * channel_count
    if len(payload) % frame_width:
        raise ValueError("PCM payload is not frame-aligned")

    if width == 2:
        samples = np.frombuffer(payload, dtype="<i2").astype(np.float32)
        samples *= np.float32(1.0 / 32768.0)
    else:
        octets = np.frombuffer(payload, dtype=np.uint8).reshape(-1, 3)
        values = (
            octets[:, 0].astype(np.int32)
            | (octets[:, 1].astype(np.int32) << 8)
            | (octets[:, 2].astype(np.int32) << 16)
        )
        values = (values ^ 0x800000) - 0x800000
        samples = values.astype(np.float32)
        samples *= np.float32(1.0 / 8388608.0)
    return samples.reshape(-1, channel_count)


def stereo_pcm(pcm: np.ndarray) -> np.ndarray:
    """Project one-or-more-channel PCM to the engine's stereo contract."""

    if pcm.ndim != 2 or pcm.shape[1] < 1:
        raise ValueError("PCM must contain at least one channel")
    if pcm.shape[1] == 1:
        return np.repeat(pcm, 2, axis=1)
    return pcm[:, :2]


__all__ = ["pcm_bytes_to_float32", "stereo_pcm"]
