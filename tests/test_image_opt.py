"""Tests for lossless PNG image optimization, chunk stripping, and palette reduction."""

import io
import pytest
from PIL import Image

from resourcepack_optimizer.image_opt import (
    MINIMAL_TRANSPARENT_PNG,
    PNG_SIGNATURE,
    get_image_pixel_hash,
    is_image_completely_transparent,
    optimize_palette_pillow,
    optimize_png,
    read_png_chunks,
    recompress_idat_chunks,
    strip_png_metadata_pure,
    write_png_chunk,
)
from tests.conftest import make_test_png


def test_png_chunk_parsing_and_writing():
    png_bytes = make_test_png(16, 16, (255, 0, 0, 255), with_text_chunk=True)
    chunks = read_png_chunks(png_bytes)
    assert len(chunks) >= 4  # IHDR, tEXt, tIME, IDAT, IEND

    chunk_types = [c[0] for c in chunks]
    assert b"IHDR" in chunk_types
    assert b"tEXt" in chunk_types
    assert b"tIME" in chunk_types
    assert b"IDAT" in chunk_types
    assert b"IEND" in chunk_types

    # Test write_png_chunk
    raw_chunk = write_png_chunk(b"tEXt", b"Key\x00Value")
    assert raw_chunk.startswith(b"\x00\x00\x00\x09tEXtKey\x00Value")


def test_read_png_chunks_invalid():
    with pytest.raises(ValueError, match="Invalid PNG signature"):
        read_png_chunks(b"NOT_A_PNG")

    # Truncated chunk
    truncated = PNG_SIGNATURE + b"\x00\x00\x00\x20IHDR"
    chunks = read_png_chunks(truncated)
    assert len(chunks) == 0


def test_strip_png_metadata():
    png_with_meta = make_test_png(16, 16, (0, 255, 0, 255), with_text_chunk=True)
    original_size = len(png_with_meta)

    stripped = strip_png_metadata_pure(png_with_meta)
    assert len(stripped) < original_size

    new_chunks = read_png_chunks(stripped)
    new_types = [c[0] for c in new_chunks]
    assert b"tEXt" not in new_types
    assert b"tIME" not in new_types
    assert b"IHDR" in new_types
    assert b"IDAT" in new_types
    assert b"IEND" in new_types

    # Stripping invalid data returns original
    assert strip_png_metadata_pure(b"corrupt") == b"corrupt"


def test_recompress_idat():
    png_bytes = make_test_png(32, 32, (100, 150, 200, 255))
    recompressed = recompress_idat_chunks(png_bytes)
    assert recompressed.startswith(PNG_SIGNATURE)

    # Recompressing non-png returns original
    assert recompress_idat_chunks(b"random_data") == b"random_data"


def test_image_pixel_hash():
    # Two images with identical pixels but one with extra metadata chunks
    png_a = make_test_png(16, 16, (255, 128, 0, 255), with_text_chunk=False)
    png_b = make_test_png(16, 16, (255, 128, 0, 255), with_text_chunk=True)

    hash_a = get_image_pixel_hash(png_a)
    hash_b = get_image_pixel_hash(png_b)
    assert hash_a is not None
    assert hash_a == hash_b  # Pixel contents match!

    # Different color gives different hash
    png_c = make_test_png(16, 16, (0, 0, 255, 255))
    hash_c = get_image_pixel_hash(png_c)
    assert hash_a != hash_c


def test_empty_transparent_detection():
    # 100% transparent image
    transparent_png = make_test_png(16, 16, (0, 0, 0, 0))
    assert is_image_completely_transparent(transparent_png) is True

    # Opaque image
    opaque_png = make_test_png(16, 16, (255, 0, 0, 255))
    assert is_image_completely_transparent(opaque_png) is False

    # Partially transparent image (1 pixel non-zero alpha)
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    img.putpixel((0, 0), (255, 0, 0, 50))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    assert is_image_completely_transparent(buf.getvalue()) is False

    assert is_image_completely_transparent(b"invalid") is False


def test_optimize_palette_pillow():
    # RGBA image with 2 unique colors (opaque)
    img = Image.new("RGBA", (16, 16), (255, 0, 0, 255))
    img.putpixel((1, 1), (0, 255, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()

    pal_result = optimize_palette_pillow(data)
    assert pal_result is not None
    assert pal_result.startswith(PNG_SIGNATURE)

    # Already palette mode
    pal_img = img.convert("P")
    buf_pal = io.BytesIO()
    pal_img.save(buf_pal, format="PNG")
    res_p = optimize_palette_pillow(buf_pal.getvalue())
    assert res_p is not None

    # Binary transparency
    img_bin = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    img_bin.putpixel((0, 0), (255, 255, 255, 255))
    buf_bin = io.BytesIO()
    img_bin.save(buf_bin, format="PNG")
    res_bin = optimize_palette_pillow(buf_bin.getvalue())
    assert res_bin is not None


def test_optimize_png_pipeline():
    png_with_meta = make_test_png(16, 16, (120, 120, 120, 255), with_text_chunk=True)
    opt_bytes, info = optimize_png(png_with_meta, enable_palette_opt=True)

    assert info["status"] == "optimized"
    assert len(opt_bytes) < len(png_with_meta)
    assert info["bytes_saved"] > 0

    # Non-PNG
    non_png, n_info = optimize_png(b"not_png_file")
    assert non_png == b"not_png_file"
    assert n_info["status"] == "not_png"

    # Empty image to minimal
    empty_png = make_test_png(32, 32, (0, 0, 0, 0))
    min_bytes, min_info = optimize_png(empty_png, empty_to_minimal=True)
    assert min_info["is_empty"] is True
    assert min_info["status"] == "replaced_with_minimal_empty"
    assert min_bytes == MINIMAL_TRANSPARENT_PNG
