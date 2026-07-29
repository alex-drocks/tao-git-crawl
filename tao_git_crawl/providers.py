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
ROOT_NETUID = 0
MIN_REGULAR_SUBNET_NETUID = 1
MAX_REGULAR_SUBNET_NETUID = 128


class SubnetIdentityProvider(Protocol):
    def fetch(self, netuids: Iterable[int] | None = None) -> Iterable[SubnetIdentityRecord]: ...


class JsonSubnetIdentityProvider:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def fetch(self, netuids: Iterable[int] | None = None) -> Iterable[SubnetIdentityRecord]:
        wanted = _regular_subnet_netuid_set(netuids) if netuids is not None else None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        for record in records_from_json_payload(payload):
            if not is_regular_subnet_netuid(record.netuid):
                continue
            if wanted is not None and record.netuid not in wanted:
                continue
            yield record


class SubstrateSubnetIdentityProvider:
    """Read active subnet identity and lifecycle blocks from SubtensorModule."""

    def __init__(self, *, endpoint: str = DEFAULT_ENDPOINT, substrate: object | None = None):
        self.endpoint = endpoint
        self._substrate = substrate

    def fetch(self, netuids: Iterable[int] | None = None) -> Iterable[SubnetIdentityRecord]:
        if netuids is None:
            yield from self.fetch_active()
            return
        substrate = self._substrate or self._connect()
        for netuid in netuids:
            regular_netuid = _normalize_regular_subnet_netuid(netuid)
            if regular_netuid is None:
                continue
            raw_identity = _query_subnet_identity(substrate, regular_netuid)
            registered_at = _positive_int(
                _query_network_registered_at(substrate, regular_netuid)
            )
            if registered_at is None:
                raise RuntimeError(
                    "NetworkRegisteredAt returned no lifecycle block for active subnet "
                    f"{regular_netuid}; refusing an unbound identity snapshot"
                )
            yield decode_substrate_identity(
                regular_netuid,
                raw_identity,
                registered_at=registered_at,
            )

    def fetch_populated(self) -> Iterable[SubnetIdentityRecord]:
        """Read populated identity-map rows without querying every active netuid separately."""
        substrate = self._substrate or self._connect()
        records: list[SubnetIdentityRecord] = []
        for key, value in substrate.query_map(module="SubtensorModule", storage_function="SubnetIdentitiesV3"):
            netuid = _unwrap_netuid_key(key)
            if not is_regular_subnet_netuid(netuid):
                continue
            records.append(decode_substrate_identity(netuid, value))
        yield from sorted(records, key=lambda record: record.netuid)

    def fetch_active(self) -> Iterable[SubnetIdentityRecord]:
        """Read every active subnet and its authoritative registration block."""
        substrate = self._substrate or self._connect()
        active_netuids = _query_network_netuids(substrate)
        identities = _query_subnet_identity_map(substrate)
        registrations = _query_network_registration_map(substrate)
        missing_registrations = sorted(set(active_netuids) - registrations.keys())
        if missing_registrations:
            missing = ", ".join(str(netuid) for netuid in missing_registrations)
            raise RuntimeError(
                "NetworkRegisteredAt omitted lifecycle blocks for active subnet(s) "
                f"{missing}; refusing an unbound identity snapshot"
            )
        for netuid in active_netuids:
            yield decode_substrate_identity(
                netuid,
                identities.get(netuid),
                registered_at=registrations.get(netuid),
            )

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
        records.append(SubnetIdentityRecord.from_mapping(_parse_json_netuid(netuid), identity))
    return records


def is_regular_subnet_netuid(netuid: int) -> bool:
    return netuid != ROOT_NETUID and MIN_REGULAR_SUBNET_NETUID <= netuid <= MAX_REGULAR_SUBNET_NETUID


def _parse_json_netuid(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ValueError("Each subnet record netuid must be an integer")
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError("Each subnet record netuid must be an integer") from exc


def _normalize_regular_subnet_netuid(netuid: object) -> int | None:
    parsed = int(netuid)
    return parsed if is_regular_subnet_netuid(parsed) else None


def _regular_subnet_netuid_set(netuids: Iterable[int]) -> set[int]:
    regular_netuids: set[int] = set()
    for netuid in netuids:
        regular_netuid = _normalize_regular_subnet_netuid(netuid)
        if regular_netuid is not None:
            regular_netuids.add(regular_netuid)
    return regular_netuids


def decode_substrate_identity(
    netuid: int,
    raw_value: object,
    *,
    registered_at: object = None,
) -> SubnetIdentityRecord:
    value = _unwrap_scale_value(raw_value)
    if value is None:
        return SubnetIdentityRecord(netuid=netuid, registered_at=_positive_int(registered_at))
    if not isinstance(value, dict):
        return SubnetIdentityRecord(netuid=netuid, registered_at=_positive_int(registered_at))
    decoded = {field: _decode_text(_unwrap_scale_value(value.get(field))) for field in IDENTITY_FIELDS}
    return SubnetIdentityRecord(
        netuid=netuid,
        registered_at=_positive_int(registered_at),
        **decoded,
    )


def _identity_mapping_from_row(row: dict[str, object]) -> dict[str, object]:
    identity: dict[str, object] = {field: row[field] for field in IDENTITY_FIELDS if field in row}
    for field in ("registered_at", "registration_block"):
        if field in row:
            identity[field] = row[field]
    nested = row.get("subnet_identity", row.get("identity"))
    if isinstance(nested, dict):
        identity.update(nested)
    return identity


def _query_subnet_identity(substrate: object, netuid: int) -> object:
    return substrate.query(module="SubtensorModule", storage_function="SubnetIdentitiesV3", params=[netuid])


def _query_network_registered_at(substrate: object, netuid: int) -> object:
    return substrate.query(module="SubtensorModule", storage_function="NetworkRegisteredAt", params=[netuid])


def _query_network_netuids(substrate: object) -> list[int]:
    rows = substrate.query_map(module="SubtensorModule", storage_function="NetworksAdded")
    netuids: list[int] = []
    for key, value in rows:
        added = _unwrap_scale_value(value)
        if added is False:
            continue
        netuid = _unwrap_netuid_key(key)
        if is_regular_subnet_netuid(netuid):
            netuids.append(netuid)
    return sorted(set(netuids))


def _query_subnet_identity_map(substrate: object) -> dict[int, object]:
    return {
        netuid: value
        for key, value in substrate.query_map(
            module="SubtensorModule",
            storage_function="SubnetIdentitiesV3",
        )
        if is_regular_subnet_netuid(netuid := _unwrap_netuid_key(key))
    }


def _query_network_registration_map(substrate: object) -> dict[int, int]:
    registrations: dict[int, int] = {}
    for key, value in substrate.query_map(
        module="SubtensorModule",
        storage_function="NetworkRegisteredAt",
    ):
        netuid = _unwrap_netuid_key(key)
        registered_at = _positive_int(value)
        if is_regular_subnet_netuid(netuid) and registered_at is not None:
            registrations[netuid] = registered_at
    return registrations


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


def _positive_int(value: object) -> int | None:
    unwrapped = _unwrap_scale_value(value)
    if unwrapped is None or isinstance(unwrapped, bool):
        return None
    if isinstance(unwrapped, int):
        parsed = unwrapped
    elif isinstance(unwrapped, str) and unwrapped.strip().isdigit():
        parsed = int(unwrapped.strip())
    else:
        return None
    return parsed if parsed > 0 else None
