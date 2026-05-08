import json
import os
from types import SimpleNamespace

from tao_git_crawl.cli import main


def test_resolve_cli_writes_resolution_manifest_owner_targets_and_unresolved(tmp_path, capsys):
    input_path = tmp_path / "subnets.json"
    input_path.write_text(
        json.dumps(
            {
                "subnets": [
                    {"netuid": 1, "subnet_identity": {"github_repo": "github.com/alice/api"}},
                    {"netuid": 2, "subnet_identity": {"github_repo": "https://github.com/bob"}},
                    {"netuid": 3, "subnet_identity": {"description": "no code here"}},
                ]
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"

    exit_code = main(["resolve", "--from-json", str(input_path), "--output-dir", str(output_dir), "--target", "tao"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Resolved 1 repository targets, 1 owner targets, 1 unresolved subnet records." in captured.out
    manifest = json.loads((output_dir / "repository-manifest.json").read_text(encoding="utf-8"))
    assert manifest == {
        "target": "tao",
        "repositories": [
            {"url": "https://github.com/alice/api", "netuids": [1], "source": "subnet_identity.github_repo"}
        ],
    }
    owner_targets = json.loads((output_dir / "owner-targets.json").read_text(encoding="utf-8"))
    assert owner_targets[0]["owner"] == "bob"
    unresolved = json.loads((output_dir / "unresolved.json").read_text(encoding="utf-8"))
    assert unresolved == [
        {
            "netuid": 3,
            "subnet_name": "",
            "reason": "no_github_link",
            "fields_checked": [
                "github_repo",
                "subnet_url",
                "description",
                "additional",
                "subnet_contact",
            ],
        }
    ]


def test_resolve_cli_applies_config_py_subnet_overrides_and_writes_split_subnet_outputs(tmp_path, capsys):
    input_path = tmp_path / "subnets.json"
    input_path.write_text(
        json.dumps(
            {
                "subnets": [
                    {
                        "netuid": 64,
                        "subnet_identity": {
                            "subnet_name": "Chutes",
                            "github_repo": "github.com/chutesai/api",
                        },
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.py"
    config_path.write_text(
        """
DEFAULT_REPOSITORY_POLICY = "repository"
SUBNET_OVERRIDES = {
    64: {
        "replace": True,
        "targets": [
            {"kind": "owner", "url": "https://github.com/chutesai"},
        ],
    }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"

    exit_code = main(
        [
            "resolve",
            "--from-json",
            str(input_path),
            "--config",
            str(config_path),
            "--output-dir",
            str(output_dir),
            "--target",
            "tao",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Resolved 0 repository targets, 1 owner targets, 0 unresolved subnet records." in captured.out
    manifest = json.loads((output_dir / "repository-manifest.json").read_text(encoding="utf-8"))
    assert manifest == {"target": "tao", "repositories": []}
    owner_targets = json.loads((output_dir / "owner-targets.json").read_text(encoding="utf-8"))
    assert [(item["netuid"], item["kind"], item["owner"], item["source_field"]) for item in owner_targets] == [
        (64, "owner", "chutesai", "manual_override")
    ]
    subnet_owner_targets = json.loads(
        (output_dir / "subnets" / "64" / "owner-targets.json").read_text(encoding="utf-8")
    )
    assert subnet_owner_targets == owner_targets


def test_resolve_cli_repository_policy_owner_promotes_repo_links_to_owner_targets(tmp_path, capsys):
    input_path = tmp_path / "subnets.json"
    input_path.write_text(
        json.dumps({"subnets": [{"netuid": 64, "subnet_identity": {"github_repo": "github.com/chutesai/api"}}]}),
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"

    exit_code = main(
        [
            "resolve",
            "--from-json",
            str(input_path),
            "--repository-policy",
            "owner",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Resolved 0 repository targets, 1 owner targets, 0 unresolved subnet records." in captured.out
    owner_targets = json.loads((output_dir / "owner-targets.json").read_text(encoding="utf-8"))
    assert [(item["netuid"], item["kind"], item["owner"], item["source_field"]) for item in owner_targets] == [
        (64, "owner", "chutesai", "github_repo")
    ]


def test_crawl_cli_loads_github_token_from_default_dotenv(monkeypatch, tmp_path):
    input_path = tmp_path / "subnets.json"
    input_path.write_text(
        json.dumps({"subnets": [{"netuid": 64, "subnet_identity": {"github_repo": "github.com/chutesai/api"}}]}),
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("GITHUB_TOKEN=dotenv-token\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    os.environ.pop("GITHUB_TOKEN", None)
    calls = []

    def fake_crawl_resolved_subnets(document, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(succeeded_netuids=[64], failed=[], skipped_unresolved_netuids=[])

    monkeypatch.setattr("tao_git_crawl.cli.crawl_resolved_subnets", fake_crawl_resolved_subnets)

    try:
        exit_code = main(
            [
                "crawl",
                "--from-json",
                str(input_path),
                "--repository-policy",
                "owner",
                "--output-dir",
                str(tmp_path / "out"),
                "--cache-dir",
                str(tmp_path / "cache"),
            ]
        )

        assert exit_code == 0
        assert calls[0]["token"] == "dotenv-token"
    finally:
        os.environ.pop("GITHUB_TOKEN", None)


def test_crawl_cli_loads_github_token_from_repo_root_dotenv_when_run_from_subdir(monkeypatch, tmp_path):
    input_path = tmp_path / "subnets.json"
    input_path.write_text(
        json.dumps({"subnets": [{"netuid": 64, "subnet_identity": {"github_repo": "github.com/chutesai/api"}}]}),
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "tao-git-crawl"\n', encoding="utf-8")
    (tmp_path / ".env").write_text("GITHUB_TOKEN=repo-root-dotenv-token\n", encoding="utf-8")
    subdir = tmp_path / "scripts"
    subdir.mkdir()
    monkeypatch.chdir(subdir)
    os.environ.pop("GITHUB_TOKEN", None)
    calls = []

    def fake_crawl_resolved_subnets(document, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(succeeded_netuids=[64], failed=[], skipped_unresolved_netuids=[])

    monkeypatch.setattr("tao_git_crawl.cli.crawl_resolved_subnets", fake_crawl_resolved_subnets)

    try:
        exit_code = main(
            [
                "crawl",
                "--from-json",
                str(input_path),
                "--repository-policy",
                "owner",
                "--output-dir",
                str(tmp_path / "out"),
                "--cache-dir",
                str(tmp_path / "cache"),
            ]
        )

        assert exit_code == 0
        assert calls[0]["token"] == "repo-root-dotenv-token"
    finally:
        os.environ.pop("GITHUB_TOKEN", None)


def test_crawl_cli_loads_github_token_from_custom_dotenv(monkeypatch, tmp_path):
    input_path = tmp_path / "subnets.json"
    input_path.write_text(
        json.dumps({"subnets": [{"netuid": 64, "subnet_identity": {"github_repo": "github.com/chutesai/api"}}]}),
        encoding="utf-8",
    )
    env_path = tmp_path / "config" / "github.env"
    env_path.parent.mkdir()
    env_path.write_text("GITHUB_TOKEN=custom-dotenv-token\n", encoding="utf-8")
    os.environ.pop("GITHUB_TOKEN", None)
    calls = []

    def fake_crawl_resolved_subnets(document, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(succeeded_netuids=[64], failed=[], skipped_unresolved_netuids=[])

    monkeypatch.setattr("tao_git_crawl.cli.crawl_resolved_subnets", fake_crawl_resolved_subnets)

    try:
        exit_code = main(
            [
                "crawl",
                "--from-json",
                str(input_path),
                "--repository-policy",
                "owner",
                "--env-file",
                str(env_path),
                "--output-dir",
                str(tmp_path / "out"),
                "--cache-dir",
                str(tmp_path / "cache"),
            ]
        )

        assert exit_code == 0
        assert calls[0]["token"] == "custom-dotenv-token"
    finally:
        os.environ.pop("GITHUB_TOKEN", None)


def test_crawl_cli_resolves_writes_manifests_and_crawls_each_subnet(monkeypatch, tmp_path, capsys):
    os.environ.pop("GITHUB_TOKEN", None)
    input_path = tmp_path / "subnets.json"
    input_path.write_text(
        json.dumps({"subnets": [{"netuid": 64, "subnet_identity": {"github_repo": "github.com/chutesai/api"}}]}),
        encoding="utf-8",
    )
    calls = []

    def fake_crawl_resolved_subnets(document, **kwargs):
        calls.append((document.target_label, [target.owner for target in document.owner_targets], kwargs))
        return SimpleNamespace(succeeded_netuids=[64], failed=[], skipped_unresolved_netuids=[])

    monkeypatch.setattr("tao_git_crawl.cli.crawl_resolved_subnets", fake_crawl_resolved_subnets)
    output_dir = tmp_path / "out"
    cache_dir = tmp_path / "cache"
    state_db = tmp_path / "state" / "git-crawl.sqlite"

    exit_code = main(
        [
            "crawl",
            "--from-json",
            str(input_path),
            "--repository-policy",
            "owner",
            "--output-dir",
            str(output_dir),
            "--cache-dir",
            str(cache_dir),
            "--state-db",
            str(state_db),
            "--env-file",
            str(tmp_path / "missing.env"),
            "--since",
            "2026-01-01",
            "--workers",
            "2",
            "--format",
            "jsonl",
        ]
    )

    assert exit_code == 0
    assert calls == [
        (
            "bittensor-subnets",
            ["chutesai"],
            {
                "output_dir": output_dir,
                "cache_dir": cache_dir,
                "state_db": state_db,
                "token": None,
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
                "output_format": "jsonl",
            },
        )
    ]
    assert (output_dir / "subnets" / "64" / "owner-targets.json").exists()
    captured = capsys.readouterr()
    assert "Crawled 1 subnets, 0 failed, 0 unresolved skipped, 0 inaccessible skipped." in captured.out
