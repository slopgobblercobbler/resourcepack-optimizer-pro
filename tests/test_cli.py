"""Tests for CLI interface and command routing."""

import json
from pathlib import Path

from resourcepack_optimizer.cli import main, print_banner


def test_cli_help(capsys):
    exit_code = main([])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "resourcepack-optimizer" in captured.out or "usage:" in captured.out


def test_cli_banner():
    # Should run without error
    print_banner()


def test_cli_validate(sample_pack_dir: Path, capsys):
    exit_code = main(["validate", str(sample_pack_dir)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "PASSED" in captured.out

    # JSON format
    exit_code_json = main(["validate", str(sample_pack_dir), "--format", "json"])
    assert exit_code_json == 0
    captured_json = capsys.readouterr()
    data = json.loads(captured_json.out)
    assert data["is_valid"] is True

    # Non existent
    assert main(["validate", "non_existent_pack_path"]) == 1


def test_cli_optimize(sample_pack_dir: Path, tmp_path: Path, capsys):
    out_zip = tmp_path / "cli_optimized.zip"
    report_file = tmp_path / "report.md"

    exit_code = main([
        "optimize",
        str(sample_pack_dir),
        "-o", str(out_zip),
        "--prune-dead-code",
        "--report-file", str(report_file),
    ])
    assert exit_code == 0
    assert out_zip.exists()
    assert report_file.exists()
    capsys.readouterr()

    # JSON output format
    exit_code_json = main([
        "optimize",
        str(sample_pack_dir),
        "--format", "json",
    ])
    assert exit_code_json == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "total_bytes_saved" in data

    # Markdown output format
    exit_code_md = main([
        "optimize",
        str(sample_pack_dir),
        "--format", "markdown",
    ])
    assert exit_code_md == 0
    captured_md = capsys.readouterr()
    assert "# Resourcepack Optimization Report" in captured_md.out

    # Invalid input
    assert main(["optimize", "does_not_exist_xyz"]) == 1


def test_cli_diff(sample_pack_dir: Path, tmp_path: Path, capsys):
    pack_b = tmp_path / "pack_copy"
    import shutil
    shutil.copytree(sample_pack_dir, pack_b)

    exit_code = main(["diff", str(sample_pack_dir), str(pack_b)])
    assert exit_code == 0
    capsys.readouterr()

    exit_code_json = main(["diff", str(sample_pack_dir), str(pack_b), "--format", "json"])
    assert exit_code_json == 0
    captured = capsys.readouterr()
    diff_data = json.loads(captured.out)
    assert "pack_a" in diff_data

    # Non-existent
    assert main(["diff", "invalid_a", str(pack_b)]) == 1
