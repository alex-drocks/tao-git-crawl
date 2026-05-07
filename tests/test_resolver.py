from tao_git_crawl.models import SubnetIdentityRecord
from tao_git_crawl.resolver import resolve_subnets


def test_resolve_subnets_emits_git_crawl_manifest_targets_and_unresolved_records():
    records = [
        SubnetIdentityRecord(netuid=1, subnet_name="repo subnet", github_repo="github.com/alice/api"),
        SubnetIdentityRecord(netuid=2, subnet_name="owner subnet", github_repo="https://github.com/bittensor"),
        SubnetIdentityRecord(netuid=3, subnet_name="missing subnet"),
    ]

    document = resolve_subnets(records, target_label="bittensor-subnets")

    assert document.schema_version == "tao-git-crawl-resolution-v1"
    assert [target.netuid for target in document.repository_targets] == [1]
    assert [target.netuid for target in document.owner_targets] == [2]
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
