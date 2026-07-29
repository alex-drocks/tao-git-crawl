from __future__ import annotations

import json
from pathlib import Path

import pytest

from tao_git_crawl.overrides import TargetOverride
from tao_git_crawl.registry import (
    DEFAULT_REGISTRY_REPO_PATH,
    DEFAULT_REGISTRY_SCHEMA_VERSION,
    RegistryError,
    load_built_in_registry,
    load_registry,
    load_registry_from_path,
    load_registry_from_remote,
    merge_registries,
    parse_registry_json,
    resolver_config_from_registry,
)

GOOD_REGISTRY = {
    "schema_version": DEFAULT_REGISTRY_SCHEMA_VERSION,
    "updated_at": "2026-07-29T00:00:00Z",
    "overrides": {
        "64": {
            "replace": True,
            "targets": [{"kind": "owner", "url": "https://github.com/chutesai"}],
            "note": "Chutes",
        },
        "1": {
            "replace": False,
            "targets": [{"kind": "repository", "url": "https://github.com/alice/api"}],
        },
    },
}


def test_parse_registry_json_valid():
    registry = parse_registry_json(json.dumps(GOOD_REGISTRY))
    assert set(registry.overrides) == {1, 64}
    assert registry.overrides[64].replace is True
    assert registry.overrides[64].targets == (
        TargetOverride(kind="owner", url="https://github.com/chutesai"),
    )
    assert registry.overrides[1].replace is False


@pytest.mark.parametrize(
    "source",
    [
        {"overrides": {}},
        {"schema_version": "tao-git-crawl-registry-v1", "overrides": {}},
        {"schema_version": "tao-git-crawl-registry-v3", "overrides": {}},
        {"schema_version": DEFAULT_REGISTRY_SCHEMA_VERSION, "overrides": []},
    ],
)
def test_parse_registry_json_rejects_invalid_source_document(source):
    with pytest.raises(RegistryError):
        parse_registry_json(json.dumps(source))


def test_parse_registry_json_rejects_registered_at_override_field():
    source = json.loads(json.dumps(GOOD_REGISTRY))
    source["overrides"]["64"]["registered_at"] = 4531295
    with pytest.raises(RegistryError, match="registered_at.*not supported"):
        parse_registry_json(json.dumps(source))


def test_parse_registry_json_invalid_json():
    with pytest.raises(RegistryError, match="invalid JSON"):
        parse_registry_json("not json")


def test_parse_registry_json_bad_netuid_key():
    source = {
        "schema_version": DEFAULT_REGISTRY_SCHEMA_VERSION,
        "overrides": {"abc": {"targets": []}},
    }
    with pytest.raises(RegistryError, match="invalid registry netuid key"):
        parse_registry_json(json.dumps(source))


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"targets": [{"kind": "other", "url": "https://github.com/x"}]}, "target 0"),
        ({"targets": [{"kind": "owner"}]}, "target 0"),
        (
            {"targets": [{"kind": "owner", "url": "https://github.com/x", "confidence": "mega"}]},
            "confidence",
        ),
        ({"replace": "false", "targets": []}, "replace"),
    ],
)
def test_parse_registry_json_rejects_invalid_override_definition(override, message):
    source = {
        "schema_version": DEFAULT_REGISTRY_SCHEMA_VERSION,
        "overrides": {"64": override},
    }
    with pytest.raises(RegistryError, match=message):
        parse_registry_json(json.dumps(source))


def test_load_registry_from_path(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(GOOD_REGISTRY), encoding="utf-8")
    assert set(load_registry_from_path(path).overrides) == {1, 64}


def test_load_registry_from_path_missing():
    with pytest.raises(RegistryError, match="does not exist"):
        load_registry_from_path("/nonexistent/registry.json")


def test_load_registry_from_remote(monkeypatch):
    calls: list[str] = []

    def fake_fetch(url: str) -> str:
        calls.append(url)
        return json.dumps(GOOD_REGISTRY)

    monkeypatch.setattr("tao_git_crawl.registry._fetch_url_text", fake_fetch)
    registry = load_registry_from_remote("https://registry.example/overrides.json")
    assert set(registry.overrides) == {1, 64}
    assert calls == ["https://registry.example/overrides.json"]


def test_resolver_config_from_registry():
    config = resolver_config_from_registry(parse_registry_json(json.dumps(GOOD_REGISTRY)))
    assert config.default_repository_policy == "repository"
    assert set(config.subnet_overrides) == {1, 64}
    assert resolver_config_from_registry(None).subnet_overrides == {}


def test_merge_registries_later_override_wins():
    extension = parse_registry_json(
        json.dumps(
            {
                "schema_version": DEFAULT_REGISTRY_SCHEMA_VERSION,
                "overrides": {
                    "64": {
                        "replace": False,
                        "targets": [{"kind": "owner", "url": "https://github.com/chutesai-v2"}],
                    },
                    "99": {
                        "targets": [{"kind": "owner", "url": "https://github.com/acme"}],
                    },
                },
            }
        )
    )
    merged = merge_registries(parse_registry_json(json.dumps(GOOD_REGISTRY)), extension)
    assert merged.overrides[64].targets[0].url == "https://github.com/chutesai-v2"
    assert set(merged.overrides) == {1, 64, 99}


def test_built_in_registry_is_target_only():
    assert Path("registry/overrides.json").resolve() == DEFAULT_REGISTRY_REPO_PATH
    registry = load_built_in_registry()
    assert {4, 5, 23, 64} <= registry.overrides.keys()
    for raw_override in registry.raw["overrides"].values():
        assert "registered_at" not in raw_override
        assert all("confidence" not in target for target in raw_override["targets"])


def test_load_registry_local_override(tmp_path):
    custom = tmp_path / "custom.json"
    custom.write_text(
        json.dumps(
            {
                "schema_version": DEFAULT_REGISTRY_SCHEMA_VERSION,
                "overrides": {
                    "99": {"targets": [{"kind": "owner", "url": "https://github.com/acme"}]},
                    "64": {"targets": [{"kind": "owner", "url": "https://github.com/chutesai-v2"}]},
                },
            }
        ),
        encoding="utf-8",
    )
    registry = load_registry(registry_path=custom)
    assert 99 in registry.overrides
    assert registry.overrides[64].targets[0].url == "https://github.com/chutesai-v2"
