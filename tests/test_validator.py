"""Tests for Resourcepack Validator and McMeta Checker."""

import json
from pathlib import Path

from resourcepack_optimizer.validator import ResourcepackValidator


def test_validator_on_sample_pack(sample_pack_dir: Path):
    validator = ResourcepackValidator(sample_pack_dir)
    report = validator.validate_all()

    assert report.is_valid is True
    assert report.pack_format == 34
    assert len(report.errors) == 0
    assert any(i.code == "PACK_FORMAT_MAPPED" for i in report.infos)


def test_validator_missing_pack_mcmeta(tmp_path: Path):
    empty_pack = tmp_path / "empty_pack"
    empty_pack.mkdir()

    validator = ResourcepackValidator(empty_pack)
    report = validator.validate_all()

    assert report.is_valid is False
    assert any(i.code == "MISSING_PACK_MCMETA" for i in report.errors)


def test_validator_mcmeta_variations(tmp_path: Path):
    pack_dir = tmp_path / "pack_var"
    pack_dir.mkdir()

    # 1. Invalid JSON
    (pack_dir / "pack.mcmeta").write_text("{ corrupt json ", encoding="utf-8")
    rep1 = ResourcepackValidator(pack_dir).validate_all()
    assert any(i.code == "INVALID_MCMETA_JSON" for i in rep1.errors)

    # 2. Root not object
    (pack_dir / "pack.mcmeta").write_text("[]", encoding="utf-8")
    rep2 = ResourcepackValidator(pack_dir).validate_all()
    assert any(i.code == "MCMETA_NOT_OBJECT" for i in rep2.errors)

    # 3. Missing pack section
    (pack_dir / "pack.mcmeta").write_text('{"other": 1}', encoding="utf-8")
    rep3 = ResourcepackValidator(pack_dir).validate_all()
    assert any(i.code == "MISSING_PACK_SECTION" for i in rep3.errors)

    # 4. Missing pack_format & missing description
    (pack_dir / "pack.mcmeta").write_text('{"pack": {}}', encoding="utf-8")
    rep4 = ResourcepackValidator(pack_dir).validate_all()
    assert any(i.code == "MISSING_PACK_FORMAT" for i in rep4.errors)
    assert any(i.code == "MISSING_DESCRIPTION" for i in rep4.warnings)

    # 5. Invalid pack_format type & negative format
    (pack_dir / "pack.mcmeta").write_text('{"pack": {"pack_format": "ten"}}', encoding="utf-8")
    rep5 = ResourcepackValidator(pack_dir).validate_all()
    assert any(i.code == "INVALID_PACK_FORMAT_TYPE" for i in rep5.errors)

    (pack_dir / "pack.mcmeta").write_text('{"pack": {"pack_format": -1}}', encoding="utf-8")
    rep6 = ResourcepackValidator(pack_dir).validate_all()
    assert any(i.code == "PACK_FORMAT_OUT_OF_RANGE" for i in rep6.errors)

    # 6. Invalid supported_formats
    bad_sf = {
        "pack": {
            "pack_format": 34,
            "description": "desc",
            "supported_formats": [34, 12]  # min > max
        }
    }
    (pack_dir / "pack.mcmeta").write_text(json.dumps(bad_sf), encoding="utf-8")
    rep7 = ResourcepackValidator(pack_dir).validate_all()
    assert any(i.code == "INVALID_SUPPORTED_FORMATS_LIST" for i in rep7.warnings)

    bad_sf_dict = {
        "pack": {
            "pack_format": 34,
            "description": "desc",
            "supported_formats": {"min_inclusive": 50, "max_inclusive": 20}
        }
    }
    (pack_dir / "pack.mcmeta").write_text(json.dumps(bad_sf_dict), encoding="utf-8")
    rep8 = ResourcepackValidator(pack_dir).validate_all()
    assert any(i.code == "INVALID_SUPPORTED_FORMATS_DICT" for i in rep8.warnings)

    bad_sf_type = {
        "pack": {
            "pack_format": 34,
            "description": "desc",
            "supported_formats": "invalid_type"
        }
    }
    (pack_dir / "pack.mcmeta").write_text(json.dumps(bad_sf_type), encoding="utf-8")
    rep9 = ResourcepackValidator(pack_dir).validate_all()
    assert any(i.code == "INVALID_SUPPORTED_FORMATS_TYPE" for i in rep9.warnings)


def test_validator_pack_png(tmp_path: Path):
    pack_dir = tmp_path / "png_pack"
    pack_dir.mkdir()
    (pack_dir / "pack.mcmeta").write_text('{"pack": {"pack_format": 34, "description": "d"}}', encoding="utf-8")

    # Missing pack.png
    rep_missing = ResourcepackValidator(pack_dir).validate_all()
    assert any(i.code == "NO_PACK_ICON" for i in rep_missing.infos)

    # Corrupt pack.png
    (pack_dir / "pack.png").write_bytes(b"corrupt image data")
    rep_corrupt = ResourcepackValidator(pack_dir).validate_all()
    assert any(i.code == "CORRUPT_PACK_PNG" for i in rep_corrupt.errors)


def test_validator_sounds_json(tmp_path: Path):
    pack_dir = tmp_path / "sound_pack"
    ns_dir = pack_dir / "assets" / "minecraft"
    ns_dir.mkdir(parents=True)
    (pack_dir / "pack.mcmeta").write_text('{"pack": {"pack_format": 34, "description": "d"}}', encoding="utf-8")

    # Corrupt sounds.json
    (ns_dir / "sounds.json").write_text("{ corrupt", encoding="utf-8")
    rep_c = ResourcepackValidator(pack_dir).validate_all()
    assert any(i.code == "INVALID_SOUNDS_JSON" for i in rep_c.errors)

    # Missing sound file & unknown category & invalid volume/pitch/weight
    bad_sounds = {
        "event.test": {
            "category": "not_a_category",
            "sounds": [
                {
                    "name": "minecraft:non_existent_sound",
                    "volume": "loud",
                    "pitch": "high",
                    "weight": 0
                }
            ]
        }
    }
    (ns_dir / "sounds.json").write_text(json.dumps(bad_sounds), encoding="utf-8")
    rep = ResourcepackValidator(pack_dir).validate_all()
    assert any(i.code == "UNKNOWN_SOUND_CATEGORY" for i in rep.warnings)
    assert any(i.code == "MISSING_SOUND_FILE" for i in rep.errors)
    assert any(i.code == "INVALID_SOUND_VOLUME" for i in rep.warnings)
    assert any(i.code == "INVALID_SOUND_PITCH" for i in rep.warnings)
    assert any(i.code == "INVALID_SOUND_WEIGHT" for i in rep.warnings)


def test_validator_models(tmp_path: Path):
    pack_dir = tmp_path / "model_pack"
    models_dir = pack_dir / "assets" / "minecraft" / "models" / "block"
    models_dir.mkdir(parents=True)
    (pack_dir / "pack.mcmeta").write_text('{"pack": {"pack_format": 34, "description": "d"}}', encoding="utf-8")

    # 1. Circular inheritance: model_a -> model_b -> model_a
    (models_dir / "model_a.json").write_text('{"parent": "minecraft:block/model_b"}', encoding="utf-8")
    (models_dir / "model_b.json").write_text('{"parent": "minecraft:block/model_a"}', encoding="utf-8")

    rep_cycle = ResourcepackValidator(pack_dir).validate_all()
    assert any(i.code == "CIRCULAR_MODEL_INHERITANCE" for i in rep_cycle.errors)

    # 2. Invalid elements and missing face texture
    elem_model = {
        "parent": "block/cube_all",
        "elements": [
            {
                "from": [0, 0, 0],
                "to": [16, 16, 16],
                "faces": {
                    "up": {},  # missing texture!
                    "not_a_face": {"texture": "#all"}
                }
            },
            {
                "from": "invalid_coords"
            }
        ]
    }
    (models_dir / "elem_test.json").write_text(json.dumps(elem_model), encoding="utf-8")
    rep_elem = ResourcepackValidator(pack_dir).validate_all()
    assert any(i.code == "MISSING_FACE_TEXTURE" for i in rep_elem.warnings)
    assert any(i.code == "UNKNOWN_CUBE_FACE" for i in rep_elem.warnings)
    assert any(i.code == "INVALID_ELEMENT_FROM" for i in rep_elem.errors)
