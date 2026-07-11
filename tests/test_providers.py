import json

import pytest

from tao_git_crawl.providers import (
    JsonSubnetIdentityProvider,
    SubstrateSubnetIdentityProvider,
    decode_substrate_identity,
)


class ScaleValue:
    def __init__(self, value):
        self.value = value


def test_json_provider_accepts_nested_subnet_identity_records(tmp_path):
    payload = {
        "subnets": [
            {"netuid": 64, "subnet_identity": {"subnet_name": "Chutes", "github_repo": "chutesai/api"}},
            {"netuid": 3, "identity": {"description": "https://github.com/opentensor/subtensor"}},
        ]
    }
    path = tmp_path / "subnets.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    records = list(JsonSubnetIdentityProvider(path).fetch())

    assert [(record.netuid, record.subnet_name, record.github_repo) for record in records] == [
        (64, "Chutes", "chutesai/api"),
        (3, "", ""),
    ]
    assert records[1].description == "https://github.com/opentensor/subtensor"


def test_json_provider_skips_root_network_netuid_zero(tmp_path):
    payload = {
        "subnets": [
            {"netuid": 0, "subnet_identity": {"subnet_name": "Root", "github_repo": "opentensor/subtensor"}},
            {"netuid": 1, "subnet_identity": {"subnet_name": "Regular", "github_repo": "opentensor/subtensor"}},
            {"netuid": 129, "subnet_identity": {"subnet_name": "Past slots", "github_repo": "opentensor/subtensor"}},
        ]
    }
    path = tmp_path / "subnets.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    records = list(JsonSubnetIdentityProvider(path).fetch())

    assert [(record.netuid, record.subnet_name) for record in records] == [(1, "Regular")]
    assert list(JsonSubnetIdentityProvider(path).fetch(netuids=[0])) == []
    assert list(JsonSubnetIdentityProvider(path).fetch(netuids=[129])) == []


@pytest.mark.parametrize("netuid", [True, False, 1.5, "1.5", ""])
def test_json_provider_rejects_non_integer_netuids(tmp_path, netuid):
    path = tmp_path / "subnets.json"
    path.write_text(json.dumps({"subnets": [{"netuid": netuid}]}), encoding="utf-8")

    with pytest.raises(ValueError, match="netuid must be an integer"):
        list(JsonSubnetIdentityProvider(path).fetch())


def test_decode_substrate_identity_decodes_scale_values_and_bytes():
    raw = ScaleValue(
        {
            "subnet_name": b"Subnet \xf0\x9f\x9a\x80",
            "github_repo": b"chutesai/api",
            "description": ScaleValue(b"A subnet"),
        }
    )

    decoded = decode_substrate_identity(64, raw)

    assert decoded.netuid == 64
    assert decoded.subnet_name == "Subnet 🚀"
    assert decoded.github_repo == "chutesai/api"
    assert decoded.description == "A subnet"


def test_substrate_provider_queries_canonical_subnet_identity_storage_for_requested_netuids():
    class FakeSubstrate:
        def __init__(self):
            self.calls = []

        def query(self, module, storage_function, params):
            self.calls.append((module, storage_function, params))
            return ScaleValue({"github_repo": b"opentensor/subtensor"})

    substrate = FakeSubstrate()
    provider = SubstrateSubnetIdentityProvider(endpoint="wss://example.invalid", substrate=substrate)

    records = list(provider.fetch(netuids=[1, 2]))

    assert [(record.netuid, record.github_repo) for record in records] == [
        (1, "opentensor/subtensor"),
        (2, "opentensor/subtensor"),
    ]
    assert substrate.calls == [
        ("SubtensorModule", "SubnetIdentitiesV3", [1]),
        ("SubtensorModule", "SubnetIdentitiesV3", [2]),
    ]


def test_substrate_provider_skips_requested_root_network_netuid_zero():
    class FakeSubstrate:
        def __init__(self):
            self.calls = []

        def query(self, module, storage_function, params):
            self.calls.append((module, storage_function, params))
            return ScaleValue({"github_repo": b"opentensor/subtensor"})

    substrate = FakeSubstrate()
    provider = SubstrateSubnetIdentityProvider(endpoint="wss://example.invalid", substrate=substrate)

    records = list(provider.fetch(netuids=[0, 1, 129]))

    assert [(record.netuid, record.github_repo) for record in records] == [(1, "opentensor/subtensor")]
    assert substrate.calls == [("SubtensorModule", "SubnetIdentitiesV3", [1])]


def test_substrate_provider_skips_root_network_from_discovered_netuids():
    class FakeSubstrate:
        def __init__(self):
            self.identity_calls = []

        def query_map(self, module, storage_function):
            if storage_function == "NetworksAdded":
                return [
                    (ScaleValue(0), ScaleValue(True)),
                    (ScaleValue(1), ScaleValue(True)),
                    (ScaleValue(2), ScaleValue(True)),
                    (ScaleValue(129), ScaleValue(True)),
                ]
            raise AssertionError(f"unexpected query_map {module}.{storage_function}")

        def query(self, module, storage_function, params):
            self.identity_calls.append((module, storage_function, params))
            return ScaleValue({"github_repo": f"owner/repo-{params[0]}".encode()})

    substrate = FakeSubstrate()
    provider = SubstrateSubnetIdentityProvider(endpoint="wss://example.invalid", substrate=substrate)

    records = list(provider.fetch())

    assert [(record.netuid, record.github_repo) for record in records] == [
        (1, "owner/repo-1"),
        (2, "owner/repo-2"),
    ]
    assert substrate.identity_calls == [
        ("SubtensorModule", "SubnetIdentitiesV3", [1]),
        ("SubtensorModule", "SubnetIdentitiesV3", [2]),
    ]
