# resourcepack-optimizer-pro

[![Python: 3.9+](https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**resourcepack-optimizer-pro** is a high-speed, pure Python CLI tool and library for validating, minifying, compressing, and optimizing Minecraft Resourcepacks.

---

## ✨ Features

- **Resourcepack Validator & McMeta Checker**:
  - Validates `pack.mcmeta` format and maps `pack_format` versions (1.6.1 through 1.21.5+).
  - Validates `sounds.json` definitions, categories, and verifies existence of referenced `.ogg` sound files.
  - Validates custom block/item model JSON schemas (cube elements, UVs, parent inheritance cycles, and missing textures).
- **Lossless Image Optimizer**:
  - Removes non-essential PNG metadata chunks (`tEXt`, `iTXt`, `zTXt`, `tIME`, `pHYs`, `iCCP`, `gAMA`).
  - Color palette reduction: Losslessly quantizes eligible 32-bit textures (<= 256 colors) to indexed 8-bit palette mode.
  - Detects completely empty / 100% transparent textures and optionally replaces them with 67-byte minimal stubs.
  - Detects duplicate textures across the entire pack using pixel SHA-256 hashes.
- **JSON Minifier & Dead Code Pruner**:
  - Strips whitespace and comments (`//` and `/* ... */`) from JSON and `.mcmeta` files.
  - Detects unused textures, orphan models, and broken references.
  - Supports `--prune-dead-code` to purge unreferenced assets.
- **Audio Normalizer & Vorbis Auditor**:
  - Pure Python Ogg Vorbis stream parser.
  - Audits audio channel configuration: flags stereo positional 3D sounds (which cause panning issues and waste 50% audio memory in Minecraft's OpenAL engine).
  - Validates sample rates against 44.1 kHz / 48 kHz standards.
  - Detects metadata comment bloat.
- **Packaging & Diffing**:
  - Compresses directory or `.zip` resourcepacks with maximum DEFLATE compression (`level=9`).
  - Generates comprehensive markdown, JSON, or terminal audit reports.
  - Built-in `diff` command to analyze size differences between packs.

---

## 🚀 Installation

```bash
pip install .
```

Or install with development dependencies:

```bash
pip install ".[dev]"
```

---

## 🛠️ Usage

### 1. Optimize a Resourcepack

```bash
# Optimize a folder or .zip to an optimized .zip
resourcepack-optimizer optimize path/to/pack -o path/to/pack_optimized.zip

# Optimize with dead code pruning and save a markdown report
resourcepack-optimizer optimize path/to/pack.zip -o optimized.zip --prune-dead-code --report-file report.md
```

### 2. Validate a Resourcepack

```bash
# Validate pack format, sounds.json, models, and textures
resourcepack-optimizer validate path/to/pack
```

### 3. Diff Two Resourcepacks

```bash
# Compare original pack with optimized pack
resourcepack-optimizer diff original.zip optimized.zip
```

---

## 🧩 Python API

```python
from resourcepack_optimizer import ResourcepackOptimizerPipeline, ResourcepackValidator

# Validate
validator = ResourcepackValidator("my_pack")
report = validator.validate_all()
print(f"Valid: {report.is_valid}, Pack format: {report.pack_format}")

# Optimize
pipeline = ResourcepackOptimizerPipeline(
    input_path="my_pack",
    output_path="my_pack_optimized.zip",
    prune_dead_code=True,
)
opt_report = pipeline.run()
print(f"Saved {opt_report.total_bytes_saved:,} bytes ({opt_report.total_reduction_percentage:.2f}%)")
```

---

## 🧪 Testing & Coverage

Run tests with `pytest`:

```bash
pytest --cov=resourcepack_optimizer
```

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
