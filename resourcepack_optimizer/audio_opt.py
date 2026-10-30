"""Audio Auditor and OGG Vorbis Inspector for Minecraft Resourcepacks.

Parses Ogg Vorbis bitstreams in pure Python, validates sample rates,
audits channel configurations (mono for 3D positional audio vs stereo for music/ambience),
and detects bloated Vorbis metadata comments.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


OGG_MAGIC = b"OggS"
VORBIS_MAGIC = b"\x01vorbis"
COMMENT_MAGIC = b"\x03vorbis"

# Recommended Minecraft audio sample rates (OpenAL native)
STANDARD_SAMPLE_RATES = {44100, 48000}

# Paths typical of 3D positional audio in Minecraft (should be MONO)
POSITIONAL_AUDIO_KEYWORDS = {
    "/block/", "/blocks/", "/entity/", "/entities/", "/mob/", "/mobs/",
    "/item/", "/items/", "/step/", "/dig/", "/hit/", "/fall/",
    "/random/", "/tile/", "/particle/", "/portal/"
}

# Paths typical of ambient / non-positional audio (can be STEREO)
NON_POSITIONAL_KEYWORDS = {
    "/music/", "/ambient/", "/records/", "/ui/", "/weather/"
}


@dataclass
class OggVorbisInfo:
    """Information extracted from an Ogg Vorbis file."""
    channels: int
    sample_rate: int
    bitrate_nominal: int
    bitrate_max: int
    bitrate_min: int
    duration_seconds: float
    vendor: str
    comments: List[str]
    is_valid: bool
    file_size: int
    error: Optional[str] = None

    @property
    def is_mono(self) -> bool:
        return self.channels == 1

    @property
    def is_stereo(self) -> bool:
        return self.channels == 2

    @property
    def is_standard_sample_rate(self) -> bool:
        return self.sample_rate in STANDARD_SAMPLE_RATES

    def to_dict(self) -> Dict[str, Any]:
        return {
            "channels": self.channels,
            "sample_rate": self.sample_rate,
            "bitrate_nominal": self.bitrate_nominal,
            "duration_seconds": round(self.duration_seconds, 2),
            "vendor": self.vendor,
            "comments": self.comments,
            "is_valid": self.is_valid,
            "file_size": self.file_size,
            "error": self.error,
        }


def parse_ogg_page_header(data: bytes, offset: int = 0) -> Optional[Tuple[Dict[str, Any], int, int]]:
    """Parse a single Ogg page header from binary data.

    Returns:
        (header_dict, header_size, body_size) or None if invalid.
    """
    if len(data) < offset + 27:
        return None

    if data[offset:offset + 4] != OGG_MAGIC:
        return None

    version = data[offset + 4]
    header_type = data[offset + 5]
    granule_pos = struct.unpack("<q", data[offset + 6:offset + 14])[0]
    serial_no = struct.unpack("<I", data[offset + 14:offset + 18])[0]
    seq_no = struct.unpack("<I", data[offset + 18:offset + 22])[0]
    crc = struct.unpack("<I", data[offset + 22:offset + 26])[0]
    num_segments = data[offset + 26]

    if len(data) < offset + 27 + num_segments:
        return None

    segment_table = data[offset + 27:offset + 27 + num_segments]
    body_size = sum(segment_table)
    header_size = 27 + num_segments

    header_info = {
        "version": version,
        "header_type": header_type,
        "is_bos": bool(header_type & 0x02),
        "is_eos": bool(header_type & 0x04),
        "granule_position": granule_pos,
        "serial_number": serial_no,
        "sequence_number": seq_no,
        "crc": crc,
        "segments": list(segment_table),
    }

    return header_info, header_size, body_size


def inspect_ogg_data(data: bytes) -> OggVorbisInfo:
    """Inspect Ogg Vorbis binary data and extract audio characteristics."""
    file_size = len(data)
    if file_size < 27:
        return OggVorbisInfo(0, 0, 0, 0, 0, 0.0, "", [], False, file_size, "File too small for Ogg header")

    first_page = parse_ogg_page_header(data, 0)
    if not first_page:
        return OggVorbisInfo(0, 0, 0, 0, 0, 0.0, "", [], False, file_size, "Missing OggS signature")

    hdr_info, hdr_size, body_size = first_page
    first_packet = data[hdr_size:hdr_size + body_size]

    # Verify Vorbis Identification Header (Packet Type 1)
    if len(first_packet) < 30 or not first_packet.startswith(VORBIS_MAGIC):
        return OggVorbisInfo(0, 0, 0, 0, 0, 0.0, "", [], False, file_size, "Not a Vorbis bitstream")

    channels = first_packet[11]
    sample_rate = struct.unpack("<I", first_packet[12:16])[0]
    bitrate_max = struct.unpack("<i", first_packet[16:20])[0]
    bitrate_nom = struct.unpack("<i", first_packet[20:24])[0]
    bitrate_min = struct.unpack("<i", first_packet[24:28])[0]

    # Parse second page for Comment Header if available
    offset = hdr_size + body_size
    vendor = ""
    comments: List[str] = []

    if offset < file_size:
        second_page = parse_ogg_page_header(data, offset)
        if second_page:
            s_hdr, s_hsize, s_bsize = second_page
            comment_packet = data[offset + s_hsize:offset + s_hsize + s_bsize]
            if comment_packet.startswith(COMMENT_MAGIC) and len(comment_packet) >= 11:
                try:
                    c_offset = 7
                    vendor_len = struct.unpack("<I", comment_packet[c_offset:c_offset + 4])[0]
                    c_offset += 4
                    if c_offset + vendor_len <= len(comment_packet):
                        vendor = comment_packet[c_offset:c_offset + vendor_len].decode("utf-8", errors="replace")
                        c_offset += vendor_len

                    if c_offset + 4 <= len(comment_packet):
                        num_comments = struct.unpack("<I", comment_packet[c_offset:c_offset + 4])[0]
                        c_offset += 4
                        for _ in range(min(num_comments, 100)):  # safety bound
                            if c_offset + 4 > len(comment_packet):
                                break
                            c_len = struct.unpack("<I", comment_packet[c_offset:c_offset + 4])[0]
                            c_offset += 4
                            if c_offset + c_len > len(comment_packet):
                                break
                            c_str = comment_packet[c_offset:c_offset + c_len].decode("utf-8", errors="replace")
                            comments.append(c_str)
                            c_offset += c_len
                except Exception:
                    pass

    # Find the last page to extract total granule position (for exact duration)
    last_granule_pos = -1
    search_offset = max(0, file_size - 65536)  # look at last 64KB
    idx = search_offset
    while idx < file_size - 27:
        pos = data.find(OGG_MAGIC, idx)
        if pos == -1:
            break
        page = parse_ogg_page_header(data, pos)
        if page:
            p_hdr, p_hsize, p_bsize = page
            if p_hdr["granule_position"] > last_granule_pos:
                last_granule_pos = p_hdr["granule_position"]
            idx = pos + p_hsize + p_bsize
        else:
            idx = pos + 1

    duration = 0.0
    if sample_rate > 0 and last_granule_pos > 0:
        duration = last_granule_pos / sample_rate

    return OggVorbisInfo(
        channels=channels,
        sample_rate=sample_rate,
        bitrate_nominal=bitrate_nom,
        bitrate_max=bitrate_max,
        bitrate_min=bitrate_min,
        duration_seconds=duration,
        vendor=vendor,
        comments=comments,
        is_valid=True,
        file_size=file_size,
    )


def audit_sound_file(file_path: Path | str, relative_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Audit an individual OGG Vorbis sound file for Minecraft compatibility issues.

    Returns:
        List of audit warnings/recommendations.
    """
    path_obj = Path(file_path)
    rel_path = relative_path or path_obj.name
    rel_lower = rel_path.lower().replace("\\", "/")

    issues: List[Dict[str, Any]] = []

    try:
        data = path_obj.read_bytes()
    except Exception as exc:
        return [{
            "code": "AUDIO_READ_ERROR",
            "severity": "ERROR",
            "file": rel_path,
            "message": f"Could not read audio file: {exc}",
        }]

    info = inspect_ogg_data(data)
    if not info.is_valid:
        return [{
            "code": "INVALID_OGG_VORBIS",
            "severity": "ERROR",
            "file": rel_path,
            "message": f"Invalid Ogg Vorbis file: {info.error}",
        }]

    # Check 1: Sample Rate
    if info.sample_rate not in STANDARD_SAMPLE_RATES:
        issues.append({
            "code": "NON_STANDARD_SAMPLE_RATE",
            "severity": "WARNING",
            "file": rel_path,
            "message": (
                f"Sample rate {info.sample_rate} Hz is non-standard. "
                "Minecraft OpenAL performs best with 44100 Hz or 48000 Hz."
            ),
            "details": {"sample_rate": info.sample_rate},
        })

    # Check 2: Stereo positional sound
    is_positional = any(kw in rel_lower for kw in POSITIONAL_AUDIO_KEYWORDS)
    is_non_positional = any(kw in rel_lower for kw in NON_POSITIONAL_KEYWORDS)

    if info.channels > 1 and is_positional and not is_non_positional:
        issues.append({
            "code": "STEREO_POSITIONAL_SOUND",
            "severity": "WARNING",
            "file": rel_path,
            "message": (
                f"Positional 3D sound is stereo ({info.channels} channels). "
                "Minecraft cannot properly pan stereo sounds in 3D space, "
                "and it uses 2x the memory. Converting to mono is strongly recommended."
            ),
            "details": {"channels": info.channels},
        })

    # Check 3: Comment bloat (> 4KB comments in a sound file)
    comment_size = sum(len(c.encode("utf-8")) for c in info.comments)
    if comment_size > 4096:
        issues.append({
            "code": "AUDIO_METADATA_BLOAT",
            "severity": "INFO",
            "file": rel_path,
            "message": f"Sound file contains {comment_size} bytes of comment metadata.",
            "details": {"comment_bytes": comment_size},
        })

    return issues
