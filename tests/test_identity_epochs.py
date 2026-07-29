from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from tao_git_crawl.identity_epochs import (
    epoch_scoped_target,
    identity_epoch,
    reconcile_identity_epochs,
)
from tao_git_crawl.models import SubnetIdentityRecord


def _record(*, registered_at: int, name: str = "Subnet") -> SubnetIdentityRecord:
    return SubnetIdentityRecord(
        netuid=80,
        registered_at=registered_at,
        subnet_name=name,
        github_repo=f"https://github.com/example/subnet-{registered_at}",
    )


def test_registration_block_is_the_epoch_and_scopes_incremental_target():
    epoch = identity_epoch(_record(registered_at=7000000))

    assert epoch.epoch_id == "registration-7000000"
    assert epoch_scoped_target("bittensor-subnet-80", epoch.epoch_id) == (
        "bittensor-subnet-80-registration-7000000"
    )


def test_recycled_netuid_archives_previous_output_and_invalidates_live_aggregates(tmp_path):
    output_dir = tmp_path / "output"
    old = _record(registered_at=6000000, name="Old subnet")
    new = _record(registered_at=7000000, name="Replacement subnet")
    detected_at = datetime(2026, 7, 29, 20, 30, tzinfo=UTC)

    assert reconcile_identity_epochs([old], output_dir, full_snapshot=True, now=detected_at) == []
    subnet_dir = output_dir / "subnets" / "80"
    crawl_dir = subnet_dir / "crawl"
    crawl_dir.mkdir()
    (crawl_dir / "commits.jsonl").write_text('{"old":true}\n', encoding="utf-8")
    (subnet_dir / "score.json").write_text('{"score":100}\n', encoding="utf-8")
    for name in ("crawl-report.json", "subnet-scores.json", "subnet-targets.json"):
        (output_dir / name).write_text("{}\n", encoding="utf-8")

    events = reconcile_identity_epochs([new], output_dir, full_snapshot=True, now=detected_at)

    assert len(events) == 1
    assert events[0].previous_epoch_id == "registration-6000000"
    assert events[0].current_epoch_id == "registration-7000000"
    assert events[0].reason == "subnet registration epoch changed"
    archive_dir = output_dir / events[0].archive_dir
    assert (archive_dir / "crawl" / "commits.jsonl").exists()
    assert (archive_dir / "score.json").exists()
    assert not (subnet_dir / "crawl").exists()
    assert not (subnet_dir / "score.json").exists()
    current_marker = json.loads((subnet_dir / "identity-epoch.json").read_text(encoding="utf-8"))
    assert current_marker["registered_at"] == 7000000
    assert current_marker["epoch_id"] == "registration-7000000"
    assert not (output_dir / "crawl-report.json").exists()
    assert not (output_dir / "subnet-scores.json").exists()
    assert not (output_dir / "subnet-targets.json").exists()
    history = json.loads((output_dir / "identity-history.json").read_text(encoding="utf-8"))
    assert history["events"] == [events[0].to_dict()]


def test_first_epoch_reconciliation_quarantines_unbound_legacy_output(tmp_path):
    output_dir = tmp_path / "output"
    legacy_crawl = output_dir / "subnets" / "80" / "crawl"
    legacy_crawl.mkdir(parents=True)
    (legacy_crawl / "summary.json").write_text('{"commits":4388}\n', encoding="utf-8")

    [event] = reconcile_identity_epochs(
        [_record(registered_at=7000000)],
        output_dir,
        full_snapshot=True,
        now=datetime(2026, 7, 29, tzinfo=UTC),
    )

    assert event.previous_epoch_id == "legacy-unbound"
    assert event.reason == "legacy output had no registration epoch"
    assert (output_dir / event.archive_dir / "crawl" / "summary.json").exists()
    assert not (output_dir / "subnets" / "80" / "crawl").exists()


def test_full_snapshot_archives_deregistered_subnet_but_partial_snapshot_does_not(tmp_path):
    output_dir = tmp_path / "output"
    record = _record(registered_at=7000000)
    reconcile_identity_epochs([record], output_dir, full_snapshot=True)
    crawl_dir = output_dir / "subnets" / "80" / "crawl"
    crawl_dir.mkdir()

    assert reconcile_identity_epochs([], output_dir, full_snapshot=False) == []
    assert crawl_dir.exists()

    [event] = reconcile_identity_epochs([], output_dir, full_snapshot=True)

    assert event.current_epoch_id is None
    assert event.reason == "netuid is no longer an active subnet"
    assert not (output_dir / "subnets" / "80").exists()


def test_failed_reconciliation_leaves_fail_closed_sentinel(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    reconcile_identity_epochs([_record(registered_at=6000000)], output_dir, full_snapshot=True)
    (output_dir / "subnets" / "80" / "crawl").mkdir()

    def fail_move(*args, **kwargs):
        raise OSError("archive unavailable")

    monkeypatch.setattr("tao_git_crawl.identity_epochs.shutil.move", fail_move)

    with pytest.raises(OSError, match="archive unavailable"):
        reconcile_identity_epochs(
            [_record(registered_at=7000000)],
            output_dir,
            full_snapshot=True,
        )

    sentinel = json.loads(
        (output_dir / "identity-reconciliation.json").read_text(encoding="utf-8")
    )
    assert sentinel["status"] == "failed"
    assert sentinel["reason"] == "archive unavailable"
