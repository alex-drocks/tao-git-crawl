"""Long-running scheduler that periodically crawls all Bittensor subnets.

Usage::

    docker compose up --build

Environment variables (all have defaults):
    GITHUB_TOKEN                    GitHub personal access token (required)
    TAO_CRAWL_INTERVAL_SECONDS      Seconds between crawl runs (default: 86400)
    TAO_CRAWL_NETWORK               Bittensor network preset (default: finney)
    TAO_CRAWL_OUTPUT_DIR            Output directory (default: /data/output)
    TAO_CRAWL_CACHE_DIR             Git mirror cache (default: /data/cache)
    TAO_CRAWL_STATE_DB              SQLite state path (default: /data/state/db.sqlite)
    TAO_CRAWL_WORKERS               Concurrent repo workers (default: 4)
    TAO_CRAWL_SINCE                 Commit since date (default: 2025-01-01)
    TAO_CRAWL_COMMIT_CHANGES_FILTRATION_LEVEL
                                    all | non_binary | source_like (default: source_like)
    TAO_CRAWL_REGISTRY_URL          Optional remote JSON registry URL
    TAO_CRAWL_REGISTRY              Optional local JSON registry path
    TAO_CRAWL_CONFIG                Optional user Python config path
    TAO_CRAWL_LOG_DIR               Directory for per-run log files (default: /data/logs)
    TAO_CRAWL_RUN_ON_START          Run immediately on container start (default: true)
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("tao-git-crawl.scheduler")


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name, "").strip().lower()
    if not val:
        return default
    return val in {"1", "true", "yes", "on"}


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
        "--state-db", _env("TAO_CRAWL_STATE_DB", "/data/state/db.sqlite"),
        "--workers", _env("TAO_CRAWL_WORKERS", "4"),
        "--since", _env("TAO_CRAWL_SINCE", "2025-01-01"),
        "--commit-changes-filtration-level", _env("TAO_CRAWL_COMMIT_CHANGES_FILTRATION_LEVEL", "source_like"),
    ]

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
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"crawl_{timestamp}.log"

    logger.info("Starting crawl run — log: %s", log_file)
    logger.info("Command: %s", " ".join(cmd))

    log_dir.mkdir(parents=True, exist_ok=True)
    with log_file.open("w", encoding="utf-8") as fh:
        fh.write(f"# crawl run started at {datetime.now(timezone.utc).isoformat()}\n")
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
# Scheduler loop
# ---------------------------------------------------------------------------

def main() -> int:  # noqa: D401
    interval = _env_int("TAO_CRAWL_INTERVAL_SECONDS", 86400)
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

    logger.info("tao-git-crawl scheduler starting — interval=%ds, run_on_start=%s", interval, run_on_start)

    if run_on_start:
        run_crawl(log_dir)

    while True:
        next_run = datetime.now(timezone.utc).timestamp() + interval
        logger.info("Next crawl scheduled at %s", datetime.fromtimestamp(next_run, tz=timezone.utc).isoformat())
        time.sleep(interval)

        # Sleep can wake up early on signals; realign to interval boundary.
        now = datetime.now(timezone.utc).timestamp()
        remaining = next_run - now
        if remaining > 0:
            time.sleep(max(0, remaining))

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
