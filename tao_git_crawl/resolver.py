from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .github_links import extract_github_targets, manual_github_target_from_url
from .models import GITHUB_DISCOVERY_FIELDS, GitHubTarget, SubnetIdentityRecord, UnresolvedSubnetRecord
from .overrides import EMPTY_RESOLVER_CONFIG, ResolverConfig

RESOLUTION_SCHEMA_VERSION = "tao-git-crawl-resolution-v1"


@dataclass(frozen=True)
class ResolutionDocument:
    target_label: str
    targets: list[GitHubTarget]
    unresolved: list[UnresolvedSubnetRecord]
    schema_version: str = RESOLUTION_SCHEMA_VERSION

    @property
    def repository_targets(self) -> list[GitHubTarget]:
        return [target for target in self.targets if target.kind == "repository"]

    @property
    def owner_targets(self) -> list[GitHubTarget]:
        return [target for target in self.targets if target.kind == "owner"]

    @property
    def netuids(self) -> list[int]:
        return sorted({target.netuid for target in self.targets} | {item.netuid for item in self.unresolved})

    @property
    def git_crawl_repository_manifest(self) -> dict[str, object]:
        return self.git_crawl_repository_manifest_for_target(self.target_label)

    def git_crawl_repository_manifest_for_target(self, target_label: str) -> dict[str, object]:
        grouped: dict[str, dict[str, object]] = {}
        for target in self.repository_targets:
            entry = grouped.setdefault(
                target.url,
                {"url": target.url, "netuids": [], "sources": set()},
            )
            entry["netuids"].append(target.netuid)  # type: ignore[union-attr]
            entry["sources"].add(_source_label(target))  # type: ignore[union-attr]

        repositories: list[dict[str, object]] = []
        for url in sorted(grouped):
            entry = grouped[url]
            sources = sorted(entry.pop("sources"))  # type: ignore[arg-type]
            netuids = sorted(set(entry["netuids"]))  # type: ignore[arg-type]
            source = sources[0] if len(sources) == 1 else "mixed"
            repositories.append({"url": url, "netuids": netuids, "source": source})
        return {"target": target_label, "repositories": repositories}

    def for_netuid(self, netuid: int) -> ResolutionDocument:
        return ResolutionDocument(
            target_label=f"bittensor-subnet-{netuid}",
            targets=[target for target in self.targets if target.netuid == netuid],
            unresolved=[item for item in self.unresolved if item.netuid == netuid],
            schema_version=self.schema_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "target": self.target_label,
            "targets": [target.to_dict() for target in self.targets],
            "unresolved": [item.to_dict() for item in self.unresolved],
            "git_crawl_repository_manifest": self.git_crawl_repository_manifest,
        }


def resolve_subnets(
    records: list[SubnetIdentityRecord] | tuple[SubnetIdentityRecord, ...],
    *,
    target_label: str,
    config: ResolverConfig | None = None,
) -> ResolutionDocument:
    resolver_config = config or EMPTY_RESOLVER_CONFIG
    targets: list[GitHubTarget] = []
    unresolved: list[UnresolvedSubnetRecord] = []
    for record in records:
        record_targets = extract_github_targets(record)
        record_targets = _apply_repository_policy(record_targets, resolver_config.default_repository_policy)
        record_targets = _apply_manual_override(record, record_targets, resolver_config)
        record_targets = _dedupe_targets(record_targets)
        if record_targets:
            targets.extend(record_targets)
            continue
        unresolved.append(
            UnresolvedSubnetRecord(
                netuid=record.netuid,
                subnet_name=record.subnet_name,
                reason=_unresolved_reason(record),
                fields_checked=list(GITHUB_DISCOVERY_FIELDS),
            )
        )
    targets.sort(key=lambda item: (item.netuid, item.kind, item.url))
    unresolved.sort(key=lambda item: item.netuid)
    return ResolutionDocument(target_label=target_label, targets=targets, unresolved=unresolved)


def write_resolution_outputs(document: ResolutionDocument, output_dir: str | Path) -> list[Path]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    files = [
        (output_path / "subnet-targets.json", document.to_dict()),
        (output_path / "repository-manifest.json", document.git_crawl_repository_manifest),
        (output_path / "owner-targets.json", [target.to_dict() for target in document.owner_targets]),
        (output_path / "unresolved.json", [item.to_dict() for item in document.unresolved]),
    ]
    written: list[Path] = []
    for path, payload in files:
        _write_json(path, payload)
        written.append(path)
    for netuid in document.netuids:
        subnet_document = document.for_netuid(netuid)
        subnet_dir = output_path / "subnets" / str(netuid)
        subnet_files = [
            (subnet_dir / "subnet-targets.json", subnet_document.to_dict()),
            (subnet_dir / "repository-manifest.json", subnet_document.git_crawl_repository_manifest),
            (subnet_dir / "owner-targets.json", [target.to_dict() for target in subnet_document.owner_targets]),
            (subnet_dir / "unresolved.json", [item.to_dict() for item in subnet_document.unresolved]),
        ]
        for path, payload in subnet_files:
            _write_json(path, payload)
            written.append(path)
    return written


def _apply_repository_policy(targets: list[GitHubTarget], policy: str) -> list[GitHubTarget]:
    if policy == "repository":
        return targets
    if policy != "owner":
        raise ValueError("repository policy must be one of 'repository' or 'owner'")
    return [
        _promote_repository_target_to_owner(target) if target.kind == "repository" else target
        for target in targets
    ]


def _promote_repository_target_to_owner(target: GitHubTarget) -> GitHubTarget:
    return GitHubTarget(
        netuid=target.netuid,
        kind="owner",
        url=f"https://github.com/{target.owner}",
        owner=target.owner,
        repo=None,
        repo_full_name=None,
        source_field=target.source_field,
        raw_value=target.raw_value,
        subnet_name=target.subnet_name,
    )


def _apply_manual_override(
    record: SubnetIdentityRecord,
    targets: list[GitHubTarget],
    config: ResolverConfig,
) -> list[GitHubTarget]:
    override = config.subnet_overrides.get(record.netuid)
    if override is None:
        return targets
    override_targets = [
        manual_github_target_from_url(
            record,
            kind=target.kind,
            url=target.url,
        )
        for target in override.targets
    ]
    if override.replace:
        return override_targets
    return [*targets, *override_targets]


def _dedupe_targets(targets: list[GitHubTarget]) -> list[GitHubTarget]:
    grouped: dict[tuple[int, str, str], GitHubTarget] = {}
    for target in targets:
        grouped.setdefault((target.netuid, target.kind, target.url.lower()), target)
    return list(grouped.values())


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _source_label(target: GitHubTarget) -> str:
    if target.source_field == "manual_override":
        return "manual_override"
    return f"subnet_identity.{target.source_field}"


def _unresolved_reason(record: SubnetIdentityRecord) -> str:
    if record.github_repo or "github" in " ".join(record.discovery_fields().values()).lower():
        return "invalid_github_link"
    return "no_github_link"
