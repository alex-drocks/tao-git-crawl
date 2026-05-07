from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from .models import IDENTITY_FIELDS, SubnetIdentityRecord

DEFAULT_NETWORK_ENDPOINTS = {
    "finney": "wss://entrypoint-finney.opentensor.ai:443",
    "test": "wss://test.finney.opentensor.ai:443",
    "archive": "wss://archive.chain.opentensor.ai:443",
    "latent-lite": "wss://lite.sub.latent.to:443",
    "local": "ws://127.0.0.1:9944",
}
DEFAULT_NETWORK = "finney"
DEFAULT_ENDPOINT = DEFAULT_NETWORK_ENDPOINTS[DEFAULT_NETWORK]


class SubnetIdentityProvider(Protocol):
    def fetch(self, netuids: Iterable[int] | None = None) -> Iterable[SubnetIdentityRecord]: ...


class JsonSubnetIdentityProvider:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def fetch(self, netuids: Iterable[int] | None = None) -> Iterable[SubnetIdentityRecord]:
        wanted = {int(netuid) for netuid in netuids} if netuids is not None else None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        for record in records_from_json_payload(payload):
            if wanted is not None and record.netuid not in wanted:
                continue
            yield record


class SubstrateSubnetIdentityProvider:
    """Read subnet identity from SubtensorModule.SubnetIdentitiesV3."""

    def __init__(self, *, endpoint: str = DEFAULT_ENDPOINT, substrate: object | None = None):
        self.endpoint = endpoint
        self._substrate = substrate

    def fetch(self, netuids: Iterable[int] | None = None) -> Iterable[SubnetIdentityRecord]:
        substrate = self._substrate or self._connect()
        if netuids is not None:
            for netuid in netuids:
                yield decode_substrate_identity(int(netuid), _query_subnet_identity(substrate, int(netuid)))
            return

        discovered_netuids = list(_query_network_netuids(substrate))
        if discovered_netuids:
            for netuid in discovered_netuids:
                yield decode_substrate_identity(netuid, _query_subnet_identity(substrate, netuid))
            return

        for key, value in substrate.query_map(module="SubtensorModule", storage_function="SubnetIdentitiesV3"):
            yield decode_substrate_identity(_unwrap_netuid_key(key), value)

    def _connect(self):
        try:
            from substrateinterface import SubstrateInterface
        except ImportError as exc:  # pragma: no cover - exercised by installed CLI users without optional extra
            raise RuntimeError("Install tao-git-crawl[chain] to query live Bittensor chain endpoints") from exc
        return SubstrateInterface(url=self.endpoint)


def records_from_json_payload(payload: object) -> list[SubnetIdentityRecord]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("subnets"), list):
            rows = payload["subnets"]
        elif isinstance(payload.get("records"), list):
            rows = payload["records"]
        elif "netuid" in payload or "net_uid" in payload:
            rows = [payload]
        else:
            raise ValueError("JSON payload must contain a 'subnets' or 'records' array")
    else:
        raise ValueError("JSON payload must be an object or array")

    records: list[SubnetIdentityRecord] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Each subnet record must be a JSON object")
        netuid = row.get("netuid", row.get("net_uid"))
        if netuid is None:
            raise ValueError("Each subnet record must include netuid")
        identity = _identity_mapping_from_row(row)
        records.append(SubnetIdentityRecord.from_mapping(int(netuid), identity))
    return records


def decode_substrate_identity(netuid: int, raw_value: object) -> SubnetIdentityRecord:
    value = _unwrap_scale_value(raw_value)
    if value is None:
        return SubnetIdentityRecord(netuid=netuid)
    if not isinstance(value, dict):
        return SubnetIdentityRecord(netuid=netuid)
    decoded = {field: _decode_text(_unwrap_scale_value(value.get(field))) for field in IDENTITY_FIELDS}
    return SubnetIdentityRecord(netuid=netuid, **decoded)


def _identity_mapping_from_row(row: dict[str, object]) -> dict[str, object]:
    identity: dict[str, object] = {field: row[field] for field in IDENTITY_FIELDS if field in row}
    nested = row.get("subnet_identity", row.get("identity"))
    if isinstance(nested, dict):
        identity.update(nested)
    return identity


def _query_subnet_identity(substrate: object, netuid: int) -> object:
    return substrate.query(module="SubtensorModule", storage_function="SubnetIdentitiesV3", params=[netuid])


def _query_network_netuids(substrate: object) -> list[int]:
    try:
        rows = substrate.query_map(module="SubtensorModule", storage_function="NetworksAdded")
    except Exception:  # noqa: BLE001 - fallback to identity map for nodes/clients that do not expose query_map
        return []
    netuids: list[int] = []
    for key, value in rows:
        added = _unwrap_scale_value(value)
        if added is False:
            continue
        netuids.append(_unwrap_netuid_key(key))
    return sorted(set(netuids))


def _unwrap_netuid_key(key: object) -> int:
    value = _unwrap_scale_value(key)
    if isinstance(value, (list, tuple)) and value:
        value = _unwrap_scale_value(value[0])
    return int(value)


def _unwrap_scale_value(value: object) -> object:
    if hasattr(value, "value"):
        return value.value
    return value


def _decode_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    if isinstance(value, list) and all(isinstance(item, int) for item in value):
        return bytes(value).decode("utf-8", errors="replace").strip()
    return str(value).strip()
