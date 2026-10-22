#!/usr/bin/env python3
"""Sync the DALI integration from Home Assistant core into this HACS repo.

Copies ``homeassistant/components/dali/`` from a local Home Assistant core
checkout into ``custom_components/dali/`` and adds the one manifest change a
HACS custom integration needs that a core integration must not have: a
``version`` field (required for custom integrations).

The ``python-dali`` requirement is copied verbatim; the needed releases
(``python-dali==0.16``) are now published on PyPI, so no git-URL swap is
required. Everything else is copied verbatim. Re-run after any change in core.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DST = REPO_ROOT / "custom_components" / "dali"

DEFAULT_VERSION = "0.2.0"

EXCLUDE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")


def patch_manifest(path: Path, version: str) -> None:
    """Add the version field required for a HACS custom integration."""
    manifest = json.loads(path.read_text(encoding="utf-8"))

    # Place version right after name for readability.
    ordered: dict[str, object] = {}
    for key, value in manifest.items():
        ordered[key] = value
        if key == "name":
            ordered["version"] = version
    if "version" not in ordered:
        ordered["version"] = version

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

    patch_manifest(DST / "manifest.json", version)

    print(f"Synced {src} -> {DST}")
    print(f"  version: {version}")
    print("Remember to bump the version and cut a matching release tag.")


if __name__ == "__main__":
    main()
