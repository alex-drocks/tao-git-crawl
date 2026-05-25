from __future__ import annotations

import re
import urllib.parse

from git_crawl.github import GITHUB_OWNER_RE, GITHUB_REPO_RE, GitHubURLParseError, parse_github_repo_url

from .models import GITHUB_DISCOVERY_FIELDS, GitHubTarget, SubnetIdentityRecord

GITHUB_OWNER_PATTERN = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?"
GITHUB_RESERVED_OWNER_PATHS = {
    "about",
    "apps",
    "codespaces",
    "collections",
    "customer-stories",
    "dashboard",
    "enterprise",
    "enterprises",
    "explore",
    "features",
    "github-copilot",
    "gist",
    "issues",
    "join",
    "login",
    "marketplace",
    "mobile",
    "new",
    "notifications",
    "open-source",
    "orgs",
    "organizations",
    "pricing",
    "pulls",
    "readme",
    "search",
    "security",
    "settings",
    "site",
    "solutions",
    "sponsors",
    "topics",
    "trending",
}
URL_LEFT_BOUNDARY = r"(?<![A-Za-z0-9._/@:-])"
OWNER_URL_RIGHT_BOUNDARY = r"(?![A-Za-z0-9_/-]|\.[A-Za-z0-9_/-])"
REPOSITORY_URL_RE = re.compile(
    URL_LEFT_BOUNDARY +
    r"(?:"
    rf"git@github\.com:{GITHUB_OWNER_PATTERN}/[A-Za-z0-9._-]+(?:\.git)?"
    r"|"
    r"(?:https?://)?(?:www\.)?github\.com/"
    rf"{GITHUB_OWNER_PATTERN}/[A-Za-z0-9._-]+(?:\.git)?"
    r"(?:(?:/(?:tree|blob|commit|releases)(?:/[^\s<>'\")]+)?)|/)?"
    r"(?:[?#][^\s<>'\")]+)?"
    r")"
    r"(?![A-Za-z0-9._/-])"
)

OWNER_URL_RE = re.compile(
    URL_LEFT_BOUNDARY +
    r"(?:https?://)?(?:www\.)?github\.com/"
    r"(?:"
    rf"orgs/{GITHUB_OWNER_PATTERN}(?:/repositories)?"
    r"|"
    rf"{GITHUB_OWNER_PATTERN}"
    r")"
    r"/?"
    r"(?:[?#][^\s<>'\")]+)?"
    + OWNER_URL_RIGHT_BOUNDARY
)

BARE_OWNER_REPO_RE = re.compile(
    rf"^(?P<owner>{GITHUB_OWNER_PATTERN})/(?P<repo>[A-Za-z0-9._-]+)(?:\.git)?$"
)
BARE_OWNER_REPO_TEXT_RE = re.compile(
    URL_LEFT_BOUNDARY +
    rf"{GITHUB_OWNER_PATTERN}/[A-Za-z0-9._-]+(?:\.git)?"
    r"(?![A-Za-z0-9._/-])"
)
BARE_OWNER_REPO_CONTEXT_RE = re.compile(
    r"github(?:\s+(?:repo|repos|repository|source(?:\s+code)?|code))?\s*(?::|=|-|is|at|->)?\s*$",
    re.IGNORECASE,
)

def extract_github_targets(record: SubnetIdentityRecord) -> list[GitHubTarget]:
    """Extract normalized GitHub repository and owner targets from subnet identity fields."""
    targets: list[GitHubTarget] = []
    seen: set[tuple[str, str]] = set()

    for field in GITHUB_DISCOVERY_FIELDS:
        raw_value = getattr(record, field)
        if not raw_value:
            continue
        for candidate in _candidate_values(field, raw_value):
            target = _target_from_candidate(record, field, raw_value, candidate)
            if target is None:
                continue
            key = (target.kind, target.url.lower())
            if key in seen:
                continue
            targets.append(target)
            seen.add(key)
    return targets


def manual_github_target_from_url(
    record: SubnetIdentityRecord,
    *,
    kind: str,
    url: str,
) -> GitHubTarget:
    """Build a normalized target from a manual config override URL."""
    if kind == "owner":
        owner = _parse_owner_candidate(url)
        if owner is None:
            repository = _parse_repository_candidate(url)
            if repository is None:
                raise ValueError(f"manual owner override is not a GitHub owner or repository URL: {url!r}")
            owner = repository.owner
        return GitHubTarget(
            netuid=record.netuid,
            kind="owner",
            url=f"https://github.com/{owner}",
            owner=owner,
            repo=None,
            repo_full_name=None,
            source_field="manual_override",
            raw_value=url,
            subnet_name=record.subnet_name,
        )
    if kind == "repository":
        repository = _parse_repository_candidate(url)
        if repository is None:
            raise ValueError(f"manual repository override is not a GitHub repository URL: {url!r}")
        return GitHubTarget(
            netuid=record.netuid,
            kind="repository",
            url=repository.html_url,
            owner=repository.owner,
            repo=repository.repo,
            repo_full_name=repository.full_name,
            source_field="manual_override",
            raw_value=url,
            subnet_name=record.subnet_name,
        )
    raise ValueError("manual override kind must be one of 'repository' or 'owner'")


def _candidate_values(field: str, raw_value: str) -> list[str]:
    candidates: list[str] = []
    if field in {"github_repo", "subnet_url"}:
        candidates.append(raw_value.strip())
    candidates.extend(match.group(0).strip().rstrip(".,;") for match in REPOSITORY_URL_RE.finditer(raw_value))
    candidates.extend(match.group(0).strip().rstrip(".,;") for match in OWNER_URL_RE.finditer(raw_value))
    candidates.extend(
        match.group(0).strip().rstrip(".,;")
        for match in BARE_OWNER_REPO_TEXT_RE.finditer(raw_value)
        if _bare_owner_repo_context_allows(field, raw_value, match.start())
    )
    return [candidate for candidate in candidates if candidate]


def _bare_owner_repo_context_allows(field: str, raw_value: str, start: int) -> bool:
    if field in {"github_repo", "subnet_url"}:
        return True
    context = raw_value[max(0, start - 80) : start]
    return BARE_OWNER_REPO_CONTEXT_RE.search(context) is not None


def _target_from_candidate(
    record: SubnetIdentityRecord,
    field: str,
    raw_value: str,
    candidate: str,
) -> GitHubTarget | None:
    owner = _parse_owner_root(candidate)
    if owner is not None:
        return GitHubTarget(
            netuid=record.netuid,
            kind="owner",
            url=f"https://github.com/{owner}",
            owner=owner,
            repo=None,
            repo_full_name=None,
            source_field=field,
            raw_value=raw_value,
            subnet_name=record.subnet_name,
        )

    repository = _parse_repository_candidate(candidate)
    if repository is not None:
        return GitHubTarget(
            netuid=record.netuid,
            kind="repository",
            url=repository.html_url,
            owner=repository.owner,
            repo=repository.repo,
            repo_full_name=repository.full_name,
            source_field=field,
            raw_value=raw_value,
            subnet_name=record.subnet_name,
        )
    return None


def _parse_repository_candidate(candidate: str):
    prepared = _prepare_repository_url(candidate)
    try:
        repository = parse_github_repo_url(prepared)
    except GitHubURLParseError:
        return None
    if repository.owner.lower() in GITHUB_RESERVED_OWNER_PATHS:
        return None
    return repository


def _prepare_repository_url(candidate: str) -> str:
    candidate = candidate.strip()
    bare = BARE_OWNER_REPO_RE.fullmatch(candidate)
    if bare:
        owner = bare.group("owner")
        repo = bare.group("repo").removesuffix(".git")
        if GITHUB_OWNER_RE.fullmatch(owner) and GITHUB_REPO_RE.fullmatch(repo):
            return f"https://github.com/{owner}/{repo}"
    if candidate.startswith("github.com/") or candidate.startswith("www.github.com/"):
        return f"https://{candidate}"
    return candidate


def _parse_owner_candidate(candidate: str) -> str | None:
    candidate = candidate.strip().rstrip("/")
    if GITHUB_OWNER_RE.fullmatch(candidate) and candidate.lower() not in GITHUB_RESERVED_OWNER_PATHS:
        return candidate
    return _parse_owner_root(candidate)


def _parse_owner_root(candidate: str) -> str | None:
    candidate = candidate.strip().rstrip("/")
    if candidate.startswith("github.com/") or candidate.startswith("www.github.com/"):
        candidate = f"https://{candidate}"
    parsed = urllib.parse.urlparse(candidate)
    if (parsed.hostname or "").lower() != "github.com":
        return None
    path_parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(path_parts) in {2, 3} and path_parts[0] == "orgs" and path_parts[-1] in {path_parts[1], "repositories"}:
        path_parts = [path_parts[1]]
    if len(path_parts) != 1:
        return None
    owner = urllib.parse.unquote(path_parts[0])
    if owner.lower() in GITHUB_RESERVED_OWNER_PATHS or not GITHUB_OWNER_RE.fullmatch(owner):
        return None
    return owner
