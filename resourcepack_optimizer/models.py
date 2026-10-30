"""Data models, version mappings, and result representations for resourcepack optimizer."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class ValidationSeverity(str, Enum):
    """Validation severity levels."""
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


# Canonical Minecraft release to pack_format mapping
PACK_FORMAT_MAP: Dict[int, str] = {
    1: "1.6.1 - 1.8.9",
    2: "1.9 - 1.10.2",
    3: "1.11 - 1.12.2",
    4: "1.13 - 1.14.4",
    5: "1.15 - 1.16.1",
    6: "1.16.2 - 1.16.5",
    7: "1.17 - 1.17.1",
    8: "1.18 - 1.18.1",
    9: "1.18.2",
    10: "1.19 - 1.19.2",
    12: "1.19.3",
    13: "1.19.4",
    15: "1.20 - 1.20.1",
    18: "1.20.2",
    22: "1.20.3 - 1.20.4",
    32: "1.20.5 - 1.20.6",
    34: "1.21 - 1.21.1",
    42: "1.21.2 - 1.21.3",
    46: "1.21.4",
    48: "1.21.5+",
}


def get_version_for_format(pack_format: int) -> str:
    """Retrieve Minecraft version string for a given pack_format."""
    if pack_format in PACK_FORMAT_MAP:
        return PACK_FORMAT_MAP[pack_format]
    if pack_format < 1:
        return "Unknown (< 1.6)"
    # Find nearest lower format
    known_formats = sorted(PACK_FORMAT_MAP.keys())
    if pack_format > known_formats[-1]:
        return f">= {PACK_FORMAT_MAP[known_formats[-1]]} (Format {pack_format})"
    for fmt in reversed(known_formats):
        if pack_format >= fmt:
            return f"~{PACK_FORMAT_MAP[fmt]} (Format {pack_format})"
    return f"Format {pack_format}"


def get_format_for_version(version_str: str) -> Optional[int]:
    """Find the pack_format corresponding to a Minecraft version string (e.g. '1.20.4')."""
    clean_ver = version_str.strip().lower().replace("minecraft", "").strip()
    for fmt, ver_range in PACK_FORMAT_MAP.items():
        if clean_ver in ver_range:
            return fmt
    # Match prefixes like '1.20'
    for fmt, ver_range in PACK_FORMAT_MAP.items():
        parts = clean_ver.split(".")
        if len(parts) >= 2:
            base = f"{parts[0]}.{parts[1]}"
            if base in ver_range:
                return fmt
    return None


@dataclass
class ValidationIssue:
    """Individual issue found during resourcepack validation."""
    severity: ValidationSeverity
    code: str
    message: str
    file_path: Optional[str] = None
    line: Optional[int] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
            "file_path": self.file_path,
            "line": self.line,
            "details": self.details,
        }


@dataclass
class ValidationReport:
    """Consolidated validation report for a resourcepack."""
    pack_name: str = "Unknown"
    pack_format: Optional[int] = None
    minecraft_version: Optional[str] = None
    description: Optional[str] = None
    issues: List[ValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Resourcepack is considered valid if there are no ERROR severity issues."""
        return not any(issue.severity == ValidationSeverity.ERROR for issue in self.issues)

    def add_issue(
        self,
        severity: ValidationSeverity,
        code: str,
        message: str,
        file_path: Optional[str] = None,
        line: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.issues.append(
            ValidationIssue(
                severity=severity,
                code=code,
                message=message,
                file_path=file_path,
                line=line,
                details=details or {},
            )
        )

    @property
    def errors(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == ValidationSeverity.ERROR]

    @property
    def warnings(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == ValidationSeverity.WARNING]

    @property
    def infos(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == ValidationSeverity.INFO]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pack_name": self.pack_name,
            "pack_format": self.pack_format,
            "minecraft_version": self.minecraft_version,
            "description": self.description,
            "is_valid": self.is_valid,
            "summary": {
                "errors": len(self.errors),
                "warnings": len(self.warnings),
                "infos": len(self.infos),
                "total": len(self.issues),
            },
            "issues": [i.to_dict() for i in self.issues],
        }


@dataclass
class FileOptimizationResult:
    """Individual file optimization result."""
    path: str
    original_size: int
    optimized_size: int
    status: str  # "optimized", "skipped", "pruned", "unmodified", "failed"
    category: str  # "image", "json", "audio", "mcmeta", "other"
    details: str = ""

    @property
    def bytes_saved(self) -> int:
        return max(0, self.original_size - self.optimized_size)

    @property
    def reduction_percentage(self) -> float:
        if self.original_size <= 0:
            return 0.0
        return ((self.original_size - self.optimized_size) / self.original_size) * 100.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "original_size": self.original_size,
            "optimized_size": self.optimized_size,
            "bytes_saved": self.bytes_saved,
            "reduction_percentage": round(self.reduction_percentage, 2),
            "status": self.status,
            "category": self.category,
            "details": self.details,
        }


@dataclass
class OptimizationReport:
    """Full optimization audit report."""
    pack_name: str = "Unknown"
    duration_seconds: float = 0.0
    file_results: List[FileOptimizationResult] = field(default_factory=list)
    duplicates_found: List[Tuple[str, str]] = field(default_factory=list)
    empty_textures_found: List[str] = field(default_factory=list)
    dead_code_pruned: List[str] = field(default_factory=list)
    broken_references: List[str] = field(default_factory=list)
    validation_report: Optional[ValidationReport] = None

    def add_result(self, result: FileOptimizationResult) -> None:
        self.file_results.append(result)

    @property
    def original_total_size(self) -> int:
        return sum(f.original_size for f in self.file_results)

    @property
    def optimized_total_size(self) -> int:
        return sum(f.optimized_size for f in self.file_results)

    @property
    def total_bytes_saved(self) -> int:
        return max(0, self.original_total_size - self.optimized_total_size)

    @property
    def total_reduction_percentage(self) -> float:
        if self.original_total_size <= 0:
            return 0.0
        return (self.total_bytes_saved / self.original_total_size) * 100.0

    def category_breakdown(self) -> Dict[str, Dict[str, Any]]:
        cats: Dict[str, Dict[str, Any]] = {}
        for res in self.file_results:
            cat = res.category
            if cat not in cats:
                cats[cat] = {"count": 0, "orig": 0, "opt": 0}
            cats[cat]["count"] += 1
            cats[cat]["orig"] += res.original_size
            cats[cat]["opt"] += res.optimized_size

        breakdown = {}
        for cat, data in cats.items():
            saved = max(0, data["orig"] - data["opt"])
            pct = (saved / data["orig"] * 100.0) if data["orig"] > 0 else 0.0
            breakdown[cat] = {
                "count": data["count"],
                "original_bytes": data["orig"],
                "optimized_bytes": data["opt"],
                "bytes_saved": saved,
                "reduction_percentage": round(pct, 2),
            }
        return breakdown

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pack_name": self.pack_name,
            "duration_seconds": round(self.duration_seconds, 3),
            "original_total_bytes": self.original_total_size,
            "optimized_total_bytes": self.optimized_total_size,
            "total_bytes_saved": self.total_bytes_saved,
            "total_reduction_percentage": round(self.total_reduction_percentage, 2),
            "files_processed": len(self.file_results),
            "categories": self.category_breakdown(),
            "duplicates_found": len(self.duplicates_found),
            "empty_textures_found": len(self.empty_textures_found),
            "dead_code_pruned": len(self.dead_code_pruned),
            "broken_references": len(self.broken_references),
            "validation": self.validation_report.to_dict() if self.validation_report else None,
            "files": [f.to_dict() for f in self.file_results],
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Resourcepack Optimization Report: {self.pack_name}",
            "",
            "## Summary",
            f"- **Processing Time**: {self.duration_seconds:.2f}s",
            f"- **Files Processed**: {len(self.file_results)}",
            f"- **Original Size**: {self.original_total_size:,} bytes ({self.original_total_size / (1024 * 1024):.2f} MB)",
            f"- **Optimized Size**: {self.optimized_total_size:,} bytes ({self.optimized_total_size / (1024 * 1024):.2f} MB)",
            f"- **Bytes Saved**: {self.total_bytes_saved:,} bytes ({self.total_bytes_saved / 1024:.2f} KB)",
            f"- **Reduction**: **{self.total_reduction_percentage:.2f}%**",
            "",
            "## Category Breakdown",
            "| Category | Files | Original Size | Optimized Size | Saved | Reduction |",
            "| :--- | :---: | :---: | :---: | :---: | :---: |",
        ]
        breakdown = self.category_breakdown()
        for cat, data in breakdown.items():
            lines.append(
                f"| {cat.capitalize()} | {data['count']} | {data['original_bytes']:,} B | "
                f"{data['optimized_bytes']:,} B | {data['bytes_saved']:,} B | {data['reduction_percentage']:.1f}% |"
            )

        if self.duplicates_found:
            lines.extend([
                "",
                f"## Duplicate Textures ({len(self.duplicates_found)})",
                "| Canonical File | Duplicate File |",
                "| :--- | :--- |",
            ])
            for canon, dup in self.duplicates_found[:20]:
                lines.append(f"| `{canon}` | `{dup}` |")
            if len(self.duplicates_found) > 20:
                lines.append(f"| ... and {len(self.duplicates_found) - 20} more | |")

        if self.empty_textures_found:
            lines.extend([
                "",
                f"## Fully Transparent / Empty Textures ({len(self.empty_textures_found)})",
            ])
            for empty_path in self.empty_textures_found[:15]:
                lines.append(f"- `{empty_path}`")
            if len(self.empty_textures_found) > 15:
                lines.append(f"- ... and {len(self.empty_textures_found) - 15} more")

        if self.dead_code_pruned:
            lines.extend([
                "",
                f"## Dead Code Pruned ({len(self.dead_code_pruned)})",
            ])
            for pruned in self.dead_code_pruned[:20]:
                lines.append(f"- `{pruned}`")

        if self.broken_references:
            lines.extend([
                "",
                f"## Broken References ({len(self.broken_references)})",
            ])
            for ref in self.broken_references[:20]:
                lines.append(f"- {ref}")

        if self.validation_report and not self.validation_report.is_valid:
            lines.extend([
                "",
                f"## Validation Issues ({len(self.validation_report.errors)} errors, {len(self.validation_report.warnings)} warnings)",
            ])
            for err in self.validation_report.errors[:15]:
                loc = f" (`{err.file_path}`)" if err.file_path else ""
                lines.append(f"- ❌ **[{err.code}]** {err.message}{loc}")
            for warn in self.validation_report.warnings[:10]:
                loc = f" (`{warn.file_path}`)" if warn.file_path else ""
                lines.append(f"- ⚠️ **[{warn.code}]** {warn.message}{loc}")

        return "\n".join(lines)
