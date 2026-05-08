from tao_git_crawl.github_links import extract_github_targets
from tao_git_crawl.models import SubnetIdentityRecord


def test_extracts_high_confidence_repository_from_github_repo_url():
    record = SubnetIdentityRecord(netuid=64, subnet_name="Chutes", github_repo="https://github.com/chutesai/api.git")

    targets = extract_github_targets(record)

    assert len(targets) == 1
    target = targets[0]
    assert target.kind == "repository"
    assert target.confidence == "high"
    assert target.repo_full_name == "chutesai/api"
    assert target.url == "https://github.com/chutesai/api"
    assert target.source_field == "github_repo"
    assert target.netuid == 64


def test_accepts_bare_owner_repo_in_github_repo_field():
    record = SubnetIdentityRecord(netuid=12, github_repo="opentensor/subtensor")

    targets = extract_github_targets(record)

    assert [target.url for target in targets] == ["https://github.com/opentensor/subtensor"]
    assert targets[0].confidence == "high"


def test_scans_fallback_text_fields_and_deduplicates_repositories():
    record = SubnetIdentityRecord(
        netuid=7,
        subnet_url="https://example.com",
        description=(
            "Code lives at https://github.com/latent-to/bittensor/tree/master "
            "and docs mention github.com/latent-to/bittensor.git"
        ),
        additional="Mirror: git@github.com:latent-to/bittensor.git",
    )

    targets = extract_github_targets(record)

    assert [target.repo_full_name for target in targets] == ["latent-to/bittensor"]
    assert targets[0].source_field == "description"
    assert targets[0].confidence == "low"


def test_owner_root_is_preserved_as_lower_confidence_owner_target_not_repo():
    record = SubnetIdentityRecord(netuid=42, github_repo="https://github.com/chutesai")

    targets = extract_github_targets(record)

    assert len(targets) == 1
    target = targets[0]
    assert target.kind == "owner"
    assert target.owner == "chutesai"
    assert target.repo is None
    assert target.repo_full_name is None
    assert target.url == "https://github.com/chutesai"
    assert target.confidence == "medium"


def test_github_orgs_owner_root_is_preserved_as_owner_target_not_repo_manifest_candidate():
    record = SubnetIdentityRecord(netuid=43, github_repo="https://github.com/orgs/chutesai")

    targets = extract_github_targets(record)

    assert len(targets) == 1
    target = targets[0]
    assert target.kind == "owner"
    assert target.owner == "chutesai"
    assert target.repo_full_name is None
    assert target.url == "https://github.com/chutesai"


def test_github_orgs_repositories_page_is_preserved_as_owner_target():
    record = SubnetIdentityRecord(netuid=44, github_repo="https://github.com/orgs/chutesai/repositories")

    targets = extract_github_targets(record)

    assert len(targets) == 1
    assert targets[0].kind == "owner"
    assert targets[0].owner == "chutesai"
    assert targets[0].url == "https://github.com/chutesai"


def test_unsupported_github_subpath_is_not_truncated_to_repository_target():
    record = SubnetIdentityRecord(
        netuid=45,
        description="Bug report lives at https://github.com/opentensor/subtensor/issues/123",
    )

    assert extract_github_targets(record) == []


def test_reserved_github_page_is_not_treated_as_owner_target():
    record = SubnetIdentityRecord(netuid=46, subnet_url="https://github.com/search?q=bittensor")

    assert extract_github_targets(record) == []


def test_invalid_github_repo_field_becomes_no_target():
    record = SubnetIdentityRecord(netuid=9, github_repo="https://example.com/not-github")

    assert extract_github_targets(record) == []
