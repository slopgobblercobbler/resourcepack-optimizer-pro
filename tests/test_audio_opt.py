"""Tests for OGG Vorbis audio parsing and Minecraft audio compliance auditing."""

from pathlib import Path

from resourcepack_optimizer.audio_opt import (
    audit_sound_file,
    inspect_ogg_data,
    parse_ogg_page_header,
)
from tests.conftest import make_synthetic_ogg


def test_parse_ogg_page_header():
    ogg_bytes = make_synthetic_ogg(channels=1, sample_rate=44100)
    page_res = parse_ogg_page_header(ogg_bytes, 0)
    assert page_res is not None
    hdr_info, hdr_size, body_size = page_res

    assert hdr_info["version"] == 0
    assert hdr_info["is_bos"] is True
    assert hdr_info["is_eos"] is False
    assert hdr_info["serial_number"] == 0x12345678
    assert hdr_size > 0
    assert body_size > 0

    # Truncated or invalid header
    assert parse_ogg_page_header(b"OggS") is None
    assert parse_ogg_page_header(b"NOT_AN_OGG_HEADER") is None


def test_inspect_ogg_data():
    ogg_bytes = make_synthetic_ogg(
        channels=2,
        sample_rate=48000,
        granule_pos=96000,
        comments=["TITLE=Victory Music", "ARTIST=C418"],
        bitrate=192000,
    )
    info = inspect_ogg_data(ogg_bytes)

    assert info.is_valid is True
    assert info.channels == 2
    assert info.is_stereo is True
    assert info.is_mono is False
    assert info.sample_rate == 48000
    assert info.is_standard_sample_rate is True
    assert info.bitrate_nominal == 192000
    assert abs(info.duration_seconds - 2.0) < 0.05
    assert info.vendor == "Xiph.Org libVorbis"
    assert "TITLE=Victory Music" in info.comments

    # Corrupt or too small data
    info_small = inspect_ogg_data(b"short")
    assert info_small.is_valid is False
    assert "too small" in info_small.error.lower()

    # Not vorbis bitstream
    fake_ogg = b"OggS" + b"\x00" * 23 + b"\x01" + b"\x05" + b"wrong"
    info_fake = inspect_ogg_data(fake_ogg)
    assert info_fake.is_valid is False


def test_audit_sound_file(tmp_path: Path):
    sound_dir = tmp_path / "sounds"
    sound_dir.mkdir()

    # 1. Positional mono audio (Clean)
    mono_ogg = make_synthetic_ogg(channels=1, sample_rate=44100)
    mono_path = sound_dir / "block_hit.ogg"
    mono_path.write_bytes(mono_ogg)

    issues_mono = audit_sound_file(mono_path, relative_path="assets/minecraft/sounds/block/block_hit.ogg")
    assert len(issues_mono) == 0

    # 2. Positional STEREO audio (Should trigger warning)
    stereo_ogg = make_synthetic_ogg(channels=2, sample_rate=44100)
    stereo_path = sound_dir / "entity_hurt.ogg"
    stereo_path.write_bytes(stereo_ogg)

    issues_stereo = audit_sound_file(stereo_path, relative_path="assets/minecraft/sounds/entity/entity_hurt.ogg")
    assert any(i["code"] == "STEREO_POSITIONAL_SOUND" for i in issues_stereo)

    # 3. Non-positional STEREO audio (Music - Stereo allowed!)
    issues_music = audit_sound_file(stereo_path, relative_path="assets/minecraft/sounds/music/menu.ogg")
    assert not any(i["code"] == "STEREO_POSITIONAL_SOUND" for i in issues_music)

    # 4. Non-standard sample rate (e.g. 22050 Hz)
    bad_rate_ogg = make_synthetic_ogg(channels=1, sample_rate=22050)
    bad_rate_path = sound_dir / "low_rate.ogg"
    bad_rate_path.write_bytes(bad_rate_ogg)

    issues_rate = audit_sound_file(bad_rate_path)
    assert any(i["code"] == "NON_STANDARD_SAMPLE_RATE" for i in issues_rate)

    # 5. Comment bloat (> 4096 bytes comments)
    bloat_comments = ["COMMENT=" + ("x" * 1000) for _ in range(5)]
    bloat_ogg = make_synthetic_ogg(channels=1, sample_rate=44100, comments=bloat_comments)
    bloat_path = sound_dir / "bloat.ogg"
    bloat_path.write_bytes(bloat_ogg)

    issues_bloat = audit_sound_file(bloat_path)
    assert any(i["code"] == "AUDIO_METADATA_BLOAT" for i in issues_bloat)

    # 6. Read error
    missing_issues = audit_sound_file(tmp_path / "does_not_exist.ogg")
    assert any(i["code"] == "AUDIO_READ_ERROR" for i in missing_issues)
