from __future__ import annotations

from collections.abc import Iterable

from .models import GitHubTarget

# Every repository under these accounts is shared Bittensor infrastructure and
# is ineligible for regular-subnet attribution, regardless of repository name.
BLOCKED_GITHUB_OWNERS = frozenset({"opentensor", "raofoundation"})


def target_attribution_rejection(target: GitHubTarget) -> str | None:
    """Return why a resolved target cannot be credited to a regular subnet."""
    if target.owner.lower() not in BLOCKED_GITHUB_OWNERS:
        return None
    return (
        f"blocked upstream GitHub owner {target.owner} cannot be attributed to "
        f"regular subnet {target.netuid}"
    )


def targets_attribution_rejection(targets: Iterable[GitHubTarget]) -> str | None:
    reasons = [reason for target in targets if (reason := target_attribution_rejection(target))]
    return "; ".join(reasons) if reasons else None


def canonical_repository_rejection(target: GitHubTarget, canonical_full_name: object) -> str | None:
    """Reject repository transfers/redirects that escape the explicit target."""
    expected = (target.repo_full_name or "").strip()
    actual = str(canonical_full_name or "").strip()
    if expected and actual and expected.lower() == actual.lower():
        return None
    return (
        f"GitHub repository target {expected or target.url} resolved to "
        f"{actual or 'an unknown repository'}; update the subnet target explicitly before crediting activity"
    )


def canonical_owner_rejection(target: GitHubTarget, canonical_full_name: object) -> str | None:
    """Reject owner discovery rows returned under a different canonical owner."""
    actual = str(canonical_full_name or "").strip()
    actual_owner = actual.partition("/")[0]
    if actual_owner and actual_owner.lower() == target.owner.lower():
        return None
    return (
        f"GitHub owner target {target.owner} returned repository "
        f"{actual or 'with an unknown owner'}; update the subnet target explicitly before crediting activity"
    )
