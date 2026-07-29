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
            {
                "netuid": 64,
                "registered_at": 4531295,
                "subnet_identity": {"subnet_name": "Chutes", "github_repo": "chutesai/api"},
            },
            {"netuid": 3, "identity": {"description": "https://github.com/opentensor/subtensor"}},
        ]
    }
    path = tmp_path / "subnets.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    records = list(JsonSubnetIdentityProvider(path).fetch())

    assert [(record.netuid, record.registered_at, record.subnet_name, record.github_repo) for record in records] == [
        (64, 4531295, "Chutes", "chutesai/api"),
        (3, None, "", ""),
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
            if storage_function == "NetworkRegisteredAt":
                return ScaleValue(1000 + params[0])
            return ScaleValue({"github_repo": b"opentensor/subtensor"})

    substrate = FakeSubstrate()
    provider = SubstrateSubnetIdentityProvider(endpoint="wss://example.invalid", substrate=substrate)

    records = list(provider.fetch(netuids=[1, 2]))

    assert [(record.netuid, record.registered_at, record.github_repo) for record in records] == [
        (1, 1001, "opentensor/subtensor"),
        (2, 1002, "opentensor/subtensor"),
    ]
    assert substrate.calls == [
        ("SubtensorModule", "SubnetIdentitiesV3", [1]),
        ("SubtensorModule", "NetworkRegisteredAt", [1]),
        ("SubtensorModule", "SubnetIdentitiesV3", [2]),
        ("SubtensorModule", "NetworkRegisteredAt", [2]),
    ]


def test_substrate_provider_skips_requested_root_network_netuid_zero():
    class FakeSubstrate:
        def __init__(self):
            self.calls = []

        def query(self, module, storage_function, params):
            self.calls.append((module, storage_function, params))
            if storage_function == "NetworkRegisteredAt":
                return ScaleValue(1000 + params[0])
            return ScaleValue({"github_repo": b"opentensor/subtensor"})

    substrate = FakeSubstrate()
    provider = SubstrateSubnetIdentityProvider(endpoint="wss://example.invalid", substrate=substrate)

    records = list(provider.fetch(netuids=[0, 1, 129]))

    assert [(record.netuid, record.github_repo) for record in records] == [(1, "opentensor/subtensor")]
    assert substrate.calls == [
        ("SubtensorModule", "SubnetIdentitiesV3", [1]),
        ("SubtensorModule", "NetworkRegisteredAt", [1]),
    ]


def test_substrate_provider_skips_root_network_from_discovered_netuids():
    class FakeSubstrate:
        def query_map(self, module, storage_function):
            if storage_function == "NetworksAdded":
                return [
                    (ScaleValue(0), ScaleValue(True)),
                    (ScaleValue(1), ScaleValue(True)),
                    (ScaleValue(2), ScaleValue(True)),
                    (ScaleValue(129), ScaleValue(True)),
                ]
            if storage_function == "SubnetIdentitiesV3":
                return [
                    (ScaleValue(netuid), ScaleValue({"github_repo": f"owner/repo-{netuid}".encode()}))
                    for netuid in (0, 1, 2, 129)
                ]
            if storage_function == "NetworkRegisteredAt":
                return [
                    (ScaleValue(netuid), ScaleValue(1000 + netuid))
                    for netuid in (0, 1, 2, 129)
                ]
            raise AssertionError(f"unexpected query_map {module}.{storage_function}")

        def query(self, *args, **kwargs):
            raise AssertionError("full crawl discovery must not issue per-netuid queries")

    substrate = FakeSubstrate()
    provider = SubstrateSubnetIdentityProvider(endpoint="wss://example.invalid", substrate=substrate)

    records = list(provider.fetch())

    assert [(record.netuid, record.github_repo) for record in records] == [
        (1, "owner/repo-1"),
        (2, "owner/repo-2"),
    ]


def test_substrate_provider_fetches_populated_identity_map_without_per_netuid_queries():
    class FakeSubstrate:
        def query_map(self, module, storage_function):
            assert (module, storage_function) == ("SubtensorModule", "SubnetIdentitiesV3")
            return [
                (ScaleValue(2), ScaleValue({"github_repo": b"owner/repo-2"})),
                (ScaleValue(0), ScaleValue({"github_repo": b"root/repo"})),
                (ScaleValue(1), ScaleValue({"github_repo": b"owner/repo-1"})),
                (ScaleValue(129), ScaleValue({"github_repo": b"past/repo"})),
            ]

        def query(self, *args, **kwargs):
            raise AssertionError("identity-map polling must not issue per-netuid queries")

    provider = SubstrateSubnetIdentityProvider(
        endpoint="wss://example.invalid",
        substrate=FakeSubstrate(),
    )

    records = list(provider.fetch_populated())

    assert [(record.netuid, record.github_repo) for record in records] == [
        (1, "owner/repo-1"),
        (2, "owner/repo-2"),
    ]


def test_substrate_provider_fetches_active_subnets_with_registration_epochs_without_per_netuid_queries():
    class FakeSubstrate:
        def query_map(self, module, storage_function):
            assert module == "SubtensorModule"
            if storage_function == "NetworksAdded":
                return [
                    (ScaleValue(0), ScaleValue(True)),
                    (ScaleValue(1), ScaleValue(True)),
                    (ScaleValue(2), ScaleValue(True)),
                ]
            if storage_function == "SubnetIdentitiesV3":
                return [(ScaleValue(1), ScaleValue({"github_repo": b"owner/repo-1"}))]
            if storage_function == "NetworkRegisteredAt":
                return [
                    (ScaleValue(1), ScaleValue(5001)),
                    (ScaleValue(2), ScaleValue(5002)),
                ]
            raise AssertionError(f"unexpected query_map {module}.{storage_function}")

        def query(self, *args, **kwargs):
            raise AssertionError("active identity polling must not issue per-netuid queries")

    provider = SubstrateSubnetIdentityProvider(
        endpoint="wss://example.invalid",
        substrate=FakeSubstrate(),
    )

    records = list(provider.fetch_active())

    assert [(record.netuid, record.registered_at, record.github_repo) for record in records] == [
        (1, 5001, "owner/repo-1"),
        (2, 5002, ""),
    ]
