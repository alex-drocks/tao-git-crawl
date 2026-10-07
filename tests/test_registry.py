from __future__ import annotations

import json
from pathlib import Path

import pytest

from tao_git_crawl.activity_filter import is_credited_change
from tao_git_crawl.models import CreditExclusion
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


def _registry_with_override(override: dict) -> str:
    return json.dumps({"schema_version": DEFAULT_REGISTRY_SCHEMA_VERSION, "overrides": {"23": override}})


def test_parse_registry_json_reads_reviewed_credit_exclusions():
    registry = parse_registry_json(
        _registry_with_override(
            {
                "replace": False,
                "targets": [],
                "exclusions": [
                    {"repo": "acme/app", "path": "/vendor-copy/", "reason": "vendored upstream"},
                    {"repo": "acme/app", "commit": "ABC1234DEF", "path": "lib/", "reason": "import commit"},
                ],
            }
        )
    )

    assert registry.overrides[23].exclusions == (
        CreditExclusion(repo="acme/app", reason="vendored upstream", path="vendor-copy/"),
        CreditExclusion(repo="acme/app", reason="import commit", path="lib/", commit="abc1234def"),
    )


@pytest.mark.parametrize(
    ("exclusion", "message"),
    [
        ({"repo": "acme/app", "path": "x/"}, "reason"),
        ({"repo": "acme", "path": "x/", "reason": "r"}, "owner/name"),
        ({"repo": "https://github.com/acme/app", "path": "x/", "reason": "r"}, "owner/name"),
        ({"repo": "acme/app", "commit": "not-a-sha", "reason": "r"}, "hex SHA"),
        ({"repo": "acme/app", "reason": "r"}, "'path', a 'commit', or both"),
        ({"repo": "acme/app", "path": "../x", "reason": "r"}, r"'\.\.'"),
        ({"repo": "acme/app", "path": "x/", "reason": "r", "confidence": "high"}, "unsupported keys"),
        ("acme/app:x/", "must be an object"),
    ],
)
def test_parse_registry_json_rejects_invalid_credit_exclusions(exclusion, message):
    with pytest.raises(RegistryError, match=message):
        parse_registry_json(_registry_with_override({"replace": False, "targets": [], "exclusions": [exclusion]}))


def test_parse_registry_json_rejects_exclusion_only_override_that_would_replace_targets():
    exclusion = {"repo": "acme/app", "path": "x/", "reason": "vendored"}
    with pytest.raises(RegistryError, match="replace to false"):
        parse_registry_json(_registry_with_override({"targets": [], "exclusions": [exclusion]}))


def test_built_in_registry_exclusions_are_reviewed_and_pinned():
    registry = load_built_in_registry()
    excluded = {netuid for netuid, override in registry.overrides.items() if override.exclusions}
    assert {2, 23, 62, 68, 91, 100, 118} <= excluded
    for override in registry.overrides.values():
        for exclusion in override.exclusions:
            assert exclusion.reason
            assert exclusion.commit is None or len(exclusion.commit) == 40
        if override.exclusions and not override.targets:
            assert override.replace is False


def test_parse_registry_json_preserves_reviewed_exclusion_exceptions():
    registry = parse_registry_json(
        _registry_with_override({"replace": False, "exclusions": [{
            "repo": "acme/app", "path": "/lib/", "reason": "import",
            "except_paths": ["/lib/adapter.py", "lib/local/"],
        }]})
    )
    assert registry.overrides[23].exclusions[0].except_paths == ("lib/adapter.py", "lib/local/")


@pytest.mark.parametrize("except_paths", ["lib/a.py", [""], ["../a.py"], ["other/a.py"], [123]])
def test_parse_registry_json_rejects_malformed_exclusion_exceptions(except_paths):
    with pytest.raises(RegistryError, match="except_paths"):
        parse_registry_json(_registry_with_override({"replace": False, "exclusions": [{
            "repo": "acme/app", "path": "lib/", "reason": "import", "except_paths": except_paths,
        }]}))


@pytest.mark.parametrize(
    ("netuid", "repo", "commit", "path", "credited"),
    [
        (68, "metanova-labs/nova", "89db91520f8cd0bde0f67ccc783252d3c2904c22",
         "boltzgen/src/boltzgen/boltzgen_wrapper.py", True),
        (68, "metanova-labs/nova", "89db91520f8cd0bde0f67ccc783252d3c2904c22",
         "boltzgen/src/boltzgen/data/const.py", False),
        (68, "metanova-labs/nova", "73c5bd5535e341762939b9036140260e756b8bf0",
         "external_tools/boltz/boltz_wrapper.py", True),
        (68, "metanova-labs/nova", "73c5bd5535e341762939b9036140260e756b8bf0",
         "external_tools/boltzgen/src/boltzgen/boltzgen_wrapper.py", True),
        (68, "metanova-labs/nova", "73c5bd5535e341762939b9036140260e756b8bf0",
         "external_tools/boltz/src/boltz/data/const.py", False),
        (100, "BaseIntelligence/agent-challenge", "2875ca832495b187d1db6cc19e072ab0d03fc247",
         "docker/canonical/live-task-cache/sanitize-git-repo/tests/test_outputs.py", False),
        (100, "BaseIntelligence/agent-challenge", "ebf20c6ae18fd1460b9ad4fc76815a8b7e3c0224",
         "docker/canonical/live-task-cache/sanitize-git-repo/tests/test_outputs.py", True),
        (118, "ditto-assistant/ditto-subnet", "d826138230154503c2e572262c33c46c12f154e5",
         ".agents/skills/impeccable/SKILL.md", False),
        (118, "ditto-assistant/ditto-subnet", "a" * 40, ".agents/skills/impeccable/SKILL.md", True),
    ],
)
def test_built_in_exclusions_preserve_local_adapters_and_later_maintenance(netuid, repo, commit, path, credited):
    exclusions = load_built_in_registry().overrides[netuid].exclusions
    assert is_credited_change({"repo": repo, "sha": commit, "path": path}, exclusions) is credited
