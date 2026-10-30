"""Tests for data models, version mappings, and report generation."""

from resourcepack_optimizer.models import (
    FileOptimizationResult,
    OptimizationReport,
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
    get_format_for_version,
    get_version_for_format,
)


def test_version_mapping():
    assert "1.20" in get_version_for_format(15)
    assert "1.21" in get_version_for_format(34)
    assert "Unknown (< 1.6)" == get_version_for_format(0)
    assert "Format" in get_version_for_format(99)  # Higher future version

    assert get_format_for_version("1.20.4") == 22
    assert get_format_for_version("1.21.1") == 34
    assert get_format_for_version("1.18.2") == 9
    assert get_format_for_version("unknown_version") is None


def test_validation_report():
    report = ValidationReport(pack_name="TestPack", pack_format=34)
    assert report.is_valid is True

    report.add_issue(
        severity=ValidationSeverity.INFO,
        code="INFO_CODE",
        message="Pack info message",
    )
    assert report.is_valid is True
    assert len(report.infos) == 1

    report.add_issue(
        severity=ValidationSeverity.WARNING,
        code="WARN_CODE",
        message="Warning message",
    )
    assert report.is_valid is True
    assert len(report.warnings) == 1

    report.add_issue(
        severity=ValidationSeverity.ERROR,
        code="ERR_CODE",
        message="Critical failure",
        file_path="pack.mcmeta",
        line=10,
    )
    assert report.is_valid is False
    assert len(report.errors) == 1

    data = report.to_dict()
    assert data["pack_name"] == "TestPack"
    assert data["is_valid"] is False
    assert data["summary"]["errors"] == 1
    assert data["summary"]["warnings"] == 1
    assert data["summary"]["infos"] == 1


def test_file_optimization_result():
    res = FileOptimizationResult(
        path="assets/minecraft/textures/block/stone.png",
        original_size=1000,
        optimized_size=400,
        status="optimized",
        category="image",
        details="chunks stripped",
    )
    assert res.bytes_saved == 600
    assert abs(res.reduction_percentage - 60.0) < 0.01

    d = res.to_dict()
    assert d["bytes_saved"] == 600
    assert d["reduction_percentage"] == 60.0
    assert d["status"] == "optimized"

    # Edge case: 0 original size
    res_zero = FileOptimizationResult("empty", 0, 0, "unmodified", "other")
    assert res_zero.reduction_percentage == 0.0


def test_optimization_report():
    opt_rep = OptimizationReport(pack_name="SuperPack", duration_seconds=1.23)
    opt_rep.add_result(FileOptimizationResult("img1.png", 2000, 1000, "optimized", "image"))
    opt_rep.add_result(FileOptimizationResult("data.json", 1000, 500, "optimized", "json"))
    opt_rep.add_result(FileOptimizationResult("sound.ogg", 5000, 5000, "unmodified", "audio"))

    assert opt_rep.original_total_size == 8000
    assert opt_rep.optimized_total_size == 6500
    assert opt_rep.total_bytes_saved == 1500
    assert abs(opt_rep.total_reduction_percentage - 18.75) < 0.01

    breakdown = opt_rep.category_breakdown()
    assert breakdown["image"]["bytes_saved"] == 1000
    assert breakdown["json"]["bytes_saved"] == 500
    assert breakdown["audio"]["bytes_saved"] == 0

    opt_rep.duplicates_found.append(("stone.png", "dirt.png"))
    opt_rep.empty_textures_found.append("empty.png")
    opt_rep.dead_code_pruned.append("orphan.json")
    opt_rep.broken_references.append("Model stone missing texture wood")

    val_rep = ValidationReport(pack_name="SuperPack")
    val_rep.add_issue(ValidationSeverity.ERROR, "ERR", "Sample error")
    val_rep.add_issue(ValidationSeverity.WARNING, "WARN", "Sample warning")
    opt_rep.validation_report = val_rep

    md = opt_rep.to_markdown()
    assert "# Resourcepack Optimization Report: SuperPack" in md
    assert "Duplicate Textures (1)" in md
    assert "Fully Transparent / Empty Textures (1)" in md
    assert "Dead Code Pruned (1)" in md
    assert "Broken References (1)" in md
    assert "Validation Issues" in md

    d = opt_rep.to_dict()
    assert d["total_bytes_saved"] == 1500
    assert d["files_processed"] == 3
