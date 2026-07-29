from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from math import ceil
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, unquote, urlparse

from .activity_filter import CODE_ACTIVITY_EXCLUDED_CHURN_CLASSES, is_noise_change, noise_change_class
from .identity_epochs import IDENTITY_HISTORY_SCHEMA_VERSION, IDENTITY_RECONCILIATION_FILENAME

DEFAULT_OUTPUT_DIR = Path("/data/output")
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080
DEFAULT_LIMIT = 100
MAX_LIMIT = 1000
DEFAULT_RATE_LIMIT_REQUESTS = 1200
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60
ACTIVITY_SCHEMA_VERSION = "tao-git-crawl-activity-v2"
SUBNET_SUMMARY_SCHEMA_VERSION = "tao-git-crawl-subnet-summary-v2"
GIT_CRAWL_ACTIVITY_SCHEMA_VERSION = "git-crawl-activity-v1"

JSON_DATASETS = {
    "summary": "summary.json",
    "score": "score.json",
    "manifest": "output_manifest.json",
    "targets": "subnet-targets.json",
    "owner-targets": "owner-targets.json",
    "repository-manifest": "repository-manifest.json",
    "unresolved": "unresolved.json",
    "identity-epoch": "identity-epoch.json",
}

PUBLIC_JSONL_DATASETS = {
    "repositories": "repositories.jsonl",
    "commits": "commits.jsonl",
    "contributor-days": "contributor_days.jsonl",
    "repo-days": "repo_days.jsonl",
    "org-days": "org_days.jsonl",
    "file-changes": "file_changes.jsonl",
}

DIAGNOSTIC_JSONL_DATASETS = {
    "failures": "repo_failures.jsonl",
    "excluded": "excluded_repositories.jsonl",
    "crawl-runs": "crawl_runs.jsonl",
}

JSONL_DATASETS = PUBLIC_JSONL_DATASETS | DIAGNOSTIC_JSONL_DATASETS
JSONL_DATASET_ALIASES = {"contributors": "contributor-days"}
DAY_DATASETS = {"contributor-days", "repo-days", "org-days"}


@dataclass(frozen=True)
class ApiResponse:
    status: HTTPStatus
    payload: object


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int = 0


@dataclass(frozen=True)
class ApiCrawlReportState:
    succeeded: set[int]
    failed_reasons: dict[int, str]
    inaccessible_reasons: dict[int, list[str]]
    attribution_reasons: dict[int, list[str]]
    skipped_unresolved: set[int]


class ApiProblem(ValueError):
    def __init__(self, status: HTTPStatus, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class SlidingWindowRateLimiter:
    """Small in-memory per-client limiter for direct Docker exposure guardrails."""

    def __init__(
        self,
        *,
        max_requests: int = DEFAULT_RATE_LIMIT_REQUESTS,
        window_seconds: int = DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
        now: Callable[[], float] | None = None,
    ):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._now = now or time.monotonic
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()

    @property
    def enabled(self) -> bool:
        return self.max_requests > 0 and self.window_seconds > 0

    def check(self, client_id: str) -> RateLimitDecision:
        if not self.enabled:
            return RateLimitDecision(allowed=True, remaining=0)

        now = self._now()
        cutoff = now - self.window_seconds
        with self._lock:
            hits = self._hits.setdefault(client_id, deque())
            while hits and hits[0] <= cutoff:
                hits.popleft()

            if len(hits) >= self.max_requests:
                retry_after = max(1, ceil(hits[0] + self.window_seconds - now))
                return RateLimitDecision(allowed=False, remaining=0, retry_after_seconds=retry_after)

            hits.append(now)
            return RateLimitDecision(allowed=True, remaining=self.max_requests - len(hits))


def handle_api_request(output_dir: str | Path, raw_target: str) -> ApiResponse:
    output_path = Path(output_dir)
    parsed = urlparse(raw_target)
    parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
    query = parse_qs(parsed.query)

    try:
        if not parts or parts == ["api"]:
            return ApiResponse(HTTPStatus.OK, _routes_payload())
        if parts == ["health"]:
            health = _health_payload(output_path)
            return ApiResponse(
                HTTPStatus.OK if health["ok"] is True else HTTPStatus.SERVICE_UNAVAILABLE,
                health,
            )
        if parts == ["api", "crawl-report"]:
            _require_no_identity_reconciliation(output_path)
            return ApiResponse(HTTPStatus.OK, _read_json_required(output_path / "crawl-report.json"))
        if parts == ["api", "scores"]:
            _require_no_identity_reconciliation(output_path)
            return ApiResponse(HTTPStatus.OK, _read_json_required(output_path / "subnet-scores.json"))
        if parts == ["api", "identity-history"]:
            history = _read_json_optional(output_path / "identity-history.json")
            return ApiResponse(
                HTTPStatus.OK,
                history
                if history is not None
                else {"schema_version": IDENTITY_HISTORY_SCHEMA_VERSION, "events": []},
            )
        if parts == ["api", "subnets"]:
            return ApiResponse(HTTPStatus.OK, {"data": list_subnets(output_path)})
        if len(parts) >= 3 and parts[:2] == ["api", "subnets"]:
            netuid = _parse_netuid(parts[2])
            if len(parts) == 3:
                return ApiResponse(HTTPStatus.OK, get_subnet_detail(output_path, netuid))
            if len(parts) == 4 and parts[3] == "activity":
                return ApiResponse(HTTPStatus.OK, get_subnet_activity(output_path, netuid))
            if len(parts) == 4:
                return ApiResponse(HTTPStatus.OK, get_subnet_dataset(output_path, netuid, parts[3], query))
        raise ApiProblem(HTTPStatus.NOT_FOUND, "unknown endpoint")
    except ApiProblem as exc:
        return ApiResponse(exc.status, {"error": exc.message})


def list_subnets(output_dir: str | Path) -> list[dict[str, object]]:
    output_path = Path(output_dir)
    subnets_dir = output_path / "subnets"
    if not subnets_dir.exists():
        return []
    report_state = _crawl_report_state(output_path)
    return [
        _subnet_overview(subnet_dir, report_state=report_state)
        for subnet_dir in sorted(
            (path for path in subnets_dir.iterdir() if path.is_dir() and path.name.isdigit()),
            key=lambda path: int(path.name),
        )
    ]


def get_subnet_detail(output_dir: str | Path, netuid: int) -> dict[str, object]:
    output_path = Path(output_dir)
    subnet_dir = _subnet_dir(output_path, netuid)
    overview = _subnet_overview(subnet_dir, report_state=_crawl_report_state(output_path))
    overview["files"] = _subnet_files(subnet_dir)
    overview["endpoints"] = _subnet_endpoints(netuid)
    overview["diagnostic_endpoints"] = _subnet_diagnostic_endpoints(netuid)
    return overview


def get_subnet_activity(output_dir: str | Path, netuid: int) -> object:
    output_path = Path(output_dir)
    subnet_dir = _subnet_dir(output_path, netuid)
    _require_current_crawl_output(output_path, netuid)
    crawl_dir = subnet_dir / "crawl"
    summary = _read_json_required(crawl_dir / "summary.json")
    return _activity_from_summary(summary, crawl_dir)


def get_subnet_dataset(
    output_dir: str | Path,
    netuid: int,
    dataset: str,
    query: dict[str, list[str]] | None = None,
) -> dict[str, object] | list[object] | object:
    dataset = JSONL_DATASET_ALIASES.get(dataset, dataset)
    output_path = Path(output_dir)
    subnet_dir = _subnet_dir(output_path, netuid)
    crawl_dir = subnet_dir / "crawl"
    query_params = query or {}

    if dataset == "activity":
        _require_current_crawl_output(output_path, netuid)
        return _activity_from_summary(_read_json_required(crawl_dir / "summary.json"), crawl_dir)

    if dataset in JSON_DATASETS:
        if dataset == "summary":
            _require_current_crawl_output(output_path, netuid)
            return _summary_with_score(
                _read_json_required(crawl_dir / JSON_DATASETS[dataset]),
                _read_json_optional(subnet_dir / "score.json"),
                crawl_dir,
            )
        if dataset == "manifest":
            _require_current_crawl_output(output_path, netuid)
        if dataset == "score":
            _require_no_identity_reconciliation(output_path)
        path = (
            (crawl_dir / JSON_DATASETS[dataset])
            if dataset in {"summary", "manifest"}
            else subnet_dir / JSON_DATASETS[dataset]
        )
        return _read_json_required(path)

    if dataset in JSONL_DATASETS:
        _require_current_crawl_output(output_path, netuid)
        limit = _parse_query_int(query_params, "limit", DEFAULT_LIMIT)
        offset = _parse_query_int(query_params, "offset", 0)
        if dataset == "file-changes":
            return _read_jsonl_page(
                crawl_dir / JSONL_DATASETS[dataset],
                limit=limit,
                offset=offset,
                row_filter=_is_code_change_row,
                row_transform=_file_change_row_payload,
            )
        if dataset == "commits":
            credited_commit_stats = _credited_commit_stats_from_file_changes(crawl_dir)
            if credited_commit_stats is not None:
                return _read_jsonl_page(
                    crawl_dir / JSONL_DATASETS[dataset],
                    limit=limit,
                    offset=offset,
                    row_filter=lambda row: (
                        _commit_key(row) in credited_commit_stats if isinstance(row, dict) else False
                    ),
                    row_transform=lambda row: _commit_row_payload(row, credited_commit_stats),
                )
            return _read_jsonl_page(
                crawl_dir / JSONL_DATASETS[dataset],
                limit=limit,
                offset=offset,
                row_transform=_files_changed_row_payload,
            )
        if dataset in DAY_DATASETS:
            day_rows = _day_rows_from_code_activity(crawl_dir, dataset)
            if day_rows is not None:
                return _paginate_rows(day_rows, limit=limit, offset=offset)
            return _read_jsonl_page(
                crawl_dir / JSONL_DATASETS[dataset],
                limit=limit,
                offset=offset,
                row_transform=_files_changed_row_payload,
            )
        return _read_jsonl_page(
            crawl_dir / JSONL_DATASETS[dataset],
            limit=limit,
            offset=offset,
            row_transform=_files_changed_row_payload,
        )

    raise ApiProblem(HTTPStatus.NOT_FOUND, f"unknown subnet dataset: {dataset}")


def serve(
    *,
    output_dir: str | Path,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    cors_origin: str = "*",
    rate_limit_requests: int = DEFAULT_RATE_LIMIT_REQUESTS,
    rate_limit_window_seconds: int = DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
) -> None:
    rate_limiter = SlidingWindowRateLimiter(
        max_requests=rate_limit_requests,
        window_seconds=rate_limit_window_seconds,
    )
    handler_class = _make_handler(Path(output_dir), cors_origin=cors_origin, rate_limiter=rate_limiter)
    server = ThreadingHTTPServer((host, port), handler_class)
    print(f"tao-git-crawl API serving {Path(output_dir)} on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tao-git-crawl-api", description="Serve tao-git-crawl output files as JSON.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(os.environ.get("TAO_API_OUTPUT_DIR", DEFAULT_OUTPUT_DIR)),
    )
    parser.add_argument("--host", default=os.environ.get("TAO_API_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("TAO_API_PORT", str(DEFAULT_PORT))))
    parser.add_argument("--cors-origin", default=os.environ.get("TAO_API_CORS_ORIGIN", "*"))
    parser.add_argument(
        "--rate-limit-requests",
        type=int,
        default=int(os.environ.get("TAO_API_RATE_LIMIT_REQUESTS", str(DEFAULT_RATE_LIMIT_REQUESTS))),
        help=(
            "maximum requests per client within the rate-limit window; "
            "set to 0 to disable (default: 1200)"
        ),
    )
    parser.add_argument(
        "--rate-limit-window-seconds",
        type=int,
        default=int(os.environ.get("TAO_API_RATE_LIMIT_WINDOW_SECONDS", str(DEFAULT_RATE_LIMIT_WINDOW_SECONDS))),
        help="rate-limit window in seconds; set to 0 to disable (default: 60)",
    )
    args = parser.parse_args(argv)
    serve(
        output_dir=args.output_dir,
        host=args.host,
        port=args.port,
        cors_origin=args.cors_origin,
        rate_limit_requests=args.rate_limit_requests,
        rate_limit_window_seconds=args.rate_limit_window_seconds,
    )
    return 0


def _make_handler(
    output_dir: Path,
    *,
    cors_origin: str,
    rate_limiter: SlidingWindowRateLimiter,
) -> type[BaseHTTPRequestHandler]:
    class OutputApiHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            rate_limit = rate_limiter.check(self._client_id())
            rate_headers = _rate_limit_headers(rate_limiter, rate_limit)
            if not rate_limit.allowed:
                self._send_json(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    {
                        "error": "rate limit exceeded",
                        "retry_after_seconds": rate_limit.retry_after_seconds,
                    },
                    extra_headers=rate_headers,
                )
                return

            response = handle_api_request(output_dir, self.path)
            self._send_json(response.status, response.payload, extra_headers=rate_headers)

        def do_OPTIONS(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            self.send_response(HTTPStatus.NO_CONTENT)
            self._send_headers()
            self.end_headers()

        def _send_json(
            self,
            status: HTTPStatus,
            payload: object,
            *,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            body = json.dumps(payload, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self._send_headers(content_length=len(body), extra_headers=extra_headers)
            self.end_headers()
            self.wfile.write(body)

        def _send_headers(
            self,
            *,
            content_length: int | None = None,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", cors_origin)
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header(
                "Access-Control-Expose-Headers",
                "Retry-After, X-RateLimit-Limit, X-RateLimit-Remaining",
            )
            if content_length is not None:
                self.send_header("Content-Length", str(content_length))
            for name, value in (extra_headers or {}).items():
                self.send_header(name, value)

        def _client_id(self) -> str:
            if isinstance(self.client_address, tuple) and self.client_address:
                return str(self.client_address[0])
            return "unknown"

        def log_message(self, fmt: str, *args: object) -> None:
            sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")

    return OutputApiHandler


def _rate_limit_headers(
    rate_limiter: SlidingWindowRateLimiter,
    decision: RateLimitDecision,
) -> dict[str, str]:
    if not rate_limiter.enabled:
        return {}
    headers = {
        "X-RateLimit-Limit": str(rate_limiter.max_requests),
        "X-RateLimit-Remaining": str(decision.remaining),
    }
    if not decision.allowed:
        headers["Retry-After"] = str(decision.retry_after_seconds)
    return headers


def _routes_payload() -> dict[str, object]:
    return {
        "name": "tao-git-crawl API",
        "summary_schema_version": SUBNET_SUMMARY_SCHEMA_VERSION,
        "activity_schema_version": ACTIVITY_SCHEMA_VERSION,
        "routes": [
            "/health",
            "/api/subnets",
            "/api/subnets/{netuid}",
            "/api/subnets/{netuid}/summary",
            "/api/subnets/{netuid}/activity",
            "/api/subnets/{netuid}/score",
            "/api/subnets/{netuid}/repositories?limit=100&offset=0",
            "/api/subnets/{netuid}/commits?limit=100&offset=0",
            "/api/subnets/{netuid}/contributor-days?limit=100&offset=0",
            "/api/subnets/{netuid}/repo-days?limit=100&offset=0",
            "/api/subnets/{netuid}/org-days?limit=100&offset=0",
            "/api/subnets/{netuid}/file-changes?limit=100&offset=0",
            "/api/crawl-report",
            "/api/scores",
            "/api/identity-history",
        ],
        "diagnostic_routes": [
            "/api/subnets/{netuid}/failures?limit=100&offset=0",
            "/api/subnets/{netuid}/excluded?limit=100&offset=0",
            "/api/subnets/{netuid}/crawl-runs?limit=100&offset=0",
        ],
    }


def _health_payload(output_dir: Path) -> dict[str, object]:
    reconciliation = _read_json_optional(output_dir / IDENTITY_RECONCILIATION_FILENAME)
    payload: dict[str, object] = {
        "ok": output_dir.exists() and reconciliation is None,
        "output_dir": str(output_dir),
        "subnets": _count_subnet_dirs(output_dir),
    }
    if reconciliation is not None:
        payload["identity_reconciliation"] = reconciliation
    return payload


def _count_subnet_dirs(output_dir: Path) -> int:
    subnets_dir = output_dir / "subnets"
    if not subnets_dir.exists():
        return 0
    try:
        return sum(1 for path in subnets_dir.iterdir() if path.is_dir() and path.name.isdigit())
    except OSError:
        return 0


def _subnet_overview(subnet_dir: Path, *, report_state: ApiCrawlReportState | None = None) -> dict[str, object]:
    netuid = int(subnet_dir.name)
    targets_doc = _read_json_optional(subnet_dir / "subnet-targets.json")
    unresolved = _read_json_optional(subnet_dir / "unresolved.json") or []
    targets = targets_doc.get("targets", []) if isinstance(targets_doc, dict) else []
    repository_targets = [
        target for target in targets if isinstance(target, dict) and target.get("kind") == "repository"
    ]
    owner_targets = [target for target in targets if isinstance(target, dict) and target.get("kind") == "owner"]
    crawl_dir = subnet_dir / "crawl"
    use_crawl_output = _is_current_crawl_output(report_state, netuid)
    summary = _read_json_optional(crawl_dir / "summary.json") if use_crawl_output else None
    score = (
        None
        if (subnet_dir.parents[1] / IDENTITY_RECONCILIATION_FILENAME).exists()
        else _read_json_optional(subnet_dir / "score.json")
    )
    identity_epoch = _read_json_optional(subnet_dir / "identity-epoch.json")
    activity = _activity_from_summary(summary, crawl_dir) if summary is not None else None

    payload: dict[str, object] = {
        "netuid": netuid,
        "subnet_name": _subnet_name(targets, unresolved),
        "has_crawl": crawl_dir.exists() and use_crawl_output,
        "has_summary": summary is not None,
        "activity": activity,
        "summary": _summary_with_score(summary, score, activity=activity),
        "score": score,
        "identity_epoch": identity_epoch,
        "target_count": len(targets),
        "repository_target_count": len(repository_targets),
        "owner_target_count": len(owner_targets),
        "unresolved_count": len(unresolved) if isinstance(unresolved, list) else 0,
    }
    current_crawl = _current_crawl_payload(report_state, netuid)
    if current_crawl is not None:
        payload["current_crawl"] = current_crawl
    return payload


def _subnet_name(targets: object, unresolved: object) -> str:
    if isinstance(targets, list):
        for target in targets:
            if isinstance(target, dict) and target.get("subnet_name"):
                return str(target["subnet_name"])
    if isinstance(unresolved, list):
        for item in unresolved:
            if isinstance(item, dict) and item.get("subnet_name"):
                return str(item["subnet_name"])
    return ""


def _subnet_files(subnet_dir: Path) -> list[str]:
    if not subnet_dir.exists():
        return []
    files: list[str] = []
    for path in subnet_dir.iterdir():
        if path.is_file():
            files.append(str(path.relative_to(subnet_dir)))
        elif path.name == "crawl":
            files.append("crawl/")
            # Do not recurse into crawl/ to avoid listing large JSONL outputs.
        else:
            files.extend(
                str(item.relative_to(subnet_dir)) for item in path.rglob("*") if item.is_file()
            )
    return sorted(files)


def _subnet_endpoints(netuid: int) -> dict[str, str]:
    base = f"/api/subnets/{netuid}"
    endpoints = {
        "detail": base,
        "summary": f"{base}/summary",
        "activity": f"{base}/activity",
        "targets": f"{base}/targets",
        "owner_targets": f"{base}/owner-targets",
        "repository_manifest": f"{base}/repository-manifest",
        "unresolved": f"{base}/unresolved",
        "identity_epoch": f"{base}/identity-epoch",
        "score": f"{base}/score",
    }
    endpoints.update(
        {dataset.replace("-", "_"): f"{base}/{dataset}?limit=100&offset=0" for dataset in PUBLIC_JSONL_DATASETS}
    )
    return endpoints


def _subnet_diagnostic_endpoints(netuid: int) -> dict[str, str]:
    base = f"/api/subnets/{netuid}"
    return {dataset.replace("-", "_"): f"{base}/{dataset}?limit=100&offset=0" for dataset in DIAGNOSTIC_JSONL_DATASETS}


def _subnet_dir(output_dir: Path, netuid: int) -> Path:
    subnet_dir = output_dir / "subnets" / str(netuid)
    if not subnet_dir.exists():
        raise ApiProblem(HTTPStatus.NOT_FOUND, f"subnet {netuid} not found")
    return subnet_dir


def _require_current_crawl_output(output_dir: Path, netuid: int) -> None:
    report_state = _crawl_report_state(output_dir)
    if _is_current_crawl_output(report_state, netuid):
        return
    current_crawl = _current_crawl_payload(report_state, netuid) or {}
    reason = current_crawl.get("reason") or current_crawl.get("status") or "not crawled in current report"
    raise ApiProblem(HTTPStatus.NOT_FOUND, f"current crawl did not produce subnet {netuid}: {reason}")


def _is_current_crawl_output(report_state: ApiCrawlReportState | None, netuid: int) -> bool:
    return report_state is None or netuid in report_state.succeeded


def _current_crawl_payload(
    report_state: ApiCrawlReportState | None,
    netuid: int,
) -> dict[str, object] | None:
    if report_state is None:
        return None
    if netuid in report_state.succeeded:
        return {"status": "success", "current": True}
    attribution_reasons = report_state.attribution_reasons.get(netuid)
    if attribution_reasons:
        return {
            "status": "attribution_rejected",
            "current": False,
            "reason": "; ".join(attribution_reasons[:3]),
        }
    failed_reason = report_state.failed_reasons.get(netuid)
    if failed_reason:
        return {"status": "crawl_failed", "current": False, "reason": failed_reason}
    inaccessible_reasons = report_state.inaccessible_reasons.get(netuid)
    if inaccessible_reasons:
        return {
            "status": "crawl_failed",
            "current": False,
            "reason": f"GitHub target inaccessible: {'; '.join(inaccessible_reasons[:3])}",
        }
    if netuid in report_state.skipped_unresolved:
        return {
            "status": "unresolved",
            "current": False,
            "reason": "no resolved GitHub target in current report",
        }
    return {"status": "no_crawl", "current": False, "reason": "not crawled in current report"}


def _crawl_report_state(output_dir: Path) -> ApiCrawlReportState | None:
    if (output_dir / IDENTITY_RECONCILIATION_FILENAME).exists():
        return ApiCrawlReportState(
            succeeded=set(),
            failed_reasons={},
            inaccessible_reasons={},
            attribution_reasons={},
            skipped_unresolved=set(),
        )
    report = _read_json_optional(output_dir / "crawl-report.json")
    if not isinstance(report, dict):
        return None

    inaccessible_reasons: dict[int, list[str]] = {}
    for item in _object_rows(report.get("skipped_inaccessible")):
        netuid = _row_netuid(item)
        if netuid is None:
            continue
        reason = item.get("reason")
        inaccessible_reasons.setdefault(netuid, []).append(str(reason) if reason is not None else "inaccessible")

    attribution_reasons: dict[int, list[str]] = {}
    for item in _object_rows(report.get("skipped_attribution")):
        netuid = _row_netuid(item)
        if netuid is None:
            continue
        reason = item.get("reason")
        attribution_reasons.setdefault(netuid, []).append(
            str(reason) if reason is not None else "repository attribution rejected"
        )

    return ApiCrawlReportState(
        succeeded=_netuid_set(report.get("succeeded")),
        failed_reasons=_netuid_reasons(report.get("failed")),
        inaccessible_reasons=inaccessible_reasons,
        attribution_reasons=attribution_reasons,
        skipped_unresolved=_integer_set(report.get("skipped_unresolved_netuids")),
    )


def _require_no_identity_reconciliation(output_dir: Path) -> None:
    if (output_dir / IDENTITY_RECONCILIATION_FILENAME).exists():
        raise ApiProblem(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "subnet identity reconciliation is in progress or requires operator recovery",
        )


def _netuid_set(value: object) -> set[int]:
    netuids: set[int] = set()
    for item in _object_rows(value):
        netuid = _row_netuid(item)
        if netuid is not None:
            netuids.add(netuid)
    return netuids


def _netuid_reasons(value: object) -> dict[int, str]:
    reasons: dict[int, str] = {}
    for item in _object_rows(value):
        netuid = _row_netuid(item)
        if netuid is None:
            continue
        reason = item.get("reason")
        reasons[netuid] = str(reason) if reason is not None else "crawl failed"
    return reasons


def _object_rows(value: object) -> list[dict[str, object]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _row_netuid(row: dict[str, object]) -> int | None:
    value = row.get("netuid")
    if isinstance(value, bool):
        return None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _integer_set(value: object) -> set[int]:
    if not isinstance(value, list):
        return set()
    integers: set[int] = set()
    for item in value:
        if isinstance(item, bool):
            continue
        try:
            integers.add(int(item))
        except (TypeError, ValueError):
            continue
    return integers


def _read_json_required(path: Path) -> object:
    payload = _read_json_optional(path)
    if payload is None:
        raise ApiProblem(HTTPStatus.NOT_FOUND, f"file not found: {path.name}")
    return payload


def _read_json_optional(path: Path) -> object | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise ApiProblem(HTTPStatus.INTERNAL_SERVER_ERROR, f"invalid UTF-8 in {path.name}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ApiProblem(HTTPStatus.INTERNAL_SERVER_ERROR, f"invalid JSON in {path.name}: {exc}") from exc
    except OSError as exc:
        raise ApiProblem(HTTPStatus.INTERNAL_SERVER_ERROR, f"could not read {path.name}: {exc}") from exc


def _summary_with_score(
    summary: object,
    score: object | None,
    crawl_dir: Path | None = None,
    *,
    activity: dict[str, object] | None = None,
) -> object:
    if summary is None:
        return summary
    if not isinstance(summary, dict):
        raise ApiProblem(HTTPStatus.INTERNAL_SERVER_ERROR, "invalid crawl summary: expected JSON object")
    canonical_activity = activity if activity is not None else _activity_from_summary(summary, crawl_dir)
    top_activity = _top_activity_payload(crawl_dir)
    return {
        "schema_version": SUBNET_SUMMARY_SCHEMA_VERSION,
        "status": summary.get("status"),
        "crawl": _crawl_metadata_payload(summary),
        "history": dict(_mapping(canonical_activity.get("history"))) if isinstance(canonical_activity, dict) else {},
        "repositories": (
            dict(_mapping(canonical_activity.get("repositories"))) if isinstance(canonical_activity, dict) else {}
        ),
        "activity": canonical_activity,
        "totals": dict(_mapping(canonical_activity.get("totals"))) if isinstance(canonical_activity, dict) else {},
        "averages": dict(_mapping(canonical_activity.get("averages"))) if isinstance(canonical_activity, dict) else {},
        "skipped": dict(_mapping(canonical_activity.get("skipped"))) if isinstance(canonical_activity, dict) else {},
        "top_repositories": top_activity["top_repositories"],
        "top_paths": top_activity["top_paths"],
        "score": score,
    }


def _crawl_metadata_payload(summary: dict[str, object]) -> dict[str, object]:
    metadata = {
        "target": summary.get("org"),
        "run_id": summary.get("run_id"),
        "ref_scope": summary.get("ref_scope"),
        "active_since": summary.get("active_since"),
    }
    return {key: value for key, value in metadata.items() if value is not None}


def _top_activity_payload(crawl_dir: Path | None) -> dict[str, list[dict[str, object]]]:
    top_from_rows = _top_activity_from_jsonl(crawl_dir)
    if top_from_rows is not None:
        return top_from_rows
    return {"top_repositories": [], "top_paths": []}


def _activity_from_summary(summary: object, crawl_dir: Path | None = None) -> dict[str, object] | None:
    if summary is None:
        return None
    if not isinstance(summary, dict):
        raise ApiProblem(HTTPStatus.INTERNAL_SERVER_ERROR, "invalid crawl summary: expected JSON object")

    source_like_totals_value = summary.get("source_like_totals")
    has_source_like_totals = isinstance(source_like_totals_value, dict)
    source_like_totals = _mapping(source_like_totals_value)
    calendar_span = _mapping(summary.get("calendar_span"))
    jsonl_activity = _code_activity_from_jsonl(crawl_dir, summary)
    upstream_activity = None if jsonl_activity is not None else _read_git_crawl_activity(crawl_dir)
    if jsonl_activity is not None:
        totals = _mapping(jsonl_activity.get("totals"))
        skipped = _mapping(jsonl_activity.get("skipped"))
    elif upstream_activity is not None:
        totals = _activity_totals_from_summary(_mapping(upstream_activity.get("totals")))
        skipped = _public_skipped_activity(_mapping(upstream_activity.get("skipped")))
    elif has_source_like_totals:
        totals = _activity_totals_from_summary(source_like_totals)
        skipped = _skipped_activity_from_summary(summary, totals)
    else:
        totals = _empty_activity_totals()
        skipped = _skipped_activity_from_summary(summary, totals)
    active_days = totals["active_days"]
    status = _activity_metadata(summary, upstream_activity, "status")
    history_since = _activity_metadata(summary, upstream_activity, "history_since")
    history_until = _activity_metadata(summary, upstream_activity, "history_until")

    return {
        "schema_version": ACTIVITY_SCHEMA_VERSION,
        "status": status,
        "history": {
            "since": history_since,
            "until": history_until,
            "calendar_span": dict(calendar_span),
        },
        "repositories": _repository_activity_payload(summary.get("repositories")),
        "totals": totals,
        "averages": {
            "per_active_day": _activity_average(totals, active_days),
            "per_calendar_day": _activity_average(totals, _number(calendar_span.get("days"))),
            "per_calendar_week": _activity_average(totals, _number(calendar_span.get("weeks"))),
            "per_calendar_month": _activity_average(totals, _number(calendar_span.get("months"))),
        },
        "skipped": skipped,
    }


def _activity_metadata(
    summary: dict[str, object],
    upstream_activity: dict[str, object] | None,
    key: str,
) -> object:
    if upstream_activity is not None and upstream_activity.get(key) is not None:
        return upstream_activity.get(key)
    return summary.get(key)


def _read_git_crawl_activity(crawl_dir: Path | None) -> dict[str, object] | None:
    if crawl_dir is None:
        return None
    payload = _read_json_optional(crawl_dir / "activity.json")
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ApiProblem(HTTPStatus.INTERNAL_SERVER_ERROR, "invalid activity.json: expected JSON object")
    schema_version = payload.get("schema_version")
    if schema_version != GIT_CRAWL_ACTIVITY_SCHEMA_VERSION:
        raise ApiProblem(
            HTTPStatus.INTERNAL_SERVER_ERROR,
            (
                f"unsupported activity schema version {schema_version!r}; "
                f"expected {GIT_CRAWL_ACTIVITY_SCHEMA_VERSION!r}"
            ),
        )
    return payload


def _activity_totals_from_summary(source_like_totals: dict[str, object]) -> dict[str, int | float]:
    return {
        "commits": _number(source_like_totals.get("commits")),
        "file_changes": _number(source_like_totals.get("file_changes")),
        "lines_added": _number(source_like_totals.get("lines_added")),
        "lines_deleted": _number(source_like_totals.get("lines_deleted")),
        "active_days": _number(source_like_totals.get("active_days")),
        "repo_days": _number(source_like_totals.get("repo_days")),
        "contributor_days": _number(source_like_totals.get("contributor_days")),
        "distinct_contributors": _number_from_keys(
            source_like_totals,
            "distinct_contributors",
            "distinct_contributor_keys",
        ),
    }


def _public_skipped_activity(value: dict[str, object]) -> dict[str, object]:
    skipped = {
        "file_changes": _number(value.get("file_changes")),
        "lines_added": _number(value.get("lines_added")),
        "lines_deleted": _number(value.get("lines_deleted")),
    }
    by_reason: dict[str, dict[str, int | float]] = {}
    for reason, totals_value in _mapping(value.get("by_reason")).items():
        totals = _mapping(totals_value)
        reason_totals = {
            "file_changes": _number(totals.get("file_changes")),
            "lines_added": _number(totals.get("lines_added")),
            "lines_deleted": _number(totals.get("lines_deleted")),
        }
        if any(_number(metric_value) > 0 for metric_value in reason_totals.values()):
            by_reason[str(reason)] = reason_totals
    if by_reason:
        skipped["by_reason"] = by_reason
    return skipped


def _empty_activity_totals() -> dict[str, int | float]:
    return {
        "commits": 0,
        "file_changes": 0,
        "lines_added": 0,
        "lines_deleted": 0,
        "active_days": 0,
        "repo_days": 0,
        "contributor_days": 0,
        "distinct_contributors": 0,
    }


def _code_activity_from_jsonl(
    crawl_dir: Path | None,
    summary: dict[str, object],
) -> dict[str, object] | None:
    if crawl_dir is None:
        return None
    file_changes_path = crawl_dir / "file_changes.jsonl"
    commits_path = crawl_dir / "commits.jsonl"
    if not file_changes_path.exists() or not commits_path.exists():
        return None

    credited_change_stats: dict[tuple[str, str], dict[str, int | float]] = {}
    credited_paths_by_commit: dict[tuple[str, str], set[str]] = {}
    skipped = _empty_skipped_activity()
    for row in _iter_jsonl_objects(file_changes_path):
        if not isinstance(row, dict):
            continue
        skipped_class = noise_change_class(row)
        if skipped_class is not None:
            _add_skipped_change(skipped, row, skipped_class)
            continue
        commit_key = _commit_key(row)
        path = _file_change_path(row)
        if commit_key is not None and path is not None:
            seen_paths = credited_paths_by_commit.setdefault(commit_key, set())
            if path in seen_paths:
                continue
            seen_paths.add(path)
            stats = credited_change_stats.setdefault(
                commit_key,
                {"file_changes": 0, "lines_added": 0, "lines_deleted": 0},
            )
            stats["file_changes"] = _number(stats.get("file_changes")) + 1
            stats["lines_added"] = _number(stats.get("lines_added")) + max(
                _file_change_lines_added(row),
                0,
            )
            stats["lines_deleted"] = _number(stats.get("lines_deleted")) + max(
                _file_change_lines_deleted(row),
                0,
            )

    commits = 0
    credited_commit_keys: set[tuple[str, str]] = set()
    active_days: set[str] = set()
    repo_days: set[tuple[str, str]] = set()
    contributor_days: set[tuple[str, str, str]] = set()
    contributors: set[str] = set()
    seen_commits: set[tuple[str, str]] = set()
    history_since, history_until, history_until_inclusive = _history_timestamp_window(summary)
    for row in _iter_jsonl_objects(commits_path):
        if not isinstance(row, dict):
            continue
        commit_key = _commit_key(row)
        if commit_key is None or commit_key not in credited_change_stats or commit_key in seen_commits:
            continue
        authored_at = _authored_timestamp(row.get("authored_at"))
        if authored_at is None or not _is_timestamp_in_history_range(
            authored_at,
            history_since,
            history_until,
            until_inclusive=history_until_inclusive,
        ):
            continue
        seen_commits.add(commit_key)
        credited_commit_keys.add(commit_key)
        commits += 1
        repo = commit_key[0]
        contributor = _contributor_key(row)
        contributors.add(contributor)
        authored_day = authored_at.date().isoformat()
        active_days.add(authored_day)
        repo_days.add((repo, authored_day))
        contributor_days.add((repo, authored_day, contributor))

    file_changes = sum(
        _number(credited_change_stats[commit_key].get("file_changes"))
        for commit_key in credited_commit_keys
    )
    lines_added = sum(
        _number(credited_change_stats[commit_key].get("lines_added"))
        for commit_key in credited_commit_keys
    )
    lines_deleted = sum(
        _number(credited_change_stats[commit_key].get("lines_deleted"))
        for commit_key in credited_commit_keys
    )
    return {
        "totals": {
            "commits": commits,
            "file_changes": file_changes,
            "lines_added": lines_added,
            "lines_deleted": lines_deleted,
            "active_days": len(active_days),
            "repo_days": len(repo_days),
            "contributor_days": len(contributor_days),
            "distinct_contributors": len(contributors),
        },
        "skipped": skipped,
    }


def _skipped_activity_from_summary(
    summary: dict[str, object],
    included_totals: dict[str, int | float],
) -> dict[str, object]:
    skipped = _empty_skipped_activity()
    generated_like_totals = _mapping(summary.get("generated_like_totals"))
    raw_totals = _mapping(summary.get("totals"))
    skipped["file_changes"] = _skipped_total(generated_like_totals, raw_totals, included_totals, "file_changes")
    skipped["lines_added"] = _skipped_total(generated_like_totals, raw_totals, included_totals, "lines_added")
    skipped["lines_deleted"] = _skipped_total(generated_like_totals, raw_totals, included_totals, "lines_deleted")
    skipped_reasons = _skipped_reasons_from_summary(summary)
    if skipped_reasons:
        skipped["by_reason"] = skipped_reasons
    return skipped


def _skipped_total(
    explicit_skipped: dict[str, object],
    raw_totals: dict[str, object],
    included_totals: dict[str, int | float],
    key: str,
) -> int | float:
    if explicit_skipped:
        return _number(explicit_skipped.get(key))
    return max(_number(raw_totals.get(key)) - _number(included_totals.get(key)), 0)


def _skipped_reasons_from_summary(summary: dict[str, object]) -> dict[str, dict[str, int | float]]:
    skipped_by_reason: dict[str, dict[str, int | float]] = {}
    for path_class, totals_value in _mapping(summary.get("path_classes")).items():
        skipped_reason = _noise_class_from_path_class(str(path_class))
        if skipped_reason is None:
            continue
        totals = _mapping(totals_value)
        reason_totals = {
            "file_changes": _number_from_keys(totals, "file_changes", "files_changed"),
            "lines_added": _number(totals.get("lines_added")),
            "lines_deleted": _number(totals.get("lines_deleted")),
        }
        if any(_number(value) > 0 for value in reason_totals.values()):
            skipped_by_reason[skipped_reason] = reason_totals
    return skipped_by_reason


def _noise_class_from_path_class(path_class: str) -> str | None:
    normalized = path_class.strip().lower()
    if normalized == "spec":
        return "spec/schema-like"
    if normalized in {"asset", "assets", "artifact", "data", "dataset", "datasets"}:
        return "artifact/data"
    if normalized in CODE_ACTIVITY_EXCLUDED_CHURN_CLASSES:
        return normalized
    return None


def _empty_skipped_activity() -> dict[str, object]:
    return {
        "file_changes": 0,
        "lines_added": 0,
        "lines_deleted": 0,
    }


def _add_skipped_change(skipped: dict[str, object], row: dict[str, object], skipped_class: str) -> None:
    lines_added = _file_change_lines_added(row)
    lines_deleted = _file_change_lines_deleted(row)
    skipped["file_changes"] = _number(skipped.get("file_changes")) + 1
    skipped["lines_added"] = _number(skipped.get("lines_added")) + lines_added
    skipped["lines_deleted"] = _number(skipped.get("lines_deleted")) + lines_deleted
    by_reason = _mapping(skipped.get("by_reason"))
    reason_totals = dict(_mapping(by_reason.get(skipped_class)))
    reason_totals["file_changes"] = _number(reason_totals.get("file_changes")) + 1
    reason_totals["lines_added"] = _number(reason_totals.get("lines_added")) + lines_added
    reason_totals["lines_deleted"] = _number(reason_totals.get("lines_deleted")) + lines_deleted
    by_reason[skipped_class] = reason_totals
    skipped["by_reason"] = by_reason


def _is_code_change_row(row: object) -> bool:
    return isinstance(row, dict) and not is_noise_change(row)


def _credited_commit_stats_from_file_changes(crawl_dir: Path) -> dict[tuple[str, str], dict[str, int | float]] | None:
    file_changes_path = crawl_dir / "file_changes.jsonl"
    if not file_changes_path.exists():
        return None
    credited_commit_stats: dict[tuple[str, str], dict[str, int | float]] = {}
    credited_paths: dict[tuple[str, str], set[str]] = {}
    for row in _iter_jsonl_objects(file_changes_path):
        if not _is_code_change_row(row):
            continue
        commit_key = _commit_key(row)
        path = _file_change_path(row)
        if commit_key is not None and path is not None:
            seen_paths = credited_paths.setdefault(commit_key, set())
            if path in seen_paths:
                continue
            seen_paths.add(path)
            stats = credited_commit_stats.setdefault(
                commit_key,
                {"file_changes": 0, "lines_added": 0, "lines_deleted": 0},
            )
            stats["file_changes"] = _number(stats.get("file_changes")) + 1
            stats["lines_added"] = _number(stats.get("lines_added")) + max(
                _file_change_lines_added(row),
                0,
            )
            stats["lines_deleted"] = _number(stats.get("lines_deleted")) + max(
                _file_change_lines_deleted(row),
                0,
            )
    return credited_commit_stats


def _commit_key(row: dict[str, object]) -> tuple[str, str] | None:
    repo = _text_key(row.get("repo"))
    sha = _text_key(row.get("sha"))
    if not sha:
        sha = _text_key(row.get("commit_sha"))
    if not repo or not sha:
        return None
    return repo, sha


def _file_change_path(row: dict[str, object]) -> str | None:
    path = row.get("path")
    if not isinstance(path, str) or not path:
        path = row.get("filename")
    return path if isinstance(path, str) and path else None


def _commit_row_payload(
    row: object,
    credited_commit_stats: dict[tuple[str, str], dict[str, int | float]],
) -> object:
    if not isinstance(row, dict):
        return row
    payload = _files_changed_row_payload(row)
    commit_key = _commit_key(row)
    stats = credited_commit_stats.get(commit_key) if commit_key is not None else None
    if stats is not None:
        payload["file_changes"] = _number(stats.get("file_changes"))
        payload["lines_added"] = _number(stats.get("lines_added"))
        payload["lines_deleted"] = _number(stats.get("lines_deleted"))
    return payload


def _file_change_row_payload(row: object) -> object:
    if not isinstance(row, dict):
        return row
    payload = dict(row)
    payload["file_changes"] = 1
    payload["lines_added"] = _file_change_lines_added(row)
    payload["lines_deleted"] = _file_change_lines_deleted(row)
    for internal_key in ("additions", "deletions", "is_binary", "is_generated_like", "is_lockfile"):
        payload.pop(internal_key, None)
    return payload


def _files_changed_row_payload(row: object) -> object:
    if not isinstance(row, dict):
        return row
    payload = dict(row)
    if "files_changed" in payload:
        payload["file_changes"] = _number(payload.pop("files_changed"))
    return payload


def _day_rows_from_code_activity(crawl_dir: Path, dataset: str) -> list[dict[str, object]] | None:
    commits_path = crawl_dir / "commits.jsonl"
    credited_commit_stats = _credited_commit_stats_from_file_changes(crawl_dir)
    if credited_commit_stats is None or not commits_path.exists():
        return None

    org_days: dict[str, dict[str, object]] = {}
    repo_days: dict[tuple[str, str], dict[str, object]] = {}
    contributor_days: dict[tuple[str, str, str], dict[str, object]] = {}
    seen_commits: set[tuple[str, str]] = set()

    for row in _iter_jsonl_objects(commits_path):
        if not isinstance(row, dict):
            continue
        commit_key = _commit_key(row)
        if commit_key is None or commit_key in seen_commits:
            continue
        stats = credited_commit_stats.get(commit_key)
        if stats is None:
            continue
        seen_commits.add(commit_key)
        authored_day = _authored_day(row.get("authored_at"))
        if not authored_day:
            continue
        repo = commit_key[0]
        contributor = _contributor_key(row)
        _add_day_metrics(
            org_days.setdefault(authored_day, _org_day_row(row, authored_day)),
            stats,
            contributor,
        )
        _add_day_metrics(
            repo_days.setdefault((repo, authored_day), _repo_day_row(row, repo, authored_day)),
            stats,
            contributor,
        )
        _add_day_metrics(
            contributor_days.setdefault(
                (repo, authored_day, contributor),
                _contributor_day_row(row, repo, authored_day),
            ),
            stats,
            contributor,
            track_unique_contributors=False,
        )

    if dataset == "org-days":
        rows = [_finalize_day_row(row) for row in org_days.values()]
        return sorted(rows, key=lambda row: str(row.get("date", "")), reverse=True)
    if dataset == "repo-days":
        rows = [_finalize_day_row(row) for row in repo_days.values()]
        return sorted(rows, key=lambda row: (str(row.get("date", "")), str(row.get("repo", ""))), reverse=True)
    if dataset == "contributor-days":
        rows = [_finalize_day_row(row) for row in contributor_days.values()]
        return sorted(
            rows,
            key=lambda row: (
                str(row.get("date", "")),
                str(row.get("repo", "")),
                str(row.get("author_login") or row.get("author_email") or row.get("author_name") or ""),
            ),
            reverse=True,
        )
    return None


def _org_day_row(commit_row: dict[str, object], authored_day: str) -> dict[str, object]:
    return {
        "run_id": commit_row.get("run_id"),
        "org": commit_row.get("org"),
        "date": authored_day,
        "commits": 0,
        "unique_contributors": set(),
        "lines_added": 0,
        "lines_deleted": 0,
        "file_changes": 0,
    }


def _repo_day_row(commit_row: dict[str, object], repo: str, authored_day: str) -> dict[str, object]:
    row = _org_day_row(commit_row, authored_day)
    row["repo"] = repo
    return row


def _contributor_day_row(commit_row: dict[str, object], repo: str, authored_day: str) -> dict[str, object]:
    row = _repo_day_row(commit_row, repo, authored_day)
    row["author_name"] = commit_row.get("author_name")
    row["author_email"] = commit_row.get("author_email")
    row["author_login"] = commit_row.get("author_login")
    row.pop("unique_contributors", None)
    return row


def _add_day_metrics(
    row: dict[str, object],
    stats: dict[str, int | float],
    contributor: str,
    *,
    track_unique_contributors: bool = True,
) -> None:
    row["commits"] = _number(row.get("commits")) + 1
    row["file_changes"] = _number(row.get("file_changes")) + _number(stats.get("file_changes"))
    row["lines_added"] = _number(row.get("lines_added")) + _number(stats.get("lines_added"))
    row["lines_deleted"] = _number(row.get("lines_deleted")) + _number(stats.get("lines_deleted"))
    if track_unique_contributors:
        contributors = row.setdefault("unique_contributors", set())
        if isinstance(contributors, set):
            contributors.add(contributor)


def _finalize_day_row(row: dict[str, object]) -> dict[str, object]:
    payload = {key: value for key, value in row.items() if value is not None}
    contributors = payload.get("unique_contributors")
    if isinstance(contributors, set):
        payload["unique_contributors"] = len(contributors)
    return payload


def _top_activity_from_jsonl(crawl_dir: Path | None) -> dict[str, list[dict[str, object]]] | None:
    if crawl_dir is None:
        return None
    commits_path = crawl_dir / "commits.jsonl"
    file_changes_path = crawl_dir / "file_changes.jsonl"
    if not commits_path.exists() or not file_changes_path.exists():
        return None

    commit_stats = _credited_commit_stats_from_file_changes(crawl_dir)
    if commit_stats is None:
        return None

    path_stats: dict[tuple[str, str, str], dict[str, object]] = {}
    for row in _iter_jsonl_objects(file_changes_path):
        if not _is_code_change_row(row) or not isinstance(row, dict):
            continue
        repo = str(row.get("repo", ""))
        path = str(row.get("path", ""))
        path_class = str(row.get("path_class", ""))
        key = (repo, path, path_class)
        payload = path_stats.setdefault(
            key,
            {
                "repo": repo,
                "path": path,
                "path_class": path_class,
                "file_changes": 0,
                "lines_added": 0,
                "lines_deleted": 0,
            },
        )
        payload["file_changes"] = _number(payload.get("file_changes")) + 1
        payload["lines_added"] = _number(payload.get("lines_added")) + _file_change_lines_added(row)
        payload["lines_deleted"] = _number(payload.get("lines_deleted")) + _file_change_lines_deleted(row)

    repo_stats: dict[str, dict[str, object]] = {}
    seen_commits: set[tuple[str, str]] = set()
    for row in _iter_jsonl_objects(commits_path):
        if not isinstance(row, dict):
            continue
        commit_key = _commit_key(row)
        if commit_key is None or commit_key in seen_commits:
            continue
        stats = commit_stats.get(commit_key)
        if stats is None:
            continue
        seen_commits.add(commit_key)
        repo = commit_key[0]
        payload = repo_stats.setdefault(
            repo,
            {"repo": repo, "commits": 0, "file_changes": 0, "lines_added": 0, "lines_deleted": 0},
        )
        payload["commits"] = _number(payload.get("commits")) + 1
        payload["file_changes"] = _number(payload.get("file_changes")) + _number(stats.get("file_changes"))
        payload["lines_added"] = _number(payload.get("lines_added")) + _number(stats.get("lines_added"))
        payload["lines_deleted"] = _number(payload.get("lines_deleted")) + _number(stats.get("lines_deleted"))

    return {
        "top_repositories": sorted(
            repo_stats.values(),
            key=lambda row: (_number(row.get("commits")), _number(row.get("lines_added"))),
            reverse=True,
        )[:10],
        "top_paths": sorted(
            path_stats.values(),
            key=lambda row: (_number(row.get("lines_added")), _number(row.get("file_changes"))),
            reverse=True,
        )[:10],
    }


def _repository_activity_payload(value: object) -> dict[str, int | float]:
    repositories = _mapping(value)
    return {
        "discovered": _number(repositories.get("discovered")),
        "selected": _number(repositories.get("selected")),
        "crawled": _number(repositories.get("crawled")),
        "excluded": _number(repositories.get("excluded")),
        "failed": _number(repositories.get("failed")),
    }


def _activity_average(totals: dict[str, int | float], denominator: int | float) -> dict[str, float]:
    return {
        "commits": _round_average(totals["commits"], denominator),
        "file_changes": _round_average(totals["file_changes"], denominator),
        "lines_added": _round_average(totals["lines_added"], denominator),
        "lines_deleted": _round_average(totals["lines_deleted"], denominator),
    }


def _round_average(value: int | float, denominator: int | float) -> float:
    if denominator <= 0:
        return 0.0
    return round(value / denominator, 2)


def _iter_jsonl_objects(path: Path) -> Iterator[object]:
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle):
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ApiProblem(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        f"invalid JSONL in {path.name} at line {line_number + 1}: {exc}",
                    ) from exc
    except UnicodeDecodeError as exc:
        raise ApiProblem(HTTPStatus.INTERNAL_SERVER_ERROR, f"invalid UTF-8 in {path.name}: {exc}") from exc
    except OSError as exc:
        raise ApiProblem(HTTPStatus.INTERNAL_SERVER_ERROR, f"could not read {path.name}: {exc}") from exc


def _authored_day(value: object) -> str | None:
    authored_at = _authored_timestamp(value)
    return authored_at.date().isoformat() if authored_at is not None else None


def _authored_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        authored_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if authored_at.tzinfo is None or authored_at.utcoffset() is None:
            authored_at = authored_at.replace(tzinfo=UTC)
        return authored_at.astimezone(UTC)
    except ValueError:
        return None


def _history_timestamp_window(
    summary: dict[str, object],
) -> tuple[datetime | None, datetime, bool]:
    since = _metadata_timestamp(summary.get("history_since"))
    explicit_until = _metadata_timestamp(summary.get("history_until"))
    if explicit_until is not None:
        return since, explicit_until, True
    now = datetime.now(UTC)
    tomorrow = now.date() + timedelta(days=1)
    implicit_until = datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=UTC)
    return since, implicit_until, False


def _metadata_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        timestamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def _is_timestamp_in_history_range(
    authored_at: datetime,
    since: datetime | None,
    until: datetime,
    *,
    until_inclusive: bool,
) -> bool:
    if since is not None and authored_at < since:
        return False
    return authored_at <= until if until_inclusive else authored_at < until


def _contributor_key(row: dict[str, object]) -> str:
    login = row.get("author_login")
    if isinstance(login, str) and login.strip():
        return f"login:{login.strip().lower()}"
    email = row.get("author_email")
    if isinstance(email, str) and email.strip():
        return f"email:{email.strip().lower()}"
    name = row.get("author_name")
    if isinstance(name, str) and name.strip():
        return f"name:{name.strip()}"
    return "unknown"


def _read_jsonl_page(
    path: Path,
    *,
    limit: int,
    offset: int,
    row_filter: Callable[[object], bool] | None = None,
    row_transform: Callable[[object], object] | None = None,
) -> dict[str, object]:
    if not path.exists():
        raise ApiProblem(HTTPStatus.NOT_FOUND, f"file not found: {path.name}")
    limit = min(max(limit, 1), MAX_LIMIT)
    offset = max(offset, 0)
    rows: list[object] = []
    row_index = 0
    has_more = False

    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ApiProblem(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        f"invalid JSONL in {path.name} at line {line_number + 1}: {exc}",
                    ) from exc
                if row_filter is not None and not row_filter(row):
                    continue
                if row_index < offset:
                    row_index += 1
                    continue
                if len(rows) >= limit:
                    has_more = True
                    break
                rows.append(row_transform(row) if row_transform is not None else row)
                row_index += 1
    except UnicodeDecodeError as exc:
        raise ApiProblem(HTTPStatus.INTERNAL_SERVER_ERROR, f"invalid UTF-8 in {path.name}: {exc}") from exc
    except OSError as exc:
        raise ApiProblem(HTTPStatus.INTERNAL_SERVER_ERROR, f"could not read {path.name}: {exc}") from exc

    return _pagination_payload(rows, offset=offset, limit=limit, has_more=has_more)


def _paginate_rows(rows: list[object], *, limit: int, offset: int) -> dict[str, object]:
    limit = min(max(limit, 1), MAX_LIMIT)
    offset = max(offset, 0)
    page = rows[offset : offset + limit]
    has_more = offset + len(page) < len(rows)
    return _pagination_payload(page, offset=offset, limit=limit, has_more=has_more)


def _pagination_payload(rows: list[object], *, offset: int, limit: int, has_more: bool) -> dict[str, object]:
    next_offset = offset + len(rows) if has_more else None
    return {
        "data": rows,
        "pagination": {
            "offset": offset,
            "limit": limit,
            "returned": len(rows),
            "next_offset": next_offset,
        },
    }


def _parse_netuid(value: str) -> int:
    if not value.isdigit():
        raise ApiProblem(HTTPStatus.BAD_REQUEST, "netuid must be an integer")
    return int(value)


def _parse_query_int(query: dict[str, list[str]], name: str, default: int) -> int:
    raw = query.get(name, [str(default)])[0]
    try:
        return int(raw)
    except ValueError as exc:
        raise ApiProblem(HTTPStatus.BAD_REQUEST, f"{name} must be an integer") from exc


def _mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _number(value: object) -> int | float:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int | float):
        return value
    return 0


def _number_from_keys(values: dict[str, object], *keys: str) -> int | float:
    for key in keys:
        if key in values:
            return _number(values.get(key))
    return 0


def _file_change_lines_added(row: dict[str, object]) -> int | float:
    return _number_from_keys(row, "additions", "lines_added")


def _file_change_lines_deleted(row: dict[str, object]) -> int | float:
    return _number_from_keys(row, "deletions", "lines_deleted")


def _text_key(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


if __name__ == "__main__":
    raise SystemExit(main())
