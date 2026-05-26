from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from git_crawl.github import (
    GitHubAPIError,
    list_owner_repositories,
    list_repositories_from_urls,
    partition_repositories,
)
from git_crawl.metrics import CommitChangesFiltrationLevel
from git_crawl.pipeline import (
    DEFAULT_COMMIT_CHANGES_FILTRATION_LEVEL,
    REF_SCOPE_DEFAULT_BRANCH,
    crawl_repositories,
    write_crawl_outputs,
)
from git_crawl.redaction import redact_text

from .models import GitHubTarget
from .resolver import ResolutionDocument
from .scoring import write_score_outputs


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
class SubnetFallbackUse:
    netuid: int
    target_label: str
    primary_reasons: list[str]
    fallback_targets: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "netuid": self.netuid,
            "target": self.target_label,
            "primary_reasons": list(self.primary_reasons),
            "fallback_targets": list(self.fallback_targets),
        }


@dataclass(frozen=True)
class RepositoryResolution:
    repositories: list[Any]
    skipped_inaccessible: list[str]
    inaccessible_status_codes: list[int]
    attempted_targets: int


@dataclass(frozen=True)
class _RepositoryLimitView:
    full_name: str
    pushed_at: str | None
    archived: bool
    fork: bool
    private: bool


@dataclass(frozen=True)
class SubnetCrawlSuccess:
    netuid: int
    target_label: str
    output_dir: Path
    repositories: int
    status: str
    run_id: str
    written_files: tuple[Path, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "netuid": self.netuid,
            "target": self.target_label,
            "output_dir": str(self.output_dir),
            "repositories": self.repositories,
            "run_id": self.run_id,
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
    fallback_used: list[SubnetFallbackUse] = field(default_factory=list)

    @property
    def succeeded_netuids(self) -> list[int]:
        return [item.netuid for item in self.succeeded]

    def to_dict(self) -> dict[str, object]:
        return {
            "succeeded": [item.to_dict() for item in self.succeeded],
            "failed": [item.to_dict() for item in self.failed],
            "skipped_unresolved_netuids": list(self.skipped_unresolved_netuids),
            "skipped_inaccessible": [item.to_dict() for item in self.skipped_inaccessible],
            "fallback_used": [item.to_dict() for item in self.fallback_used],
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
    commit_changes_filtration_level: CommitChangesFiltrationLevel = DEFAULT_COMMIT_CHANGES_FILTRATION_LEVEL,
) -> SubnetCrawlReport:
    """Crawl each resolved subnet independently under subnet-scoped target labels."""
    output_path = Path(output_dir)
    cache_path = Path(cache_dir)
    succeeded: list[SubnetCrawlSuccess] = []
    failed: list[SubnetCrawlFailure] = []
    skipped_inaccessible: list[SubnetCrawlSkip] = []
    fallback_used: list[SubnetFallbackUse] = []
    unresolved_netuids = {item.netuid for item in document.unresolved}
    _publish_progress_outputs(
        document,
        output_path,
        succeeded=succeeded,
        failed=failed,
        skipped_unresolved_netuids=unresolved_netuids,
        skipped_inaccessible=skipped_inaccessible,
        fallback_used=fallback_used,
    )

    for netuid in document.netuids:
        subnet_document = document.for_netuid(netuid)
        if not subnet_document.targets:
            continue
        target_label = subnet_document.target_label
        try:
            resolution = _resolve_repositories_for_subnet(
                subnet_document.targets,
                token=token,
                active_since=active_since,
                include_archived=include_archived,
                include_forks=include_forks,
                max_repos=max_repos,
            )
            if _should_retry_with_fallback(resolution, subnet_document.fallback_targets):
                fallback_resolution = _resolve_repositories_for_subnet(
                    subnet_document.fallback_targets,
                    token=token,
                    active_since=active_since,
                    include_archived=include_archived,
                    include_forks=include_forks,
                    max_repos=max_repos,
                )
                if fallback_resolution.repositories:
                    fallback_used.append(
                        SubnetFallbackUse(
                            netuid=netuid,
                            target_label=target_label,
                            primary_reasons=list(resolution.skipped_inaccessible),
                            fallback_targets=[target.url for target in subnet_document.fallback_targets],
                        )
                    )
                    skipped_inaccessible.extend(
                        SubnetCrawlSkip(netuid=netuid, target_label=target_label, reason=reason)
                        for reason in fallback_resolution.skipped_inaccessible
                    )
                    resolution = fallback_resolution
                else:
                    skipped_inaccessible.extend(
                        SubnetCrawlSkip(netuid=netuid, target_label=target_label, reason=reason)
                        for reason in resolution.skipped_inaccessible
                    )
                    skipped_inaccessible.extend(
                        SubnetCrawlSkip(netuid=netuid, target_label=target_label, reason=reason)
                        for reason in fallback_resolution.skipped_inaccessible
                    )
                    _publish_progress_outputs(
                        document,
                        output_path,
                        succeeded=succeeded,
                        failed=failed,
                        skipped_unresolved_netuids=unresolved_netuids,
                        skipped_inaccessible=skipped_inaccessible,
                        fallback_used=fallback_used,
                    )
                    continue
            else:
                skipped_inaccessible.extend(
                    SubnetCrawlSkip(netuid=netuid, target_label=target_label, reason=reason)
                    for reason in resolution.skipped_inaccessible
                )
                if not resolution.repositories and resolution.skipped_inaccessible:
                    _publish_progress_outputs(
                        document,
                        output_path,
                        succeeded=succeeded,
                        failed=failed,
                        skipped_unresolved_netuids=unresolved_netuids,
                        skipped_inaccessible=skipped_inaccessible,
                        fallback_used=fallback_used,
                    )
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
                commit_changes_filtration_level=commit_changes_filtration_level,
            )
            subnet_output_dir = output_path / "subnets" / str(netuid) / "crawl"
            written_files = tuple(
                write_crawl_outputs(
                    result,
                    subnet_output_dir,
                    write_json=True,
                    write_csv_files=False,
                )
            )
            success = SubnetCrawlSuccess(
                netuid=netuid,
                target_label=target_label,
                output_dir=subnet_output_dir,
                repositories=len(result.repositories),
                status=result.run.status,
                run_id=getattr(result.run, "run_id", ""),
                written_files=written_files,
            )
            if result.run.status == "success":
                succeeded.append(success)
                _publish_progress_outputs(
                    document,
                    output_path,
                    succeeded=succeeded,
                    failed=failed,
                    skipped_unresolved_netuids=unresolved_netuids,
                    skipped_inaccessible=skipped_inaccessible,
                    fallback_used=fallback_used,
                )
                continue
            failed.append(
                SubnetCrawlFailure(
                    netuid=netuid,
                    target_label=target_label,
                    reason=_crawl_status_failure_reason(result),
                )
            )
            _publish_progress_outputs(
                document,
                output_path,
                succeeded=succeeded,
                failed=failed,
                skipped_unresolved_netuids=unresolved_netuids,
                skipped_inaccessible=skipped_inaccessible,
                fallback_used=fallback_used,
            )
            if fail_fast:
                break
        except Exception as exc:  # noqa: BLE001 - per-subnet failures should not abort the whole dataset
            failed.append(SubnetCrawlFailure(netuid=netuid, target_label=target_label, reason=redact_text(exc)))
            _publish_progress_outputs(
                document,
                output_path,
                succeeded=succeeded,
                failed=failed,
                skipped_unresolved_netuids=unresolved_netuids,
                skipped_inaccessible=skipped_inaccessible,
                fallback_used=fallback_used,
            )
            if fail_fast:
                break

    return _publish_progress_outputs(
        document,
        output_path,
        succeeded=succeeded,
        failed=failed,
        skipped_unresolved_netuids=unresolved_netuids,
        skipped_inaccessible=skipped_inaccessible,
        fallback_used=fallback_used,
    )


def _publish_progress_outputs(
    document: ResolutionDocument,
    output_path: Path,
    *,
    succeeded: list[SubnetCrawlSuccess],
    failed: list[SubnetCrawlFailure],
    skipped_unresolved_netuids: set[int],
    skipped_inaccessible: list[SubnetCrawlSkip],
    fallback_used: list[SubnetFallbackUse],
) -> SubnetCrawlReport:
    report = SubnetCrawlReport(
        succeeded=list(succeeded),
        failed=list(failed),
        skipped_unresolved_netuids=sorted(skipped_unresolved_netuids),
        skipped_inaccessible=list(skipped_inaccessible),
        report_path=output_path / "crawl-report.json",
        fallback_used=list(fallback_used),
    )
    report_path = output_path / "crawl-report.json"
    _write_report(report_path, report.to_dict())
    write_score_outputs(document, output_path)
    return report


def _resolve_repositories_for_subnet(
    targets: list[GitHubTarget] | tuple[GitHubTarget, ...],
    *,
    token: str | None,
    active_since: str | None,
    include_archived: bool,
    include_forks: bool,
    max_repos: int | None,
) -> RepositoryResolution:
    repositories: list[Any] = []
    skipped_inaccessible: list[str] = []
    inaccessible_status_codes: list[int] = []
    attempted_targets = 0
    repo_urls = [target.url for target in targets if target.kind == "repository"]
    for repo_url in repo_urls:
        if _has_reached_selected_repo_limit(
            repositories,
            active_since=active_since,
            include_archived=include_archived,
            include_forks=include_forks,
            max_repos=max_repos,
        ):
            break
        attempted_targets += 1
        try:
            _append_unique_repositories(
                repositories,
                list_repositories_from_urls([repo_url], token=token, max_repos=1),
                active_since=active_since,
                include_archived=include_archived,
                include_forks=include_forks,
                max_repos=max_repos,
            )
        except GitHubAPIError as exc:
            if exc.status_code != 404:
                raise
            skipped_inaccessible.append(redact_text(exc))
            inaccessible_status_codes.append(exc.status_code)
    for target in targets:
        if target.kind != "owner":
            continue
        if _has_reached_selected_repo_limit(
            repositories,
            active_since=active_since,
            include_archived=include_archived,
            include_forks=include_forks,
            max_repos=max_repos,
        ):
            break
        attempted_targets += 1
        try:
            owner_repos = list_owner_repositories(target.owner, owner_type="auto", token=token)
            _append_unique_repositories(
                repositories,
                owner_repos,
                active_since=active_since,
                include_archived=include_archived,
                include_forks=include_forks,
                max_repos=max_repos,
            )
        except GitHubAPIError as exc:
            if exc.status_code != 404:
                raise
            skipped_inaccessible.append(redact_text(exc))
            inaccessible_status_codes.append(exc.status_code)
    return RepositoryResolution(
        repositories=_dedupe_repositories(repositories),
        skipped_inaccessible=skipped_inaccessible,
        inaccessible_status_codes=inaccessible_status_codes,
        attempted_targets=attempted_targets,
    )


def _should_retry_with_fallback(
    resolution: RepositoryResolution,
    fallback_targets: list[GitHubTarget] | tuple[GitHubTarget, ...],
) -> bool:
    if not fallback_targets or resolution.repositories or resolution.attempted_targets <= 0:
        return False
    return (
        len(resolution.inaccessible_status_codes) == resolution.attempted_targets
        and all(status == 404 for status in resolution.inaccessible_status_codes)
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


def _has_reached_selected_repo_limit(
    repositories: list[Any],
    *,
    active_since: str | None,
    include_archived: bool,
    include_forks: bool,
    max_repos: int | None,
) -> bool:
    if max_repos is None:
        return False
    selected, _excluded = partition_repositories(
        [_repository_limit_view(repo) for repo in _dedupe_repositories(repositories)],
        active_since=active_since,
        include_archived=include_archived,
        include_forks=include_forks,
        max_repos=max_repos,
    )
    return len(selected) >= max_repos


def _append_unique_repositories(
    repositories: list[Any],
    candidates: list[Any],
    *,
    active_since: str | None,
    include_archived: bool,
    include_forks: bool,
    max_repos: int | None,
) -> None:
    seen = {_repository_key(repo) for repo in repositories}
    seen.discard("")
    for repo in candidates:
        key = _repository_key(repo)
        if not key or key in seen:
            continue
        repositories.append(repo)
        seen.add(key)
        # Count the same selected repository set that git-crawl will crawl; excluded
        # archived/fork/private/inactive repos should not consume --max-repos.
        if _has_reached_selected_repo_limit(
            repositories,
            active_since=active_since,
            include_archived=include_archived,
            include_forks=include_forks,
            max_repos=max_repos,
        ):
            break


def _dedupe_repositories(repositories: list[Any]) -> list[Any]:
    seen: set[str] = set()
    deduped: list[Any] = []
    for repo in repositories:
        key = _repository_key(repo)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(repo)
    return deduped


def _repository_key(repo: Any) -> str:
    return str(getattr(repo, "full_name", getattr(repo, "name", ""))).lower()


def _repository_limit_view(repo: Any) -> _RepositoryLimitView:
    return _RepositoryLimitView(
        full_name=_repository_key(repo),
        pushed_at=getattr(repo, "pushed_at", None),
        archived=bool(getattr(repo, "archived", False)),
        fork=bool(getattr(repo, "fork", False)),
        private=bool(getattr(repo, "private", False)),
    )


def _write_report(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
