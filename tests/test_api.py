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


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


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
    (crawl_dir / "summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "history_since": "2025-01-01",
                "calendar_span": {"days": 10, "weeks": 2, "months": 1},
                "repositories": {"discovered": 4, "selected": 3, "crawled": 3, "excluded": 1, "failed": 0},
                "totals": {
                    "commits": 20,
                    "file_changes": 999,
                    "lines_added": 9999,
                    "lines_deleted": 888,
                    "active_days": 5,
                    "repo_days": 6,
                    "contributor_days": 7,
                    "distinct_contributor_keys": 2,
                },
                "source_like_totals": {
                    "commits": 20,
                    "file_changes": 40,
                    "lines_added": 400,
                    "lines_deleted": 20,
                    "active_days": 5,
                    "repo_days": 6,
                    "contributor_days": 7,
                    "distinct_contributors": 2,
                },
                "generated_like_totals": {"file_changes": 9, "lines_added": 90, "lines_deleted": 8},
            }
        ),
        encoding="utf-8",
    )
    (subnet_dir / "score.json").write_text(json.dumps({"score": 88.5, "percentile": 95.0}), encoding="utf-8")

    payload = list_subnets(tmp_path)

    assert len(payload) == 1
    subnet = payload[0]
    assert subnet["netuid"] == 94
    assert subnet["subnet_name"] == "Example subnet"
    assert subnet["has_crawl"] is True
    assert subnet["has_summary"] is True
    assert subnet["score"] == {"score": 88.5, "percentile": 95.0}
    assert subnet["target_count"] == 1
    assert subnet["repository_target_count"] == 0
    assert subnet["owner_target_count"] == 1
    assert subnet["unresolved_count"] == 0
    assert subnet["activity"]["activity_scope"] == "code_changes"
    assert subnet["activity"]["calculation_source"] == "summary"
    assert subnet["activity"]["totals"]["commits"] == 20
    assert subnet["activity"]["totals"]["file_changes"] == 40
    assert subnet["activity"]["averages"]["per_calendar_day"] == {
        "commits": 2.0,
        "file_changes": 4.0,
        "lines_added": 40.0,
        "lines_deleted": 2.0,
    }
    assert subnet["activity"]["averages"]["per_active_day"] == {
        "commits": 4.0,
        "file_changes": 8.0,
        "lines_added": 80.0,
        "lines_deleted": 4.0,
    }
    assert subnet["activity"]["churn_filter"]["excluded_generated_like_totals"] == {
        "file_changes": 9,
        "lines_added": 90,
        "lines_deleted": 8,
    }
    assert subnet["activity"]["churn_filter"]["excluded_totals_are_included_in_activity"] is False
    assert subnet["summary"]["activity"] == subnet["activity"]
    assert subnet["summary"]["score"] == {"score": 88.5, "percentile": 95.0}


def test_get_subnet_detail_lists_files_and_endpoints(tmp_path):
    subnet_dir = tmp_path / "subnets" / "94"
    subnet_dir.mkdir(parents=True)
    (subnet_dir / "subnet-targets.json").write_text(json.dumps({"targets": []}), encoding="utf-8")
    (subnet_dir / "unresolved.json").write_text("[]\n", encoding="utf-8")

    detail = get_subnet_detail(tmp_path, 94)

    assert detail["files"] == ["subnet-targets.json", "unresolved.json"]
    assert detail["endpoints"]["summary"] == "/api/subnets/94/summary"
    assert detail["endpoints"]["activity"] == "/api/subnets/94/activity"
    assert detail["endpoints"]["score"] == "/api/subnets/94/score"


def test_get_subnet_detail_omits_crawl_directory_contents_for_performance(tmp_path):
    subnet_dir = tmp_path / "subnets" / "94"
    crawl_dir = subnet_dir / "crawl"
    crawl_dir.mkdir(parents=True)
    (crawl_dir / "summary.json").write_text("{}", encoding="utf-8")
    (crawl_dir / "commits.jsonl").write_text(
        "\n".join(json.dumps({"sha": i}) for i in range(500)) + "\n",
        encoding="utf-8",
    )
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
    (crawl_dir / "summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "calendar_span": {"days": 2, "weeks": 1, "months": 1},
                "repositories": {"crawled": 1},
                "totals": {
                    "commits": 6,
                    "file_changes": 10,
                    "lines_added": 20,
                    "lines_deleted": 4,
                    "active_days": 2,
                    "distinct_contributor_keys": 1,
                },
                "source_like_totals": {
                    "commits": 6,
                    "file_changes": 8,
                    "lines_added": 16,
                    "lines_deleted": 2,
                    "active_days": 2,
                    "distinct_contributors": 1,
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "subnets" / "94" / "score.json").write_text(json.dumps({"score": 42.0}), encoding="utf-8")

    payload = get_subnet_dataset(tmp_path, 94, "summary")

    assert payload["status"] == "success"
    assert payload["score"] == {"score": 42.0}
    assert payload["activity"]["totals"]["file_changes"] == 8
    assert payload["activity"]["averages"]["per_calendar_day"]["file_changes"] == 4.0
    assert payload["activity"]["averages"]["per_active_day"]["commits"] == 3.0


def test_activity_endpoint_returns_consistent_code_changes_activity_payload(tmp_path):
    crawl_dir = tmp_path / "subnets" / "64" / "crawl"
    crawl_dir.mkdir(parents=True)
    (crawl_dir / "summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "history_since": "2025-01-01",
                "history_until": None,
                "calendar_span": {"days": 5, "weeks": 1, "months": 1},
                "repositories": {"discovered": 2, "selected": 1, "crawled": 1, "excluded": 1, "failed": 0},
                "totals": {
                    "commits": 10,
                    "file_changes": 1000,
                    "lines_added": 10000,
                    "lines_deleted": 5000,
                    "active_days": 2,
                    "repo_days": 2,
                    "contributor_days": 3,
                    "distinct_contributor_keys": 2,
                },
                "source_like_totals": {"file_changes": 20, "lines_added": 200, "lines_deleted": 50},
                "generated_like_totals": {"file_changes": 980, "lines_added": 9800, "lines_deleted": 4950},
                "path_classes": {"source": {"files_changed": 20, "lines_added": 200, "lines_deleted": 50}},
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        crawl_dir / "file_changes.jsonl",
        [
            {
                "repo": "owner/code",
                "sha": "code-a",
                "additions": 10,
                "deletions": 1,
                "path_class": "source",
                "is_generated_like": False,
            },
            {
                "repo": "owner/code",
                "sha": "code-a",
                "additions": 5,
                "deletions": 2,
                "path_class": "source",
                "is_generated_like": False,
            },
            {
                "repo": "owner/code",
                "sha": "code-b",
                "additions": 20,
                "deletions": 3,
                "path_class": "source",
                "is_generated_like": False,
            },
            {
                "repo": "owner/code",
                "sha": "code-b",
                "additions": 0,
                "lines_added": 999,
                "deletions": 0,
                "lines_deleted": 999,
                "path_class": "source",
                "is_generated_like": False,
            },
            {
                "repo": "owner/code",
                "sha": "noise-c",
                "additions": 1000,
                "deletions": 500,
                "path_class": "lockfile",
                "is_generated_like": True,
            },
            {
                "repo": "owner/code",
                "sha": "schema-d",
                "additions": 800,
                "deletions": 400,
                "path_class": "spec/schema-like",
                "is_generated_like": False,
            },
        ],
    )
    _write_jsonl(
        crawl_dir / "commits.jsonl",
        [
            {
                "repo": "owner/code",
                "sha": "code-a",
                "authored_at": "2025-01-01T10:00:00Z",
                "author_login": "alice",
            },
            {
                "repo": "owner/code",
                "sha": "code-b",
                "authored_at": "2025-01-02T10:00:00Z",
                "author_email": "bob@example.com",
            },
            {
                "repo": "owner/code",
                "sha": "noise-c",
                "authored_at": "2025-01-03T10:00:00Z",
                "author_login": "build-bot",
            },
            {
                "repo": "owner/code",
                "sha": "schema-d",
                "authored_at": "2025-01-04T10:00:00Z",
                "author_login": "schema-bot",
            },
        ],
    )

    payload = get_subnet_dataset(tmp_path, 64, "activity")

    assert payload["schema_version"] == "tao-git-crawl-activity-v1"
    assert payload["activity_scope"] == "code_changes"
    assert payload["calculation_source"] == "jsonl"
    assert payload["history"]["since"] == "2025-01-01"
    assert payload["repositories"]["crawled"] == 1
    assert payload["totals"] == {
        "commits": 2,
        "file_changes": 4,
        "lines_added": 35,
        "lines_deleted": 6,
        "active_days": 2,
        "repo_days": 2,
        "contributor_days": 2,
        "distinct_contributors": 2,
    }
    assert payload["averages"]["per_active_day"] == {
        "commits": 1.0,
        "file_changes": 2.0,
        "lines_added": 17.5,
        "lines_deleted": 3.0,
    }
    assert payload["averages"]["per_calendar_day"] == {
        "commits": 0.4,
        "file_changes": 0.8,
        "lines_added": 7.0,
        "lines_deleted": 1.2,
    }
    assert payload["churn_filter"]["excluded_classes"] == [
        "binary",
        "lockfile",
        "generated",
        "vendored",
        "spec/schema-like",
    ]
    assert payload["churn_filter"]["excluded_totals_are_included_in_activity"] is False


def test_summary_activity_matches_activity_endpoint_when_jsonl_rows_exist(tmp_path):
    crawl_dir = tmp_path / "subnets" / "94" / "crawl"
    crawl_dir.mkdir(parents=True)
    (crawl_dir / "summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "calendar_span": {"days": 1, "weeks": 1, "months": 1},
                "repositories": {"crawled": 1},
                "totals": {"commits": 99, "file_changes": 99, "lines_added": 99, "active_days": 99},
                "source_like_totals": {"commits": 9, "file_changes": 9, "lines_added": 9, "active_days": 9},
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        crawl_dir / "file_changes.jsonl",
        [
            {
                "repo": "owner/code",
                "sha": "code-a",
                "additions": 3,
                "deletions": 1,
                "path_class": "source",
                "is_generated_like": False,
            },
            {
                "repo": "owner/code",
                "sha": "lock-b",
                "additions": 300,
                "deletions": 100,
                "path_class": "lockfile",
                "is_generated_like": True,
            },
        ],
    )
    _write_jsonl(
        crawl_dir / "commits.jsonl",
        [
            {
                "repo": "owner/code",
                "sha": "code-a",
                "authored_at": "2025-01-01T10:00:00Z",
                "author_login": "dev",
            },
            {
                "repo": "owner/code",
                "sha": "lock-b",
                "authored_at": "2025-01-02T10:00:00Z",
                "author_login": "bot",
            },
        ],
    )
    (tmp_path / "subnets" / "94" / "score.json").write_text(json.dumps({"score": 42.0}), encoding="utf-8")

    summary_payload = get_subnet_dataset(tmp_path, 94, "summary")
    activity_payload = get_subnet_dataset(tmp_path, 94, "activity")

    assert summary_payload["activity"] == activity_payload
    assert activity_payload["calculation_source"] == "jsonl"
    assert activity_payload["totals"]["commits"] == 1
    assert activity_payload["totals"]["file_changes"] == 1


def test_activity_does_not_fall_back_to_raw_churn_totals(tmp_path):
    crawl_dir = tmp_path / "subnets" / "94" / "crawl"
    crawl_dir.mkdir(parents=True)
    (crawl_dir / "summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "calendar_span": {"days": 7, "weeks": 1, "months": 1},
                "repositories": {"crawled": 1},
                "totals": {
                    "commits": 30,
                    "file_changes": 500,
                    "lines_added": 10000,
                    "lines_deleted": 2000,
                    "active_days": 7,
                    "repo_days": 7,
                    "contributor_days": 10,
                    "distinct_contributor_keys": 4,
                },
            }
        ),
        encoding="utf-8",
    )

    payload = get_subnet_dataset(tmp_path, 94, "activity")

    assert payload["calculation_source"] == "unavailable"
    assert payload["totals"] == {
        "commits": 0,
        "file_changes": 0,
        "lines_added": 0,
        "lines_deleted": 0,
        "active_days": 0,
        "repo_days": 0,
        "contributor_days": 0,
        "distinct_contributors": 0,
    }


def test_activity_marks_present_empty_source_like_totals_as_summary_source(tmp_path):
    crawl_dir = tmp_path / "subnets" / "94" / "crawl"
    crawl_dir.mkdir(parents=True)
    (crawl_dir / "summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "repositories": {"crawled": 1},
                "totals": {"commits": 3, "file_changes": 100, "lines_added": 500, "active_days": 2},
                "source_like_totals": {},
            }
        ),
        encoding="utf-8",
    )

    payload = get_subnet_dataset(tmp_path, 94, "activity")

    assert payload["calculation_source"] == "summary"
    assert payload["totals"] == {
        "commits": 0,
        "file_changes": 0,
        "lines_added": 0,
        "lines_deleted": 0,
        "active_days": 0,
        "repo_days": 0,
        "contributor_days": 0,
        "distinct_contributors": 0,
    }


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
