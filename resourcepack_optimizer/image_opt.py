"""Lossless Image Optimizer for Minecraft Resourcepacks.

Removes ancillary/metadata PNG chunks, recompresses IDAT streams,
detects 100% transparent/empty textures, identifies duplicate textures,
and performs lossless palette reduction where possible.
"""

from __future__ import annotations

import hashlib
import io
import struct
import zlib
from typing import Dict, List, Optional, Set, Tuple

try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# Essential chunks needed to render image correctly in Minecraft / OpenGL
ESSENTIAL_CHUNKS: Set[bytes] = {
    b"IHDR",  # Image header
    b"PLTE",  # Palette
    b"IDAT",  # Image data
    b"IEND",  # Image trailer
    b"tRNS",  # Transparency
}

# Metadata / ancillary chunks safe to discard for Minecraft textures
METADATA_CHUNKS: Set[bytes] = {
    b"tEXt",  # Uncompressed text (author, software, comments)
    b"zTXt",  # Compressed text
    b"iTXt",  # International text
    b"tIME",  # Modification time
    b"pHYs",  # Physical pixel dimensions / DPI
    b"sBIT",  # Significant bits
    b"sRGB",  # Standard RGB color space
    b"iCCP",  # Embedded ICC profile (often 2-4 KB on 16x16 textures!)
    b"gAMA",  # Gamma
    b"cHRM",  # Primary chromaticities
    b"bKGD",  # Background color
    b"hIST",  # Palette histogram
    b"vpAg",  # Virtual page size
}

# Pre-computed 1x1 fully transparent PNG (RGBA 0,0,0,0) - 67 bytes
MINIMAL_TRANSPARENT_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\x0bIDATx\x9cc`\x00\x02\x00\x00\x05\x00\x01\xe2&\x05\x9b"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def read_png_chunks(data: bytes) -> List[Tuple[bytes, bytes, int]]:
    """Parse PNG bytes into a list of (chunk_type, chunk_data, crc).

    Raises:
        ValueError: If data does not start with valid PNG signature or is truncated.
    """
    if len(data) < 8 or data[:8] != PNG_SIGNATURE:
        raise ValueError("Invalid PNG signature")

    chunks: List[Tuple[bytes, bytes, int]] = []
    offset = 8
    length_data = len(data)

    while offset + 8 <= length_data:
        chunk_len = struct.unpack(">I", data[offset:offset + 4])[0]
        chunk_type = data[offset + 4:offset + 8]
        offset += 8

        if offset + chunk_len + 4 > length_data:
            # Corrupted / truncated chunk
            break

        chunk_data = data[offset:offset + chunk_len]
        chunk_crc = struct.unpack(">I", data[offset + chunk_len:offset + chunk_len + 4])[0]
        offset += chunk_len + 4

        chunks.append((chunk_type, chunk_data, chunk_crc))

        if chunk_type == b"IEND":
            break

    return chunks


def write_png_chunk(chunk_type: bytes, chunk_data: bytes) -> bytes:
    """Build a valid PNG chunk binary block with calculated CRC32."""
    length_bytes = struct.pack(">I", len(chunk_data))
    type_and_data = chunk_type + chunk_data
    crc = zlib.crc32(type_and_data) & 0xFFFFFFFF
    crc_bytes = struct.pack(">I", crc)
    return length_bytes + type_and_data + crc_bytes


def strip_png_metadata_pure(data: bytes, preserve_icc: bool = False) -> bytes:
    """Strip unnecessary ancillary chunks from PNG data using pure Python.

    Returns the stripped PNG bytes. If parsing fails, returns original data.
    """
    try:
        chunks = read_png_chunks(data)
    except Exception:
        return data

    filtered_chunks: List[Tuple[bytes, bytes]] = []
    has_ihdr = False
    has_iend = False

    chunks_to_strip = set(METADATA_CHUNKS)
    if preserve_icc:
        chunks_to_strip.discard(b"iCCP")
        chunks_to_strip.discard(b"sRGB")

    for c_type, c_data, _ in chunks:
        if c_type == b"IHDR":
            has_ihdr = True
            filtered_chunks.append((c_type, c_data))
        elif c_type == b"IEND":
            has_iend = True
            filtered_chunks.append((c_type, c_data))
        elif c_type in chunks_to_strip:
            continue
        else:
            # Keep other chunks (IDAT, PLTE, tRNS, unknown custom)
            filtered_chunks.append((c_type, c_data))

    if not has_ihdr or not has_iend:
        return data

    # Assemble new PNG
    out = bytearray(PNG_SIGNATURE)
    for c_type, c_data in filtered_chunks:
        out.extend(write_png_chunk(c_type, c_data))

    return bytes(out)


def recompress_idat_chunks(data: bytes) -> bytes:
    """Decompresses and recompresses IDAT chunks with optimal DEFLATE parameters."""
    try:
        chunks = read_png_chunks(data)
    except Exception:
        return data

    idat_data = bytearray()
    other_chunks_before: List[Tuple[bytes, bytes]] = []
    other_chunks_after: List[Tuple[bytes, bytes]] = []
    seen_idat = False
    past_idat = False

    for c_type, c_data, _ in chunks:
        if c_type == b"IDAT":
            seen_idat = True
            idat_data.extend(c_data)
        elif not seen_idat:
            other_chunks_before.append((c_type, c_data))
        else:
            past_idat = True
            other_chunks_after.append((c_type, c_data))

    if not idat_data:
        return data

    try:
        uncompressed = zlib.decompress(bytes(idat_data))
    except Exception:
        return data

    # Try different zlib strategies to find the smallest representation
    best_compressed = bytes(idat_data)
    for strategy in [zlib.Z_DEFAULT_STRATEGY, zlib.Z_FILTERED]:
        compressor = zlib.compressobj(level=9, method=zlib.DEFLATED, wbits=15, memLevel=9, strategy=strategy)
        candidate = compressor.compress(uncompressed) + compressor.flush()
        if len(candidate) < len(best_compressed):
            best_compressed = candidate

    out = bytearray(PNG_SIGNATURE)
    for c_type, c_data in other_chunks_before:
        out.extend(write_png_chunk(c_type, c_data))

    out.extend(write_png_chunk(b"IDAT", best_compressed))

    for c_type, c_data in other_chunks_after:
        out.extend(write_png_chunk(c_type, c_data))

    return bytes(out)


def get_image_pixel_hash(image_bytes: bytes) -> Optional[str]:
    """Calculate SHA-256 hash of normalized RGBA pixel bytes.

    Useful for finding duplicates regardless of file compression differences.
    """
    if not HAS_PILLOW:
        # Fallback to direct raw content hash if Pillow is not installed
        return hashlib.sha256(image_bytes).hexdigest()

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            rgba_img = img.convert("RGBA")
            pixel_bytes = rgba_img.tobytes()
            # Include dimensions in hash
            header = f"{rgba_img.width}x{rgba_img.height}:".encode("ascii")
            return hashlib.sha256(header + pixel_bytes).hexdigest()
    except Exception:
        return hashlib.sha256(image_bytes).hexdigest()


def is_image_completely_transparent(image_bytes: bytes) -> bool:
    """Check if all pixels in the image have alpha == 0 (completely invisible)."""
    if not HAS_PILLOW:
        return False

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            rgba_img = img.convert("RGBA")
            # Get extrema for alpha channel (band 3: R=0, G=1, B=2, A=3)
            extrema = rgba_img.getextrema()
            alpha_extrema = extrema[3]
            # If max alpha is 0, the entire image is 100% transparent
            return alpha_extrema[1] == 0
    except Exception:
        return False


def optimize_palette_pillow(image_bytes: bytes) -> Optional[bytes]:
    """Convert RGBA image to 8-bit palette mode if <= 256 unique colors with exact losslessness."""
    if not HAS_PILLOW:
        return None

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            if img.mode == "P":
                # Already palette mode; optimize save
                out_buf = io.BytesIO()
                img.save(out_buf, format="PNG", optimize=True)
                return out_buf.getvalue()

            rgba = img.convert("RGBA")
            colors = rgba.getcolors(maxcolors=257)
            if colors is None or len(colors) > 256:
                # More than 256 unique RGBA colors
                return None

            # Losslessly convert to palette mode with transparency
            # Pillow's convert('P') can preserve exact palette
            # Check transparency: if all alphas are 255, simple RGB palette.
            # If binary transparency (0 or 255), we can use transparency index.
            alphas = {col[1][3] for col in colors}
            if len(alphas) == 1 and 255 in alphas:
                # Opaque RGB with <= 256 colors
                rgb = rgba.convert("RGB")
                pal_img = rgb.convert("P", palette=Image.Palette.ADAPTIVE, colors=len(colors))
                out_buf = io.BytesIO()
                pal_img.save(out_buf, format="PNG", optimize=True)
                result = out_buf.getvalue()
                # Verify exact pixel match
                with Image.open(io.BytesIO(result)) as test_img:
                    if test_img.convert("RGB").tobytes() == rgb.tobytes():
                        return result
            elif all(a in (0, 255) for a in alphas):
                # Binary transparency: 1 transparent index
                # Quantize with transparency
                pal_img = rgba.quantize(colors=256, method=Image.Quantize.FASTOCTREE)
                out_buf = io.BytesIO()
                pal_img.save(out_buf, format="PNG", optimize=True)
                result = out_buf.getvalue()
                # Verify exact losslessness
                with Image.open(io.BytesIO(result)) as test_img:
                    if test_img.convert("RGBA").tobytes() == rgba.tobytes():
                        return result
    except Exception:
        return None

    return None


def optimize_png(
    data: bytes,
    enable_palette_opt: bool = True,
    empty_to_minimal: bool = False,
    preserve_icc: bool = False,
) -> Tuple[bytes, Dict[str, Any]]:
    """Losslessly optimize PNG image data.

    Returns:
        (optimized_bytes, info_dict)
    """
    original_size = len(data)
    info: Dict[str, Any] = {
        "original_size": original_size,
        "is_empty": False,
        "palette_reduced": False,
        "chunks_stripped": False,
    }

    if original_size < 8 or data[:8] != PNG_SIGNATURE:
        info["status"] = "not_png"
        return data, info

    # Check if empty (100% transparent)
    if is_image_completely_transparent(data):
        info["is_empty"] = True
        if empty_to_minimal and len(MINIMAL_TRANSPARENT_PNG) < original_size:
            info["status"] = "replaced_with_minimal_empty"
            info["optimized_size"] = len(MINIMAL_TRANSPARENT_PNG)
            return MINIMAL_TRANSPARENT_PNG, info

    best_data = data

    # 1. Strip metadata chunks
    stripped = strip_png_metadata_pure(data, preserve_icc=preserve_icc)
    if len(stripped) < len(best_data):
        best_data = stripped
        info["chunks_stripped"] = True

    # 2. Recompress IDAT
    recompressed = recompress_idat_chunks(best_data)
    if len(recompressed) < len(best_data):
        best_data = recompressed

    # 3. Try palette optimization if enabled
    if enable_palette_opt and HAS_PILLOW:
        pal_data = optimize_palette_pillow(best_data)
        if pal_data and len(pal_data) < len(best_data):
            # Also strip metadata from pillow's output just in case
            pal_stripped = strip_png_metadata_pure(pal_data, preserve_icc=preserve_icc)
            candidate = pal_stripped if len(pal_stripped) < len(pal_data) else pal_data
            if len(candidate) < len(best_data):
                best_data = candidate
                info["palette_reduced"] = True

    info["optimized_size"] = len(best_data)
    info["bytes_saved"] = original_size - len(best_data)
    info["status"] = "optimized" if len(best_data) < original_size else "unmodified"

    return best_data, info
