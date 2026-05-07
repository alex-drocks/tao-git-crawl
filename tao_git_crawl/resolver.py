from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .github_links import extract_github_targets
from .models import GITHUB_DISCOVERY_FIELDS, GitHubTarget, SubnetIdentityRecord, UnresolvedSubnetRecord

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
    def git_crawl_repository_manifest(self) -> dict[str, object]:
        grouped: dict[str, dict[str, object]] = {}
        for target in self.repository_targets:
            entry = grouped.setdefault(
                target.url,
                {"url": target.url, "netuids": [], "sources": set()},
            )
            entry["netuids"].append(target.netuid)  # type: ignore[union-attr]
            entry["sources"].add(f"subnet_identity.{target.source_field}")  # type: ignore[union-attr]

        repositories: list[dict[str, object]] = []
        for url in sorted(grouped):
            entry = grouped[url]
            sources = sorted(entry.pop("sources"))  # type: ignore[arg-type]
            netuids = sorted(set(entry["netuids"]))  # type: ignore[arg-type]
            source = sources[0] if len(sources) == 1 else "mixed"
            repositories.append({"url": url, "netuids": netuids, "source": source})
        return {"target": self.target_label, "repositories": repositories}

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
) -> ResolutionDocument:
    targets: list[GitHubTarget] = []
    unresolved: list[UnresolvedSubnetRecord] = []
    for record in records:
        record_targets = extract_github_targets(record)
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
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
    return written


def _unresolved_reason(record: SubnetIdentityRecord) -> str:
    if record.github_repo or "github" in " ".join(record.discovery_fields().values()).lower():
        return "invalid_github_link"
    return "no_github_link"
