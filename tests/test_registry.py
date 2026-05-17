from __future__ import annotations

import json

import pytest

from tao_git_crawl.overrides import TargetOverride
from tao_git_crawl.registry import (
    DEFAULT_REGISTRY_SCHEMA_VERSION,
    RegistryError,
    load_registry,
    load_registry_from_path,
    merge_registries,
    parse_registry_json,
    resolver_config_from_registry,
)

GOOD_REGISTRY = {
    "schema_version": "tao-git-crawl-registry-v1",
    "updated_at": "2026-05-17T00:00:00Z",
    "overrides": {
        "64": {
            "replace": True,
            "targets": [{"kind": "owner", "url": "https://github.com/chutesai", "confidence": "high"}],
            "note": "Chutes",
        },
        "1": {
            "replace": False,
            "targets": [
                {"kind": "repository", "url": "https://github.com/alice/api", "confidence": "medium"},
            ],
        },
    },
}


def test_parse_registry_json_valid():
    registry = parse_registry_json(json.dumps(GOOD_REGISTRY))
    assert len(registry.overrides) == 2
    assert 64 in registry.overrides
    assert 1 in registry.overrides

    override_64 = registry.overrides[64]
    assert override_64.replace is True
    assert override_64.targets == (
        TargetOverride(kind="owner", url="https://github.com/chutesai", confidence="high"),
    )

    override_1 = registry.overrides[1]
    assert override_1.replace is False
    assert override_1.targets == (
        TargetOverride(kind="repository", url="https://github.com/alice/api", confidence="medium"),
    )


def test_parse_registry_json_missing_schema_version():
    with pytest.raises(RegistryError, match="unsupported registry schema"):
        parse_registry_json(json.dumps({"overrides": {}}))


def test_parse_registry_json_bad_version():
    with pytest.raises(RegistryError, match="unsupported registry schema"):
        parse_registry_json(json.dumps({"schema_version": "v2", "overrides": {}}))


def test_parse_registry_json_invalid_json():
    with pytest.raises(RegistryError, match="invalid JSON"):
        parse_registry_json("not json")


def test_parse_registry_json_non_dict_root():
    with pytest.raises(RegistryError):
        parse_registry_json(json.dumps([]))


def test_parse_registry_json_bad_netuid_key():
    with pytest.raises(RegistryError, match="invalid registry netuid key"):
        parse_registry_json(
            json.dumps(
                {
                    "schema_version": DEFAULT_REGISTRY_SCHEMA_VERSION,
                    "overrides": {"abc": {"targets": []}},
                }
            )
        )


def test_parse_registry_json_bad_target_kind():
    with pytest.raises(RegistryError, match="target 0"):
        parse_registry_json(
            json.dumps(
                {
                    "schema_version": DEFAULT_REGISTRY_SCHEMA_VERSION,
                    "overrides": {
                        "64": {"targets": [{"kind": "other", "url": "https://github.com/x"}]}
                    },
                }
            )
        )


def test_parse_registry_json_missing_url():
    with pytest.raises(RegistryError, match="target 0"):
        parse_registry_json(
            json.dumps(
                {
                    "schema_version": DEFAULT_REGISTRY_SCHEMA_VERSION,
                    "overrides": {
                        "64": {"targets": [{"kind": "owner"}]}
                    },
                }
            )
        )


def test_parse_registry_json_invalid_confidence():
    with pytest.raises(RegistryError, match="target 0"):
        parse_registry_json(
            json.dumps(
                {
                    "schema_version": DEFAULT_REGISTRY_SCHEMA_VERSION,
                    "overrides": {
                        "64": {"targets": [{"kind": "owner", "url": "https://github.com/x", "confidence": "mega"}]}
                    },
                }
            )
        )


def test_load_registry_from_path(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(GOOD_REGISTRY), encoding="utf-8")
    registry = load_registry_from_path(path)
    assert 64 in registry.overrides


def test_load_registry_from_path_missing():
    with pytest.raises(RegistryError, match="does not exist"):
        load_registry_from_path("/nonexistent/registry.json")


def test_resolver_config_from_registry():
    registry = parse_registry_json(json.dumps(GOOD_REGISTRY))
    config = resolver_config_from_registry(registry)
    assert config.default_repository_policy == "repository"
    assert 64 in config.subnet_overrides
    assert 1 in config.subnet_overrides


def test_resolver_config_from_none():
    config = resolver_config_from_registry(None)
    assert config.subnet_overrides == {}


def test_merge_registries():
    base = parse_registry_json(json.dumps(GOOD_REGISTRY))
    extension = parse_registry_json(
        json.dumps(
            {
                "schema_version": DEFAULT_REGISTRY_SCHEMA_VERSION,
                "overrides": {
                    "64": {
                        "replace": False,
                        "targets": [{"kind": "owner", "url": "https://github.com/chutesai-v2", "confidence": "high"}],
                    },
                    "99": {
                        "replace": True,
                        "targets": [{"kind": "owner", "url": "https://github.com/acme", "confidence": "medium"}],
                    },
                },
            }
        )
    )
    merged = merge_registries(base, extension)
    # Later wins for netuid 64
    assert merged.overrides[64].targets == (
        TargetOverride(kind="owner", url="https://github.com/chutesai-v2", confidence="high"),
    )
    # Netuid 99 added
    assert 99 in merged.overrides
    # Netuid 1 preserved from base
    assert 1 in merged.overrides


def test_load_registry_built_in_only():
    registry = load_registry()
    # Built-in SN64 should be present
    assert 64 in registry.overrides


def test_load_registry_local_override(tmp_path):
    custom = tmp_path / "custom.json"
    custom.write_text(
        json.dumps(
            {
                "schema_version": DEFAULT_REGISTRY_SCHEMA_VERSION,
                "overrides": {
                    "99": {"targets": [{"kind": "owner", "url": "https://github.com/acme"}]}
                },
            }
        ),
        encoding="utf-8",
    )
    registry = load_registry(registry_path=custom)
    assert 64 in registry.overrides  # built-in
    assert 99 in registry.overrides  # local override


def test_load_registry_local_override_replaces_built_in(tmp_path):
    custom = tmp_path / "custom.json"
    custom.write_text(
        json.dumps(
            {
                "schema_version": DEFAULT_REGISTRY_SCHEMA_VERSION,
                "overrides": {
                    "64": {"targets": [{"kind": "owner", "url": "https://github.com/chutesai-v2"}]}
                },
            }
        ),
        encoding="utf-8",
    )
    registry = load_registry(registry_path=custom)
    assert registry.overrides[64].targets[0].url == "https://github.com/chutesai-v2"
