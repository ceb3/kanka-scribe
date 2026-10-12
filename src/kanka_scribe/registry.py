"""Load module paths and visibility rules from CE/SaaS overrides (docs-backed)."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

_PACKAGE_DIR = Path(__file__).resolve().parent
_CANDIDATES = [
    Path(os.environ["KANKA_API_DOCS"])
    if os.environ.get("KANKA_API_DOCS")
    else None,
    Path("/app/vendor/kanka-api-docs"),
    _PACKAGE_DIR.parents[1] / "vendor" / "kanka-api-docs",  # src/../vendor (editable)
    _PACKAGE_DIR.parents[2] / "vendor" / "kanka-api-docs",  # repo root
    _PACKAGE_DIR / "vendor" / "kanka-api-docs",
]


def docs_root() -> Path:
    for candidate in _CANDIDATES:
        if candidate and candidate.is_dir():
            return candidate
    raise RuntimeError(
        "kanka API docs not found; set KANKA_API_DOCS or ship vendor/kanka-api-docs"
    )


DOCS_ROOT = None  # resolved lazily


@lru_cache
def load_profile(profile: str = "ce") -> dict:
    root = docs_root()
    name = "ce-overrides.yaml" if profile != "saas" else "saas-overrides.yaml"
    path = root / name
    data = yaml.safe_load(path.read_text()) or {}
    if "modules" not in data:
        raise RuntimeError(f"overrides missing modules: {path}")
    return data


def module_path(profile: str, module: str) -> str | None:
    return load_profile(profile).get("modules", {}).get(module)


def allowed_modules(profile: str) -> list[str]:
    return sorted(load_profile(profile).get("modules", {}).keys())


def visibility_id(profile: str, kind: str) -> int:
    vis = load_profile(profile).get("visibility", {})
    return int(vis.get(kind, 1 if kind == "all" else 2))


def alias_asset_type_id(profile: str) -> int:
    body = load_profile(profile).get("aliases", {}).get("body", {})
    return int(body.get("type_id", 3))


def docs_index_path() -> Path:
    return docs_root() / "1.0" / "index.md"
