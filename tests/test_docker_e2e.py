import json
import os
import socket
import subprocess
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_DOCKER_E2E = os.environ.get("TAO_GIT_CRAWL_DOCKER_E2E") == "1"

pytestmark = [
    pytest.mark.docker_e2e,
    pytest.mark.skipif(
        not RUN_DOCKER_E2E,
        reason="set TAO_GIT_CRAWL_DOCKER_E2E=1 to run Docker service E2E tests",
    ),
]


def test_docker_api_service_serves_mounted_crawl_outputs(tmp_path):
    output_dir = tmp_path / "output"
    _write_crawl_output_fixture(output_dir)
    host_port = _free_local_port()
    compose_file = tmp_path / "compose.yml"
    compose_file.write_text(_compose_file(output_dir, host_port), encoding="utf-8")
    project_name = f"tao-git-crawl-e2e-{uuid.uuid4().hex[:12]}"
    compose = _compose_command()

    try:
        _run_compose(compose, compose_file, project_name, "up", "-d", "--build", "api", timeout=600)
        _wait_for_healthy_service(host_port, compose, compose_file, project_name)

        health = _get_json(host_port, "/health")
        assert health["status"] == 200
        assert health["payload"] == {"ok": True, "output_dir": "/data/output", "subnets": 1}

        subnets = _get_json(host_port, "/api/subnets")
        assert subnets["status"] == 200
        subnet = subnets["payload"]["data"][0]
        assert subnet["netuid"] == 7
        assert subnet["has_crawl"] is True
        assert subnet["activity"]["totals"]["commits"] == 2
        assert subnet["activity"]["totals"]["file_changes"] == 2
        assert subnet["activity"]["skipped"]["by_reason"]["lockfile"]["file_changes"] == 1

        summary = _get_json(host_port, "/api/subnets/7/summary")
        assert summary["status"] == 200
        assert summary["payload"]["schema_version"] == "tao-git-crawl-subnet-summary-v2"
        assert summary["payload"]["score"] == {"score": 91.25, "percentile": 97.0}
        assert summary["payload"]["top_repositories"][0] == {
            "repo": "acme/api",
            "commits": 2,
            "file_changes": 2,
            "lines_added": 13,
            "lines_deleted": 2,
        }

        commits = _get_json(host_port, "/api/subnets/7/commits?limit=1&offset=0")
        assert commits["status"] == 200
        assert commits["payload"]["pagination"] == {
            "offset": 0,
            "limit": 1,
            "returned": 1,
            "next_offset": 1,
        }
        assert commits["payload"]["data"][0]["sha"] == "code-a"
        assert commits["payload"]["data"][0]["file_changes"] == 1
    finally:
        _run_compose(
            compose,
            compose_file,
            project_name,
            "down",
            "--volumes",
            "--remove-orphans",
            timeout=120,
            check=False,
        )


def _write_crawl_output_fixture(output_dir: Path) -> None:
    subnet_dir = output_dir / "subnets" / "7"
    crawl_dir = subnet_dir / "crawl"
    crawl_dir.mkdir(parents=True)
    _write_json(
        subnet_dir / "subnet-targets.json",
        {
            "targets": [
                {
                    "netuid": 7,
                    "kind": "repository",
                    "url": "https://github.com/acme/api",
                    "owner": "acme",
                    "repo": "api",
                    "repo_full_name": "acme/api",
                    "source_field": "subnet_identity.github_repo",
                    "raw_value": "github.com/acme/api",
                    "subnet_name": "E2E Subnet",
                }
            ]
        },
    )
    _write_json(subnet_dir / "unresolved.json", [])
    _write_json(subnet_dir / "score.json", {"score": 91.25, "percentile": 97.0})
    _write_json(
        output_dir / "subnet-scores.json",
        {"scores": [{"netuid": 7, "score": 91.25, "percentile": 97.0}]},
    )
    _write_json(
        output_dir / "crawl-report.json",
        {
            "succeeded": [{"netuid": 7, "target": "bittensor-subnet-7"}],
            "failed": [],
            "skipped_unresolved_netuids": [],
            "skipped_inaccessible": [],
        },
    )
    _write_json(
        crawl_dir / "summary.json",
        {
            "status": "success",
            "org": "bittensor-subnet-7",
            "run_id": "run-e2e",
            "ref_scope": "default-branch",
            "history_since": "2026-01-01",
            "history_until": "2026-01-02",
            "calendar_span": {"days": 2, "weeks": 1, "months": 1},
            "repositories": {"discovered": 1, "selected": 1, "crawled": 1, "excluded": 0, "failed": 0},
            "totals": {
                "commits": 3,
                "file_changes": 3,
                "lines_added": 112,
                "lines_deleted": 11,
                "active_days": 2,
                "repo_days": 2,
                "contributor_days": 2,
                "distinct_contributor_keys": 2,
            },
            "source_like_totals": {
                "commits": 2,
                "file_changes": 2,
                "lines_added": 13,
                "lines_deleted": 2,
                "active_days": 2,
                "repo_days": 2,
                "contributor_days": 2,
                "distinct_contributors": 2,
            },
        },
    )
    _write_jsonl(
        crawl_dir / "file_changes.jsonl",
        [
            {
                "run_id": "run-e2e",
                "org": "bittensor-subnet-7",
                "repo": "acme/api",
                "sha": "code-a",
                "path": "src/app.py",
                "path_class": "source",
                "additions": 10,
                "deletions": 2,
            },
            {
                "run_id": "run-e2e",
                "org": "bittensor-subnet-7",
                "repo": "acme/api",
                "sha": "code-b",
                "path": "README.md",
                "path_class": "docs",
                "additions": 3,
                "deletions": 0,
            },
            {
                "run_id": "run-e2e",
                "org": "bittensor-subnet-7",
                "repo": "acme/api",
                "sha": "lock-only",
                "path": "package-lock.json",
                "path_class": "lockfile",
                "additions": 99,
                "deletions": 9,
            },
        ],
    )
    _write_jsonl(
        crawl_dir / "commits.jsonl",
        [
            {
                "run_id": "run-e2e",
                "org": "bittensor-subnet-7",
                "repo": "acme/api",
                "sha": "code-a",
                "authored_at": "2026-01-01T12:00:00Z",
                "author_name": "Alice",
                "author_email": "alice@example.com",
                "author_login": "alice",
                "message": "Add app",
            },
            {
                "run_id": "run-e2e",
                "org": "bittensor-subnet-7",
                "repo": "acme/api",
                "sha": "code-b",
                "authored_at": "2026-01-02T12:00:00Z",
                "author_name": "Bob",
                "author_email": "bob@example.com",
                "author_login": "bob",
                "message": "Document app",
            },
            {
                "run_id": "run-e2e",
                "org": "bittensor-subnet-7",
                "repo": "acme/api",
                "sha": "lock-only",
                "authored_at": "2026-01-02T13:00:00Z",
                "author_name": "Bot",
                "author_email": "bot@example.com",
                "author_login": "bot",
                "message": "Refresh lockfile",
            },
        ],
    )


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def _compose_file(output_dir: Path, host_port: int) -> str:
    image = os.environ.get("TAO_GIT_CRAWL_DOCKER_IMAGE")
    service_source = (
        f"    image: {json.dumps(image)}\n"
        if image
        else (
            "    build:\n"
            f"      context: {json.dumps(str(REPO_ROOT))}\n"
            "      dockerfile: Dockerfile\n"
            "      args:\n"
            '        INSTALL_EXTRAS: ""\n'
        )
    )
    return (
        "services:\n"
        "  api:\n"
        f"{service_source}"
        '    entrypoint: ["python", "-m", "tao_git_crawl.api"]\n'
        "    environment:\n"
        "      TAO_API_OUTPUT_DIR: /data/output\n"
        "      TAO_API_HOST: 0.0.0.0\n"
        '      TAO_API_PORT: "8080"\n'
        '      TAO_API_RATE_LIMIT_REQUESTS: "0"\n'
        "    ports:\n"
        f'      - "127.0.0.1:{host_port}:8080"\n'
        "    volumes:\n"
        "      - type: bind\n"
        f"        source: {json.dumps(str(output_dir))}\n"
        "        target: /data/output\n"
        "        read_only: true\n"
    )


def _compose_command() -> list[str]:
    for command in (["docker", "compose"], ["docker-compose"]):
        try:
            result = subprocess.run(
                [*command, "version"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except FileNotFoundError:
            continue
        if result.returncode == 0:
            return command
    pytest.skip("Docker Compose is required for Docker E2E tests")


def _run_compose(
    compose: list[str],
    compose_file: Path,
    project_name: str,
    *args: str,
    timeout: int,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = [*compose, "-f", str(compose_file), "-p", project_name, *args]
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"command failed with exit code {result.returncode}: {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result


def _wait_for_healthy_service(
    host_port: int,
    compose: list[str],
    compose_file: Path,
    project_name: str,
) -> None:
    deadline = time.monotonic() + 90
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            health = _get_json(host_port, "/health")
            if health["status"] == 200 and health["payload"].get("ok") is True:
                return
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            last_error = exc
        time.sleep(1)
    logs = _run_compose(compose, compose_file, project_name, "logs", "--no-color", "api", timeout=60, check=False)
    raise AssertionError(
        f"Docker API service did not become healthy: {last_error}\n"
        f"stdout:\n{logs.stdout[-4000:]}\n"
        f"stderr:\n{logs.stderr[-4000:]}"
    )


def _get_json(host_port: int, path: str) -> dict[str, object]:
    request = Request(f"http://127.0.0.1:{host_port}{path}", method="GET")
    with urlopen(request, timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))
        return {
            "status": response.status,
            "payload": payload,
            "headers": dict(response.headers.items()),
        }


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
