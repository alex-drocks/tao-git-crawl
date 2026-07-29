from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .overrides import ResolverConfig, SubnetOverride, TargetOverride

DEFAULT_REGISTRY_SCHEMA_VERSION = "tao-git-crawl-registry-v2"
DEFAULT_REGISTRY_CACHE_TTL_SECONDS = 3600  # 1 hour
DEFAULT_REGISTRY_REPO_PATH = Path(__file__).resolve().parents[1] / "registry" / "overrides.json"
PACKAGED_DEFAULT_REGISTRY_PATH = Path(__file__).with_name("registry_overrides.json")


class RegistryError(ValueError):
    """Raised when a registry file or remote fetch is malformed or unavailable."""


@dataclass(frozen=True)
class Registry:
    """A collection of subnet overrides loaded from JSON."""

    overrides: dict[int, SubnetOverride]
    raw: dict[str, Any]

    @classmethod
    def empty(cls) -> Registry:
        return cls(overrides={}, raw={})


def load_registry_from_path(path: str | Path) -> Registry:
    """Load a registry from a local JSON file."""
    registry_path = Path(path)
    if not registry_path.exists():
        raise RegistryError(f"registry file does not exist: {registry_path}")
    try:
        text = registry_path.read_text(encoding="utf-8")
    except Exception as exc:
        raise RegistryError(f"could not read registry file {path}: {exc}") from exc
    return parse_registry_json(text)


def load_built_in_registry() -> Registry:
    """Load the tracked built-in registry from source tree or packaged data."""
    for path in (DEFAULT_REGISTRY_REPO_PATH, PACKAGED_DEFAULT_REGISTRY_PATH):
        if path.exists():
            return load_registry_from_path(path)
    raise RegistryError(
        "built-in registry file is missing; expected registry/overrides.json in source "
        "or registry_overrides.json in package"
    )


def load_registry_from_remote(
    url: str,
    *,
    cache_path: str | Path | None = None,
    cache_ttl_seconds: int = DEFAULT_REGISTRY_CACHE_TTL_SECONDS,
) -> Registry:
    """Fetch a remote registry JSON with optional local disk caching.

    If ``cache_path`` is provided and the cached file is still fresh, it is
    returned without a network request. Otherwise the remote URL is fetched,
    validated, written to cache, and returned.
    """
    cache_file = Path(cache_path) if cache_path else None

    if cache_file is not None and cache_file.exists():
        try:
            age_seconds = time.time() - cache_file.stat().st_mtime
            if age_seconds < cache_ttl_seconds:
                text = cache_file.read_text(encoding="utf-8")
                return parse_registry_json(text)
        except Exception:
            pass

    text = _fetch_url_text(url)
    registry = parse_registry_json(text)

    if cache_file is not None:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(text, encoding="utf-8")
        except Exception:
            pass

    return registry


def parse_registry_json(text: str) -> Registry:
    """Parse a registry JSON string."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RegistryError(f"invalid JSON in registry: {exc}") from exc

    if not isinstance(data, dict):
        raise RegistryError("registry root must be a JSON object")

    schema_version = data.get("schema_version", "")
    if schema_version != DEFAULT_REGISTRY_SCHEMA_VERSION:
        raise RegistryError(
            f"unsupported registry schema version {schema_version!r}; expected {DEFAULT_REGISTRY_SCHEMA_VERSION!r}"
        )

    overrides_raw = data.get("overrides", {})
    if not isinstance(overrides_raw, dict):
        raise RegistryError("registry 'overrides' must be an object mapping netuid to override definitions")

    overrides: dict[int, SubnetOverride] = {}
    for raw_netuid, raw_override in overrides_raw.items():
        try:
            netuid = int(raw_netuid)
        except (TypeError, ValueError) as exc:
            raise RegistryError(f"invalid registry netuid key: {raw_netuid!r}") from exc
        overrides[netuid] = _parse_registry_subnet_override(raw_netuid, raw_override)

    return Registry(overrides=overrides, raw=data)


def _parse_registry_subnet_override(netuid_key: str, value: Any) -> SubnetOverride:
    if not isinstance(value, dict):
        raise RegistryError(f"override for netuid {netuid_key} must be a JSON object")
    if "registered_at" in value:
        raise RegistryError(f"override for netuid {netuid_key}: 'registered_at' is not supported")
    replace = _parse_registry_replace(netuid_key, value.get("replace", True))
    raw_targets = value.get("targets", [])
    if not isinstance(raw_targets, list):
        raise RegistryError(f"override for netuid {netuid_key}: 'targets' must be a list")
    targets: list[TargetOverride] = []
    for idx, item in enumerate(raw_targets):
        try:
            targets.append(_parse_registry_target_override(netuid_key, idx, item))
        except RegistryError:
            raise
        except Exception as exc:
            raise RegistryError(f"override for netuid {netuid_key}: target at index {idx}: {exc}") from exc
    return SubnetOverride(targets=tuple(targets), replace=replace)


def _parse_registry_target_override(netuid_key: str, idx: int, item: Any) -> TargetOverride:
    if not isinstance(item, dict):
        raise RegistryError(f"override for netuid {netuid_key}: target at index {idx} must be a JSON object")
    kind_item = item.get("kind", "owner")
    if not isinstance(kind_item, str):
        raise RegistryError(f"override for netuid {netuid_key}: target {idx}: 'kind' must be a string")
    kind = kind_item.strip().lower()
    if kind not in {"owner", "repository"}:
        raise RegistryError(f"override for netuid {netuid_key}: target {idx}: 'kind' must be 'owner' or 'repository'")

    url_item = item.get("url", "")
    if not isinstance(url_item, str) or not url_item.strip():
        raise RegistryError(f"override for netuid {netuid_key}: target {idx}: 'url' must be a non-empty string")

    if "confidence" in item:
        raise RegistryError(f"override for netuid {netuid_key}: target {idx}: 'confidence' is not supported")

    return TargetOverride(kind=kind, url=url_item.strip())  # type: ignore[arg-type]


def _parse_registry_replace(netuid_key: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    raise RegistryError(f"override for netuid {netuid_key}: 'replace' must be a boolean")


def _fetch_url_text(url: str) -> str:
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
            return response.read().decode("utf-8")
    except Exception as exc:
        raise RegistryError(f"failed to fetch remote registry from {url}: {exc}") from exc


def merge_registries(base: Registry, *others: Registry) -> Registry:
    """Merge multiple registries. Later overrides overwrite earlier ones."""
    merged_overrides = dict(base.overrides)
    merged_raw = dict(base.raw)
    for other in others:
        merged_overrides.update(other.overrides)
        if other.raw:
            merged_raw.update({k: v for k, v in other.raw.items() if k != "overrides"})
            merged_overrides_raw = dict(merged_raw.get("overrides", {}))
            merged_overrides_raw.update(other.raw.get("overrides", {}))
            merged_raw["overrides"] = merged_overrides_raw
    return Registry(overrides=merged_overrides, raw=merged_raw)


def resolver_config_from_registry(registry: Registry | None) -> ResolverConfig:
    """Build a ResolverConfig from a loaded registry."""
    if registry is None:
        return ResolverConfig()
    return ResolverConfig(default_repository_policy="repository", subnet_overrides=registry.overrides)


def load_registry(
    *,
    registry_path: str | Path | None = None,
    registry_url: str | None = None,
    cache_dir: str | Path | None = None,
    use_built_in: bool = True,
) -> Registry:
    """Load and merge registries from built-in defaults, a remote URL, and a local path.

    Merge order (later wins):
    1. tracked built-in ``registry/overrides.json`` (if ``use_built_in=True``)
    2. remote ``registry_url`` (fetched with optional cache)
    3. local ``registry_path`` (user override)
    """
    parts: list[Registry] = []

    if use_built_in:
        parts.append(load_built_in_registry())

    if registry_url:
        cache_file: Path | None = None
        if cache_dir:
            cache_file = Path(cache_dir) / "remote-registry-cache.json"
        parts.append(load_registry_from_remote(registry_url, cache_path=cache_file))

    if registry_path:
        parts.append(load_registry_from_path(registry_path))

    if not parts:
        return Registry.empty()

    base = parts[0]
    return merge_registries(base, *parts[1:])
