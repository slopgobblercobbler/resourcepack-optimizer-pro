"""Tests for JSON minification, comment stripping, and asset reference graph."""

from pathlib import Path

from resourcepack_optimizer.json_opt import (
    AssetReferenceGraph,
    load_lenient_json,
    minify_json_bytes,
    minify_json_text,
    normalize_identifier,
    remove_trailing_commas,
    strip_json_comments,
)


def test_strip_json_comments():
    raw = """
    {
        // Single line comment
        "name": "Minecraft // Not A Comment",
        /* Multi-line
           comment */
        "url": "https://example.com/api",
        "nested": {
            "val": "Escaped \\" /* preserved */ inside string"
        }
    }
    """
    clean = strip_json_comments(raw)
    assert "// Single line" not in clean
    assert "/* Multi-line" not in clean
    assert "Minecraft // Not A Comment" in clean
    assert "https://example.com/api" in clean


def test_remove_trailing_commas():
    raw = """{
        "a": 1,
        "b": [1, 2, 3,],
        "c": "text, with, comma,",
    }"""
    clean = remove_trailing_commas(raw)
    parsed = load_lenient_json(clean)
    assert parsed["a"] == 1
    assert parsed["b"] == [1, 2, 3]
    assert parsed["c"] == "text, with, comma,"


def test_minify_json():
    raw_text = """
    {
        // Comment here
        "pack": {
            "pack_format": 34,
            "description": "Awesome Pack"
        }
    }
    """
    minified = minify_json_text(raw_text)
    assert "\n" not in minified
    assert "  " not in minified
    assert minified == '{"pack":{"pack_format":34,"description":"Awesome Pack"}}'

    # Bytes version
    min_bytes = minify_json_bytes(raw_text.encode("utf-8"))
    assert min_bytes == minified.encode("utf-8")


def test_normalize_identifier():
    assert normalize_identifier("block/stone") == ("minecraft", "block/stone")
    assert normalize_identifier("custom:item/sword") == ("custom", "item/sword")
    assert normalize_identifier("minecraft:textures/block/stone", prefix="textures") == ("minecraft", "block/stone")


def test_asset_reference_graph(sample_pack_dir: Path):
    graph = AssetReferenceGraph(sample_pack_dir)
    graph.scan()

    assert len(graph.textures_on_disk) >= 4
    assert len(graph.models_on_disk) >= 2
    assert len(graph.referenced_models) >= 1
    assert len(graph.referenced_textures) >= 1
    assert len(graph.referenced_sounds) >= 1

    # Unused textures: 'unused_texture.png' should be identified as unused
    unused = graph.get_unused_textures()
    assert any("unused_texture.png" in u for u in unused)
    # stone.png is referenced by stone model, so not unused
    assert not any("block/stone.png" in u for u in unused)

    # Orphan models: 'orphan_model.json' in custom/ should be identified as orphan
    orphans = graph.get_orphan_models()
    assert any("orphan_model.json" in o for o in orphans)

    # Prune dry run
    pruned_dry = graph.prune_unused_assets(dry_run=True)
    assert len(pruned_dry) > 0
    # Files should still exist
    for f in pruned_dry:
        assert (sample_pack_dir / f).exists()

    # Actual prune
    pruned_real = graph.prune_unused_assets(dry_run=False)
    for f in pruned_real:
        assert not (sample_pack_dir / f).exists()


def test_asset_reference_graph_broken_refs(tmp_path: Path):
    pack_dir = tmp_path / "broken_pack"
    models_dir = pack_dir / "assets" / "minecraft" / "models" / "block"
    models_dir.mkdir(parents=True)

    # Model referencing non-existent parent and non-existent texture
    bad_model = """{
        "parent": "custom:non_existent_parent",
        "textures": {
            "all": "minecraft:block/missing_texture"
        }
    }"""
    (models_dir / "bad.json").write_text(bad_model, encoding="utf-8")

    graph = AssetReferenceGraph(pack_dir)
    graph.scan()

    assert len(graph.broken_parent_refs) == 1
    assert len(graph.broken_texture_refs) == 1
    assert graph.broken_parent_refs[0]["parent"] == "custom:non_existent_parent"
    assert graph.broken_texture_refs[0]["texture"] == "minecraft:block/missing_texture"
