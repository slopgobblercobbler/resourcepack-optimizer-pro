"""Pytest fixtures and test helpers for resourcepack-optimizer-pro."""

from __future__ import annotations

import io
import struct
from pathlib import Path
from typing import Tuple

import pytest
from PIL import Image

from resourcepack_optimizer.image_opt import write_png_chunk


def make_test_png(
    width: int = 16,
    height: int = 16,
    color: Tuple[int, int, int, int] = (255, 0, 0, 255),
    with_text_chunk: bool = False,
    mode: str = "RGBA",
) -> bytes:
    """Create a valid PNG image byte string with optional metadata chunk."""
    img = Image.new(mode, (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()

    if with_text_chunk:
        iend_pos = data.rfind(b"IEND")
        chunk_type = b"tEXt"
        chunk_data = b"Software\x00Minecraft Resourcepack Optimizer Test"
        custom_chunk = write_png_chunk(chunk_type, chunk_data)
        time_chunk = write_png_chunk(b"tIME", struct.pack(">HBBBBB", 2026, 10, 26, 12, 0, 0))
        split_pt = iend_pos - 4
        data = data[:split_pt] + custom_chunk + time_chunk + data[split_pt:]

    return data


def build_ogg_page(header_type: int, granule_pos: int, seq_no: int, serial_no: int, packet: bytes) -> bytes:
    """Build a valid Ogg page with proper segment lacing values."""
    segments = bytearray()
    rem = len(packet)
    while rem >= 255:
        segments.append(255)
        rem -= 255
    segments.append(rem)

    hdr = bytearray(b"OggS")
    hdr.append(0)  # version
    hdr.append(header_type)
    hdr.extend(struct.pack("<q", granule_pos))
    hdr.extend(struct.pack("<I", serial_no))
    hdr.extend(struct.pack("<I", seq_no))
    hdr.extend(struct.pack("<I", 0))  # crc placeholder
    hdr.append(len(segments))
    hdr.extend(segments)
    return bytes(hdr + packet)


def make_synthetic_ogg(
    channels: int = 1,
    sample_rate: int = 44100,
    granule_pos: int = 88200,  # 2.0 seconds at 44100 Hz
    comments: list[str] | None = None,
    bitrate: int = 128000,
) -> bytes:
    """Construct a synthetically valid Ogg Vorbis bitstream."""
    comments = comments or ["TITLE=Test Sound", "ARTIST=Minecraft"]
    serial_no = 0x12345678

    # --- Page 1: Vorbis Identification Header (Packet 1) ---
    packet1 = bytearray()
    packet1.extend(b"\x01vorbis")
    packet1.extend(struct.pack("<I", 0))  # vorbis_version
    packet1.append(channels)  # channels
    packet1.extend(struct.pack("<I", sample_rate))  # sample rate
    packet1.extend(struct.pack("<i", 0))  # max bitrate
    packet1.extend(struct.pack("<i", bitrate))  # nom bitrate
    packet1.extend(struct.pack("<i", 0))  # min bitrate
    packet1.append(0xB8)  # blocksize_0 and 1
    packet1.append(0x01)  # framing flag

    page1 = build_ogg_page(0x02, 0, 0, serial_no, bytes(packet1))

    # --- Page 2: Vorbis Comment Header (Packet 2) ---
    packet2 = bytearray()
    packet2.extend(b"\x03vorbis")
    vendor_bytes = b"Xiph.Org libVorbis"
    packet2.extend(struct.pack("<I", len(vendor_bytes)))
    packet2.extend(vendor_bytes)
    packet2.extend(struct.pack("<I", len(comments)))
    for c in comments:
        c_bytes = c.encode("utf-8")
        packet2.extend(struct.pack("<I", len(c_bytes)))
        packet2.extend(c_bytes)
    packet2.append(0x01)  # framing flag

    page2 = build_ogg_page(0x00, 0, 1, serial_no, bytes(packet2))

    # --- Page 3: Audio data page with final granule position (EOS) ---
    packet3 = b"\x00" * 32
    page3 = build_ogg_page(0x04, granule_pos, 2, serial_no, packet3)

    return page1 + page2 + page3


@pytest.fixture
def sample_pack_dir(tmp_path: Path) -> Path:
    """Create a complete sample Minecraft resourcepack directory."""
    pack_dir = tmp_path / "test_pack"
    pack_dir.mkdir()

    # pack.mcmeta
    mcmeta_content = """{
        // Sample Pack mcmeta
        "pack": {
            "pack_format": 34,
            "description": "Test Resourcepack Description",
            "supported_formats": {"min_inclusive": 32, "max_inclusive": 34}
        }
    }"""
    (pack_dir / "pack.mcmeta").write_text(mcmeta_content, encoding="utf-8")

    # pack.png
    (pack_dir / "pack.png").write_bytes(make_test_png(64, 64, (0, 128, 255, 255)))

    # assets/minecraft/
    mc_dir = pack_dir / "assets" / "minecraft"
    textures_dir = mc_dir / "textures" / "block"
    textures_dir.mkdir(parents=True)
    item_tex_dir = mc_dir / "textures" / "item"
    item_tex_dir.mkdir(parents=True)

    # stone.png
    stone_png = make_test_png(16, 16, (128, 128, 128, 255), with_text_chunk=True)
    (textures_dir / "stone.png").write_bytes(stone_png)

    # dirt.png (identical to stone to test duplicate detection)
    (textures_dir / "dirt.png").write_bytes(stone_png)

    # empty.png (100% transparent)
    (textures_dir / "empty.png").write_bytes(make_test_png(16, 16, (0, 0, 0, 0)))

    # unused_texture.png
    (textures_dir / "unused_texture.png").write_bytes(make_test_png(16, 16, (50, 50, 50, 255)))

    # sword.png
    (item_tex_dir / "custom_sword.png").write_bytes(make_test_png(16, 16, (200, 20, 20, 255)))

    # models
    models_block = mc_dir / "models" / "block"
    models_block.mkdir(parents=True)
    models_item = mc_dir / "models" / "item"
    models_item.mkdir(parents=True)

    # stone.json model
    stone_model = """{
        "parent": "block/cube_all",
        "textures": {
            "all": "minecraft:block/stone"
        },
        "elements": [
            {
                "from": [0, 0, 0],
                "to": [16, 16, 16],
                "faces": {
                    "up": {"texture": "#all", "uv": [0, 0, 16, 16]},
                    "down": {"texture": "#all"}
                }
            }
        ]
    }"""
    (models_block / "stone.json").write_text(stone_model, encoding="utf-8")

    # custom_sword.json
    sword_model = """{
        "parent": "item/handheld",
        "textures": {
            "layer0": "minecraft:item/custom_sword"
        }
    }"""
    (models_item / "custom_sword.json").write_text(sword_model, encoding="utf-8")

    # orphan_custom.json (in a subfolder, not referenced)
    custom_models = mc_dir / "models" / "custom"
    custom_models.mkdir(parents=True)
    (custom_models / "orphan_model.json").write_text('{"parent": "block/cube_all"}', encoding="utf-8")

    # blockstates
    blockstates_dir = mc_dir / "blockstates"
    blockstates_dir.mkdir(parents=True)
    stone_bs = """{
        "variants": {
            "": {"model": "minecraft:block/stone"}
        }
    }"""
    (blockstates_dir / "stone.json").write_text(stone_bs, encoding="utf-8")

    # sounds.json & sound files
    sounds_dir = mc_dir / "sounds" / "block"
    sounds_dir.mkdir(parents=True)
    ogg_data = make_synthetic_ogg(channels=1, sample_rate=44100)
    (sounds_dir / "stone_break.ogg").write_bytes(ogg_data)

    sounds_json = """{
        "block.stone.break": {
            "category": "block",
            "subtitle": "subtitles.block.stone.break",
            "sounds": [
                {
                    "name": "minecraft:block/stone_break",
                    "volume": 0.8,
                    "pitch": 1.0,
                    "weight": 1
                }
            ]
        }
    }"""
    (mc_dir / "sounds.json").write_text(sounds_json, encoding="utf-8")

    return pack_dir
