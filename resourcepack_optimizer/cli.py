"""CLI entrypoint for resourcepack-optimizer-pro."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from resourcepack_optimizer.models import (
    OptimizationReport,
    ValidationReport,
    ValidationSeverity,
)
from resourcepack_optimizer.packager import (
    ResourcepackOptimizerPipeline,
    diff_resourcepacks,
)
from resourcepack_optimizer.validator import ResourcepackValidator

try:
    from rich import print as rprint
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


def print_banner() -> None:
    """Print tool banner."""
    if HAS_RICH:
        console = Console()
        console.print(
            Panel.fit(
                "[bold cyan]Resourcepack Optimizer Pro[/bold cyan]\n"
                "[dim]High-speed Minecraft Resourcepack Validator, Minifier & Compressor[/dim]",
                border_style="cyan",
            )
        )
    else:
        print("=== Resourcepack Optimizer Pro ===")


def cmd_validate(args: argparse.Namespace) -> int:
    """Run resourcepack validation."""
    pack_path = Path(args.input)
    if not pack_path.exists():
        print(f"Error: Path '{pack_path}' does not exist.", file=sys.stderr)
        return 1

    validator = ResourcepackValidator(pack_path)
    report = validator.validate_all()

    if args.format == "json":
        print(json.dumps(report.to_dict(), indent=2))
        return 0 if report.is_valid else 1

    if HAS_RICH:
        console = Console()
        status_color = "green" if report.is_valid else "red"
        status_text = "PASSED" if report.is_valid else "FAILED"
        console.print(f"\n[bold]Validation Result:[/bold] [{status_color}]{status_text}[/{status_color}]")
        if report.pack_format:
            console.print(f"[bold]Pack Format:[/bold] {report.pack_format} (Minecraft {report.minecraft_version})")

        table = Table(title="Validation Issues", show_header=True, header_style="bold magenta")
        table.add_column("Severity", width=10)
        table.add_column("Code", width=25)
        table.add_column("Location")
        table.add_column("Message")

        for iss in report.issues:
            color = "red" if iss.severity == ValidationSeverity.ERROR else ("yellow" if iss.severity == ValidationSeverity.WARNING else "blue")
            table.add_row(
                f"[{color}]{iss.severity.value}[/{color}]",
                iss.code,
                iss.file_path or "-",
                iss.message,
            )
        console.print(table)
    else:
        print(f"\nValidation Result: {'PASSED' if report.is_valid else 'FAILED'}")
        if report.pack_format:
            print(f"Pack Format: {report.pack_format} (Minecraft {report.minecraft_version})")
        for iss in report.issues:
            loc = f" in {iss.file_path}" if iss.file_path else ""
            print(f"[{iss.severity.value}] {iss.code}{loc}: {iss.message}")

    return 0 if report.is_valid else 1


def cmd_optimize(args: argparse.Namespace) -> int:
    """Run optimization pipeline."""
    input_p = Path(args.input)
    if not input_p.exists():
        print(f"Error: Input path '{input_p}' does not exist.", file=sys.stderr)
        return 1

    pipeline = ResourcepackOptimizerPipeline(
        input_path=input_p,
        output_path=args.output,
        strip_metadata=not args.no_strip_metadata,
        enable_palette_opt=not args.no_palette_opt,
        minify_json=not args.no_minify_json,
        prune_dead_code=args.prune_dead_code,
        audit_audio=not args.no_audit_audio,
        empty_to_minimal=not args.no_empty_opt,
    )

    report = pipeline.run()

    if args.report_file:
        out_p = Path(args.report_file)
        if out_p.suffix.lower() == ".json":
            out_p.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        else:
            out_p.write_text(report.to_markdown(), encoding="utf-8")

    if args.format == "json":
        print(json.dumps(report.to_dict(), indent=2))
        return 0

    if args.format == "markdown":
        print(report.to_markdown())
        return 0

    # Rich or Text display
    if HAS_RICH:
        console = Console()
        console.print(f"\n[bold green]Optimization Complete![/bold green] (in {report.duration_seconds:.2f}s)")
        console.print(f"Original Size:  {report.original_total_size:,} bytes")
        console.print(f"Optimized Size: {report.optimized_total_size:,} bytes")
        console.print(
            f"Bytes Saved:    [bold cyan]{report.total_bytes_saved:,} bytes[/bold cyan] "
            f"([bold yellow]{report.total_reduction_percentage:.2f}%[/bold yellow])"
        )

        table = Table(title="Category Savings", show_header=True, header_style="bold magenta")
        table.add_column("Category")
        table.add_column("Files", justify="right")
        table.add_column("Original", justify="right")
        table.add_column("Optimized", justify="right")
        table.add_column("Saved", justify="right")
        table.add_column("Reduction", justify="right")

        for cat, data in report.category_breakdown().items():
            table.add_row(
                cat.capitalize(),
                str(data["count"]),
                f"{data['original_bytes']:,} B",
                f"{data['optimized_bytes']:,} B",
                f"{data['bytes_saved']:,} B",
                f"{data['reduction_percentage']:.1f}%",
            )
        console.print(table)

        if report.duplicates_found:
            console.print(f"\n[bold yellow]Found {len(report.duplicates_found)} duplicate textures![/bold yellow]")
        if report.empty_textures_found:
            console.print(f"[bold yellow]Found {len(report.empty_textures_found)} fully transparent textures.[/bold yellow]")
        if report.dead_code_pruned:
            console.print(f"[bold red]Pruned {len(report.dead_code_pruned)} dead code assets.[/bold red]")
    else:
        print(f"\nOptimization Complete in {report.duration_seconds:.2f}s")
        print(f"Original Size:  {report.original_total_size:,} bytes")
        print(f"Optimized Size: {report.optimized_total_size:,} bytes")
        print(f"Bytes Saved:    {report.total_bytes_saved:,} bytes ({report.total_reduction_percentage:.2f}%)")
        print(f"Files Processed: {len(report.file_results)}")

    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    """Compare two resourcepack folders or zip archives."""
    pack_a = Path(args.pack_a)
    pack_b = Path(args.pack_b)

    if not pack_a.exists() or not pack_b.exists():
        print("Error: Both pack paths must exist.", file=sys.stderr)
        return 1

    diff_data = diff_resourcepacks(pack_a, pack_b)

    if args.format == "json":
        print(json.dumps(diff_data, indent=2))
        return 0

    if HAS_RICH:
        console = Console()
        console.print(f"\n[bold]Diffing Packs:[/bold]")
        console.print(f"  Pack A: {diff_data['pack_a']} ({diff_data['total_size_a']:,} bytes)")
        console.print(f"  Pack B: {diff_data['pack_b']} ({diff_data['total_size_b']:,} bytes)")
        diff_bytes = diff_data["diff_total_bytes"]
        diff_pct = diff_data["diff_percentage"]
        color = "green" if diff_bytes < 0 else "red"
        console.print(f"  Net Change: [{color}]{diff_bytes:+,} bytes ({diff_pct:+.2f}%)[/{color}]")

        console.print(f"  Added files: {len(diff_data['files_added'])}")
        console.print(f"  Removed files: {len(diff_data['files_removed'])}")
        console.print(f"  Modified files: {len(diff_data['files_modified'])}")
        console.print(f"  Unchanged files: {diff_data['files_unchanged_count']}")
    else:
        print(f"\nPack A: {diff_data['pack_a']} ({diff_data['total_size_a']:,} bytes)")
        print(f"Pack B: {diff_data['pack_b']} ({diff_data['total_size_b']:,} bytes)")
        print(f"Net Change: {diff_data['diff_total_bytes']:+,} bytes ({diff_data['diff_percentage']:+.2f}%)")
        print(f"Modified files: {len(diff_data['files_modified'])}")

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint router."""
    parser = argparse.ArgumentParser(
        prog="resourcepack-optimizer",
        description="High-speed Minecraft Resourcepack Validator, Minifier & Compressor.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Command: optimize
    opt_parser = subparsers.add_parser("optimize", help="Optimize, minify, and package a resourcepack")
    opt_parser.add_argument("input", help="Input resourcepack folder or .zip archive")
    opt_parser.add_argument("-o", "--output", help="Output path (folder or .zip)")
    opt_parser.add_argument("--no-strip-metadata", action="store_true", help="Do not strip PNG metadata chunks")
    opt_parser.add_argument("--no-palette-opt", action="store_true", help="Disable 8-bit palette reduction")
    opt_parser.add_argument("--no-minify-json", action="store_true", help="Disable JSON minification")
    opt_parser.add_argument("--no-empty-opt", action="store_true", help="Do not convert 100% empty textures to 1x1")
    opt_parser.add_argument("--prune-dead-code", action="store_true", help="Remove unused textures and orphan models")
    opt_parser.add_argument("--no-audit-audio", action="store_true", help="Disable audio Vorbis auditing")
    opt_parser.add_argument("--format", choices=["text", "json", "markdown"], default="text", help="Output format")
    opt_parser.add_argument("--report-file", help="Path to write audit report (Markdown or JSON)")

    # Command: validate
    val_parser = subparsers.add_parser("validate", help="Validate resourcepack structure, mcmeta, sounds & models")
    val_parser.add_argument("input", help="Resourcepack folder or .zip to validate")
    val_parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format")

    # Command: diff
    diff_parser = subparsers.add_parser("diff", help="Diff two resourcepack archives or folders")
    diff_parser.add_argument("pack_a", help="First resourcepack (original)")
    diff_parser.add_argument("pack_b", help="Second resourcepack (optimized)")
    diff_parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format")

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "validate":
        return cmd_validate(args)
    elif args.command == "optimize":
        return cmd_optimize(args)
    elif args.command == "diff":
        return cmd_diff(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
