from __future__ import annotations

import pytest

from tao_git_crawl.attribution import target_attribution_rejection
from tao_git_crawl.models import GitHubTarget


@pytest.mark.parametrize(
    ("owner", "repo"),
    [
        ("opentensor", "subtensor"),
        ("opentensor", "any-new-repository"),
        ("RaoFoundation", "subtensor"),
        ("RAOFOUNDATION", "unrelated-name"),
        ("opentensor", None),
    ],
)
def test_every_repository_and_owner_scope_under_blocked_upstreams_is_rejected(owner, repo):
    url = f"https://github.com/{owner}" + (f"/{repo}" if repo else "")
    target = GitHubTarget(
        netuid=80,
        kind="repository" if repo else "owner",
        url=url,
        owner=owner,
        repo=repo,
        repo_full_name=f"{owner}/{repo}" if repo else None,
        source_field="github_repo",
        raw_value=url,
    )

    reason = target_attribution_rejection(target)

    assert reason is not None
    assert "blocked upstream GitHub owner" in reason


def test_non_blocked_owner_is_not_rejected_by_owner_policy():
    target = GitHubTarget(
        netuid=80,
        kind="repository",
        url="https://github.com/openroboto-ai/openroboto-subnet",
        owner="openroboto-ai",
        repo="openroboto-subnet",
        repo_full_name="openroboto-ai/openroboto-subnet",
        source_field="github_repo",
        raw_value="openroboto-ai/openroboto-subnet",
    )

    assert target_attribution_rejection(target) is None
