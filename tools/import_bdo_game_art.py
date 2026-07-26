"""Import game-owned composition artwork into an explicit local cache.

This tool is intentionally narrow.  It reads two allow-listed resources from
the user's own Black Desert PAZ directory, validates the game's CSS sprite
coordinates, and writes per-instrument PNG tiles to a local cache selected by
the user.  It never changes PAZ files, never writes into a Git worktree, and
never places extracted assets in an application project or distributable.

The PAZ container and ICE implementation are shared with
``tools.list_bdo_paz_audio``.  Unknown archive/container versions, paths,
compression modes, sprite layouts, and oversized inputs fail closed.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile
from typing import Iterable, Mapping

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.list_bdo_paz_audio import (
    Ice,
    archive_table_span,
    decode_game_path,
    validate_game_path,
)


IMPORT_FORMAT = 1
IMPORT_VERSION = "bdo-local-instrument-art-v1"
SUPPORTED_META_VERSIONS = frozenset({757})
KNOWN_UI_ARCHIVES: Mapping[int, tuple[int, ...]] = {757: (6445,)}

COMPOSITION_CSS_PATH = "ui_data/ui_html/contents/css/musiccomposition.css"
INSTRUMENT_SPRITE_PATH = "ui_data/ui_html/contents/img/spr_instrument.png"
ALLOWED_GAME_PATHS = frozenset({COMPOSITION_CSS_PATH, INSTRUMENT_SPRITE_PATH})

# These are the editor's logical instrument IDs.  The four Marnian source-mode
# variants are encoded by the game as base ID + 0..3, but the editor stores the
# base ID and its source mode separately.  One base tile is therefore enough.
EDITOR_INSTRUMENT_IDS = (
    0x00, 0x01, 0x02, 0x04, 0x05, 0x06, 0x07, 0x08,
    0x0A, 0x0B, 0x0D, 0x0E, 0x0F, 0x10, 0x11, 0x12, 0x13,
    0x14, 0x18, 0x1C, 0x20, 0x24, 0x25, 0x26, 0x27, 0x28,
)

PAZ_ICE_KEY = bytes.fromhex("51 F3 0F 11 04 24 6A 00")
MAX_META_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_TABLE_BYTES = 128 * 1024 * 1024
MAX_PATH_TABLE_BYTES = 64 * 1024 * 1024
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_DECOMPRESSED_BYTES = 16 * 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class GameArtImportError(ValueError):
    """A validation failure that must leave the previous cache untouched."""


@dataclass(frozen=True, slots=True)
class PazMeta:
    version: int
    sha256: str
    archives: Mapping[int, tuple[int, int]]  # archive id -> (crc, size)


@dataclass(frozen=True, slots=True)
class PazEntry:
    archive_id: int
    offset: int
    packed_size: int
    original_size: int
    game_path: str


@dataclass(frozen=True, slots=True)
class SpriteLayout:
    tile_width: int
    tile_height: int
    positions: Mapping[int, tuple[int, int]]


@dataclass(frozen=True, slots=True)
class GameArtImportReport:
    output_dir: str
    meta_version: int
    meta_sha256: str
    sprite_sha256: str
    css_sha256: str
    image_count: int
    reused: bool


def _read_bounded(path: Path, maximum: int, label: str) -> bytes:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise GameArtImportError(f"{label} is unavailable: {path.name}") from exc
    if size <= 0 or size > maximum:
        raise GameArtImportError(
            f"{label} size is outside the supported range: {size}"
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise GameArtImportError(f"cannot read {label}: {path.name}") from exc


def read_paz_meta(
    paz_root: str | Path,
    *,
    allow_unverified_meta_version: bool = False,
) -> PazMeta:
    """Read the bounded archive table and reject unreviewed versions by default."""

    raw_root = str(paz_root or "").strip()
    if not raw_root:
        raise GameArtImportError("PAZ directory is empty")
    root = Path(raw_root)
    if not root.is_dir():
        raise GameArtImportError("PAZ directory is unavailable")
    meta_path = root / "pad00000.meta"
    try:
        meta_size = meta_path.stat().st_size
    except OSError as exc:
        raise GameArtImportError("PAZ meta is unavailable") from exc
    if meta_size < 8 or meta_size > MAX_META_BYTES:
        raise GameArtImportError(
            f"PAZ meta size is outside the supported range: {meta_size}"
        )
    digest = hashlib.sha256()
    try:
        with meta_path.open("rb") as stream:
            header = stream.read(8)
            if len(header) != 8:
                raise GameArtImportError("PAZ meta header is truncated")
            version, count = struct.unpack("<II", header)
            table_size = count * 12
            if 8 + table_size > meta_size or 8 + table_size > MAX_META_BYTES:
                raise GameArtImportError("PAZ meta archive table is truncated")
            table = stream.read(table_size)
            if len(table) != table_size:
                raise GameArtImportError("PAZ meta archive table is truncated")
            digest.update(header)
            digest.update(table)
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise GameArtImportError("cannot read PAZ meta") from exc
    table_end = 8 + count * 12
    if table_end > MAX_META_BYTES:
        raise GameArtImportError("PAZ meta archive table is too large")
    if (
        version not in SUPPORTED_META_VERSIONS
        and not allow_unverified_meta_version
    ):
        raise GameArtImportError(
            f"PAZ meta version {version} is not reviewed; "
            "explicit override is required"
        )
    archives: dict[int, tuple[int, int]] = {}
    for archive_id, crc, size in struct.iter_unpack("<III", table):
        if archive_id in archives:
            raise GameArtImportError(f"duplicate PAZ archive id: {archive_id}")
        archives[int(archive_id)] = (int(crc), int(size))
    return PazMeta(
        version=int(version),
        sha256=digest.hexdigest(),
        archives=archives,
    )


def _archive_candidates(meta: PazMeta) -> tuple[int, ...]:
    preferred = tuple(
        archive_id
        for archive_id in KNOWN_UI_ARCHIVES.get(meta.version, ())
        if archive_id in meta.archives
    )
    remainder = tuple(
        archive_id for archive_id in meta.archives if archive_id not in preferred
    )
    return preferred + remainder


def _index_archive(
    paz_root: Path,
    meta: PazMeta,
    archive_id: int,
    wanted: frozenset[str],
) -> dict[str, PazEntry]:
    archive = paz_root / f"PAD{archive_id:05}.PAZ"
    if not archive.is_file():
        return {}
    try:
        archive_size = archive.stat().st_size
    except OSError as exc:
        raise GameArtImportError(f"cannot stat {archive.name}") from exc
    expected_size = meta.archives[archive_id][1]
    if expected_size and archive_size != expected_size:
        raise GameArtImportError(
            f"{archive.name} size does not match PAZ meta"
        )
    try:
        with archive.open("rb") as stream:
            header = stream.read(12)
            if len(header) != 12:
                raise GameArtImportError(f"{archive.name} header is truncated")
            _crc, file_count, path_length = struct.unpack("<III", header)
            info_size, _table_end = archive_table_span(
                archive_size, file_count, path_length
            )
            if info_size > MAX_ARCHIVE_TABLE_BYTES:
                raise GameArtImportError(f"{archive.name} file table is too large")
            if path_length > MAX_PATH_TABLE_BYTES:
                raise GameArtImportError(f"{archive.name} path table is too large")
            info_bytes = stream.read(info_size)
            encrypted_paths = stream.read(path_length)
    except OSError as exc:
        raise GameArtImportError(f"cannot read {archive.name}") from exc
    except ValueError as exc:
        raise GameArtImportError(str(exc)) from exc
    if len(info_bytes) != info_size or len(encrypted_paths) != path_length:
        raise GameArtImportError(f"{archive.name} tables are truncated")
    try:
        path_parts = Ice(PAZ_ICE_KEY).decrypt(encrypted_paths).split(b"\0")
    except ValueError as exc:
        raise GameArtImportError(f"{archive.name} path decryption failed") from exc

    found: dict[str, PazEntry] = {}
    for (
        _file_crc,
        folder_id,
        file_id,
        offset,
        packed_size,
        original_size,
    ) in struct.iter_unpack("<IIIIII", info_bytes):
        if folder_id >= len(path_parts) or file_id >= len(path_parts):
            raise GameArtImportError(f"{archive.name} contains invalid path ids")
        decoded, _encoding = decode_game_path(
            path_parts[folder_id] + path_parts[file_id]
        )
        try:
            normalized = validate_game_path(decoded)
        except ValueError as exc:
            raise GameArtImportError(str(exc)) from exc
        if normalized not in wanted:
            continue
        if normalized in found:
            raise GameArtImportError(f"duplicate game UI path: {normalized}")
        if packed_size <= 0 or packed_size > MAX_SOURCE_BYTES:
            raise GameArtImportError(f"game UI asset is too large: {normalized}")
        if original_size <= 0 or original_size > MAX_DECOMPRESSED_BYTES:
            raise GameArtImportError(
                f"game UI decoded asset is too large: {normalized}"
            )
        if offset > archive_size or packed_size > archive_size - offset:
            raise GameArtImportError(f"game UI asset is outside {archive.name}")
        found[normalized] = PazEntry(
            archive_id=int(archive_id),
            offset=int(offset),
            packed_size=int(packed_size),
            original_size=int(original_size),
            game_path=normalized,
        )
    return found


def index_composition_ui_assets(
    paz_root: str | Path,
    *,
    allow_unverified_meta_version: bool = False,
) -> tuple[PazMeta, Mapping[str, PazEntry]]:
    """Locate only the allow-listed CSS and sprite without a broad extraction."""

    meta = read_paz_meta(
        paz_root,
        allow_unverified_meta_version=allow_unverified_meta_version,
    )
    root = Path(str(paz_root).strip())
    remaining = set(ALLOWED_GAME_PATHS)
    found: dict[str, PazEntry] = {}
    for archive_id in _archive_candidates(meta):
        matches = _index_archive(root, meta, archive_id, frozenset(remaining))
        found.update(matches)
        remaining.difference_update(matches)
        if not remaining:
            break
    if remaining:
        missing = ", ".join(sorted(remaining))
        raise GameArtImportError(f"composition UI assets were not found: {missing}")
    return meta, found


def decompress_paz_payload(
    decrypted: bytes,
    *,
    expected_size: int,
    maximum_size: int = MAX_DECOMPRESSED_BYTES,
) -> bytes:
    """Decode one bounded PAZ payload using the reviewed 0x6e/0x6f wrapper."""

    if expected_size <= 0 or expected_size > maximum_size:
        raise GameArtImportError("decoded PAZ payload size is not allowed")
    if len(decrypted) < expected_size and not decrypted:
        raise GameArtImportError("decrypted PAZ payload is empty")
    if decrypted[0] not in (0x6E, 0x6F):
        if len(decrypted) < expected_size:
            raise GameArtImportError("raw PAZ payload is truncated")
        return bytes(decrypted[:expected_size])
    if len(decrypted) < 9:
        raise GameArtImportError("PAZ compression header is truncated")
    packed_length, output_length = struct.unpack_from("<II", decrypted, 1)
    if output_length != expected_size or output_length > maximum_size:
        raise GameArtImportError("PAZ compression size does not match the index")
    if packed_length < 9 or packed_length > len(decrypted):
        raise GameArtImportError("PAZ compressed length is invalid")
    if decrypted[0] == 0x6E:
        end = 9 + output_length
        if end > packed_length:
            raise GameArtImportError("stored PAZ payload is truncated")
        return bytes(decrypted[9:end])
    return _decompress_black_desert_lz(
        decrypted,
        packed_length=packed_length,
        output_length=output_length,
    )


def _decompress_black_desert_lz(
    source: bytes,
    *,
    packed_length: int,
    output_length: int,
) -> bytes:
    """Bounds-checked Python translation of the game's 0x6f LZ decoder."""

    literal_lengths = (4, 0, 1, 0, 2, 0, 1, 0, 3, 0, 1, 0, 2, 0, 1, 0)
    output = bytearray(output_length)
    source_index = 9
    output_index = 0
    group_header = 1

    while True:
        while True:
            if group_header == 1:
                if source_index + 4 > packed_length:
                    raise GameArtImportError("compressed PAZ group header is truncated")
                group_header = struct.unpack_from("<I", source, source_index)[0]
                source_index += 4
            if source_index + 4 > packed_length:
                raise GameArtImportError("compressed PAZ token is truncated")
            token = struct.unpack_from("<I", source, source_index)[0]
            if not (group_header & 1):
                break
            if (token & 0x03) == 0x03:
                if (token & 0x7F) == 3:
                    distance = token >> 15
                    length = ((token >> 7) & 0xFF) + 3
                    token_size = 4
                else:
                    distance = (token >> 7) & 0x1FFFF
                    length = ((token >> 2) & 0x1F) + 2
                    token_size = 3
            elif (token & 0x03) == 0x02:
                distance = (token & 0xFFFF) >> 6
                length = ((token >> 2) & 0x0F) + 3
                token_size = 2
            elif (token & 0x03) == 0x01:
                distance = (token & 0xFFFF) >> 2
                length = 3
                token_size = 2
            else:
                distance = (token & 0xFF) >> 2
                length = 3
                token_size = 1
            if source_index + token_size > packed_length:
                raise GameArtImportError("compressed PAZ match token is truncated")
            if distance < 3 or distance > output_index:
                raise GameArtImportError("compressed PAZ match distance is invalid")
            if output_index + length > output_length:
                raise GameArtImportError("compressed PAZ match exceeds output")
            source_index += token_size
            for index in range(length):
                output[output_index + index] = output[
                    output_index + index - distance
                ]
            output_index += length
            group_header >>= 1

        if output_index >= output_length - 11:
            break
        literal_length = literal_lengths[group_header & 0x0F]
        if literal_length <= 0:
            raise GameArtImportError("compressed PAZ literal state is invalid")
        if source_index + literal_length > packed_length:
            raise GameArtImportError("compressed PAZ literal is truncated")
        if output_index + literal_length > output_length:
            raise GameArtImportError("compressed PAZ literal exceeds output")
        output[output_index:output_index + literal_length] = source[
            source_index:source_index + literal_length
        ]
        source_index += literal_length
        output_index += literal_length
        group_header >>= literal_length

    while output_index < output_length:
        if group_header == 1:
            if source_index + 4 > packed_length:
                raise GameArtImportError("compressed PAZ tail header is truncated")
            source_index += 4
            group_header = 0x80000000
        if source_index >= packed_length:
            raise GameArtImportError("compressed PAZ tail is truncated")
        output[output_index] = source[source_index]
        output_index += 1
        source_index += 1
        group_header >>= 1
    return bytes(output)


def read_indexed_asset(paz_root: str | Path, entry: PazEntry) -> bytes:
    """Read and decode one already validated allow-listed entry."""

    archive = Path(str(paz_root).strip()) / f"PAD{entry.archive_id:05}.PAZ"
    try:
        with archive.open("rb") as stream:
            stream.seek(entry.offset)
            encrypted = stream.read(entry.packed_size)
    except OSError as exc:
        raise GameArtImportError(f"cannot read {archive.name} payload") from exc
    if len(encrypted) != entry.packed_size:
        raise GameArtImportError(f"{archive.name} payload is truncated")
    try:
        decrypted = Ice(PAZ_ICE_KEY).decrypt(encrypted)
    except ValueError as exc:
        raise GameArtImportError(f"{archive.name} payload decryption failed") from exc
    return decompress_paz_payload(
        decrypted,
        expected_size=entry.original_size,
    )


_BASE_RULE_RE = re.compile(
    r"\.icn_instrument\s*\{[^{}]*?width\s*:\s*(\d+)px\s*;"
    r"[^{}]*?height\s*:\s*(\d+)px\s*;"
    r"[^{}]*?spr_instrument\.png",
    re.IGNORECASE | re.DOTALL,
)
_POSITION_BLOCK_RE = re.compile(
    r"((?:\.icn_instrument\.instrument_\d+\s*,?\s*)+)"
    r"\{\s*background-position\s*:\s*(-?\d+)px\s+(-?\d+)px\s*;?\s*\}",
    re.IGNORECASE,
)
_INSTRUMENT_SELECTOR_RE = re.compile(r"instrument_(\d+)", re.IGNORECASE)


def parse_instrument_sprite_layout(css_payload: bytes) -> SpriteLayout:
    """Parse only the reviewed instrument sprite declarations from game CSS."""

    if len(css_payload) > MAX_DECOMPRESSED_BYTES:
        raise GameArtImportError("composition CSS is too large")
    try:
        css = css_payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise GameArtImportError("composition CSS is not valid UTF-8") from exc
    base = _BASE_RULE_RE.search(css)
    if base is None:
        raise GameArtImportError("instrument sprite dimensions are missing from CSS")
    tile_width, tile_height = (int(base.group(1)), int(base.group(2)))
    if not (16 <= tile_width <= 1024 and 16 <= tile_height <= 512):
        raise GameArtImportError("instrument sprite tile dimensions are unsafe")
    positions: dict[int, tuple[int, int]] = {}
    for match in _POSITION_BLOCK_RE.finditer(css):
        x = -int(match.group(2))
        y = -int(match.group(3))
        if x < 0 or y < 0:
            raise GameArtImportError("instrument sprite CSS uses positive offsets")
        for value in _INSTRUMENT_SELECTOR_RE.findall(match.group(1)):
            instrument_id = int(value)
            position = (x, y)
            if instrument_id in positions and positions[instrument_id] != position:
                raise GameArtImportError(
                    f"instrument {instrument_id} has conflicting sprite positions"
                )
            positions[instrument_id] = position
    missing = sorted(set(EDITOR_INSTRUMENT_IDS) - positions.keys())
    if missing:
        raise GameArtImportError(
            f"instrument sprite CSS is incomplete: {missing}"
        )
    return SpriteLayout(tile_width, tile_height, positions)


def _safe_cache_root(paz_root: str | Path, cache_root: str | Path) -> Path:
    raw_cache = str(cache_root or "").strip()
    if not raw_cache:
        raise GameArtImportError("local artwork cache directory is empty")
    root = Path(raw_cache).resolve()
    paz = Path(str(paz_root or "").strip()).resolve()
    if root == Path(root.anchor):
        raise GameArtImportError("filesystem root cannot be used as artwork cache")
    if root == paz or paz in root.parents:
        raise GameArtImportError("artwork cache must not modify the PAZ directory")
    for parent in (root, *root.parents):
        if (parent / ".git").exists():
            raise GameArtImportError("artwork cache must not be inside a Git worktree")
    return root


def _validate_png(payload: bytes, label: str) -> None:
    if not payload.startswith(PNG_SIGNATURE):
        raise GameArtImportError(f"{label} is not a PNG image")


def _write_tiles(
    sprite_payload: bytes,
    layout: SpriteLayout,
    destination: Path,
) -> list[dict[str, object]]:
    # Qt is imported lazily so pure PAZ indexing/decompression remains usable
    # in a headless Python environment.  The desktop application already ships
    # PySide6, and QImage decoding needs no window or GUI event loop.
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImage

    image = QImage.fromData(sprite_payload, "PNG")
    if image.isNull():
        raise GameArtImportError("instrument sprite cannot be decoded")
    records: list[dict[str, object]] = []
    for instrument_id in EDITOR_INSTRUMENT_IDS:
        x, y = layout.positions[instrument_id]
        if (
            x + layout.tile_width > image.width()
            or y + layout.tile_height > image.height()
        ):
            raise GameArtImportError(
                f"instrument {instrument_id} sprite tile is outside the image"
            )
        tile = image.copy(x, y, layout.tile_width, layout.tile_height)
        if tile.isNull():
            raise GameArtImportError(f"instrument {instrument_id} tile is empty")
        buffer = QBuffer()
        if not buffer.open(QIODevice.WriteOnly) or not tile.save(buffer, "PNG"):
            raise GameArtImportError(f"instrument {instrument_id} tile encode failed")
        encoded = bytes(buffer.data())
        filename = f"instrument_{instrument_id:02x}.png"
        (destination / filename).write_bytes(encoded)
        records.append({
            "instrument_id": instrument_id,
            "file": filename,
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "width": layout.tile_width,
            "height": layout.tile_height,
            "source_xy": [x, y],
        })
    return records


def _manifest_valid(path: Path, identity: Mapping[str, object]) -> bool:
    manifest_path = path / "bdo-local-art-manifest.json"
    if not manifest_path.is_file():
        return False
    try:
        if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
            return False
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    for key, expected in identity.items():
        if manifest.get(key) != expected:
            return False
    images = manifest.get("images")
    if not isinstance(images, list) or len(images) != len(EDITOR_INSTRUMENT_IDS):
        return False
    for row in images:
        if not isinstance(row, dict):
            return False
        filename = row.get("file")
        digest = row.get("sha256")
        if not isinstance(filename, str) or Path(filename).name != filename:
            return False
        image_path = path / filename
        try:
            payload = _read_bounded(
                image_path, MAX_SOURCE_BYTES, "cached instrument image"
            )
        except GameArtImportError:
            return False
        if hashlib.sha256(payload).hexdigest() != digest:
            return False
    return True


def import_game_instrument_art(
    paz_root: str | Path,
    cache_root: str | Path,
    *,
    allow_unverified_meta_version: bool = False,
) -> GameArtImportReport:
    """Create or reuse one validated, local-only per-instrument art cache."""

    cache = _safe_cache_root(paz_root, cache_root)
    meta, entries = index_composition_ui_assets(
        paz_root,
        allow_unverified_meta_version=allow_unverified_meta_version,
    )
    css_payload = read_indexed_asset(paz_root, entries[COMPOSITION_CSS_PATH])
    sprite_payload = read_indexed_asset(paz_root, entries[INSTRUMENT_SPRITE_PATH])
    _validate_png(sprite_payload, "instrument sprite")
    layout = parse_instrument_sprite_layout(css_payload)
    css_sha256 = hashlib.sha256(css_payload).hexdigest()
    sprite_sha256 = hashlib.sha256(sprite_payload).hexdigest()
    identity: dict[str, object] = {
        "format": IMPORT_FORMAT,
        "import_version": IMPORT_VERSION,
        "meta_version": meta.version,
        "meta_sha256": meta.sha256,
        "css_sha256": css_sha256,
        "sprite_sha256": sprite_sha256,
    }
    target_name = (
        f"game-art-meta{meta.version}-"
        f"{sprite_sha256[:12]}-{css_sha256[:8]}"
    )
    target = cache / target_name
    if target.exists():
        if not target.is_dir() or not _manifest_valid(target, identity):
            raise GameArtImportError(
                "existing artwork cache has failed integrity validation"
            )
        return GameArtImportReport(
            output_dir=str(target),
            meta_version=meta.version,
            meta_sha256=meta.sha256,
            sprite_sha256=sprite_sha256,
            css_sha256=css_sha256,
            image_count=len(EDITOR_INSTRUMENT_IDS),
            reused=True,
        )

    try:
        cache.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise GameArtImportError("cannot create local artwork cache") from exc
    staging = Path(tempfile.mkdtemp(prefix=".bdo-game-art-", dir=cache))
    try:
        images = _write_tiles(sprite_payload, layout, staging)
        manifest = dict(identity)
        manifest.update({
            "source_game_paths": sorted(ALLOWED_GAME_PATHS),
            "tile_size": [layout.tile_width, layout.tile_height],
            "images": images,
        })
        manifest_path = staging / "bdo-local-art-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if target.exists():
            if not target.is_dir() or not _manifest_valid(target, identity):
                raise GameArtImportError(
                    "concurrent artwork cache has failed integrity validation"
                )
            reused = True
        else:
            os.replace(staging, target)
            reused = False
    except OSError as exc:
        raise GameArtImportError("cannot write local artwork cache") from exc
    finally:
        # Only the exact directory returned by mkdtemp is removed.  A
        # successful os.replace makes this path disappear, so no user-owned
        # cache or game directory can be selected by the cleanup.
        if staging.exists() and staging.parent.resolve() == cache.resolve():
            shutil.rmtree(staging)
    return GameArtImportReport(
        output_dir=str(target),
        meta_version=meta.version,
        meta_sha256=meta.sha256,
        sprite_sha256=sprite_sha256,
        css_sha256=css_sha256,
        image_count=len(EDITOR_INSTRUMENT_IDS),
        reused=reused,
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Import allow-listed Black Desert composition artwork from a "
            "user-owned PAZ directory into a local-only cache."
        )
    )
    parser.add_argument("paz_dir", type=Path)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument(
        "--allow-unverified-meta-version",
        action="store_true",
        help=(
            "Explicitly permit a newer PAZ meta version. CSS coordinates, "
            "image bounds, paths, and cache integrity are still validated."
        ),
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        report = import_game_instrument_art(
            args.paz_dir,
            args.cache_root,
            allow_unverified_meta_version=args.allow_unverified_meta_version,
        )
    except GameArtImportError as exc:
        parser.exit(1, f"game art import failed: {exc}\n")
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ALLOWED_GAME_PATHS",
    "EDITOR_INSTRUMENT_IDS",
    "GameArtImportError",
    "GameArtImportReport",
    "PazEntry",
    "PazMeta",
    "SpriteLayout",
    "decompress_paz_payload",
    "import_game_instrument_art",
    "index_composition_ui_assets",
    "parse_instrument_sprite_layout",
    "read_paz_meta",
]
