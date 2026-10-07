#!/usr/bin/env python3
"""Sync the DALI integration from Home Assistant core into this HACS repo.

Copies ``homeassistant/components/dali/`` from a local Home Assistant core
checkout into ``custom_components/dali/`` and applies the two manifest changes a
HACS custom integration needs that a core integration must not have:

1. add a ``version`` field (required for custom integrations), and
2. replace the ``python-dali`` PyPI pin with a git-URL requirement pointing at
   the Tridonic fork (the needed 0.12 changes are not on PyPI yet).

Everything else is copied verbatim. Re-run after any change in core.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DST = REPO_ROOT / "custom_components" / "dali"

# Immutable ref of github.com/tridonic-com/python-dali@to-upstream (tip 63810e8).
DEFAULT_PYTHON_DALI_REF = "63810e867a0d4604072f7f95028404a275a622ff"
DEFAULT_VERSION = "0.1.0"

EXCLUDE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")


def patch_manifest(path: Path, version: str, python_dali_ref: str) -> None:
    """Add the version field and swap python-dali for a git-URL requirement."""
    manifest = json.loads(path.read_text(encoding="utf-8"))

    # Place version right after name for readability.
    ordered: dict[str, object] = {}
    for key, value in manifest.items():
        ordered[key] = value
        if key == "name":
            ordered["version"] = version
    if "version" not in ordered:
        ordered["version"] = version

    requirements = ordered.get("requirements", [])
    git_url = (
        "python-dali @ git+https://github.com/tridonic-com/"
        f"python-dali@{python_dali_ref}"
    )
    ordered["requirements"] = [
        git_url if req.startswith("python-dali") else req for req in requirements
    ]

    path.write_text(
        json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--core-path",
        type=Path,
        default=REPO_ROOT.parent / "core",
        help="Path to the Home Assistant core checkout (default: ../core).",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Integration version for the manifest (default: keep existing or "
        f"{DEFAULT_VERSION}).",
    )
    parser.add_argument(
        "--python-dali-ref",
        default=DEFAULT_PYTHON_DALI_REF,
        help="Git ref (commit SHA, tag or branch) of the python-dali fork.",
    )
    args = parser.parse_args()

    src = args.core_path / "homeassistant" / "components" / "dali"
    if not src.is_dir():
        raise SystemExit(f"DALI integration not found at {src}")

    # Preserve the existing version unless explicitly overridden.
    version = args.version
    if version is None:
        existing = DST / "manifest.json"
        if existing.is_file():
            version = json.loads(existing.read_text(encoding="utf-8")).get(
                "version", DEFAULT_VERSION
            )
        else:
            version = DEFAULT_VERSION

    if DST.exists():
        shutil.rmtree(DST)
    shutil.copytree(src, DST, ignore=EXCLUDE)

    patch_manifest(DST / "manifest.json", version, args.python_dali_ref)

    print(f"Synced {src} -> {DST}")
    print(f"  version: {version}")
    print(f"  python-dali ref: {args.python_dali_ref}")
    print("Remember to bump the version and cut a matching release tag.")


if __name__ == "__main__":
    main()
