import json
from http import HTTPStatus
from pathlib import Path

from tao_git_crawl.api import (
    SlidingWindowRateLimiter,
    get_subnet_dataset,
    get_subnet_detail,
    handle_api_request,
    list_subnets,
)


def test_list_subnets_includes_summary_and_target_counts(tmp_path):
    subnet_dir = tmp_path / "subnets" / "94"
    crawl_dir = subnet_dir / "crawl"
    crawl_dir.mkdir(parents=True)
    (subnet_dir / "subnet-targets.json").write_text(
        json.dumps(
            {
                "targets": [
                    {
                        "kind": "owner",
                        "subnet_name": "Example subnet",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (subnet_dir / "unresolved.json").write_text("[]\n", encoding="utf-8")
    (crawl_dir / "summary.json").write_text(json.dumps({"repositories": 3}), encoding="utf-8")
    (subnet_dir / "score.json").write_text(json.dumps({"score": 88.5, "percentile": 95.0}), encoding="utf-8")

    assert list_subnets(tmp_path) == [
        {
            "netuid": 94,
            "subnet_name": "Example subnet",
            "has_crawl": True,
            "has_summary": True,
            "summary": {"repositories": 3, "score": {"score": 88.5, "percentile": 95.0}},
            "score": {"score": 88.5, "percentile": 95.0},
            "target_count": 1,
            "repository_target_count": 0,
            "owner_target_count": 1,
            "unresolved_count": 0,
        }
    ]


def test_get_subnet_detail_lists_files_and_endpoints(tmp_path):
    subnet_dir = tmp_path / "subnets" / "94"
    subnet_dir.mkdir(parents=True)
    (subnet_dir / "subnet-targets.json").write_text(json.dumps({"targets": []}), encoding="utf-8")
    (subnet_dir / "unresolved.json").write_text("[]\n", encoding="utf-8")

    detail = get_subnet_detail(tmp_path, 94)

    assert detail["files"] == ["subnet-targets.json", "unresolved.json"]
    assert detail["endpoints"]["summary"] == "/api/subnets/94/summary"
    assert detail["endpoints"]["score"] == "/api/subnets/94/score"


def test_get_subnet_detail_omits_crawl_directory_contents_for_performance(tmp_path):
    subnet_dir = tmp_path / "subnets" / "94"
    crawl_dir = subnet_dir / "crawl"
    crawl_dir.mkdir(parents=True)
    (crawl_dir / "summary.json").write_text("{}", encoding="utf-8")
    (crawl_dir / "commits.jsonl").write_text("\n".join(json.dumps({"sha": i}) for i in range(500)) + "\n", encoding="utf-8")
    (subnet_dir / "subnet-targets.json").write_text(json.dumps({"targets": []}), encoding="utf-8")

    detail = get_subnet_detail(tmp_path, 94)

    assert "crawl/" in detail["files"]
    assert "crawl/summary.json" not in detail["files"]
    assert "crawl/commits.jsonl" not in detail["files"]


def test_get_subnet_dataset_paginates_jsonl(tmp_path):
    crawl_dir = tmp_path / "subnets" / "94" / "crawl"
    crawl_dir.mkdir(parents=True)
    (crawl_dir / "commits.jsonl").write_text(
        "\n".join(json.dumps({"sha": idx}) for idx in range(4)) + "\n",
        encoding="utf-8",
    )

    payload = get_subnet_dataset(tmp_path, 94, "commits", {"limit": ["2"], "offset": ["1"]})

    assert payload == {
        "data": [{"sha": 1}, {"sha": 2}],
        "pagination": {
            "offset": 1,
            "limit": 2,
            "returned": 2,
            "next_offset": 3,
        },
    }


def test_get_subnet_dataset_omits_next_offset_at_end(tmp_path):
    crawl_dir = tmp_path / "subnets" / "94" / "crawl"
    crawl_dir.mkdir(parents=True)
    (crawl_dir / "commits.jsonl").write_text(
        "\n".join(json.dumps({"sha": idx}) for idx in range(3)) + "\n",
        encoding="utf-8",
    )

    payload = get_subnet_dataset(tmp_path, 94, "commits", {"limit": ["2"], "offset": ["1"]})

    assert payload["pagination"]["next_offset"] is None


def test_handle_api_request_returns_json_errors(tmp_path):
    response = handle_api_request(tmp_path, "/api/subnets/nope")

    assert response.status == HTTPStatus.BAD_REQUEST
    assert response.payload == {"error": "netuid must be an integer"}


def test_handle_api_request_returns_aggregate_scores(tmp_path):
    (tmp_path / "subnet-scores.json").write_text(json.dumps({"scores": [{"netuid": 1}]}), encoding="utf-8")

    response = handle_api_request(tmp_path, "/api/scores")

    assert response.status == HTTPStatus.OK
    assert response.payload == {"scores": [{"netuid": 1}]}


def test_summary_endpoint_includes_score_when_available(tmp_path):
    crawl_dir = tmp_path / "subnets" / "94" / "crawl"
    crawl_dir.mkdir(parents=True)
    (crawl_dir / "summary.json").write_text(json.dumps({"status": "success"}), encoding="utf-8")
    (tmp_path / "subnets" / "94" / "score.json").write_text(json.dumps({"score": 42.0}), encoding="utf-8")

    payload = get_subnet_dataset(tmp_path, 94, "summary")

    assert payload == {"status": "success", "score": {"score": 42.0}}


def test_sliding_window_rate_limiter_blocks_and_recovers():
    now = 100.0
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=10, now=lambda: now)

    first = limiter.check("127.0.0.1")
    second = limiter.check("127.0.0.1")
    blocked = limiter.check("127.0.0.1")

    assert first.allowed is True
    assert first.remaining == 1
    assert second.allowed is True
    assert second.remaining == 0
    assert blocked.allowed is False
    assert blocked.retry_after_seconds == 10

    now = 110.0
    recovered = limiter.check("127.0.0.1")

    assert recovered.allowed is True
    assert recovered.remaining == 1


def test_sliding_window_rate_limiter_can_be_disabled():
    limiter = SlidingWindowRateLimiter(max_requests=0, window_seconds=60)

    decision = limiter.check("127.0.0.1")

    assert decision.allowed is True
    assert decision.remaining == 0


def test_api_is_exposed_in_project_metadata_and_compose():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert 'tao-git-crawl-api = "tao_git_crawl.api:main"' in pyproject
    assert "tao_git_crawl.api" in compose
    assert "TAO_API_PORT" in compose
    assert "tao-data:/data:ro" in compose


def test_readme_one_off_compose_command_overrides_entrypoint():
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "docker compose run --rm --entrypoint python scheduler" in readme
    assert "docker compose run --rm scheduler \\\n  python -m tao_git_crawl.cli crawl" not in readme
