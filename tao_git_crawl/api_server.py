"""HTTP API server for querying tao-git-crawl resolution and crawl data.

Usage::

    # Install optional API dependencies
    pip install 'tao-git-crawl[api]'

    # Run directly
    python -m tao_git_crawl.api_server

    # Or via uvicorn
    uvicorn tao_git_crawl.api_server:app --host 0.0.0.0 --port 8000

Environment variables (all have defaults):
    TAO_API_OUTPUT_DIR      Root directory where crawl outputs live (default: /data/output)
    TAO_API_HOST            Bind host (default: 0.0.0.0)
    TAO_API_PORT            Bind port (default: 8000)
    TAO_API_LOG_LEVEL       uvicorn log level (default: info)
    TAO_API_CORS_ORIGINS    Comma-separated allowed CORS origins (default: *)
    TAO_API_READ_TIMEOUT    Seconds before request times out (default: 30)
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from .registry import DEFAULT_REGISTRY

app = FastAPI(
    title="tao-git-crawl API",
    description="Read-only API for Bittensor subnet GitHub crawl metrics.",
    version="0.1.0",
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_OUTPUT_DIR = Path(os.environ.get("TAO_API_OUTPUT_DIR", "/data/output"))
_CORS_ORIGINS = [o.strip() for o in os.environ.get("TAO_API_CORS_ORIGINS", "*").split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path, *, since: str | None = None, until: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            row_date = str(row.get("date", ""))
            if since and row_date and row_date < since:
                continue
            if until and row_date and row_date > until:
                continue
            rows.append(row)
            if limit is not None and len(rows) >= limit:
                break
    return rows


def _subnet_crawl_dir(netuid: int) -> Path:
    return _OUTPUT_DIR / "subnets" / str(netuid) / "crawl"


def _subnet_resolution_dir(netuid: int) -> Path:
    return _OUTPUT_DIR / "subnets" / str(netuid)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", response_class=PlainTextResponse)
async def health() -> str:
    if not _OUTPUT_DIR.exists():
        raise HTTPException(status_code=503, detail="output directory does not exist")
    return "ok"


@app.get("/api/v1/subnets")
async def list_subnets() -> JSONResponse:
    """List all subnets that have been resolved/crawled."""
    subnets_dir = _OUTPUT_DIR / "subnets"
    if not subnets_dir.exists():
        return JSONResponse(content={"subnets": [], "count": 0})

    subnets: list[dict[str, Any]] = []
    for netuid_dir in sorted(subnets_dir.iterdir()):
        if not netuid_dir.is_dir():
            continue
        try:
            netuid = int(netuid_dir.name)
        except ValueError:
            continue

        targets = _read_json(netuid_dir / "subnet-targets.json") or {}
        summary = _read_json(netuid_dir / "crawl" / "summary.json") or {}
        run = summary.get("run", {})

        subnets.append({
            "netuid": netuid,
            "target_label": targets.get("target"),
            "repository_count": len(targets.get("targets", [])),
            "crawl_status": run.get("status"),
            "crawl_run_id": run.get("run_id"),
            "crawled_at": run.get("started_at") if isinstance(run, dict) else None,
        })

    return JSONResponse(content={"subnets": subnets, "count": len(subnets)})


@app.get("/api/v1/subnets/{netuid}")
async def get_subnet(netuid: int) -> JSONResponse:
    """Get resolution targets and crawl status for a single subnet."""
    targets = _read_json(_subnet_resolution_dir(netuid) / "subnet-targets.json")
    if targets is None:
        raise HTTPException(status_code=404, detail=f"subnet {netuid} not found")

    summary = _read_json(_subnet_crawl_dir(netuid) / "summary.json") or {}
    report = _read_json(_OUTPUT_DIR / "crawl-report.json") or {}

    # Find per-subnet crawl info from the top-level report
    subnet_success = None
    for item in report.get("succeeded", []):
        if item.get("netuid") == netuid:
            subnet_success = item
            break

    return JSONResponse(content={
        "netuid": netuid,
        "target_label": targets.get("target"),
        "schema_version": targets.get("schema_version"),
        "targets": targets.get("targets", []),
        "unresolved": targets.get("unresolved", []),
        "crawl": {
            "status": (summary.get("run") or {}).get("status"),
            "run_id": (summary.get("run") or {}).get("run_id"),
            "repositories": summary.get("repositories"),
            "summary": summary,
        },
        "crawl_report_entry": subnet_success,
    })


@app.get("/api/v1/subnets/{netuid}/metrics/summary")
async def get_subnet_summary(netuid: int) -> JSONResponse:
    """Return the summary.json for a subnet crawl."""
    summary = _read_json(_subnet_crawl_dir(netuid) / "summary.json")
    if summary is None:
        raise HTTPException(status_code=404, detail=f"no crawl summary for subnet {netuid}")
    return JSONResponse(content=summary)


@app.get("/api/v1/subnets/{netuid}/metrics/{dataset}")
async def get_subnet_metrics(
    netuid: int,
    dataset: str,
    since: str | None = Query(None, description="ISO date filter (inclusive)"),
    until: str | None = Query(None, description="ISO date filter (inclusive)"),
    limit: int | None = Query(None, ge=1, le=10000, description="Max rows to return"),
) -> JSONResponse:
    """Return metrics rows from a JSONL dataset.

    Supported datasets: org_days, repo_days, contributor_days, repositories,
    excluded_repositories, commits, file_changes, repo_failures.
    """
    filename = f"{dataset}.jsonl"
    path = _subnet_crawl_dir(netuid) / filename

    rows = _read_jsonl(path, since=since, until=until, limit=limit)
    return JSONResponse(content={
        "netuid": netuid,
        "dataset": dataset,
        "count": len(rows),
        "filters": {"since": since, "until": until, "limit": limit},
        "rows": rows,
    })


@app.get("/api/v1/aggregate/summary")
async def get_aggregate_summary() -> JSONResponse:
    """Return the top-level summary across all subnets."""
    # Prefer top-level crawl report; fallback to nothing yet
    report = _read_json(_OUTPUT_DIR / "crawl-report.json") or {}
    targets = _read_json(_OUTPUT_DIR / "subnet-targets.json") or {}

    return JSONResponse(content={
        "target_label": targets.get("target"),
        "total_targets": len(targets.get("targets", [])),
        "total_unresolved": len(targets.get("unresolved", [])),
        "succeeded_subnets": len(report.get("succeeded", [])),
        "failed_subnets": len(report.get("failed", [])),
        "skipped_unresolved": report.get("skipped_unresolved_netuids", []),
    })


@app.get("/api/v1/registries")
async def list_registries() -> JSONResponse:
    """Show the currently active built-in registry entries."""
    return JSONResponse(content=DEFAULT_REGISTRY)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:  # noqa: D401
    import uvicorn
    host = os.environ.get("TAO_API_HOST", "0.0.0.0")
    port = int(os.environ.get("TAO_API_PORT", "8000"))
    log_level = os.environ.get("TAO_API_LOG_LEVEL", "info")
    uvicorn.run("tao_git_crawl.api_server:app", host=host, port=port, log_level=log_level)


if __name__ == "__main__":
    main()
