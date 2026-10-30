"""Resourcepack and McMeta Validator for Minecraft.

Validates:
- pack.mcmeta format, pack_format version mapping, text component descriptions.
- sounds.json audio definitions, categories, and referenced .ogg file existence.
- Custom block/item model JSON schemas (elements, UVs, parent inheritance cycles, textures).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from resourcepack_optimizer.image_opt import PNG_SIGNATURE
from resourcepack_optimizer.json_opt import (
    KNOWN_VANILLA_MODEL_PARENTS,
    load_lenient_json,
    normalize_identifier,
)
from resourcepack_optimizer.models import (
    PACK_FORMAT_MAP,
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
    get_version_for_format,
)

VALID_SOUND_CATEGORIES = {
    "master", "music", "record", "weather", "block",
    "hostile", "neutral", "player", "ambient", "voice",
}

VALID_CUBE_FACES = {"down", "up", "north", "south", "east", "west"}


class ResourcepackValidator:
    """Validator for Minecraft Resourcepack directories."""

    def __init__(self, root_dir: Path | str):
        self.root = Path(root_dir)
        self.report = ValidationReport(pack_name=self.root.name)

    def validate_all(self) -> ValidationReport:
        """Run complete validation suite on the resourcepack."""
        self.validate_pack_mcmeta()
        self.validate_pack_png()
        self.validate_sounds_json()
        self.validate_models()
        return self.report

    def validate_pack_mcmeta(self) -> None:
        """Validate root pack.mcmeta structure and pack_format version mapping."""
        mcmeta_path = self.root / "pack.mcmeta"
        if not mcmeta_path.exists():
            self.report.add_issue(
                severity=ValidationSeverity.ERROR,
                code="MISSING_PACK_MCMETA",
                message="Resourcepack is missing root 'pack.mcmeta' file.",
                file_path="pack.mcmeta",
            )
            return

        try:
            data = load_lenient_json(mcmeta_path.read_bytes())
        except Exception as exc:
            self.report.add_issue(
                severity=ValidationSeverity.ERROR,
                code="INVALID_MCMETA_JSON",
                message=f"Failed to parse 'pack.mcmeta' as JSON: {exc}",
                file_path="pack.mcmeta",
            )
            return

        if not isinstance(data, dict):
            self.report.add_issue(
                severity=ValidationSeverity.ERROR,
                code="MCMETA_NOT_OBJECT",
                message="'pack.mcmeta' root must be a JSON object.",
                file_path="pack.mcmeta",
            )
            return

        pack_obj = data.get("pack")
        if not isinstance(pack_obj, dict):
            self.report.add_issue(
                severity=ValidationSeverity.ERROR,
                code="MISSING_PACK_SECTION",
                message="'pack.mcmeta' missing required 'pack' object.",
                file_path="pack.mcmeta",
            )
            return

        # Validate pack_format
        if "pack_format" not in pack_obj:
            self.report.add_issue(
                severity=ValidationSeverity.ERROR,
                code="MISSING_PACK_FORMAT",
                message="'pack.mcmeta' is missing 'pack_format'.",
                file_path="pack.mcmeta",
            )
        else:
            pack_format = pack_obj.get("pack_format")
            if not isinstance(pack_format, int):
                self.report.add_issue(
                    severity=ValidationSeverity.ERROR,
                    code="INVALID_PACK_FORMAT_TYPE",
                    message=f"'pack_format' must be an integer, got {type(pack_format).__name__}.",
                    file_path="pack.mcmeta",
                )
            elif pack_format < 1:
                self.report.add_issue(
                    severity=ValidationSeverity.ERROR,
                    code="PACK_FORMAT_OUT_OF_RANGE",
                    message=f"'pack_format' must be >= 1, got {pack_format}.",
                    file_path="pack.mcmeta",
                )
            else:
                self.report.pack_format = pack_format
                mc_version = get_version_for_format(pack_format)
                self.report.minecraft_version = mc_version
                self.report.add_issue(
                    severity=ValidationSeverity.INFO,
                    code="PACK_FORMAT_MAPPED",
                    message=f"Pack format {pack_format} maps to Minecraft {mc_version}.",
                    file_path="pack.mcmeta",
                    details={"pack_format": pack_format, "minecraft_version": mc_version},
                )

        # Validate description
        if "description" not in pack_obj:
            self.report.add_issue(
                severity=ValidationSeverity.WARNING,
                code="MISSING_DESCRIPTION",
                message="'pack.mcmeta' is missing 'description'.",
                file_path="pack.mcmeta",
            )
        else:
            desc = pack_obj.get("description")
            if isinstance(desc, str):
                self.report.description = desc
            elif isinstance(desc, (dict, list)):
                self.report.description = json.dumps(desc)
            else:
                self.report.add_issue(
                    severity=ValidationSeverity.WARNING,
                    code="INVALID_DESCRIPTION_TYPE",
                    message=f"'description' should be a string or JSON text component, got {type(desc).__name__}.",
                    file_path="pack.mcmeta",
                )

        # Validate supported_formats (Minecraft 1.20.2+ / format 18+)
        if "supported_formats" in pack_obj:
            sf = pack_obj["supported_formats"]
            if isinstance(sf, int):
                pass
            elif isinstance(sf, list):
                if len(sf) != 2 or not all(isinstance(x, int) for x in sf) or sf[0] > sf[1]:
                    self.report.add_issue(
                        severity=ValidationSeverity.WARNING,
                        code="INVALID_SUPPORTED_FORMATS_LIST",
                        message="'supported_formats' list must contain [min_inclusive, max_inclusive] integers.",
                        file_path="pack.mcmeta",
                    )
            elif isinstance(sf, dict):
                min_inc = sf.get("min_inclusive")
                max_inc = sf.get("max_inclusive")
                if not isinstance(min_inc, int) or not isinstance(max_inc, int) or min_inc > max_inc:
                    self.report.add_issue(
                        severity=ValidationSeverity.WARNING,
                        code="INVALID_SUPPORTED_FORMATS_DICT",
                        message="'supported_formats' object must specify valid integer 'min_inclusive' and 'max_inclusive'.",
                        file_path="pack.mcmeta",
                    )
            else:
                self.report.add_issue(
                    severity=ValidationSeverity.WARNING,
                    code="INVALID_SUPPORTED_FORMATS_TYPE",
                    message="'supported_formats' must be integer, [min, max] list, or dict.",
                    file_path="pack.mcmeta",
                )

    def validate_pack_png(self) -> None:
        """Validate optional pack.png icon."""
        pack_png = self.root / "pack.png"
        if not pack_png.exists():
            self.report.add_issue(
                severity=ValidationSeverity.INFO,
                code="NO_PACK_ICON",
                message="Resourcepack has no root 'pack.png' icon.",
            )
            return

        try:
            data = pack_png.read_bytes()
            if len(data) < 8 or data[:8] != PNG_SIGNATURE:
                self.report.add_issue(
                    severity=ValidationSeverity.ERROR,
                    code="CORRUPT_PACK_PNG",
                    message="'pack.png' is not a valid PNG image file.",
                    file_path="pack.png",
                )
        except Exception as exc:
            self.report.add_issue(
                severity=ValidationSeverity.ERROR,
                code="PACK_PNG_READ_ERROR",
                message=f"Failed to read 'pack.png': {exc}",
                file_path="pack.png",
            )

    def validate_sounds_json(self) -> None:
        """Validate sounds.json files across namespaces."""
        assets_dir = self.root / "assets"
        if not assets_dir.is_dir():
            return

        for ns_dir in assets_dir.iterdir():
            if not ns_dir.is_dir():
                continue
            sounds_path = ns_dir / "sounds.json"
            if not sounds_path.exists():
                continue

            rel_path = sounds_path.relative_to(self.root).as_posix()
            try:
                data = load_lenient_json(sounds_path.read_bytes())
            except Exception as exc:
                self.report.add_issue(
                    severity=ValidationSeverity.ERROR,
                    code="INVALID_SOUNDS_JSON",
                    message=f"Failed to parse '{rel_path}': {exc}",
                    file_path=rel_path,
                )
                continue

            if not isinstance(data, dict):
                self.report.add_issue(
                    severity=ValidationSeverity.ERROR,
                    code="SOUNDS_JSON_NOT_OBJECT",
                    message=f"Root of '{rel_path}' must be an object of sound events.",
                    file_path=rel_path,
                )
                continue

            for event_name, event_data in data.items():
                if not isinstance(event_data, dict):
                    self.report.add_issue(
                        severity=ValidationSeverity.WARNING,
                        code="INVALID_SOUND_EVENT_ENTRY",
                        message=f"Sound event '{event_name}' in '{rel_path}' must be an object.",
                        file_path=rel_path,
                    )
                    continue

                # Validate category
                category = event_data.get("category")
                if category and category not in VALID_SOUND_CATEGORIES:
                    self.report.add_issue(
                        severity=ValidationSeverity.WARNING,
                        code="UNKNOWN_SOUND_CATEGORY",
                        message=f"Sound event '{event_name}' specifies unknown category '{category}'.",
                        file_path=rel_path,
                    )

                # Validate sounds list
                sounds_list = event_data.get("sounds")
                if sounds_list is None:
                    continue

                if not isinstance(sounds_list, list):
                    self.report.add_issue(
                        severity=ValidationSeverity.WARNING,
                        code="INVALID_SOUNDS_LIST",
                        message=f"'sounds' in event '{event_name}' must be an array.",
                        file_path=rel_path,
                    )
                    continue

                for sound_entry in sounds_list:
                    sound_name = None
                    sound_type = "file"

                    if isinstance(sound_entry, str):
                        sound_name = sound_entry
                    elif isinstance(sound_entry, dict):
                        sound_name = sound_entry.get("name")
                        sound_type = sound_entry.get("type", "file")

                        # Validate volume
                        if "volume" in sound_entry and not isinstance(sound_entry["volume"], (int, float)):
                            self.report.add_issue(
                                severity=ValidationSeverity.WARNING,
                                code="INVALID_SOUND_VOLUME",
                                message=f"Volume in sound '{sound_name}' must be numeric.",
                                file_path=rel_path,
                            )
                        # Validate pitch
                        if "pitch" in sound_entry and not isinstance(sound_entry["pitch"], (int, float)):
                            self.report.add_issue(
                                severity=ValidationSeverity.WARNING,
                                code="INVALID_SOUND_PITCH",
                                message=f"Pitch in sound '{sound_name}' must be numeric.",
                                file_path=rel_path,
                            )
                        # Validate weight
                        if "weight" in sound_entry and (not isinstance(sound_entry["weight"], int) or sound_entry["weight"] < 1):
                            self.report.add_issue(
                                severity=ValidationSeverity.WARNING,
                                code="INVALID_SOUND_WEIGHT",
                                message=f"Weight in sound '{sound_name}' must be a positive integer.",
                                file_path=rel_path,
                            )
                    else:
                        self.report.add_issue(
                            severity=ValidationSeverity.WARNING,
                            code="INVALID_SOUND_DEF",
                            message=f"Sound entry in event '{event_name}' must be string or object.",
                            file_path=rel_path,
                        )
                        continue

                    if sound_type == "file" and sound_name:
                        s_ns, s_path = normalize_identifier(sound_name, default_namespace=ns_dir.name)
                        expected_file = self.root / "assets" / s_ns / "sounds" / f"{s_path}.ogg"
                        if not expected_file.exists():
                            self.report.add_issue(
                                severity=ValidationSeverity.ERROR,
                                code="MISSING_SOUND_FILE",
                                message=f"Sound event '{event_name}' references missing file '{expected_file.relative_to(self.root).as_posix()}'.",
                                file_path=rel_path,
                                details={"sound": sound_name, "expected": expected_file.as_posix()},
                            )

    def validate_models(self) -> None:
        """Validate model JSON schemas, parent inheritance cycles, and texture references."""
        assets_dir = self.root / "assets"
        if not assets_dir.is_dir():
            return

        # Map of model_key -> (model_data, file_path)
        loaded_models: Dict[str, Tuple[Dict[str, Any], Path]] = {}

        for ns_dir in assets_dir.iterdir():
            if not ns_dir.is_dir():
                continue
            models_dir = ns_dir / "models"
            if not models_dir.is_dir():
                continue

            for model_path in models_dir.rglob("*.json"):
                rel_path = model_path.relative_to(self.root).as_posix()
                rel_name = model_path.relative_to(models_dir).with_suffix("").as_posix()
                model_key = f"{ns_dir.name}:{rel_name}"

                try:
                    data = load_lenient_json(model_path.read_bytes())
                except Exception as exc:
                    self.report.add_issue(
                        severity=ValidationSeverity.ERROR,
                        code="INVALID_MODEL_JSON",
                        message=f"Failed to parse model JSON: {exc}",
                        file_path=rel_path,
                    )
                    continue

                if not isinstance(data, dict):
                    self.report.add_issue(
                        severity=ValidationSeverity.ERROR,
                        code="MODEL_NOT_OBJECT",
                        message="Model root must be a JSON object.",
                        file_path=rel_path,
                    )
                    continue

                loaded_models[model_key] = (data, model_path)

        # 1. Check parent chains and detect inheritance cycles
        for model_key, (data, model_path) in loaded_models.items():
            rel_file = model_path.relative_to(self.root).as_posix()
            visited: Set[str] = {model_key}
            curr_parent = data.get("parent")

            while curr_parent and isinstance(curr_parent, str):
                p_ns, p_path = normalize_identifier(curr_parent)
                p_key = f"{p_ns}:{p_path}"

                if p_key in visited:
                    self.report.add_issue(
                        severity=ValidationSeverity.ERROR,
                        code="CIRCULAR_MODEL_INHERITANCE",
                        message=f"Circular model inheritance detected: {' -> '.join(visited)} -> {p_key}",
                        file_path=rel_file,
                    )
                    break

                visited.add(p_key)

                if p_key in loaded_models:
                    curr_parent = loaded_models[p_key][0].get("parent")
                else:
                    # Check if vanilla parent
                    is_vanilla = (
                        p_ns == "minecraft" and p_path in KNOWN_VANILLA_MODEL_PARENTS
                    ) or p_path.startswith("builtin/") or curr_parent.startswith("builtin/")
                    if not is_vanilla:
                        self.report.add_issue(
                            severity=ValidationSeverity.WARNING,
                            code="MISSING_PARENT_MODEL",
                            message=f"Model references missing parent '{curr_parent}'.",
                            file_path=rel_file,
                        )
                    break

            # 2. Validate elements schema if present
            elements = data.get("elements")
            if elements is not None:
                if not isinstance(elements, list):
                    self.report.add_issue(
                        severity=ValidationSeverity.ERROR,
                        code="INVALID_ELEMENTS_TYPE",
                        message="'elements' must be an array of cube elements.",
                        file_path=rel_file,
                    )
                else:
                    for idx, elem in enumerate(elements):
                        if not isinstance(elem, dict):
                            self.report.add_issue(
                                severity=ValidationSeverity.ERROR,
                                code="INVALID_ELEMENT_OBJECT",
                                message=f"Element at index {idx} must be an object.",
                                file_path=rel_file,
                            )
                            continue

                        # Validate from/to
                        for coord_key in ("from", "to"):
                            if coord_key not in elem:
                                self.report.add_issue(
                                    severity=ValidationSeverity.ERROR,
                                    code=f"MISSING_ELEMENT_{coord_key.upper()}",
                                    message=f"Element at index {idx} missing '{coord_key}' coordinates.",
                                    file_path=rel_file,
                                )
                            else:
                                coord = elem[coord_key]
                                if not isinstance(coord, list) or len(coord) != 3 or not all(isinstance(v, (int, float)) for v in coord):
                                    self.report.add_issue(
                                        severity=ValidationSeverity.ERROR,
                                        code=f"INVALID_ELEMENT_{coord_key.upper()}",
                                        message=f"'{coord_key}' at index {idx} must be an array of 3 numbers.",
                                        file_path=rel_file,
                                    )

                        # Validate faces
                        faces = elem.get("faces")
                        if faces is not None:
                            if not isinstance(faces, dict):
                                self.report.add_issue(
                                    severity=ValidationSeverity.ERROR,
                                    code="INVALID_FACES_OBJECT",
                                    message=f"Element {idx} 'faces' must be an object.",
                                    file_path=rel_file,
                                )
                            else:
                                for face_name, face_def in faces.items():
                                    if face_name not in VALID_CUBE_FACES:
                                        self.report.add_issue(
                                            severity=ValidationSeverity.WARNING,
                                            code="UNKNOWN_CUBE_FACE",
                                            message=f"Unknown face '{face_name}' at element {idx}.",
                                            file_path=rel_file,
                                        )
                                    if isinstance(face_def, dict) and "texture" not in face_def:
                                        self.report.add_issue(
                                            severity=ValidationSeverity.WARNING,
                                            code="MISSING_FACE_TEXTURE",
                                            message=f"Face '{face_name}' at element {idx} is missing 'texture'.",
                                            file_path=rel_file,
                                        )
