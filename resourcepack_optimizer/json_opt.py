"""JSON Minifier and Dead Code / Asset Graph Pruner for Minecraft Resourcepacks."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


def strip_json_comments(text: str) -> str:
    """Strip single-line (//) and multi-line (/* ... */) comments from JSON string.

    Respects string literals so that URLs and comment-like characters in strings
    are preserved intact.
    """
    result: List[str] = []
    i = 0
    n = len(text)
    in_string = False
    escape = False

    while i < n:
        char = text[i]

        if in_string:
            result.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            i += 1
            continue

        # Outside string literal
        if char == '"':
            in_string = True
            result.append(char)
            i += 1
        elif char == "/" and i + 1 < n:
            next_char = text[i + 1]
            if next_char == "/":
                # Single line comment - skip until newline
                i += 2
                while i < n and text[i] not in ("\r", "\n"):
                    i += 1
            elif next_char == "*":
                # Multi-line comment - skip until */
                i += 2
                while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                    i += 1
                i += 2  # skip closing */
            else:
                result.append(char)
                i += 1
        else:
            result.append(char)
            i += 1

    return "".join(result)


def remove_trailing_commas(json_str: str) -> str:
    """Remove trailing commas before closing braces/brackets outside of strings."""
    # Matches a comma followed by whitespace and closing brace/bracket
    # Only applies outside string literals
    parts: List[str] = []
    in_string = False
    escape = False
    i = 0
    n = len(json_str)

    while i < n:
        c = json_str[i]
        if in_string:
            parts.append(c)
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            i += 1
            continue

        if c == '"':
            in_string = True
            parts.append(c)
            i += 1
            continue

        if c == ",":
            # Look ahead for next non-whitespace character
            j = i + 1
            while j < n and json_str[j] in " \t\r\n":
                j += 1
            if j < n and json_str[j] in "}]":
                # Trailing comma! Skip this comma
                i += 1
                continue

        parts.append(c)
        i += 1

    return "".join(parts)


def load_lenient_json(text_or_bytes: str | bytes) -> Any:
    """Parse JSON supporting comments and trailing commas."""
    if isinstance(text_or_bytes, bytes):
        text = text_or_bytes.decode("utf-8", errors="replace")
    else:
        text = text_or_bytes

    clean = strip_json_comments(text)
    clean = remove_trailing_commas(clean)
    return json.loads(clean)


def minify_json_text(text: str) -> str:
    """Minify JSON text by removing comments and unnecessary whitespace."""
    obj = load_lenient_json(text)
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def minify_json_bytes(data: bytes) -> bytes:
    """Minify JSON bytes with UTF-8 encoding."""
    text = data.decode("utf-8", errors="replace")
    minified = minify_json_text(text)
    return minified.encode("utf-8")


# Standard vanilla parents that packs inherit from without needing local model files
KNOWN_VANILLA_MODEL_PARENTS: Set[str] = {
    "builtin/generated",
    "builtin/entity",
    "item/generated",
    "item/handheld",
    "item/handheld_rod",
    "item/bundle",
    "block/block",
    "block/cube",
    "block/cube_all",
    "block/cube_bottom_top",
    "block/cube_column",
    "block/cube_column_horizontal",
    "block/cube_directional",
    "block/cube_mirrored",
    "block/cube_mirrored_all",
    "block/cube_top",
    "block/orientable",
    "block/orientable_with_bottom",
    "block/orientable_vertical",
    "block/cross",
    "block/tinted_cross",
    "block/crop",
    "block/carpet",
    "block/flower_pot_cross",
    "block/thin_block",
    "block/wall_inventory",
    "block/fence_inventory",
    "block/button_inventory",
    "block/pressure_plate_up",
    "block/stairs",
    "block/slab",
    "block/slab_top",
}


def normalize_identifier(identifier: str, default_namespace: str = "minecraft", prefix: str = "") -> Tuple[str, str]:
    """Normalize a resource identifier like 'block/dirt' or 'minecraft:block/dirt'.

    Returns:
        (namespace, path)
    """
    clean = identifier.strip().replace("\\", "/")
    if ":" in clean:
        ns, path = clean.split(":", 1)
    else:
        ns, path = default_namespace, clean

    # Strip optional prefix if present
    if prefix and path.startswith(prefix + "/"):
        path = path[len(prefix) + 1:]

    # Remove leading slashes
    path = path.lstrip("/")
    return ns, path


class AssetReferenceGraph:
    """Graph that scans and tracks references between models, blockstates, textures, and sounds."""

    def __init__(self, root_dir: Path | str):
        self.root = Path(root_dir)
        self.textures_on_disk: Set[str] = set()       # relative path: 'assets/<ns>/textures/<name>.png'
        self.models_on_disk: Dict[str, Path] = {}     # 'ns:path' -> Path
        self.blockstates_on_disk: Set[str] = set()
        self.sounds_on_disk: Set[str] = set()         # 'assets/<ns>/sounds/<name>.ogg'

        self.referenced_textures: Set[str] = set()    # 'assets/<ns>/textures/<name>.png'
        self.referenced_models: Set[str] = set()      # 'ns:path'
        self.referenced_sounds: Set[str] = set()      # 'assets/<ns>/sounds/<name>.ogg'

        self.broken_texture_refs: List[Dict[str, str]] = []
        self.broken_parent_refs: List[Dict[str, str]] = []

    def scan(self) -> None:
        """Scan resourcepack directory and build references."""
        if not self.root.exists() or not self.root.is_dir():
            return

        assets_dir = self.root / "assets"
        if not assets_dir.exists():
            return

        for ns_dir in assets_dir.iterdir():
            if not ns_dir.is_dir():
                continue
            namespace = ns_dir.name

            # 1. Discover all textures on disk
            textures_dir = ns_dir / "textures"
            if textures_dir.is_dir():
                for p in textures_dir.rglob("*.png"):
                    rel = p.relative_to(self.root).as_posix()
                    self.textures_on_disk.add(rel)

            # 2. Discover all sounds on disk
            sounds_dir = ns_dir / "sounds"
            if sounds_dir.is_dir():
                for p in sounds_dir.rglob("*.ogg"):
                    rel = p.relative_to(self.root).as_posix()
                    self.sounds_on_disk.add(rel)

            # 3. Discover all models on disk
            models_dir = ns_dir / "models"
            if models_dir.is_dir():
                for p in models_dir.rglob("*.json"):
                    rel_p = p.relative_to(models_dir).with_suffix("").as_posix()
                    model_key = f"{namespace}:{rel_p}"
                    self.models_on_disk[model_key] = p

            # 4. Discover blockstates on disk
            blockstates_dir = ns_dir / "blockstates"
            if blockstates_dir.is_dir():
                for p in blockstates_dir.rglob("*.json"):
                    self.blockstates_on_disk.add(p.relative_to(self.root).as_posix())

        # Scan blockstates for model references
        self._scan_blockstates()

        # Scan models for parents, texture references, and overrides
        self._scan_models()

        # Scan sounds.json
        self._scan_sounds()

        # Scan fonts and particles
        self._scan_fonts_and_particles()

    def _scan_blockstates(self) -> None:
        for bs_rel in self.blockstates_on_disk:
            bs_file = self.root / bs_rel
            try:
                data = load_lenient_json(bs_file.read_bytes())
            except Exception:
                continue

            # Blockstate can have "variants" or "multipart"
            models_to_check: List[Any] = []
            if isinstance(data, dict):
                if "variants" in data and isinstance(data["variants"], dict):
                    for var_val in data["variants"].values():
                        if isinstance(var_val, list):
                            models_to_check.extend(var_val)
                        elif isinstance(var_val, dict):
                            models_to_check.append(var_val)
                if "multipart" in data and isinstance(data["multipart"], list):
                    for part in data["multipart"]:
                        if isinstance(part, dict) and "apply" in part:
                            apply_val = part["apply"]
                            if isinstance(apply_val, list):
                                models_to_check.extend(apply_val)
                            elif isinstance(apply_val, dict):
                                models_to_check.append(apply_val)

            for item in models_to_check:
                if isinstance(item, dict) and "model" in item:
                    model_name = str(item["model"])
                    ns, path = normalize_identifier(model_name)
                    # Normalize: if starts with block/ or item/
                    self.referenced_models.add(f"{ns}:{path}")

    def _scan_models(self) -> None:
        # Loop over models on disk
        for model_key, model_path in self.models_on_disk.items():
            try:
                data = load_lenient_json(model_path.read_bytes())
            except Exception:
                continue

            if not isinstance(data, dict):
                continue

            # Check parent
            parent = data.get("parent")
            if parent and isinstance(parent, str):
                p_ns, p_path = normalize_identifier(parent)
                full_parent_key = f"{p_ns}:{p_path}"
                self.referenced_models.add(full_parent_key)

                # Check if parent is neither vanilla nor on disk
                is_vanilla = (
                    p_ns == "minecraft" and p_path in KNOWN_VANILLA_MODEL_PARENTS
                ) or p_path.startswith("builtin/") or parent.startswith("builtin/")
                if not is_vanilla and full_parent_key not in self.models_on_disk:
                    self.broken_parent_refs.append({
                        "model": model_key,
                        "file": model_path.relative_to(self.root).as_posix(),
                        "parent": parent,
                    })

            # Check overrides (e.g. for custom items)
            overrides = data.get("overrides")
            if isinstance(overrides, list):
                for ov in overrides:
                    if isinstance(ov, dict) and "model" in ov:
                        ov_model = str(ov["model"])
                        o_ns, o_path = normalize_identifier(ov_model)
                        self.referenced_models.add(f"{o_ns}:{o_path}")

            # Check textures
            textures = data.get("textures")
            if isinstance(textures, dict):
                for var_name, tex_ref in textures.items():
                    if not isinstance(tex_ref, str):
                        continue
                    if tex_ref.startswith("#"):
                        # Texture variable, resolved via parent or self
                        continue

                    t_ns, t_path = normalize_identifier(tex_ref, prefix="textures")
                    # If path does not start with textures/ after normalization, add it
                    expected_rel = f"assets/{t_ns}/textures/{t_path}.png"
                    self.referenced_textures.add(expected_rel)

                    # Check existence if this is within our pack's namespace(s)
                    pack_namespaces = {
                        d.name for d in (self.root / "assets").iterdir() if d.is_dir()
                    }
                    if t_ns in pack_namespaces and expected_rel not in self.textures_on_disk:
                        self.broken_texture_refs.append({
                            "model": model_key,
                            "file": model_path.relative_to(self.root).as_posix(),
                            "variable": var_name,
                            "texture": tex_ref,
                            "expected_path": expected_rel,
                        })

    def _scan_sounds(self) -> None:
        assets_dir = self.root / "assets"
        if not assets_dir.is_dir():
            return

        for ns_dir in assets_dir.iterdir():
            if not ns_dir.is_dir():
                continue
            sounds_json = ns_dir / "sounds.json"
            if not sounds_json.exists():
                continue

            try:
                data = load_lenient_json(sounds_json.read_bytes())
            except Exception:
                continue

            if not isinstance(data, dict):
                continue

            for event_name, event_data in data.items():
                if not isinstance(event_data, dict):
                    continue
                sounds_list = event_data.get("sounds", [])
                if not isinstance(sounds_list, list):
                    continue

                for sound_entry in sounds_list:
                    sound_path = None
                    sound_type = "file"
                    if isinstance(sound_entry, str):
                        sound_path = sound_entry
                    elif isinstance(sound_entry, dict):
                        sound_path = sound_entry.get("name")
                        sound_type = sound_entry.get("type", "file")

                    if sound_path and sound_type == "file":
                        s_ns, s_file = normalize_identifier(sound_path, default_namespace=ns_dir.name)
                        rel_ogg = f"assets/{s_ns}/sounds/{s_file}.ogg"
                        self.referenced_sounds.add(rel_ogg)

    def _scan_fonts_and_particles(self) -> None:
        assets_dir = self.root / "assets"
        if not assets_dir.is_dir():
            return

        for ns_dir in assets_dir.iterdir():
            if not ns_dir.is_dir():
                continue

            # Fonts
            font_dir = ns_dir / "font"
            if font_dir.is_dir():
                for f_path in font_dir.rglob("*.json"):
                    try:
                        f_data = load_lenient_json(f_path.read_bytes())
                        providers = f_data.get("providers", []) if isinstance(f_data, dict) else []
                        for prov in providers:
                            if isinstance(prov, dict) and "file" in prov:
                                prov_file = str(prov["file"])
                                f_ns, f_name = normalize_identifier(prov_file)
                                # Font textures can be in textures/font or textures/
                                rel_tex = f"assets/{f_ns}/textures/{f_name}"
                                if not rel_tex.endswith(".png"):
                                    rel_tex += ".png"
                                self.referenced_textures.add(rel_tex)
                    except Exception:
                        pass

            # Particles
            particles_dir = ns_dir / "particles"
            if particles_dir.is_dir():
                for p_path in particles_dir.rglob("*.json"):
                    try:
                        p_data = load_lenient_json(p_path.read_bytes())
                        textures = p_data.get("textures", []) if isinstance(p_data, dict) else []
                        for tex in textures:
                            if isinstance(tex, str):
                                t_ns, t_name = normalize_identifier(tex)
                                rel_tex = f"assets/{t_ns}/textures/{t_name}.png"
                                self.referenced_textures.add(rel_tex)
                    except Exception:
                        pass

    def get_unused_textures(self) -> List[str]:
        """Return list of texture paths on disk that are never referenced."""
        unused: List[str] = []
        for tex in sorted(self.textures_on_disk):
            # Special case: GUI, particle, colormap, environment, or pack.png
            # textures are sometimes referenced by code rather than models
            lower = tex.lower()
            if any(k in lower for k in [
                "/gui/", "/colormap/", "/environment/", "/font/", "/map/",
                "/painting/", "/particle/", "/mob_effect/", "pack.png"
            ]):
                continue
            if tex not in self.referenced_textures:
                unused.append(tex)
        return unused

    def get_orphan_models(self) -> List[str]:
        """Return list of model identifiers on disk not referenced by any blockstate, item, or parent."""
        orphan: List[str] = []
        for model_key, model_path in sorted(self.models_on_disk.items()):
            rel_file = model_path.relative_to(self.root).as_posix()
            # If model is directly in models/item or models/block, Minecraft auto-binds
            # items with same name, but custom models in subdirectories may be orphans
            if model_key not in self.referenced_models:
                # Check if it is a top-level standard item model (item/diamond_sword.json etc.)
                # In Minecraft, items with matching names are automatically loaded.
                if "/models/item/" in rel_file:
                    continue
                orphan.append(rel_file)
        return orphan

    def prune_unused_assets(self, dry_run: bool = False) -> List[str]:
        """Prune unused textures and orphan models from disk."""
        unused_textures = self.get_unused_textures()
        orphan_models = self.get_orphan_models()
        pruned_files: List[str] = []

        for rel_tex in unused_textures:
            p = self.root / rel_tex
            if p.exists() and p.is_file():
                if not dry_run:
                    p.unlink()
                    # Also prune mcmeta if exists
                    mcmeta = p.with_name(p.name + ".mcmeta")
                    if mcmeta.exists():
                        mcmeta.unlink()
                pruned_files.append(rel_tex)

        for rel_model in orphan_models:
            p = self.root / rel_model
            if p.exists() and p.is_file():
                if not dry_run:
                    p.unlink()
                pruned_files.append(rel_model)

        return pruned_files
