"""Tests for Resourcepack packaging pipeline, zip deflation, and diffing engine."""

import zipfile
from pathlib import Path

import pytest

from resourcepack_optimizer.packager import (
    ResourcepackOptimizerPipeline,
    diff_resourcepacks,
)


def test_pipeline_directory_to_zip(sample_pack_dir: Path, tmp_path: Path):
    out_zip = tmp_path / "optimized_pack.zip"

    pipeline = ResourcepackOptimizerPipeline(
        input_path=sample_pack_dir,
        output_path=out_zip,
        strip_metadata=True,
        enable_palette_opt=True,
        minify_json=True,
        prune_dead_code=True,
        audit_audio=True,
    )

    report = pipeline.run()

    assert out_zip.exists()
    assert report.total_bytes_saved > 0
    assert len(report.file_results) > 0
    assert len(report.dead_code_pruned) > 0

    # Verify zip content structure
    with zipfile.ZipFile(out_zip, "r") as zf:
        namelist = zf.namelist()
        assert "pack.mcmeta" in namelist
        assert namelist[0] == "pack.mcmeta"  # mcmeta should be at root / first
        assert "pack.png" in namelist
        assert "assets/minecraft/textures/block/stone.png" in namelist
        # Pruned unused texture should NOT be in zip!
        assert not any("unused_texture.png" in name for name in namelist)


def test_pipeline_zip_to_directory(sample_pack_dir: Path, tmp_path: Path):
    # First create a source zip
    src_zip = tmp_path / "source_pack.zip"
    with zipfile.ZipFile(src_zip, "w") as zf:
        for f in sample_pack_dir.rglob("*"):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(sample_pack_dir).as_posix())

    out_dir = tmp_path / "optimized_extracted"

    pipeline = ResourcepackOptimizerPipeline(
        input_path=src_zip,
        output_path=out_dir,
        strip_metadata=True,
        prune_dead_code=False,
    )

    report = pipeline.run()

    assert out_dir.exists()
    assert (out_dir / "pack.mcmeta").exists()
    assert (out_dir / "assets" / "minecraft" / "textures" / "block" / "stone.png").exists()


def test_pipeline_invalid_input(tmp_path: Path):
    pipeline = ResourcepackOptimizerPipeline(input_path=tmp_path / "non_existent")
    with pytest.raises(FileNotFoundError):
        pipeline.run()


def test_diff_resourcepacks(sample_pack_dir: Path, tmp_path: Path):
    # Create pack B with modifications
    pack_b = tmp_path / "pack_b"
    import shutil
    shutil.copytree(sample_pack_dir, pack_b)

    # Modify a file
    (pack_b / "pack.mcmeta").write_text('{"pack": {"pack_format": 34, "description": "mod"}}', encoding="utf-8")
    # Add a file
    (pack_b / "extra.txt").write_text("extra", encoding="utf-8")
    # Remove a file
    (pack_b / "pack.png").unlink()

    diff = diff_resourcepacks(sample_pack_dir, pack_b)

    assert "extra.txt" in diff["files_added"]
    assert "pack.png" in diff["files_removed"]
    assert any(m["file"] == "pack.mcmeta" for m in diff["files_modified"])
    assert diff["files_unchanged_count"] > 0
