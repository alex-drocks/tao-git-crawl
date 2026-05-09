from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from git_crawl.github import GitHubAPIError, list_owner_repositories, list_repositories_from_urls
from git_crawl.pipeline import REF_SCOPE_DEFAULT_BRANCH, crawl_repositories, write_crawl_outputs
from git_crawl.redaction import redact_text

from .models import GitHubTarget
from .resolver import ResolutionDocument


@dataclass(frozen=True)
class SubnetCrawlFailure:
    netuid: int
    target_label: str
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {"netuid": self.netuid, "target": self.target_label, "reason": self.reason}


@dataclass(frozen=True)
class SubnetCrawlSkip:
    netuid: int
    target_label: str
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {"netuid": self.netuid, "target": self.target_label, "reason": self.reason}


@dataclass(frozen=True)
class RepositoryResolution:
    repositories: list[Any]
    skipped_inaccessible: list[str]


@dataclass(frozen=True)
class SubnetCrawlSuccess:
    netuid: int
    target_label: str
    output_dir: Path
    repositories: int
    status: str
    written_files: tuple[Path, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "netuid": self.netuid,
            "target": self.target_label,
            "output_dir": str(self.output_dir),
            "repositories": self.repositories,
            "status": self.status,
            "written_files": [str(path) for path in self.written_files],
        }


@dataclass(frozen=True)
class SubnetCrawlReport:
    succeeded: list[SubnetCrawlSuccess]
    failed: list[SubnetCrawlFailure]
    skipped_unresolved_netuids: list[int]
    skipped_inaccessible: list[SubnetCrawlSkip]
    report_path: Path | None = None

    @property
    def succeeded_netuids(self) -> list[int]:
        return [item.netuid for item in self.succeeded]

    def to_dict(self) -> dict[str, object]:
        return {
            "succeeded": [item.to_dict() for item in self.succeeded],
            "failed": [item.to_dict() for item in self.failed],
            "skipped_unresolved_netuids": list(self.skipped_unresolved_netuids),
            "skipped_inaccessible": [item.to_dict() for item in self.skipped_inaccessible],
        }


def crawl_resolved_subnets(
    document: ResolutionDocument,
    *,
    output_dir: str | Path,
    cache_dir: str | Path,
    state_db: str | Path | None = None,
    token: str | None = None,
    active_since: str | None = None,
    since: str | None = None,
    until: str | None = None,
    include_archived: bool = False,
    include_forks: bool = False,
    max_repos: int | None = None,
    prefer_ssh: bool = False,
    ref_scope: str = REF_SCOPE_DEFAULT_BRANCH,
    workers: int = 1,
    fail_fast: bool = False,
    output_format: str = "all",
) -> SubnetCrawlReport:
    """Crawl each resolved subnet independently under subnet-scoped target labels."""
    output_path = Path(output_dir)
    cache_path = Path(cache_dir)
    succeeded: list[SubnetCrawlSuccess] = []
    failed: list[SubnetCrawlFailure] = []
    skipped_inaccessible: list[SubnetCrawlSkip] = []
    unresolved_netuids = {item.netuid for item in document.unresolved}

    for netuid in document.netuids:
        subnet_document = document.for_netuid(netuid)
        if not subnet_document.targets:
            continue
        target_label = subnet_document.target_label
        try:
            resolution = _resolve_repositories_for_subnet(subnet_document.targets, token=token, max_repos=max_repos)
            skipped_inaccessible.extend(
                SubnetCrawlSkip(netuid=netuid, target_label=target_label, reason=reason)
                for reason in resolution.skipped_inaccessible
            )
            if not resolution.repositories and resolution.skipped_inaccessible:
                continue
            result = crawl_repositories(
                target_label,
                resolution.repositories,
                cache_dir=cache_path,
                state_db=state_db,
                active_since=active_since,
                since=since,
                until=until,
                include_archived=include_archived,
                include_forks=include_forks,
                max_repos=max_repos,
                prefer_ssh=prefer_ssh,
                ref_scope=ref_scope,
                workers=workers,
                fail_fast=fail_fast,
            )
            subnet_output_dir = output_path / "subnets" / str(netuid) / "crawl"
            written_files = tuple(
                write_crawl_outputs(
                    result,
                    subnet_output_dir,
                    write_json=output_format in {"all", "jsonl"},
                    write_csv_files=output_format in {"all", "csv"},
                )
            )
            success = SubnetCrawlSuccess(
                netuid=netuid,
                target_label=target_label,
                output_dir=subnet_output_dir,
                repositories=len(result.repositories),
                status=result.run.status,
                written_files=written_files,
            )
            if result.run.status == "success":
                succeeded.append(success)
                continue
            failed.append(
                SubnetCrawlFailure(
                    netuid=netuid,
                    target_label=target_label,
                    reason=_crawl_status_failure_reason(result),
                )
            )
            if fail_fast:
                break
        except Exception as exc:  # noqa: BLE001 - per-subnet failures should not abort the whole dataset
            failed.append(SubnetCrawlFailure(netuid=netuid, target_label=target_label, reason=redact_text(exc)))
            if fail_fast:
                break

    report = SubnetCrawlReport(
        succeeded=succeeded,
        failed=failed,
        skipped_unresolved_netuids=sorted(unresolved_netuids),
        skipped_inaccessible=skipped_inaccessible,
    )
    report_path = output_path / "crawl-report.json"
    _write_report(report_path, report.to_dict())
    return SubnetCrawlReport(
        succeeded=report.succeeded,
        failed=report.failed,
        skipped_unresolved_netuids=report.skipped_unresolved_netuids,
        skipped_inaccessible=report.skipped_inaccessible,
        report_path=report_path,
    )


def _resolve_repositories_for_subnet(
    targets: list[GitHubTarget] | tuple[GitHubTarget, ...],
    *,
    token: str | None,
    max_repos: int | None,
) -> RepositoryResolution:
    repositories: list[Any] = []
    skipped_inaccessible: list[str] = []
    repo_urls = [target.url for target in targets if target.kind == "repository"]
    for repo_url in repo_urls:
        if _has_reached_max_repos(repositories, max_repos):
            break
        try:
            repositories.extend(list_repositories_from_urls([repo_url], token=token, max_repos=1))
        except GitHubAPIError as exc:
            if exc.status_code != 404:
                raise
            skipped_inaccessible.append(redact_text(exc))
    for target in targets:
        if target.kind != "owner":
            continue
        if _has_reached_max_repos(repositories, max_repos):
            break
        try:
            owner_repos = list_owner_repositories(target.owner, owner_type="auto", token=token)
            if max_repos is not None:
                remaining = max_repos - len(_dedupe_repositories(repositories))
                if remaining <= 0:
                    break
                owner_repos = owner_repos[:remaining]
            repositories.extend(owner_repos)
        except GitHubAPIError as exc:
            if exc.status_code != 404:
                raise
            skipped_inaccessible.append(redact_text(exc))
    return RepositoryResolution(
        repositories=_dedupe_repositories(repositories),
        skipped_inaccessible=skipped_inaccessible,
    )


def _crawl_status_failure_reason(result: Any) -> str:
    status = str(getattr(getattr(result, "run", None), "status", "unknown"))
    failed_repositories = list(getattr(result, "failed_repositories", []) or [])
    if not failed_repositories:
        return f"crawl completed with status {status}"

    details: list[str] = []
    for failure in failed_repositories[:5]:
        full_name = getattr(failure, "full_name", getattr(failure, "repo", "repository"))
        error = getattr(failure, "error", "")
        details.append(f"{full_name}: {error}" if error else str(full_name))
    if len(failed_repositories) > len(details):
        details.append(f"{len(failed_repositories) - len(details)} more failed repositories")
    return redact_text(f"crawl completed with status {status}; failed repositories: {'; '.join(details)}")


def _has_reached_max_repos(repositories: list[Any], max_repos: int | None) -> bool:
    return max_repos is not None and len(_dedupe_repositories(repositories)) >= max_repos


def _dedupe_repositories(repositories: list[Any]) -> list[Any]:
    seen: set[str] = set()
    deduped: list[Any] = []
    for repo in repositories:
        key = str(getattr(repo, "full_name", getattr(repo, "name", ""))).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(repo)
    return deduped


def _write_report(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
