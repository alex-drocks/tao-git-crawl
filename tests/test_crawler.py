import json
from types import SimpleNamespace

from git_crawl.github import GitHubAPIError, partition_repositories
from git_crawl.metrics import CommitChangesFiltrationLevel

from tao_git_crawl.crawler import crawl_resolved_subnets
from tao_git_crawl.identity_epochs import epoch_scoped_target
from tao_git_crawl.models import SubnetIdentityRecord
from tao_git_crawl.overrides import ResolverConfig, SubnetOverride, TargetOverride
from tao_git_crawl.resolver import resolve_subnets


def _repo(
    full_name,
    *,
    archived=False,
    fork=False,
    private=False,
    pushed_at="2026-02-01T00:00:00Z",
):
    return SimpleNamespace(
        name=full_name.rsplit("/", 1)[-1],
        full_name=full_name,
        clone_url=f"https://github.com/{full_name}.git",
        ssh_url=f"git@github.com:{full_name}.git",
        default_branch="main",
        pushed_at=pushed_at,
        archived=archived,
        fork=fork,
        private=private,
        language=None,
    )


def _selected_repo_names_for_crawl(repositories, kwargs):
    selected, _excluded = partition_repositories(
        repositories,
        active_since=kwargs["active_since"],
        include_archived=kwargs["include_archived"],
        include_forks=kwargs["include_forks"],
        max_repos=kwargs["max_repos"],
    )
    return [repo.full_name for repo in selected], selected


def test_crawl_resolved_subnets_discovers_owner_repos_and_labels_metrics_by_subnet(monkeypatch, tmp_path):
    document = resolve_subnets(
        [SubnetIdentityRecord(netuid=64, subnet_name="Chutes", github_repo="https://github.com/chutesai/api")],
        target_label="bittensor-subnets",
        config=ResolverConfig(default_repository_policy="owner"),
    )
    repo = SimpleNamespace(name="api", full_name="chutesai/api")
    calls = {"owners": [], "repo_manifests": [], "crawls": [], "writes": []}

    def fake_list_owner_repositories(owner, *, owner_type="auto", token=None):
        calls["owners"].append((owner, owner_type, token))
        return [repo]

    def fake_list_repositories_from_urls(urls, **kwargs):
        calls["repo_manifests"].append((list(urls), kwargs))
        return []

    def fake_crawl_repositories(target_label, repositories, **kwargs):
        calls["crawls"].append((target_label, [item.full_name for item in repositories], kwargs))
        return SimpleNamespace(
            run=SimpleNamespace(status="success", run_id="test-run-0"),
            repositories=list(repositories),
        )

    def fake_write_crawl_outputs(result, output_dir, *, write_json=True, write_csv_files=True):
        calls["writes"].append((output_dir, write_json, write_csv_files))
        output_dir.mkdir(parents=True, exist_ok=True)
        summary_path = output_dir / "summary.json"
        summary_path.write_text('{"status":"success"}\n', encoding="utf-8")
        return [summary_path]

    monkeypatch.setattr("tao_git_crawl.crawler.list_owner_repositories", fake_list_owner_repositories)
    monkeypatch.setattr("tao_git_crawl.crawler.list_repositories_from_urls", fake_list_repositories_from_urls)
    monkeypatch.setattr("tao_git_crawl.crawler.crawl_repositories", fake_crawl_repositories)
    monkeypatch.setattr("tao_git_crawl.crawler.write_crawl_outputs", fake_write_crawl_outputs)

    report = crawl_resolved_subnets(
        document,
        output_dir=tmp_path / "out",
        cache_dir=tmp_path / "cache",
        state_db=tmp_path / "state" / "git-crawl.sqlite",
        since="2026-01-01",
        workers=2,
    )

    assert calls["owners"] == [("chutesai", "auto", None)]
    assert calls["repo_manifests"] == []
    expected_target = epoch_scoped_target(
        "bittensor-subnet-64",
        document.identity_epoch_for_netuid(64),
    )
    assert calls["crawls"] == [
        (
            expected_target,
            ["chutesai/api"],
            {
                "cache_dir": tmp_path / "cache",
                "state_db": tmp_path / "state" / "git-crawl.sqlite",
                "active_since": None,
                "since": "2026-01-01",
                "until": None,
                "include_archived": False,
                "include_forks": False,
                "max_repos": None,
                "prefer_ssh": False,
                "ref_scope": "default-branch",
                "workers": 2,
                "fail_fast": False,
                "commit_changes_filtration_level": CommitChangesFiltrationLevel.SOURCE_LIKE,
            },
        )
    ]
    assert calls["writes"] == [(tmp_path / "out" / "subnets" / "64" / "crawl", True, False)]
    assert report.succeeded_netuids == [64]
    assert report.failed == []
    assert (tmp_path / "out" / "subnets" / "64" / "crawl" / "summary.json").exists()
    assert (tmp_path / "out" / "subnet-scores.json").exists()
    assert (tmp_path / "out" / "subnets" / "64" / "score.json").exists()


def test_crawl_resolved_subnets_publishes_score_progress_before_full_run_finishes(monkeypatch, tmp_path):
    document = resolve_subnets(
        [
            SubnetIdentityRecord(netuid=1, subnet_name="One", github_repo="https://github.com/alice/api"),
            SubnetIdentityRecord(netuid=2, subnet_name="Two", github_repo="https://github.com/bob/app"),
        ],
        target_label="bittensor-subnets",
    )
    output_dir = tmp_path / "out"
    crawl_calls = []

    def fake_list_repositories_from_urls(urls, **kwargs):
        url = next(iter(urls))
        if "alice/api" in url:
            return [_repo("alice/api")]
        return [_repo("bob/app")]

    def fake_crawl_repositories(target_label, repositories, **kwargs):
        crawl_calls.append(target_label)
        if target_label.startswith("bittensor-subnet-2-"):
            first_score = json.loads((output_dir / "subnets" / "1" / "score.json").read_text(encoding="utf-8"))
            aggregate_scores = json.loads((output_dir / "subnet-scores.json").read_text(encoding="utf-8"))
            assert first_score["status"] == "scored"
            assert any(item["netuid"] == 1 and item["status"] == "scored" for item in aggregate_scores["scores"])
        return SimpleNamespace(
            run=SimpleNamespace(status="success", run_id=f"test-run-{len(crawl_calls)}"),
            repositories=list(repositories),
        )

    def fake_write_crawl_outputs(result, output_dir, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "summary.json"
        path.write_text(
            json.dumps(
                {
                    "status": "success",
                    "repositories": {"crawled": len(result.repositories)},
                    "totals": {
                        "commits": 3,
                        "active_days": 2,
                        "distinct_contributor_keys": 2,
                    },
                    "source_like_totals": {
                        "file_changes": 7,
                        "lines_added": 50,
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return [path]

    monkeypatch.setattr("tao_git_crawl.crawler.list_repositories_from_urls", fake_list_repositories_from_urls)
    monkeypatch.setattr("tao_git_crawl.crawler.crawl_repositories", fake_crawl_repositories)
    monkeypatch.setattr("tao_git_crawl.crawler.write_crawl_outputs", fake_write_crawl_outputs)

    report = crawl_resolved_subnets(document, output_dir=output_dir, cache_dir=tmp_path / "cache")

    assert report.succeeded_netuids == [1, 2]
    assert crawl_calls == [
        epoch_scoped_target("bittensor-subnet-1", document.identity_epoch_for_netuid(1)),
        epoch_scoped_target("bittensor-subnet-2", document.identity_epoch_for_netuid(2)),
    ]


def test_crawl_resolved_subnets_skips_inaccessible_github_404_targets(monkeypatch, tmp_path):
    document = resolve_subnets(
        [
            SubnetIdentityRecord(netuid=1, subnet_name="Good", github_repo="https://github.com/alice/api"),
            SubnetIdentityRecord(netuid=2, subnet_name="Gone", github_repo="https://github.com/gone/missing"),
            SubnetIdentityRecord(netuid=3, subnet_name="Missing"),
        ],
        target_label="bittensor-subnets",
    )

    def fake_list_repositories_from_urls(urls, **kwargs):
        url = next(iter(urls))
        if "gone/missing" in url:
            raise GitHubAPIError(
                "GitHub API request failed with HTTP 404: Not Found",
                status_code=404,
                url="https://api.github.com/repos/gone/missing",
            )
        return [SimpleNamespace(name="api", full_name="alice/api")]

    def fake_crawl_repositories(target_label, repositories, **kwargs):
        return SimpleNamespace(
            run=SimpleNamespace(status="success", run_id="test-run-0"),
            repositories=list(repositories),
        )

    def fake_write_crawl_outputs(result, output_dir, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "summary.json"
        path.write_text("{}\n", encoding="utf-8")
        return [path]

    monkeypatch.setattr("tao_git_crawl.crawler.list_repositories_from_urls", fake_list_repositories_from_urls)
    monkeypatch.setattr("tao_git_crawl.crawler.crawl_repositories", fake_crawl_repositories)
    monkeypatch.setattr("tao_git_crawl.crawler.write_crawl_outputs", fake_write_crawl_outputs)

    report = crawl_resolved_subnets(document, output_dir=tmp_path / "out", cache_dir=tmp_path / "cache")

    assert report.succeeded_netuids == [1]
    assert report.failed == []
    assert [(skip.netuid, skip.reason) for skip in report.skipped_inaccessible] == [
        (2, "GitHub API request failed with HTTP 404: Not Found")
    ]
    assert report.skipped_unresolved_netuids == [3]
    report_json = (tmp_path / "out" / "crawl-report.json").read_text(encoding="utf-8")
    assert '"skipped_inaccessible"' in report_json
    assert '"netuid": 2' in report_json


def test_crawl_rejects_shared_upstream_repository_before_github_lookup(monkeypatch, tmp_path):
    document = resolve_subnets(
        [
            SubnetIdentityRecord(
                netuid=80,
                subnet_name="Old subnet occupant",
                github_repo="https://github.com/opentensor/subtensor",
            )
        ],
        target_label="bittensor-subnets",
    )

    def fail_github_lookup(*args, **kwargs):
        raise AssertionError("shared upstream target must not reach GitHub discovery")

    def fail_crawl(*args, **kwargs):
        raise AssertionError("shared upstream target must not be crawled")

    monkeypatch.setattr("tao_git_crawl.crawler.list_repositories_from_urls", fail_github_lookup)
    monkeypatch.setattr("tao_git_crawl.crawler.crawl_repositories", fail_crawl)

    report = crawl_resolved_subnets(document, output_dir=tmp_path / "out", cache_dir=tmp_path / "cache")

    assert report.succeeded_netuids == []
    assert report.failed == []
    assert report.skipped_inaccessible == []
    assert len(report.skipped_attribution) == 1
    assert "blocked upstream GitHub owner opentensor" in report.skipped_attribution[0].reason
    score = json.loads((tmp_path / "out" / "subnets" / "80" / "score.json").read_text(encoding="utf-8"))
    assert score["status"] == "attribution_rejected"
    assert score["score"] == 0.0


def test_crawl_rejects_repository_redirect_to_different_canonical_repo(monkeypatch, tmp_path):
    document = resolve_subnets(
        [SubnetIdentityRecord(netuid=80, github_repo="https://github.com/legacy-owner/project")],
        target_label="bittensor-subnets",
    )

    monkeypatch.setattr(
        "tao_git_crawl.crawler.list_repositories_from_urls",
        lambda urls, **kwargs: [_repo("new-owner/project")],
    )

    def fail_crawl(*args, **kwargs):
        raise AssertionError("redirected repository must not be crawled")

    monkeypatch.setattr("tao_git_crawl.crawler.crawl_repositories", fail_crawl)

    report = crawl_resolved_subnets(document, output_dir=tmp_path / "out", cache_dir=tmp_path / "cache")

    assert report.succeeded_netuids == []
    assert report.failed == []
    assert report.skipped_inaccessible == []
    assert len(report.skipped_attribution) == 1
    assert "legacy-owner/project resolved to new-owner/project" in report.skipped_attribution[0].reason
    score = json.loads((tmp_path / "out" / "subnets" / "80" / "score.json").read_text(encoding="utf-8"))
    assert score["status"] == "attribution_rejected"
    assert score["score"] == 0.0


def test_replace_override_primary_success_does_not_attempt_fallback(monkeypatch, tmp_path):
    document = resolve_subnets(
        [SubnetIdentityRecord(netuid=23, registered_at=2300, subnet_name="Subnet", github_repo="https://github.com/current/repo")],
        target_label="bittensor-subnets",
        config=ResolverConfig(
            subnet_overrides={
                23: SubnetOverride(
                    replace=True,
                    targets=(TargetOverride(kind="repository", url="https://github.com/manual/repo"),),
                )
            }
        ),
    )
    calls = {"repo_urls": [], "crawls": []}

    def fake_list_repositories_from_urls(urls, **kwargs):
        url = next(iter(urls))
        calls["repo_urls"].append(url)
        if "current/repo" in url:
            raise AssertionError("fallback target should not be resolved when primary succeeds")
        return [_repo("manual/repo")]

    def fake_crawl_repositories(target_label, repositories, **kwargs):
        calls["crawls"].append([repo.full_name for repo in repositories])
        return SimpleNamespace(
            run=SimpleNamespace(status="success", run_id="test-run-0"),
            repositories=list(repositories),
        )

    def fake_write_crawl_outputs(result, output_dir, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "summary.json"
        path.write_text("{}\n", encoding="utf-8")
        return [path]

    monkeypatch.setattr("tao_git_crawl.crawler.list_repositories_from_urls", fake_list_repositories_from_urls)
    monkeypatch.setattr("tao_git_crawl.crawler.crawl_repositories", fake_crawl_repositories)
    monkeypatch.setattr("tao_git_crawl.crawler.write_crawl_outputs", fake_write_crawl_outputs)

    report = crawl_resolved_subnets(document, output_dir=tmp_path / "out", cache_dir=tmp_path / "cache")

    assert report.succeeded_netuids == [23]
    assert calls["repo_urls"] == ["https://github.com/manual/repo"]
    assert calls["crawls"] == [["manual/repo"]]
    assert report.fallback_used == []


def test_replace_override_404_primary_falls_back_to_identity_target(monkeypatch, tmp_path):
    document = resolve_subnets(
        [SubnetIdentityRecord(netuid=23, registered_at=2300, subnet_name="Subnet", github_repo="https://github.com/current/repo")],
        target_label="bittensor-subnets",
        config=ResolverConfig(
            subnet_overrides={
                23: SubnetOverride(
                    replace=True,
                    targets=(TargetOverride(kind="repository", url="https://github.com/manual/missing"),),
                )
            }
        ),
    )
    calls = {"repo_urls": [], "crawls": []}

    def fake_list_repositories_from_urls(urls, **kwargs):
        url = next(iter(urls))
        calls["repo_urls"].append(url)
        if "manual/missing" in url:
            raise GitHubAPIError(
                "GitHub API request failed with HTTP 404: Not Found",
                status_code=404,
                url="https://api.github.com/repos/manual/missing",
            )
        return [_repo("current/repo")]

    def fake_crawl_repositories(target_label, repositories, **kwargs):
        calls["crawls"].append([repo.full_name for repo in repositories])
        return SimpleNamespace(
            run=SimpleNamespace(status="success", run_id="test-run-0"),
            repositories=list(repositories),
        )

    def fake_write_crawl_outputs(result, output_dir, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "summary.json"
        path.write_text("{}\n", encoding="utf-8")
        return [path]

    monkeypatch.setattr("tao_git_crawl.crawler.list_repositories_from_urls", fake_list_repositories_from_urls)
    monkeypatch.setattr("tao_git_crawl.crawler.crawl_repositories", fake_crawl_repositories)
    monkeypatch.setattr("tao_git_crawl.crawler.write_crawl_outputs", fake_write_crawl_outputs)

    report = crawl_resolved_subnets(document, output_dir=tmp_path / "out", cache_dir=tmp_path / "cache")

    assert report.succeeded_netuids == [23]
    assert report.skipped_inaccessible == []
    assert calls["repo_urls"] == ["https://github.com/manual/missing", "https://github.com/current/repo"]
    assert calls["crawls"] == [["current/repo"]]
    assert len(report.fallback_used) == 1
    assert report.fallback_used[0].fallback_targets == ["https://github.com/current/repo"]
    report_json = json.loads((tmp_path / "out" / "crawl-report.json").read_text(encoding="utf-8"))
    assert report_json["fallback_used"][0]["netuid"] == 23
    assert report_json["fallback_used"][0]["fallback_targets"] == ["https://github.com/current/repo"]


def test_replace_override_404_primary_and_404_fallback_keep_inaccessible_skip(monkeypatch, tmp_path):
    document = resolve_subnets(
        [SubnetIdentityRecord(netuid=23, registered_at=2300, subnet_name="Subnet", github_repo="https://github.com/current/missing")],
        target_label="bittensor-subnets",
        config=ResolverConfig(
            subnet_overrides={
                23: SubnetOverride(
                    replace=True,
                    targets=(TargetOverride(kind="repository", url="https://github.com/manual/missing"),),
                )
            }
        ),
    )

    def fake_list_repositories_from_urls(urls, **kwargs):
        url = next(iter(urls))
        full_name = url.removeprefix("https://github.com/")
        raise GitHubAPIError(
            "GitHub API request failed with HTTP 404: Not Found",
            status_code=404,
            url=f"https://api.github.com/repos/{full_name}",
        )

    def fake_crawl_repositories(target_label, repositories, **kwargs):
        raise AssertionError("subnet should be skipped when primary and fallback targets are inaccessible")

    monkeypatch.setattr("tao_git_crawl.crawler.list_repositories_from_urls", fake_list_repositories_from_urls)
    monkeypatch.setattr("tao_git_crawl.crawler.crawl_repositories", fake_crawl_repositories)

    report = crawl_resolved_subnets(document, output_dir=tmp_path / "out", cache_dir=tmp_path / "cache")

    assert report.succeeded_netuids == []
    assert report.failed == []
    assert len(report.skipped_inaccessible) == 2
    assert report.fallback_used == []


def test_replace_override_non_404_primary_error_does_not_attempt_fallback(monkeypatch, tmp_path):
    document = resolve_subnets(
        [SubnetIdentityRecord(netuid=23, registered_at=2300, subnet_name="Subnet", github_repo="https://github.com/current/repo")],
        target_label="bittensor-subnets",
        config=ResolverConfig(
            subnet_overrides={
                23: SubnetOverride(
                    replace=True,
                    targets=(TargetOverride(kind="repository", url="https://github.com/manual/error"),),
                )
            }
        ),
    )
    calls = []

    def fake_list_repositories_from_urls(urls, **kwargs):
        url = next(iter(urls))
        calls.append(url)
        if "current/repo" in url:
            raise AssertionError("fallback target should not be resolved after a non-404 primary error")
        raise GitHubAPIError(
            "GitHub API request failed with HTTP 500: Server Error",
            status_code=500,
            url="https://api.github.com/repos/manual/error",
        )

    monkeypatch.setattr("tao_git_crawl.crawler.list_repositories_from_urls", fake_list_repositories_from_urls)

    report = crawl_resolved_subnets(document, output_dir=tmp_path / "out", cache_dir=tmp_path / "cache")

    assert report.succeeded_netuids == []
    assert len(report.failed) == 1
    assert calls == ["https://github.com/manual/error"]
    assert report.fallback_used == []


def test_replace_override_mixed_primary_success_and_404_does_not_attempt_fallback(monkeypatch, tmp_path):
    document = resolve_subnets(
        [SubnetIdentityRecord(netuid=23, registered_at=2300, subnet_name="Subnet", github_repo="https://github.com/current/repo")],
        target_label="bittensor-subnets",
        config=ResolverConfig(
            subnet_overrides={
                23: SubnetOverride(
                    replace=True,
                    targets=(
                        TargetOverride(kind="repository", url="https://github.com/manual/good"),
                        TargetOverride(kind="repository", url="https://github.com/manual/missing"),
                    ),
                )
            }
        ),
    )
    calls = {"repo_urls": [], "crawls": []}

    def fake_list_repositories_from_urls(urls, **kwargs):
        url = next(iter(urls))
        calls["repo_urls"].append(url)
        if "current/repo" in url:
            raise AssertionError("fallback target should not be resolved when one primary target succeeds")
        if "manual/missing" in url:
            raise GitHubAPIError(
                "GitHub API request failed with HTTP 404: Not Found",
                status_code=404,
                url="https://api.github.com/repos/manual/missing",
            )
        return [_repo("manual/good")]

    def fake_crawl_repositories(target_label, repositories, **kwargs):
        calls["crawls"].append([repo.full_name for repo in repositories])
        return SimpleNamespace(
            run=SimpleNamespace(status="success", run_id="test-run-0"),
            repositories=list(repositories),
        )

    def fake_write_crawl_outputs(result, output_dir, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "summary.json"
        path.write_text("{}\n", encoding="utf-8")
        return [path]

    monkeypatch.setattr("tao_git_crawl.crawler.list_repositories_from_urls", fake_list_repositories_from_urls)
    monkeypatch.setattr("tao_git_crawl.crawler.crawl_repositories", fake_crawl_repositories)
    monkeypatch.setattr("tao_git_crawl.crawler.write_crawl_outputs", fake_write_crawl_outputs)

    report = crawl_resolved_subnets(document, output_dir=tmp_path / "out", cache_dir=tmp_path / "cache")

    assert report.succeeded_netuids == [23]
    assert calls["repo_urls"] == ["https://github.com/manual/good", "https://github.com/manual/missing"]
    assert calls["crawls"] == [["manual/good"]]
    assert len(report.skipped_inaccessible) == 1
    assert report.fallback_used == []


def test_crawl_resolved_subnets_continues_after_unresolved_and_per_subnet_failures(monkeypatch, tmp_path):
    document = resolve_subnets(
        [
            SubnetIdentityRecord(netuid=1, subnet_name="Good", github_repo="https://github.com/alice/api"),
            SubnetIdentityRecord(netuid=2, subnet_name="Bad", github_repo="https://github.com/bad/missing"),
            SubnetIdentityRecord(netuid=3, subnet_name="Missing"),
        ],
        target_label="bittensor-subnets",
    )

    def fake_list_repositories_from_urls(urls, **kwargs):
        url = next(iter(urls))
        if "bad/missing" in url:
            raise RuntimeError("not found")
        return [SimpleNamespace(name="api", full_name="alice/api")]

    def fake_crawl_repositories(target_label, repositories, **kwargs):
        return SimpleNamespace(
            run=SimpleNamespace(status="success", run_id="test-run-0"),
            repositories=list(repositories),
        )

    def fake_write_crawl_outputs(result, output_dir, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "summary.json"
        path.write_text("{}\n", encoding="utf-8")
        return [path]

    monkeypatch.setattr("tao_git_crawl.crawler.list_repositories_from_urls", fake_list_repositories_from_urls)
    monkeypatch.setattr("tao_git_crawl.crawler.crawl_repositories", fake_crawl_repositories)
    monkeypatch.setattr("tao_git_crawl.crawler.write_crawl_outputs", fake_write_crawl_outputs)

    report = crawl_resolved_subnets(document, output_dir=tmp_path / "out", cache_dir=tmp_path / "cache")

    assert report.succeeded_netuids == [1]
    assert [(failure.netuid, failure.reason) for failure in report.failed] == [(2, "not found")]
    assert report.skipped_unresolved_netuids == [3]
    assert (tmp_path / "out" / "subnets" / "1" / "crawl" / "summary.json").exists()


def test_crawl_resolved_subnets_treats_non_success_crawl_status_as_failure(monkeypatch, tmp_path):
    document = resolve_subnets(
        [SubnetIdentityRecord(netuid=1, subnet_name="Partial", github_repo="https://github.com/alice/api")],
        target_label="bittensor-subnets",
    )

    def fake_list_repositories_from_urls(urls, **kwargs):
        return [SimpleNamespace(name="api", full_name="alice/api")]

    def fake_crawl_repositories(target_label, repositories, **kwargs):
        return SimpleNamespace(
            run=SimpleNamespace(status="partial", run_id=""),
            repositories=list(repositories),
            failed_repositories=[
                SimpleNamespace(full_name="alice/api", error="clone failed for https://token@example.com/repo.git")
            ],
        )

    def fake_write_crawl_outputs(result, output_dir, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "summary.json"
        path.write_text("{}\n", encoding="utf-8")
        return [path]

    monkeypatch.setattr("tao_git_crawl.crawler.list_repositories_from_urls", fake_list_repositories_from_urls)
    monkeypatch.setattr("tao_git_crawl.crawler.crawl_repositories", fake_crawl_repositories)
    monkeypatch.setattr("tao_git_crawl.crawler.write_crawl_outputs", fake_write_crawl_outputs)

    report = crawl_resolved_subnets(document, output_dir=tmp_path / "out", cache_dir=tmp_path / "cache")

    assert report.succeeded_netuids == []
    assert len(report.failed) == 1
    assert report.failed[0].netuid == 1
    assert "crawl completed with status partial" in report.failed[0].reason
    assert "https://[REDACTED]@example.com/repo.git" in report.failed[0].reason
    assert (tmp_path / "out" / "subnets" / "1" / "crawl" / "summary.json").exists()


def test_crawl_resolved_subnets_does_not_fetch_owner_targets_after_max_repos_is_reached(monkeypatch, tmp_path):
    document = resolve_subnets(
        [SubnetIdentityRecord(netuid=64, registered_at=6400, subnet_name="Chutes", github_repo="https://github.com/chutesai/api")],
        target_label="bittensor-subnets",
        config=ResolverConfig(
            subnet_overrides={
                64: SubnetOverride(
                    replace=False,
                    targets=(TargetOverride(kind="owner", url="https://github.com/chutesai"),),
                )
            }
        ),
    )
    calls = {"owners": 0, "crawls": []}

    def fake_list_repositories_from_urls(urls, **kwargs):
        return [SimpleNamespace(name="api", full_name="chutesai/api")]

    def fake_list_owner_repositories(owner, **kwargs):
        calls["owners"] += 1
        return [SimpleNamespace(name="sdk", full_name="chutesai/sdk")]

    def fake_crawl_repositories(target_label, repositories, **kwargs):
        calls["crawls"].append([repo.full_name for repo in repositories])
        return SimpleNamespace(
            run=SimpleNamespace(status="success", run_id="test-run-0"),
            repositories=list(repositories),
        )

    def fake_write_crawl_outputs(result, output_dir, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "summary.json"
        path.write_text("{}\n", encoding="utf-8")
        return [path]

    monkeypatch.setattr("tao_git_crawl.crawler.list_repositories_from_urls", fake_list_repositories_from_urls)
    monkeypatch.setattr("tao_git_crawl.crawler.list_owner_repositories", fake_list_owner_repositories)
    monkeypatch.setattr("tao_git_crawl.crawler.crawl_repositories", fake_crawl_repositories)
    monkeypatch.setattr("tao_git_crawl.crawler.write_crawl_outputs", fake_write_crawl_outputs)

    report = crawl_resolved_subnets(
        document,
        output_dir=tmp_path / "out",
        cache_dir=tmp_path / "cache",
        max_repos=1,
    )

    assert report.succeeded_netuids == [64]
    assert calls["owners"] == 0
    assert calls["crawls"] == [["chutesai/api"]]


def test_owner_fetch_respects_max_repos_and_does_not_overfetch(monkeypatch, tmp_path):
    document = resolve_subnets(
        [SubnetIdentityRecord(netuid=64, subnet_name="Chutes", github_repo="https://github.com/chutesai")],
        target_label="bittensor-subnets",
    )
    calls = {"crawls": []}

    def fake_list_owner_repositories(owner, **kwargs):
        return [
            SimpleNamespace(name="api", full_name="chutesai/api"),
            SimpleNamespace(name="sdk", full_name="chutesai/sdk"),
            SimpleNamespace(name="cli", full_name="chutesai/cli"),
        ]

    def fake_crawl_repositories(target_label, repositories, **kwargs):
        calls["crawls"].append([repo.full_name for repo in repositories])
        return SimpleNamespace(
            run=SimpleNamespace(status="success", run_id="test-run-0"),
            repositories=list(repositories),
        )

    def fake_write_crawl_outputs(result, output_dir, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "summary.json"
        path.write_text("{}\n", encoding="utf-8")
        return [path]

    monkeypatch.setattr("tao_git_crawl.crawler.list_owner_repositories", fake_list_owner_repositories)
    monkeypatch.setattr("tao_git_crawl.crawler.crawl_repositories", fake_crawl_repositories)
    monkeypatch.setattr("tao_git_crawl.crawler.write_crawl_outputs", fake_write_crawl_outputs)

    report = crawl_resolved_subnets(
        document,
        output_dir=tmp_path / "out",
        cache_dir=tmp_path / "cache",
        max_repos=2,
    )

    assert report.succeeded_netuids == [64]
    assert calls["crawls"] == [["chutesai/api", "chutesai/sdk"]]


def test_owner_fetch_max_repos_counts_unique_repositories_after_explicit_repo_overlap(monkeypatch, tmp_path):
    document = resolve_subnets(
        [SubnetIdentityRecord(netuid=64, registered_at=6400, subnet_name="Chutes", github_repo="https://github.com/chutesai/api")],
        target_label="bittensor-subnets",
        config=ResolverConfig(
            subnet_overrides={
                64: SubnetOverride(
                    replace=False,
                    targets=(TargetOverride(kind="owner", url="https://github.com/chutesai"),),
                )
            }
        ),
    )
    calls = {"crawls": []}

    def fake_list_repositories_from_urls(urls, **kwargs):
        return [SimpleNamespace(name="api", full_name="chutesai/api")]

    def fake_list_owner_repositories(owner, **kwargs):
        return [
            SimpleNamespace(name="api", full_name="chutesai/api"),
            SimpleNamespace(name="sdk", full_name="chutesai/sdk"),
            SimpleNamespace(name="cli", full_name="chutesai/cli"),
        ]

    def fake_crawl_repositories(target_label, repositories, **kwargs):
        calls["crawls"].append([repo.full_name for repo in repositories])
        return SimpleNamespace(
            run=SimpleNamespace(status="success", run_id="test-run-0"),
            repositories=list(repositories),
        )

    def fake_write_crawl_outputs(result, output_dir, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "summary.json"
        path.write_text("{}\n", encoding="utf-8")
        return [path]

    monkeypatch.setattr("tao_git_crawl.crawler.list_repositories_from_urls", fake_list_repositories_from_urls)
    monkeypatch.setattr("tao_git_crawl.crawler.list_owner_repositories", fake_list_owner_repositories)
    monkeypatch.setattr("tao_git_crawl.crawler.crawl_repositories", fake_crawl_repositories)
    monkeypatch.setattr("tao_git_crawl.crawler.write_crawl_outputs", fake_write_crawl_outputs)

    report = crawl_resolved_subnets(
        document,
        output_dir=tmp_path / "out",
        cache_dir=tmp_path / "cache",
        max_repos=2,
    )

    assert report.succeeded_netuids == [64]
    assert calls["crawls"] == [["chutesai/api", "chutesai/sdk"]]


def test_owner_fetch_max_repos_counts_only_crawlable_repositories(monkeypatch, tmp_path):
    document = resolve_subnets(
        [SubnetIdentityRecord(netuid=77, subnet_name="Acme", github_repo="https://github.com/acme")],
        target_label="bittensor-subnets",
    )
    calls = {"crawls": []}

    def fake_list_owner_repositories(owner, **kwargs):
        return [
            _repo("acme/archived", archived=True),
            _repo("acme/api"),
            _repo("acme/sdk"),
        ]

    def fake_crawl_repositories(target_label, repositories, **kwargs):
        selected_names, selected = _selected_repo_names_for_crawl(list(repositories), kwargs)
        calls["crawls"].append(selected_names)
        return SimpleNamespace(
            run=SimpleNamespace(status="success", run_id="test-run-0"),
            repositories=selected,
        )

    def fake_write_crawl_outputs(result, output_dir, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "summary.json"
        path.write_text("{}\n", encoding="utf-8")
        return [path]

    monkeypatch.setattr("tao_git_crawl.crawler.list_owner_repositories", fake_list_owner_repositories)
    monkeypatch.setattr("tao_git_crawl.crawler.crawl_repositories", fake_crawl_repositories)
    monkeypatch.setattr("tao_git_crawl.crawler.write_crawl_outputs", fake_write_crawl_outputs)

    report = crawl_resolved_subnets(
        document,
        output_dir=tmp_path / "out",
        cache_dir=tmp_path / "cache",
        max_repos=1,
    )

    assert report.succeeded_netuids == [77]
    assert calls["crawls"] == [["acme/api"]]


def test_owner_fetch_still_runs_when_exact_repo_is_excluded_by_crawl_filters(monkeypatch, tmp_path):
    document = resolve_subnets(
        [SubnetIdentityRecord(netuid=78, registered_at=7800, subnet_name="Acme", github_repo="https://github.com/acme/archived")],
        target_label="bittensor-subnets",
        config=ResolverConfig(
            subnet_overrides={
                78: SubnetOverride(
                    replace=False,
                    targets=(TargetOverride(kind="owner", url="https://github.com/acme"),),
                )
            }
        ),
    )
    calls = {"owners": 0, "crawls": []}

    def fake_list_repositories_from_urls(urls, **kwargs):
        return [_repo("acme/archived", archived=True)]

    def fake_list_owner_repositories(owner, **kwargs):
        calls["owners"] += 1
        return [_repo("acme/api"), _repo("acme/sdk")]

    def fake_crawl_repositories(target_label, repositories, **kwargs):
        selected_names, selected = _selected_repo_names_for_crawl(list(repositories), kwargs)
        calls["crawls"].append(selected_names)
        return SimpleNamespace(
            run=SimpleNamespace(status="success", run_id="test-run-0"),
            repositories=selected,
        )

    def fake_write_crawl_outputs(result, output_dir, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "summary.json"
        path.write_text("{}\n", encoding="utf-8")
        return [path]

    monkeypatch.setattr("tao_git_crawl.crawler.list_repositories_from_urls", fake_list_repositories_from_urls)
    monkeypatch.setattr("tao_git_crawl.crawler.list_owner_repositories", fake_list_owner_repositories)
    monkeypatch.setattr("tao_git_crawl.crawler.crawl_repositories", fake_crawl_repositories)
    monkeypatch.setattr("tao_git_crawl.crawler.write_crawl_outputs", fake_write_crawl_outputs)

    report = crawl_resolved_subnets(
        document,
        output_dir=tmp_path / "out",
        cache_dir=tmp_path / "cache",
        max_repos=1,
    )

    assert report.succeeded_netuids == [78]
    assert calls["owners"] == 1
    assert calls["crawls"] == [["acme/api"]]
