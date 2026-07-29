from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from .models import GITHUB_DISCOVERY_FIELDS, SubnetIdentityRecord

IDENTITY_EPOCH_SCHEMA_VERSION = "tao-git-crawl-identity-epoch-v1"
IDENTITY_HISTORY_SCHEMA_VERSION = "tao-git-crawl-identity-history-v1"
IDENTITY_RECONCILIATION_FILENAME = "identity-reconciliation.json"
LIVE_AGGREGATE_FILES = (
    "crawl-report.json",
    "subnet-scores.json",
    "subnet-targets.json",
    "repository-manifest.json",
    "owner-targets.json",
    "unresolved.json",
)


@dataclass(frozen=True)
class IdentityEpoch:
    netuid: int
    epoch_id: str
    registered_at: int | None
    subnet_name: str
    attribution_fingerprint: str
    schema_version: str = IDENTITY_EPOCH_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class IdentityHistoryEvent:
    netuid: int
    previous_epoch_id: str
    current_epoch_id: str | None
    detected_at: str
    reason: str
    archive_dir: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def identity_epoch(record: SubnetIdentityRecord) -> IdentityEpoch:
    """Build the immutable crawl epoch for one subnet lifecycle."""
    fingerprint = attribution_identity_fingerprint(record)
    epoch_id = (
        f"registration-{record.registered_at}"
        if record.registered_at is not None
        else f"identity-{fingerprint[:16]}"
    )
    return IdentityEpoch(
        netuid=record.netuid,
        epoch_id=epoch_id,
        registered_at=record.registered_at,
        subnet_name=record.subnet_name,
        attribution_fingerprint=fingerprint,
    )


def attribution_identity_fingerprint(record: SubnetIdentityRecord) -> str:
    payload = {
        "netuid": record.netuid,
        "subnet_name": record.subnet_name,
        "github_discovery_fields": {
            field: getattr(record, field) for field in GITHUB_DISCOVERY_FIELDS
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def epoch_scoped_target(target_label: str, epoch_id: str | None) -> str:
    return f"{target_label}-{epoch_id}" if epoch_id else target_label


def reconcile_identity_epochs(
    records: list[SubnetIdentityRecord] | tuple[SubnetIdentityRecord, ...],
    output_dir: str | Path,
    *,
    full_snapshot: bool,
    now: datetime | None = None,
) -> list[IdentityHistoryEvent]:
    """Run epoch reconciliation while publishing a fail-closed API sentinel."""
    output_path = Path(output_dir)
    detected_at = (now or datetime.now(UTC)).astimezone(UTC)
    sentinel_path = output_path / IDENTITY_RECONCILIATION_FILENAME
    _write_json_atomic(
        sentinel_path,
        {
            "status": "in_progress",
            "started_at": detected_at.isoformat(),
        },
    )
    try:
        events = _reconcile_identity_epochs(
            records,
            output_path,
            full_snapshot=full_snapshot,
            detected_at=detected_at,
        )
    except Exception as exc:
        _write_json_atomic(
            sentinel_path,
            {
                "status": "failed",
                "started_at": detected_at.isoformat(),
                "reason": str(exc),
            },
        )
        raise
    sentinel_path.unlink()
    return events


def _reconcile_identity_epochs(
    records: list[SubnetIdentityRecord] | tuple[SubnetIdentityRecord, ...],
    output_dir: str | Path,
    *,
    full_snapshot: bool,
    detected_at: datetime,
) -> list[IdentityHistoryEvent]:
    """Quarantine output that belongs to a prior registration lifecycle.

    Current subnet output is intentionally never merged into a new epoch. On
    first adoption, unbound legacy output is also archived so it cannot be
    mistaken for the currently registered subnet.
    """
    output_path = Path(output_dir)
    missing_lifecycle_netuids = sorted(
        record.netuid for record in records if record.registered_at is None
    )
    if missing_lifecycle_netuids:
        missing = ", ".join(str(netuid) for netuid in missing_lifecycle_netuids)
        raise ValueError(
            "crawl identity snapshot is missing NetworkRegisteredAt for subnet(s) "
            f"{missing}; refusing to reconcile lifecycle-unbound output"
        )
    subnets_path = output_path / "subnets"
    current_epochs = {record.netuid: identity_epoch(record) for record in records}
    events: list[IdentityHistoryEvent] = []

    for netuid, current in sorted(current_epochs.items()):
        subnet_dir = subnets_path / str(netuid)
        previous = _read_epoch_marker(subnet_dir / "identity-epoch.json")
        if subnet_dir.exists() and previous is None:
            events.append(
                _archive_subnet_dir(
                    output_path,
                    subnet_dir,
                    netuid=netuid,
                    previous_epoch_id="legacy-unbound",
                    current_epoch_id=current.epoch_id,
                    detected_at=detected_at,
                    reason="legacy output had no registration epoch",
                )
            )
        elif previous is not None and (
            previous.netuid != netuid
            or previous.epoch_id != current.epoch_id
            or previous.registered_at != current.registered_at
        ):
            events.append(
                _archive_subnet_dir(
                    output_path,
                    subnet_dir,
                    netuid=netuid,
                    previous_epoch_id=previous.epoch_id,
                    current_epoch_id=current.epoch_id,
                    detected_at=detected_at,
                    reason="subnet registration epoch changed",
                )
            )
        _write_json_atomic(subnet_dir / "identity-epoch.json", current.to_dict())

    if full_snapshot and subnets_path.exists():
        for subnet_dir in sorted(subnets_path.iterdir()):
            if not subnet_dir.is_dir() or not subnet_dir.name.isdigit():
                continue
            netuid = int(subnet_dir.name)
            if netuid in current_epochs:
                continue
            previous = _read_epoch_marker(subnet_dir / "identity-epoch.json")
            events.append(
                _archive_subnet_dir(
                    output_path,
                    subnet_dir,
                    netuid=netuid,
                    previous_epoch_id=previous.epoch_id if previous else "legacy-unbound",
                    current_epoch_id=None,
                    detected_at=detected_at,
                    reason="netuid is no longer an active subnet",
                )
            )

    if events:
        _invalidate_live_aggregate_files(output_path)
        _append_history_events(output_path, events)
    return events


def _archive_subnet_dir(
    output_path: Path,
    subnet_dir: Path,
    *,
    netuid: int,
    previous_epoch_id: str,
    current_epoch_id: str | None,
    detected_at: datetime,
    reason: str,
) -> IdentityHistoryEvent:
    timestamp = detected_at.strftime("%Y%m%dT%H%M%SZ")
    safe_epoch = _safe_path_segment(previous_epoch_id)
    archive_parent = output_path / "subnet-history" / str(netuid)
    archive_parent.mkdir(parents=True, exist_ok=True)
    archive_dir = archive_parent / f"{safe_epoch}--ended-{timestamp}"
    suffix = 2
    while archive_dir.exists():
        archive_dir = archive_parent / f"{safe_epoch}--ended-{timestamp}-{suffix}"
        suffix += 1
    shutil.move(str(subnet_dir), str(archive_dir))
    return IdentityHistoryEvent(
        netuid=netuid,
        previous_epoch_id=previous_epoch_id,
        current_epoch_id=current_epoch_id,
        detected_at=detected_at.isoformat(),
        reason=reason,
        archive_dir=str(archive_dir.relative_to(output_path)),
    )


def _read_epoch_marker(path: Path) -> IdentityEpoch | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        if payload.get("schema_version") != IDENTITY_EPOCH_SCHEMA_VERSION:
            return None
        return IdentityEpoch(
            netuid=int(payload["netuid"]),
            epoch_id=str(payload["epoch_id"]),
            registered_at=(
                int(payload["registered_at"])
                if payload.get("registered_at") is not None
                else None
            ),
            subnet_name=str(payload.get("subnet_name", "")),
            attribution_fingerprint=str(payload["attribution_fingerprint"]),
        )
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
        return None


def _append_history_events(output_path: Path, events: list[IdentityHistoryEvent]) -> None:
    history_path = output_path / "identity-history.json"
    existing: list[object] = []
    if history_path.exists():
        try:
            payload = json.loads(history_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("events"), list):
                existing = payload["events"]
        except (OSError, json.JSONDecodeError):
            existing = []
    _write_json_atomic(
        history_path,
        {
            "schema_version": IDENTITY_HISTORY_SCHEMA_VERSION,
            "events": [*existing, *(event.to_dict() for event in events)],
        },
    )


def _invalidate_live_aggregate_files(output_path: Path) -> None:
    for name in LIVE_AGGREGATE_FILES:
        path = output_path / name
        if path.is_file():
            path.unlink()


def _safe_path_segment(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-.")
    return normalized[:80] or "unknown"


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
