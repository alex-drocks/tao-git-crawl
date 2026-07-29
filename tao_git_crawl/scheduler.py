"""Long-running scheduler that periodically crawls all Bittensor subnets.

Usage::

    docker compose up --build

Environment variables (all have defaults):
    GITHUB_TOKEN                    GitHub personal access token (required)
    TAO_CRAWL_INTERVAL_SECONDS      Seconds between crawl runs (default: 86400)
    TAO_CRAWL_IDENTITY_CHECK_SECONDS
                                    Poll live subnet identities while idle (default: 900; 0 disables)
    TAO_CRAWL_NETWORK               Bittensor network preset (default: finney)
    TAO_CRAWL_OUTPUT_DIR            Output directory (default: /data/output)
    TAO_CRAWL_CACHE_DIR             Git mirror cache (default: /data/cache)
    TAO_CRAWL_INCREMENTAL           Use git-crawl incremental state (default: false)
    TAO_CRAWL_STATE_DB              SQLite state path when incremental mode is enabled
    TAO_CRAWL_WORKERS               Concurrent repo workers (default: 4)
    TAO_CRAWL_WINDOW_DAYS           Rolling score/activity window (default: 365)
    TAO_CRAWL_SINCE                 Fixed commit since date override (default: unset)
    TAO_CRAWL_COMMIT_CHANGES_FILTRATION_LEVEL
                                    all | non_binary | source_like (default: source_like)
    TAO_CRAWL_REGISTRY_URL          Optional remote JSON registry URL
    TAO_CRAWL_REGISTRY              Optional local JSON registry path
    TAO_CRAWL_CONFIG                Optional user Python config path
    TAO_CRAWL_LOG_DIR               Directory for per-run log files (default: /data/logs)
    TAO_CRAWL_RUN_ON_START          Run immediately on container start (default: true)
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from .identity_epochs import IDENTITY_RECONCILIATION_FILENAME
from .models import GITHUB_DISCOVERY_FIELDS, SubnetIdentityRecord
from .providers import DEFAULT_NETWORK_ENDPOINTS, SubstrateSubnetIdentityProvider

logger = logging.getLogger("tao-git-crawl.scheduler")
DEFAULT_CRAWL_WINDOW_DAYS = 365
DEFAULT_IDENTITY_CHECK_SECONDS = 900
MAX_IDENTITY_GUARD_RUNS = 3
type IdentityFingerprint = tuple[tuple[int, int | None, str, tuple[str, ...]], ...]


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    return int(value)


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name, "").strip().lower()
    if not val:
        return default
    return val in {"1", "true", "yes", "on"}


def _today_utc() -> date:
    return datetime.now(UTC).date()


def _crawl_since_from_env(today: date | None = None) -> str:
    explicit_since = os.environ.get("TAO_CRAWL_SINCE", "").strip()
    if explicit_since:
        return explicit_since

    window_days = _env_int("TAO_CRAWL_WINDOW_DAYS", DEFAULT_CRAWL_WINDOW_DAYS)
    if window_days <= 0:
        raise ValueError("TAO_CRAWL_WINDOW_DAYS must be greater than 0")
    anchor_date = today if today is not None else _today_utc()
    return (anchor_date - timedelta(days=window_days)).isoformat()


# ---------------------------------------------------------------------------
# CLI invocation
# ---------------------------------------------------------------------------

def build_crawl_command() -> list[str]:
    """Construct the tao-git-crawl crawl CLI from env vars."""
    cmd = [
        sys.executable, "-m", "tao_git_crawl.cli", "crawl",
        "--network", _env("TAO_CRAWL_NETWORK", "finney"),
        "--output-dir", _env("TAO_CRAWL_OUTPUT_DIR", "/data/output"),
        "--cache-dir", _env("TAO_CRAWL_CACHE_DIR", "/data/cache"),
        "--workers", _env("TAO_CRAWL_WORKERS", "4"),
        "--since", _crawl_since_from_env(),
        "--commit-changes-filtration-level", _env("TAO_CRAWL_COMMIT_CHANGES_FILTRATION_LEVEL", "source_like"),
    ]

    if _env_bool("TAO_CRAWL_INCREMENTAL", False):
        cmd += ["--state-db", _env("TAO_CRAWL_STATE_DB", "/data/state/db.sqlite")]

    registry_url = os.environ.get("TAO_CRAWL_REGISTRY_URL")
    if registry_url:
        cmd += ["--registry-url", registry_url]

    registry = os.environ.get("TAO_CRAWL_REGISTRY")
    if registry:
        cmd += ["--registry", registry]

    config = os.environ.get("TAO_CRAWL_CONFIG")
    if config:
        cmd += ["--config", config]

    return cmd


def run_crawl(log_dir: Path) -> int:
    """Execute one crawl run. Return exit code."""
    cmd = build_crawl_command()
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"crawl_{timestamp}.log"

    logger.info("Starting crawl run — log: %s", log_file)
    logger.info("Command: %s", " ".join(cmd))

    log_dir.mkdir(parents=True, exist_ok=True)
    with log_file.open("w", encoding="utf-8") as fh:
        fh.write(f"# crawl run started at {datetime.now(UTC).isoformat()}\n")
        fh.write(f"# command: {' '.join(cmd)}\n")
        fh.flush()
        result = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT)
        fh.write(f"# exit code: {result.returncode}\n")

    if result.returncode == 0:
        logger.info("Crawl run completed successfully — log: %s", log_file)
    else:
        logger.error("Crawl run failed with exit code %d — log: %s", result.returncode, log_file)

    return result.returncode


# ---------------------------------------------------------------------------
# Live identity change detection
# ---------------------------------------------------------------------------

def _identity_fingerprint(records: list[SubnetIdentityRecord]) -> IdentityFingerprint:
    """Capture the on-chain identity fields that can change subnet attribution."""
    return tuple(
        sorted(
            (
                record.netuid,
                record.registered_at,
                record.subnet_name,
                tuple(getattr(record, field) for field in GITHUB_DISCOVERY_FIELDS),
            )
            for record in records
        )
    )


def _fetch_live_identity_fingerprint() -> IdentityFingerprint:
    network = _env("TAO_CRAWL_NETWORK", "finney")
    try:
        endpoint = DEFAULT_NETWORK_ENDPOINTS[network]
    except KeyError as exc:
        raise ValueError(f"unsupported TAO_CRAWL_NETWORK {network!r}") from exc
    records = list(SubstrateSubnetIdentityProvider(endpoint=endpoint).fetch_active())
    return _identity_fingerprint(records)


def _fetch_live_identity_fingerprint_safely() -> IdentityFingerprint | None:
    try:
        return _fetch_live_identity_fingerprint()
    except Exception as exc:  # noqa: BLE001 - a transient RPC failure must not stop scheduled crawls
        logger.warning("Could not check live subnet identities: %s", exc)
        return None


def _wait_for_crawl_trigger(
    interval: int,
    identity_check_interval: int,
    baseline: IdentityFingerprint | None,
) -> tuple[bool, IdentityFingerprint | None]:
    """Wait for the normal deadline or return early when subnet identity changes."""
    deadline = time.monotonic() + interval
    latest = baseline
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False, latest

        wait_seconds = remaining
        if identity_check_interval > 0:
            wait_seconds = min(wait_seconds, identity_check_interval)
        time.sleep(wait_seconds)

        if identity_check_interval <= 0:
            continue
        current = _fetch_live_identity_fingerprint_safely()
        if current is None:
            continue
        if latest is not None and current != latest:
            return True, current
        latest = current


def _run_crawl_with_identity_guard(
    log_dir: Path,
    baseline: IdentityFingerprint | None,
) -> tuple[int, IdentityFingerprint | None]:
    """Run until attribution is stable, then fail closed after a bounded number of attempts."""
    before = baseline if baseline is not None else _fetch_live_identity_fingerprint_safely()
    exit_code = 1
    after = before
    for attempt in range(1, MAX_IDENTITY_GUARD_RUNS + 1):
        exit_code = run_crawl(log_dir)
        observed_after = _fetch_live_identity_fingerprint_safely()
        if observed_after is None or before is None or observed_after == before:
            return exit_code, observed_after if observed_after is not None else before
        after = observed_after
        if attempt < MAX_IDENTITY_GUARD_RUNS:
            logger.warning(
                "Subnet identity changed during crawl; starting immediate reconciliation crawl %d/%d",
                attempt + 1,
                MAX_IDENTITY_GUARD_RUNS,
            )
            before = observed_after
            continue

        reason = (
            "subnet identity changed during every bounded reconciliation crawl; "
            "score publication is disabled until a stable crawl succeeds"
        )
        logger.error(reason)
        _write_identity_guard_failure(reason)
        return 1, after
    return exit_code, after


def _write_identity_guard_failure(reason: str) -> None:
    output_dir = Path(_env("TAO_CRAWL_OUTPUT_DIR", "/data/output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    sentinel = output_dir / IDENTITY_RECONCILIATION_FILENAME
    temporary = sentinel.with_name(f".{sentinel.name}.tmp")
    temporary.write_text(
        json.dumps(
            {
                "status": "failed",
                "detected_at": datetime.now(UTC).isoformat(),
                "reason": reason,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(sentinel)


# ---------------------------------------------------------------------------
# Scheduler loop
# ---------------------------------------------------------------------------

def main() -> int:  # noqa: D401
    interval = _env_int("TAO_CRAWL_INTERVAL_SECONDS", 86400)
    identity_check_interval = _env_int(
        "TAO_CRAWL_IDENTITY_CHECK_SECONDS",
        DEFAULT_IDENTITY_CHECK_SECONDS,
    )
    log_dir = Path(_env("TAO_CRAWL_LOG_DIR", "/data/logs"))
    run_on_start = _env_bool("TAO_CRAWL_RUN_ON_START", True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )

    if not os.environ.get("GITHUB_TOKEN"):
        logger.error("GITHUB_TOKEN environment variable is required")
        return 1

    if interval <= 0:
        logger.error("TAO_CRAWL_INTERVAL_SECONDS must be greater than 0")
        return 1
    if identity_check_interval < 0:
        logger.error("TAO_CRAWL_IDENTITY_CHECK_SECONDS must be 0 or greater")
        return 1

    logger.info(
        "tao-git-crawl scheduler starting — interval=%ds, identity_check_interval=%ds, run_on_start=%s",
        interval,
        identity_check_interval,
        run_on_start,
    )

    identity_fingerprint = (
        _fetch_live_identity_fingerprint_safely() if identity_check_interval > 0 else None
    )

    if run_on_start:
        if identity_check_interval > 0:
            _, identity_fingerprint = _run_crawl_with_identity_guard(log_dir, identity_fingerprint)
        else:
            run_crawl(log_dir)

    while True:
        next_run = datetime.now(UTC).timestamp() + interval
        logger.info("Next crawl scheduled by %s", datetime.fromtimestamp(next_run, tz=UTC).isoformat())
        identity_changed, observed_fingerprint = _wait_for_crawl_trigger(
            interval,
            identity_check_interval,
            identity_fingerprint,
        )
        if identity_changed:
            logger.warning("Live subnet identity changed; starting crawl before the normal interval")
        if identity_check_interval > 0:
            _, identity_fingerprint = _run_crawl_with_identity_guard(log_dir, observed_fingerprint)
        else:
            run_crawl(log_dir)


# ---------------------------------------------------------------------------
# Docker healthcheck
# ---------------------------------------------------------------------------

def healthcheck() -> None:
    """Lightweight check used by docker-compose healthcheck.

    Verifies the scheduler module is importable and the output directory is writable.
    """
    output_dir = Path(_env("TAO_CRAWL_OUTPUT_DIR", "/data/output"))
    if not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)
    test_file = output_dir / ".healthcheck"
    try:
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
    except OSError as exc:
        print(f"HEALTHCHECK FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
    print("HEALTHCHECK OK")


if __name__ == "__main__":
    raise SystemExit(main())
