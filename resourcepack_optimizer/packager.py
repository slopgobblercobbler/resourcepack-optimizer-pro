"""Packager, compression pipeline, and diffing engine for Minecraft Resourcepacks."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from resourcepack_optimizer.audio_opt import audit_sound_file
from resourcepack_optimizer.image_opt import (
    get_image_pixel_hash,
    optimize_png,
)
from resourcepack_optimizer.json_opt import (
    AssetReferenceGraph,
    minify_json_bytes,
)
from resourcepack_optimizer.models import (
    FileOptimizationResult,
    OptimizationReport,
    ValidationReport,
)
from resourcepack_optimizer.validator import ResourcepackValidator


class ResourcepackOptimizerPipeline:
    """End-to-end optimization, minification, and packaging pipeline."""

    def __init__(
        self,
        input_path: Path | str,
        output_path: Optional[Path | str] = None,
        strip_metadata: bool = True,
        enable_palette_opt: bool = True,
        minify_json: bool = True,
        prune_dead_code: bool = False,
        audit_audio: bool = True,
        empty_to_minimal: bool = True,
    ):
        self.input_path = Path(input_path)
        self.output_path = Path(output_path) if output_path else None
        self.strip_metadata = strip_metadata
        self.enable_palette_opt = enable_palette_opt
        self.minify_json = minify_json
        self.prune_dead_code = prune_dead_code
        self.audit_audio = audit_audio
        self.empty_to_minimal = empty_to_minimal

    def run(self) -> OptimizationReport:
        """Execute the optimization pipeline and return the audit report."""
        start_time = time.time()
        report = OptimizationReport(pack_name=self.input_path.stem)

        temp_input_dir: Optional[tempfile.TemporaryDirectory[str]] = None
        temp_work_dir = tempfile.TemporaryDirectory(prefix="rp_opt_work_")

        try:
            # 1. Prepare input directory
            if self.input_path.is_file() and self.input_path.suffix.lower() == ".zip":
                temp_input_dir = tempfile.TemporaryDirectory(prefix="rp_opt_in_")
                source_dir = Path(temp_input_dir.name)
                with zipfile.ZipFile(self.input_path, "r") as zf:
                    zf.extractall(source_dir)
            elif self.input_path.is_dir():
                source_dir = self.input_path
            else:
                raise FileNotFoundError(f"Input path '{self.input_path}' is neither a directory nor a zip file.")

            work_dir = Path(temp_work_dir.name)
            # Copy source to working directory
            shutil.copytree(source_dir, work_dir, dirs_exist_ok=True)

            # 2. Run validator
            validator = ResourcepackValidator(work_dir)
            val_report = validator.validate_all()
            report.validation_report = val_report

            # 3. Dead code detection and pruning
            ref_graph = AssetReferenceGraph(work_dir)
            ref_graph.scan()

            if self.prune_dead_code:
                pruned = ref_graph.prune_unused_assets(dry_run=False)
                report.dead_code_pruned = pruned
                for p_file in pruned:
                    report.add_result(
                        FileOptimizationResult(
                            path=p_file,
                            original_size=0,
                            optimized_size=0,
                            status="pruned",
                            category="dead_code",
                            details="Unused texture or orphan model pruned",
                        )
                    )

            for item in ref_graph.broken_texture_refs:
                report.broken_references.append(
                    f"Model '{item['model']}' ({item['file']}) missing texture '{item['texture']}'"
                )
            for item in ref_graph.broken_parent_refs:
                report.broken_references.append(
                    f"Model '{item['model']}' ({item['file']}) missing parent '{item['parent']}'"
                )

            # 4. Process files: Images, JSON, Audio
            seen_hashes: Dict[str, str] = {}  # hash -> first seen relative path

            # Walk through all files in working directory
            for root, _, files in os.walk(work_dir):
                for fname in sorted(files):
                    file_path = Path(root) / fname
                    rel_posix = file_path.relative_to(work_dir).as_posix()
                    ext = file_path.suffix.lower()

                    orig_bytes = file_path.read_bytes()
                    orig_size = len(orig_bytes)

                    # --- PNG Optimization ---
                    if ext == ".png":
                        # Check duplicate texture
                        pix_hash = get_image_pixel_hash(orig_bytes)
                        if pix_hash:
                            if pix_hash in seen_hashes:
                                canon_path = seen_hashes[pix_hash]
                                report.duplicates_found.append((canon_path, rel_posix))
                            else:
                                seen_hashes[pix_hash] = rel_posix

                        opt_bytes, opt_info = optimize_png(
                            orig_bytes,
                            enable_palette_opt=self.enable_palette_opt,
                            empty_to_minimal=self.empty_to_minimal,
                        )

                        if opt_info.get("is_empty"):
                            report.empty_textures_found.append(rel_posix)

                        if len(opt_bytes) < orig_size:
                            file_path.write_bytes(opt_bytes)
                            opt_size = len(opt_bytes)
                            status = "optimized"
                            details = []
                            if opt_info.get("chunks_stripped"):
                                details.append("chunks_stripped")
                            if opt_info.get("palette_reduced"):
                                details.append("palette_8bit")
                            if opt_info.get("status") == "replaced_with_minimal_empty":
                                details.append("empty_1x1_minimal")
                            details_str = ", ".join(details) or "recompressed"
                        else:
                            opt_size = orig_size
                            status = "unmodified"
                            details_str = "already optimal"

                        report.add_result(
                            FileOptimizationResult(
                                path=rel_posix,
                                original_size=orig_size,
                                optimized_size=opt_size,
                                status=status,
                                category="image",
                                details=details_str,
                            )
                        )

                    # --- JSON & MCMETA Minification ---
                    elif ext in (".json", ".mcmeta") or rel_posix.endswith(".mcmeta"):
                        cat = "mcmeta" if rel_posix.endswith(".mcmeta") else "json"
                        if self.minify_json:
                            try:
                                opt_bytes = minify_json_bytes(orig_bytes)
                                if len(opt_bytes) < orig_size:
                                    file_path.write_bytes(opt_bytes)
                                    opt_size = len(opt_bytes)
                                    status = "optimized"
                                    details_str = "minified comments & whitespace"
                                else:
                                    opt_size = orig_size
                                    status = "unmodified"
                                    details_str = "already compact"
                            except Exception as exc:
                                opt_size = orig_size
                                status = "skipped"
                                details_str = f"minify error: {exc}"
                        else:
                            opt_size = orig_size
                            status = "unmodified"
                            details_str = "minification disabled"

                        report.add_result(
                            FileOptimizationResult(
                                path=rel_posix,
                                original_size=orig_size,
                                optimized_size=opt_size,
                                status=status,
                                category=cat,
                                details=details_str,
                            )
                        )

                    # --- Audio OGG Auditing ---
                    elif ext == ".ogg":
                        details_list: List[str] = []
                        if self.audit_audio:
                            audio_issues = audit_sound_file(file_path, relative_path=rel_posix)
                            for iss in audio_issues:
                                details_list.append(f"[{iss['code']}] {iss['message']}")
                                if val_report:
                                    from resourcepack_optimizer.models import ValidationSeverity
                                    sev = ValidationSeverity.ERROR if iss["severity"] == "ERROR" else ValidationSeverity.WARNING
                                    val_report.add_issue(
                                        severity=sev,
                                        code=iss["code"],
                                        message=iss["message"],
                                        file_path=rel_posix,
                                    )

                        report.add_result(
                            FileOptimizationResult(
                                path=rel_posix,
                                original_size=orig_size,
                                optimized_size=orig_size,
                                status="unmodified",
                                category="audio",
                                details="; ".join(details_list) if details_list else "valid vorbis",
                            )
                        )

                    # --- Other Files (TXT, Properties, OBF, etc.) ---
                    else:
                        report.add_result(
                            FileOptimizationResult(
                                path=rel_posix,
                                original_size=orig_size,
                                optimized_size=orig_size,
                                status="unmodified",
                                category="other",
                                details="non-optimizable format",
                            )
                        )

            # 5. Packaging output if requested
            if self.output_path:
                self._package_output(work_dir, self.output_path)

        finally:
            if temp_input_dir:
                temp_input_dir.cleanup()
            temp_work_dir.cleanup()

        report.duration_seconds = time.time() - start_time
        return report

    def _package_output(self, work_dir: Path, out_path: Path) -> None:
        """Write optimized resourcepack to directory or .zip with max compression."""
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if out_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(
                out_path,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            ) as zf:
                # Add pack.mcmeta first if present
                mcmeta = work_dir / "pack.mcmeta"
                if mcmeta.exists():
                    zf.write(mcmeta, arcname="pack.mcmeta")

                for root, _, files in os.walk(work_dir):
                    for fname in sorted(files):
                        file_p = Path(root) / fname
                        arc_name = file_p.relative_to(work_dir).as_posix()
                        if arc_name == "pack.mcmeta":
                            continue
                        zf.write(file_p, arcname=arc_name)
        else:
            # Output is a directory
            if out_path.exists():
                shutil.rmtree(out_path)
            shutil.copytree(work_dir, out_path)


def diff_resourcepacks(pack_a_path: Path | str, pack_b_path: Path | str) -> Dict[str, Any]:
    """Compare two resourcepack folders or archives and generate a diff summary."""
    p_a = Path(pack_a_path)
    p_b = Path(pack_b_path)

    temp_a: Optional[tempfile.TemporaryDirectory[str]] = None
    temp_b: Optional[tempfile.TemporaryDirectory[str]] = None

    try:
        if p_a.is_file() and p_a.suffix.lower() == ".zip":
            temp_a = tempfile.TemporaryDirectory(prefix="diff_a_")
            dir_a = Path(temp_a.name)
            with zipfile.ZipFile(p_a, "r") as zf:
                zf.extractall(dir_a)
        else:
            dir_a = p_a

        if p_b.is_file() and p_b.suffix.lower() == ".zip":
            temp_b = tempfile.TemporaryDirectory(prefix="diff_b_")
            dir_b = Path(temp_b.name)
            with zipfile.ZipFile(p_b, "r") as zf:
                zf.extractall(dir_b)
        else:
            dir_b = p_b

        files_a: Dict[str, int] = {}
        for r, _, fs in os.walk(dir_a):
            for f in fs:
                fp = Path(r) / f
                files_a[fp.relative_to(dir_a).as_posix()] = fp.stat().st_size

        files_b: Dict[str, int] = {}
        for r, _, fs in os.walk(dir_b):
            for f in fs:
                fp = Path(r) / f
                files_b[fp.relative_to(dir_b).as_posix()] = fp.stat().st_size

        all_keys = sorted(set(files_a.keys()) | set(files_b.keys()))

        added: List[str] = []
        removed: List[str] = []
        modified: List[Dict[str, Any]] = []
        unchanged: List[str] = []

        total_size_a = sum(files_a.values())
        total_size_b = sum(files_b.values())

        for k in all_keys:
            if k not in files_a:
                added.append(k)
            elif k not in files_b:
                removed.append(k)
            else:
                sz_a = files_a[k]
                sz_b = files_b[k]
                if sz_a != sz_b:
                    diff_bytes = sz_b - sz_a
                    pct = (diff_bytes / sz_a * 100.0) if sz_a > 0 else 0.0
                    modified.append({
                        "file": k,
                        "size_a": sz_a,
                        "size_b": sz_b,
                        "diff_bytes": diff_bytes,
                        "percentage": round(pct, 2),
                    })
                else:
                    unchanged.append(k)

        diff_total = total_size_b - total_size_a
        diff_pct = (diff_total / total_size_a * 100.0) if total_size_a > 0 else 0.0

        return {
            "pack_a": str(p_a),
            "pack_b": str(p_b),
            "total_size_a": total_size_a,
            "total_size_b": total_size_b,
            "diff_total_bytes": diff_total,
            "diff_percentage": round(diff_pct, 2),
            "files_added": added,
            "files_removed": removed,
            "files_modified": modified,
            "files_unchanged_count": len(unchanged),
        }
    finally:
        if temp_a:
            temp_a.cleanup()
        if temp_b:
            temp_b.cleanup()
