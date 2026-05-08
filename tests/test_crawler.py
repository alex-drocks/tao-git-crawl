from types import SimpleNamespace

from git_crawl.github import GitHubAPIError

from tao_git_crawl.crawler import crawl_resolved_subnets
from tao_git_crawl.models import SubnetIdentityRecord
from tao_git_crawl.overrides import ResolverConfig
from tao_git_crawl.resolver import resolve_subnets


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
        return SimpleNamespace(run=SimpleNamespace(status="success"), repositories=list(repositories))

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
        output_format="jsonl",
    )

    assert calls["owners"] == [("chutesai", "auto", None)]
    assert calls["repo_manifests"] == []
    assert calls["crawls"] == [
        (
            "bittensor-subnet-64",
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
            },
        )
    ]
    assert calls["writes"] == [(tmp_path / "out" / "subnets" / "64" / "crawl", True, False)]
    assert report.succeeded_netuids == [64]
    assert report.failed == []
    assert (tmp_path / "out" / "subnets" / "64" / "crawl" / "summary.json").exists()


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
        return SimpleNamespace(run=SimpleNamespace(status="success"), repositories=list(repositories))

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
        return SimpleNamespace(run=SimpleNamespace(status="success"), repositories=list(repositories))

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
