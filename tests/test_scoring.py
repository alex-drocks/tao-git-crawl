import json

from tao_git_crawl.models import SubnetIdentityRecord
from tao_git_crawl.resolver import resolve_subnets
from tao_git_crawl.scoring import build_score_document, write_score_outputs


def _write_summary(output_dir, netuid, *, repos_crawled, file_changes, lines_added):
    crawl_dir = output_dir / "subnets" / str(netuid) / "crawl"
    crawl_dir.mkdir(parents=True)
    (crawl_dir / "summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "repositories": {"crawled": repos_crawled},
                "totals": {
                    "commits": 0,
                    "file_changes": file_changes,
                    "lines_added": lines_added,
                    "active_days": 0,
                    "distinct_contributor_keys": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    return crawl_dir


def _write_commits(crawl_dir, rows, *, repo="acme/repo"):
    normalized_rows = []
    for row in rows:
        normalized = dict(row)
        normalized.setdefault("repo", repo)
        normalized_rows.append(normalized)
    (crawl_dir / "commits.jsonl").write_text(
        "\n".join(json.dumps(row) for row in normalized_rows) + "\n",
        encoding="utf-8",
    )


def _write_file_changes(crawl_dir, rows):
    (crawl_dir / "file_changes.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def _write_source_file_changes(crawl_dir, changes, *, repo="acme/repo"):
    rows = []
    for sha, file_changes, lines_added in changes:
        additions = lines_added // file_changes if file_changes else 0
        rows.extend(
            {
                "repo": repo,
                "sha": sha,
                "path": f"src/{sha}-{index}.py",
                "additions": additions,
                "is_binary": False,
                "path_class": "source",
                "is_generated_like": False,
            }
            for index in range(file_changes)
        )
    _write_file_changes(crawl_dir, rows)


def test_build_score_document_uses_global_raw_max_and_full_population(tmp_path):
    document = resolve_subnets(
        [
            SubnetIdentityRecord(netuid=1, subnet_name="Strong", github_repo="https://github.com/acme/strong"),
            SubnetIdentityRecord(netuid=2, subnet_name="Small", github_repo="https://github.com/acme/small"),
            SubnetIdentityRecord(netuid=3, subnet_name="Missing"),
        ],
        target_label="bittensor-subnets",
    )
    strong_crawl = _write_summary(tmp_path, 1, repos_crawled=2, file_changes=10, lines_added=100)
    _write_commits(
        strong_crawl,
        [
            {
                "sha": "a",
                "authored_at": "2026-01-01T00:00:00+00:00",
                "author_login": "alice",
                "files_changed": 2,
            },
            {
                "sha": "b",
                "authored_at": "2026-01-01T12:00:00+00:00",
                "author_login": "alice",
                "files_changed": 1,
            },
            {
                "sha": "noise",
                "authored_at": "2026-01-02T00:00:00+00:00",
                "author_login": "noise",
                "files_changed": 0,
            },
            {
                "sha": "c",
                "authored_at": "2026-01-02T00:00:00+00:00",
                "author_login": "bob",
                "files_changed": 1,
            },
        ],
    )
    _write_source_file_changes(strong_crawl, [("a", 4, 40), ("b", 3, 30), ("c", 3, 30)])
    small_crawl = _write_summary(tmp_path, 2, repos_crawled=1, file_changes=5, lines_added=50)
    _write_commits(
        small_crawl,
        [
            {
                "sha": "d",
                "authored_at": "2026-01-03T00:00:00+00:00",
                "author_login": "cara",
                "files_changed": 1,
            }
        ],
    )
    _write_source_file_changes(small_crawl, [("d", 5, 50)])

    score_document = build_score_document(document, tmp_path)

    scores = {item["netuid"]: item for item in score_document["scores"]}
    assert score_document["normalization"]["metric_method"] == "global_max"
    assert score_document["normalization"]["score_method"] == "max_weighted_composite_to_100"
    assert score_document["normalization"]["rank_method"] == "competition_score_desc"
    assert score_document["normalization"]["metric_maxima"] == {
        "active_days": 2.0,
        "avg_credited_commits_per_active_day": 1.5,
        "credited_file_changes": 10.0,
        "credited_lines_added": 100.0,
        "distinct_contributors": 2.0,
        "repos_crawled": 2.0,
    }
    assert scores[1]["score"] == 100.0
    assert scores[1]["composite_score"] == 100.0
    assert scores[1]["rank"] == 1
    assert scores[1]["rank_total"] == 3
    assert scores[1]["percentile"] == 100.0
    assert scores[1]["raw_metrics"]["avg_credited_commits_per_active_day"] == 1.5
    assert scores[1]["raw_metrics"]["active_days"] == 2.0
    assert scores[1]["raw_metrics"]["distinct_contributors"] == 2.0
    assert scores[2]["score"] == 54.17
    assert scores[2]["composite_score"] == 54.17
    assert scores[2]["rank"] == 2
    assert scores[2]["rank_total"] == 3
    assert scores[2]["percentile"] == 50.0
    assert scores[3]["score"] == 0.0
    assert scores[3]["composite_score"] == 0.0
    assert scores[3]["rank"] == 3
    assert scores[3]["rank_total"] == 3
    assert scores[3]["status"] == "unresolved"
    assert scores[3]["percentile"] == 0.0


def test_score_is_rescaled_so_top_composite_is_100(tmp_path):
    document = resolve_subnets(
        [
            SubnetIdentityRecord(netuid=1, subnet_name="Broad", github_repo="https://github.com/acme/broad"),
            SubnetIdentityRecord(netuid=2, subnet_name="Bursty", github_repo="https://github.com/acme/bursty"),
        ],
        target_label="bittensor-subnets",
    )
    broad_crawl = _write_summary(tmp_path, 1, repos_crawled=10, file_changes=80, lines_added=80)
    _write_commits(
        broad_crawl,
        [
            {
                "sha": f"broad-{index}",
                "authored_at": f"2026-01-{index + 1:02d}T00:00:00+00:00",
                "author_login": f"dev-{index % 5}",
                "files_changed": 1,
            }
            for index in range(10)
        ],
    )
    _write_source_file_changes(
        broad_crawl,
        [(f"broad-{index}", 8, 8) for index in range(10)],
    )
    bursty_crawl = _write_summary(tmp_path, 2, repos_crawled=1, file_changes=100, lines_added=100)
    _write_commits(
        bursty_crawl,
        [
            {
                "sha": f"bursty-{index}",
                "authored_at": "2026-01-01T00:00:00+00:00",
                "author_login": f"dev-{index}",
                "files_changed": 1,
            }
            for index in range(10)
        ],
    )
    _write_source_file_changes(
        bursty_crawl,
        [(f"bursty-{index}", 10, 10) for index in range(10)],
    )

    scores = {item["netuid"]: item for item in build_score_document(document, tmp_path)["scores"]}

    assert scores[2]["composite_score"] == 73.0
    assert scores[2]["score"] == 100.0
    assert scores[2]["rank"] == 1
    assert scores[1]["composite_score"] == 65.5
    assert scores[1]["score"] == 89.73
    assert scores[1]["rank"] == 2


def test_equal_scores_share_the_same_rank(tmp_path):
    document = resolve_subnets(
        [
            SubnetIdentityRecord(netuid=1, subnet_name="Alpha", github_repo="https://github.com/acme/alpha"),
            SubnetIdentityRecord(netuid=2, subnet_name="Beta", github_repo="https://github.com/acme/beta"),
            SubnetIdentityRecord(netuid=3, subnet_name="Missing"),
        ],
        target_label="bittensor-subnets",
    )
    alpha_crawl = _write_summary(tmp_path, 1, repos_crawled=1, file_changes=10, lines_added=100)
    beta_crawl = _write_summary(tmp_path, 2, repos_crawled=1, file_changes=10, lines_added=100)
    for crawl_dir, sha in [(alpha_crawl, "a"), (beta_crawl, "b")]:
        _write_commits(
            crawl_dir,
            [
                {
                    "sha": sha,
                    "authored_at": "2026-01-01T00:00:00+00:00",
                    "author_login": "dev",
                    "files_changed": 1,
                }
            ],
        )
        _write_source_file_changes(crawl_dir, [(sha, 10, 100)])

    scores = {item["netuid"]: item for item in build_score_document(document, tmp_path)["scores"]}

    assert scores[1]["score"] == 100.0
    assert scores[2]["score"] == 100.0
    assert scores[1]["rank"] == 1
    assert scores[2]["rank"] == 1
    assert scores[3]["rank"] == 3
    assert scores[1]["rank_total"] == 3


def test_write_score_outputs_writes_aggregate_and_per_subnet_files(tmp_path):
    document = resolve_subnets(
        [SubnetIdentityRecord(netuid=1, subnet_name="Example", github_repo="https://github.com/acme/api")],
        target_label="bittensor-subnets",
    )
    crawl_dir = _write_summary(tmp_path, 1, repos_crawled=1, file_changes=1, lines_added=10)
    _write_commits(
        crawl_dir,
        [
            {
                "sha": "a",
                "authored_at": "2026-01-01T00:00:00+00:00",
                "author_email": "dev@example.com",
                "files_changed": 1,
            }
        ],
    )
    _write_source_file_changes(crawl_dir, [("a", 1, 10)])

    written = write_score_outputs(document, tmp_path)

    assert tmp_path / "subnet-scores.json" in written
    assert tmp_path / "subnets" / "1" / "score.json" in written
    score = json.loads((tmp_path / "subnets" / "1" / "score.json").read_text(encoding="utf-8"))
    assert score["score"] == 100.0
    assert score["rank"] == 1
    assert score["rank_total"] == 1


def test_score_prefers_git_crawl_path_classification_when_file_changes_are_available(tmp_path):
    document = resolve_subnets(
        [SubnetIdentityRecord(netuid=1, subnet_name="Example", github_repo="https://github.com/acme/api")],
        target_label="bittensor-subnets",
    )
    crawl_dir = _write_summary(tmp_path, 1, repos_crawled=1, file_changes=999, lines_added=9999)
    _write_commits(
        crawl_dir,
        [
            {
                "repo": "acme/api",
                "sha": "source",
                "authored_at": "2026-01-01T00:00:00+00:00",
                "author_login": "dev",
                "files_changed": 2,
            },
            {
                "repo": "acme/api",
                "sha": "lock",
                "authored_at": "2026-01-02T00:00:00+00:00",
                "author_login": "bot",
                "files_changed": 1,
            },
            {
                "repo": "acme/api",
                "sha": "schema",
                "authored_at": "2026-01-03T00:00:00+00:00",
                "author_login": "schema-bot",
                "files_changed": 1,
            },
        ],
    )
    _write_file_changes(
        crawl_dir,
        [
            {
                "repo": "acme/api",
                "sha": "source",
                "path": "src/app.py",
                "additions": 10,
                "is_binary": False,
                "path_class": "source",
                "is_generated_like": False,
            },
            {
                "repo": "acme/api",
                "sha": "source",
                "path": "src/lib.py",
                "additions": 20,
                "is_binary": False,
                "path_class": "source",
                "is_generated_like": False,
            },
            {
                "repo": "acme/api",
                "sha": "lock",
                "path": "package-lock.json",
                "additions": 10000,
                "is_binary": False,
                "path_class": "lockfile",
                "is_generated_like": True,
            },
            {
                "repo": "acme/api",
                "sha": "schema",
                "path": "schema/openapi.json",
                "additions": 5000,
                "is_binary": False,
                "path_class": "spec/schema-like",
                "is_generated_like": False,
            },
        ],
    )

    score = build_score_document(document, tmp_path)["scores"][0]

    assert score["raw_metrics"]["credited_file_changes"] == 2.0
    assert score["raw_metrics"]["credited_lines_added"] == 30.0
    assert score["raw_metrics"]["active_days"] == 1.0
    assert score["raw_metrics"]["distinct_contributors"] == 1.0


def test_score_does_not_fall_back_to_raw_churn_totals(tmp_path):
    document = resolve_subnets(
        [SubnetIdentityRecord(netuid=1, subnet_name="Example", github_repo="https://github.com/acme/api")],
        target_label="bittensor-subnets",
    )
    _write_summary(tmp_path, 1, repos_crawled=1, file_changes=999, lines_added=9999)

    score = build_score_document(document, tmp_path)["scores"][0]

    assert score["raw_metrics"]["credited_file_changes"] == 0.0
    assert score["raw_metrics"]["credited_lines_added"] == 0.0
    assert score["raw_metrics"]["active_days"] == 0.0
    assert score["raw_metrics"]["avg_credited_commits_per_active_day"] == 0.0
    assert score["raw_metrics"]["distinct_contributors"] == 0.0
    assert score["raw_metrics"]["repos_crawled"] == 0.0
    assert score["score"] == 0.0


def test_score_uses_filtered_summary_totals_when_detailed_rows_are_unavailable(tmp_path):
    document = resolve_subnets(
        [SubnetIdentityRecord(netuid=1, subnet_name="Example", github_repo="https://github.com/acme/api")],
        target_label="bittensor-subnets",
    )
    crawl_dir = tmp_path / "subnets" / "1" / "crawl"
    crawl_dir.mkdir(parents=True)
    (crawl_dir / "summary.json").write_text(
        json.dumps(
            {
                "status": "success",
                "repositories": {"crawled": 1},
                "totals": {
                    "commits": 50,
                    "file_changes": 999,
                    "lines_added": 9999,
                    "active_days": 20,
                    "distinct_contributor_keys": 10,
                },
                "source_like_totals": {
                    "commits": 2,
                    "file_changes": 3,
                    "lines_added": 30,
                    "active_days": 1,
                    "distinct_contributors": 1,
                },
            }
        ),
        encoding="utf-8",
    )

    score = build_score_document(document, tmp_path)["scores"][0]

    assert score["raw_metrics"]["avg_credited_commits_per_active_day"] == 2.0
    assert score["raw_metrics"]["credited_file_changes"] == 3.0
    assert score["raw_metrics"]["credited_lines_added"] == 30.0
    assert score["raw_metrics"]["active_days"] == 1.0
    assert score["raw_metrics"]["distinct_contributors"] == 1.0


def test_score_active_days_match_git_crawl_utc_day_convention(tmp_path):
    document = resolve_subnets(
        [SubnetIdentityRecord(netuid=1, subnet_name="Example", github_repo="https://github.com/acme/api")],
        target_label="bittensor-subnets",
    )
    crawl_dir = _write_summary(tmp_path, 1, repos_crawled=1, file_changes=2, lines_added=20)
    _write_commits(
        crawl_dir,
        [
            {
                "repo": "acme/api",
                "sha": "a",
                "authored_at": "2026-01-01T23:30:00-02:00",
                "author_login": "dev",
                "files_changed": 1,
            },
            {
                "repo": "acme/api",
                "sha": "b",
                "authored_at": "2026-01-02T00:30:00+00:00",
                "author_login": "dev",
                "files_changed": 1,
            },
        ],
    )
    _write_file_changes(
        crawl_dir,
        [
            {
                "repo": "acme/api",
                "sha": "a",
                "path": "src/app.py",
                "additions": 10,
                "is_binary": False,
                "path_class": "source",
                "is_generated_like": False,
            },
            {
                "repo": "acme/api",
                "sha": "b",
                "path": "src/lib.py",
                "additions": 10,
                "is_binary": False,
                "path_class": "source",
                "is_generated_like": False,
            },
        ],
    )

    score = build_score_document(document, tmp_path)["scores"][0]

    assert score["raw_metrics"]["active_days"] == 1.0
    assert score["raw_metrics"]["avg_credited_commits_per_active_day"] == 2.0
