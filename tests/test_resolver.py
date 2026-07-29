import json

from tao_git_crawl.models import SubnetIdentityRecord
from tao_git_crawl.overrides import ResolverConfig, SubnetOverride, TargetOverride
from tao_git_crawl.resolver import resolve_subnets, write_resolution_outputs


def test_resolve_subnets_emits_git_crawl_manifest_targets_and_unresolved_records():
    records = [
        SubnetIdentityRecord(netuid=1, subnet_name="repo subnet", github_repo="github.com/alice/api"),
        SubnetIdentityRecord(netuid=2, subnet_name="owner subnet", github_repo="https://github.com/bittensor"),
        SubnetIdentityRecord(netuid=3, subnet_name="missing subnet"),
    ]

    document = resolve_subnets(records, target_label="bittensor-subnets")

    assert document.schema_version == "tao-git-crawl-resolution-v3"
    assert [target.netuid for target in document.repository_targets] == [1]
    assert [target.netuid for target in document.owner_targets] == [2]
    assert "confidence" not in document.repository_targets[0].to_dict()
    assert document.git_crawl_repository_manifest == {
        "target": "bittensor-subnets",
        "repositories": [
            {
                "url": "https://github.com/alice/api",
                "netuids": [1],
                "source": "subnet_identity.github_repo",
            }
        ],
    }
    assert [(item.netuid, item.reason) for item in document.unresolved] == [(3, "no_github_link")]


def test_resolve_subnets_deduplicates_manifest_repositories_but_keeps_provenance():
    records = [
        SubnetIdentityRecord(netuid=10, github_repo="https://github.com/alice/api"),
        SubnetIdentityRecord(netuid=11, subnet_url="https://github.com/alice/api"),
    ]

    document = resolve_subnets(records, target_label="tao")

    assert len(document.repository_targets) == 2
    assert document.git_crawl_repository_manifest["repositories"] == [
        {
            "url": "https://github.com/alice/api",
            "netuids": [10, 11],
            "source": "mixed",
        }
    ]


def test_subnet_override_can_replace_single_repo_identity_with_owner_crawl_target():
    records = [
        SubnetIdentityRecord(
            netuid=64,
            registered_at=4531295,
            subnet_name="Chutes",
            github_repo="https://github.com/chutesai/api",
        ),
    ]
    config = ResolverConfig(
        subnet_overrides={
            64: SubnetOverride(
                replace=True,
                targets=(TargetOverride(kind="owner", url="https://github.com/chutesai"),),
            )
        }
    )

    document = resolve_subnets(records, target_label="bittensor-subnets", config=config)

    assert document.repository_targets == []
    owner_target_rows = [
        (target.netuid, target.kind, target.owner, target.url, target.source_field)
        for target in document.owner_targets
    ]
    assert owner_target_rows == [(64, "owner", "chutesai", "https://github.com/chutesai", "manual_override")]
    fallback_target_rows = [
        (target.netuid, target.kind, target.repo_full_name, target.source_field)
        for target in document.fallback_targets
    ]
    assert fallback_target_rows == [(64, "repository", "chutesai/api", "github_repo")]
    assert document.git_crawl_repository_manifest == {"target": "bittensor-subnets", "repositories": []}


def test_replace_false_subnet_override_does_not_duplicate_identity_targets_as_fallback():
    records = [
        SubnetIdentityRecord(
            netuid=64,
            registered_at=4531295,
            subnet_name="Chutes",
            github_repo="https://github.com/chutesai/api",
        ),
    ]
    config = ResolverConfig(
        subnet_overrides={
            64: SubnetOverride(
                replace=False,
                targets=(TargetOverride(kind="owner", url="https://github.com/chutesai"),),
            )
        }
    )

    document = resolve_subnets(records, target_label="bittensor-subnets", config=config)

    assert [(target.kind, target.url) for target in document.targets] == [
        ("owner", "https://github.com/chutesai"),
        ("repository", "https://github.com/chutesai/api"),
    ]
    assert document.fallback_targets == []


def test_repository_policy_owner_promotes_repo_links_to_owner_targets_without_manual_netuid_override():
    records = [
        SubnetIdentityRecord(
            netuid=64,
            registered_at=4531295,
            subnet_name="Chutes",
            github_repo="https://github.com/chutesai/api",
        ),
    ]

    document = resolve_subnets(
        records,
        target_label="bittensor-subnets",
        config=ResolverConfig(default_repository_policy="owner"),
    )

    assert document.repository_targets == []
    owner_target_rows = [
        (target.netuid, target.kind, target.owner, target.repo_full_name, target.source_field)
        for target in document.owner_targets
    ]
    assert owner_target_rows == [(64, "owner", "chutesai", None, "github_repo")]


def test_resolution_outputs_include_per_subnet_manifests_for_company_scoped_crawls(tmp_path):
    records = [
        SubnetIdentityRecord(netuid=1, subnet_name="Repo Co", github_repo="https://github.com/alice/api"),
        SubnetIdentityRecord(
            netuid=64,
            registered_at=4531295,
            subnet_name="Chutes",
            github_repo="https://github.com/chutesai/api",
        ),
    ]
    config = ResolverConfig(
        subnet_overrides={
            64: SubnetOverride(
                replace=True,
                targets=(TargetOverride(kind="owner", url="https://github.com/chutesai"),),
            )
        }
    )
    document = resolve_subnets(records, target_label="bittensor-subnets", config=config)

    written = write_resolution_outputs(document, tmp_path)

    assert tmp_path / "subnets" / "1" / "repository-manifest.json" in written
    assert tmp_path / "subnets" / "64" / "owner-targets.json" in written
    subnet_one_manifest = json.loads(
        (tmp_path / "subnets" / "1" / "repository-manifest.json").read_text(encoding="utf-8")
    )
    assert subnet_one_manifest == {
        "target": "bittensor-subnet-1",
        "repositories": [
            {"url": "https://github.com/alice/api", "netuids": [1], "source": "subnet_identity.github_repo"}
        ],
    }
    subnet_64_manifest = json.loads(
        (tmp_path / "subnets" / "64" / "repository-manifest.json").read_text(encoding="utf-8")
    )
    assert subnet_64_manifest == {"target": "bittensor-subnet-64", "repositories": []}
    subnet_64_owners = json.loads((tmp_path / "subnets" / "64" / "owner-targets.json").read_text(encoding="utf-8"))
    assert [(item["kind"], item["owner"], item["source_field"]) for item in subnet_64_owners] == [
        ("owner", "chutesai", "manual_override")
    ]
    subnet_64_targets = json.loads((tmp_path / "subnets" / "64" / "subnet-targets.json").read_text(encoding="utf-8"))
    fallback_rows = [
        (item["kind"], item["repo_full_name"], item["source_field"])
        for item in subnet_64_targets["fallback_targets"]
    ]
    assert fallback_rows == [
        ("repository", "chutesai/api", "github_repo")
    ]
