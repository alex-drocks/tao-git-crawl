from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from math import ceil
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, unquote, urlparse

DEFAULT_OUTPUT_DIR = Path("/data/output")
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080
DEFAULT_LIMIT = 100
MAX_LIMIT = 1000
DEFAULT_RATE_LIMIT_REQUESTS = 1200
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60

JSON_DATASETS = {
    "summary": "summary.json",
    "score": "score.json",
    "manifest": "output_manifest.json",
    "targets": "subnet-targets.json",
    "owner-targets": "owner-targets.json",
    "repository-manifest": "repository-manifest.json",
    "unresolved": "unresolved.json",
}

JSONL_DATASETS = {
    "repositories": "repositories.jsonl",
    "commits": "commits.jsonl",
    "contributors": "contributor_days.jsonl",
    "contributor-days": "contributor_days.jsonl",
    "repo-days": "repo_days.jsonl",
    "org-days": "org_days.jsonl",
    "file-changes": "file_changes.jsonl",
    "failures": "repo_failures.jsonl",
    "excluded": "excluded_repositories.jsonl",
    "crawl-runs": "crawl_runs.jsonl",
}


@dataclass(frozen=True)
class ApiResponse:
    status: HTTPStatus
    payload: object


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int = 0


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
            return ApiResponse(HTTPStatus.OK, _health_payload(output_path))
        if parts == ["api", "crawl-report"]:
            return ApiResponse(HTTPStatus.OK, _read_json_required(output_path / "crawl-report.json"))
        if parts == ["api", "scores"]:
            return ApiResponse(HTTPStatus.OK, _read_json_required(output_path / "subnet-scores.json"))
        if parts == ["api", "subnets"]:
            return ApiResponse(HTTPStatus.OK, {"data": list_subnets(output_path)})
        if len(parts) >= 3 and parts[:2] == ["api", "subnets"]:
            netuid = _parse_netuid(parts[2])
            if len(parts) == 3:
                return ApiResponse(HTTPStatus.OK, get_subnet_detail(output_path, netuid))
            if len(parts) == 4:
                return ApiResponse(HTTPStatus.OK, get_subnet_dataset(output_path, netuid, parts[3], query))
        raise ApiProblem(HTTPStatus.NOT_FOUND, "unknown endpoint")
    except ApiProblem as exc:
        return ApiResponse(exc.status, {"error": exc.message})


def list_subnets(output_dir: str | Path) -> list[dict[str, object]]:
    subnets_dir = Path(output_dir) / "subnets"
    if not subnets_dir.exists():
        return []
    return [
        _subnet_overview(subnet_dir)
        for subnet_dir in sorted(
            (path for path in subnets_dir.iterdir() if path.is_dir() and path.name.isdigit()),
            key=lambda path: int(path.name),
        )
    ]


def get_subnet_detail(output_dir: str | Path, netuid: int) -> dict[str, object]:
    subnet_dir = _subnet_dir(Path(output_dir), netuid)
    overview = _subnet_overview(subnet_dir)
    overview["files"] = _subnet_files(subnet_dir)
    overview["endpoints"] = _subnet_endpoints(netuid)
    return overview


def get_subnet_dataset(
    output_dir: str | Path,
    netuid: int,
    dataset: str,
    query: dict[str, list[str]] | None = None,
) -> dict[str, object] | list[object] | object:
    subnet_dir = _subnet_dir(Path(output_dir), netuid)
    crawl_dir = subnet_dir / "crawl"
    query_params = query or {}

    if dataset in JSON_DATASETS:
        if dataset == "summary":
            return _summary_with_score(
                _read_json_required(crawl_dir / JSON_DATASETS[dataset]),
                _read_json_optional(subnet_dir / "score.json"),
            )
        path = (
            (crawl_dir / JSON_DATASETS[dataset])
            if dataset in {"summary", "manifest"}
            else subnet_dir / JSON_DATASETS[dataset]
        )
        return _read_json_required(path)

    if dataset in JSONL_DATASETS:
        limit = _parse_query_int(query_params, "limit", DEFAULT_LIMIT)
        offset = _parse_query_int(query_params, "offset", 0)
        return _read_jsonl_page(crawl_dir / JSONL_DATASETS[dataset], limit=limit, offset=offset)

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
        "routes": [
            "/health",
            "/api/subnets",
            "/api/subnets/{netuid}",
            "/api/subnets/{netuid}/summary",
            "/api/subnets/{netuid}/score",
            "/api/subnets/{netuid}/repositories?limit=100&offset=0",
            "/api/subnets/{netuid}/commits?limit=100&offset=0",
            "/api/subnets/{netuid}/contributors?limit=100&offset=0",
            "/api/subnets/{netuid}/repo-days?limit=100&offset=0",
            "/api/subnets/{netuid}/org-days?limit=100&offset=0",
            "/api/subnets/{netuid}/file-changes?limit=100&offset=0",
            "/api/crawl-report",
            "/api/scores",
        ],
    }


def _health_payload(output_dir: Path) -> dict[str, object]:
    return {
        "ok": output_dir.exists(),
        "output_dir": str(output_dir),
        "subnets": len(list_subnets(output_dir)),
    }


def _subnet_overview(subnet_dir: Path) -> dict[str, object]:
    netuid = int(subnet_dir.name)
    targets_doc = _read_json_optional(subnet_dir / "subnet-targets.json")
    unresolved = _read_json_optional(subnet_dir / "unresolved.json") or []
    targets = targets_doc.get("targets", []) if isinstance(targets_doc, dict) else []
    repository_targets = [
        target for target in targets if isinstance(target, dict) and target.get("kind") == "repository"
    ]
    owner_targets = [target for target in targets if isinstance(target, dict) and target.get("kind") == "owner"]
    summary = _read_json_optional(subnet_dir / "crawl" / "summary.json")
    score = _read_json_optional(subnet_dir / "score.json")

    return {
        "netuid": netuid,
        "subnet_name": _subnet_name(targets, unresolved),
        "has_crawl": (subnet_dir / "crawl").exists(),
        "has_summary": summary is not None,
        "summary": _summary_with_score(summary, score),
        "score": score,
        "target_count": len(targets),
        "repository_target_count": len(repository_targets),
        "owner_target_count": len(owner_targets),
        "unresolved_count": len(unresolved) if isinstance(unresolved, list) else 0,
    }


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
            # Do not recurse into crawl/ to avoid listing large JSONL/CSV outputs.
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
        "targets": f"{base}/targets",
        "owner_targets": f"{base}/owner-targets",
        "repository_manifest": f"{base}/repository-manifest",
        "unresolved": f"{base}/unresolved",
        "score": f"{base}/score",
    }
    endpoints.update({dataset.replace("-", "_"): f"{base}/{dataset}?limit=100&offset=0" for dataset in JSONL_DATASETS})
    return endpoints


def _subnet_dir(output_dir: Path, netuid: int) -> Path:
    subnet_dir = output_dir / "subnets" / str(netuid)
    if not subnet_dir.exists():
        raise ApiProblem(HTTPStatus.NOT_FOUND, f"subnet {netuid} not found")
    return subnet_dir


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
    except json.JSONDecodeError as exc:
        raise ApiProblem(HTTPStatus.INTERNAL_SERVER_ERROR, f"invalid JSON in {path.name}: {exc}") from exc


def _summary_with_score(summary: object, score: object | None) -> object:
    if not isinstance(summary, dict):
        return summary
    enriched = dict(summary)
    enriched["score"] = score
    return enriched


def _read_jsonl_page(path: Path, *, limit: int, offset: int) -> dict[str, object]:
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
                if row_index < offset:
                    row_index += 1
                    continue
                if len(rows) >= limit:
                    has_more = True
                    break
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ApiProblem(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        f"invalid JSONL in {path.name} at line {line_number + 1}: {exc}",
                    ) from exc
                row_index += 1
    except OSError as exc:
        raise ApiProblem(HTTPStatus.INTERNAL_SERVER_ERROR, f"could not read {path.name}: {exc}") from exc

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


if __name__ == "__main__":
    raise SystemExit(main())
