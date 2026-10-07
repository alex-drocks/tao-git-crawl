from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

from .models import CreditExclusion, TargetKind

RepositoryPolicy = Literal["repository", "owner"]

VALID_REPOSITORY_POLICIES = {"repository", "owner"}
VALID_TARGET_KINDS = {"repository", "owner"}
CREDIT_EXCLUSION_KEYS = {"repo", "path", "commit", "reason", "except_paths"}
_REPOSITORY_FULL_NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?/[A-Za-z0-9._-]+$")
_COMMIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")


class ResolverConfigError(ValueError):
    """Raised when a user-supplied resolver config cannot be loaded safely."""


@dataclass(frozen=True)
class TargetOverride:
    kind: TargetKind
    url: str

    def __post_init__(self) -> None:
        if self.kind not in VALID_TARGET_KINDS:
            raise ResolverConfigError("target override kind must be one of 'repository' or 'owner'")
        if not self.url or not self.url.strip():
            raise ResolverConfigError("target override url must be a non-empty string")


@dataclass(frozen=True)
class SubnetOverride:
    targets: tuple[TargetOverride, ...] = ()
    replace: bool = True
    exclusions: tuple[CreditExclusion, ...] = ()

    def __post_init__(self) -> None:
        if self.exclusions and self.replace and not self.targets:
            raise ResolverConfigError(
                "a subnet override with exclusions but no targets must set replace to false so the subnet keeps "
                "its on-chain targets"
            )


@dataclass(frozen=True)
class ResolverConfig:
    default_repository_policy: RepositoryPolicy = "repository"
    subnet_overrides: dict[int, SubnetOverride] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.default_repository_policy not in VALID_REPOSITORY_POLICIES:
            raise ResolverConfigError("default_repository_policy must be one of 'repository' or 'owner'")


EMPTY_RESOLVER_CONFIG = ResolverConfig(
    subnet_overrides={},
)


def load_resolver_config(path: str | Path) -> ResolverConfig:
    """Load manual Bittensor target overrides from a user-owned Python file.

    The config file is intentionally Python because subnet-to-company mappings
    are messy and user-maintained. Only load files you control; Python configs
    execute as normal local code.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise ResolverConfigError(f"resolver config does not exist: {config_path}")
    module = _load_python_module(config_path)
    default_policy = getattr(module, "DEFAULT_REPOSITORY_POLICY", None)
    if default_policy is None:
        default_policy = getattr(module, "default_repository_policy", "repository")
    subnet_overrides = getattr(module, "SUBNET_OVERRIDES", None)
    if subnet_overrides is None:
        subnet_overrides = getattr(module, "subnet_overrides", {})
    return ResolverConfig(
        default_repository_policy=_parse_repository_policy(default_policy),
        subnet_overrides=_parse_subnet_overrides(subnet_overrides),
    )


def _load_python_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("_tao_git_crawl_user_config", path)
    if spec is None or spec.loader is None:
        raise ResolverConfigError(f"could not load resolver config: {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports config failures
        raise ResolverConfigError(f"failed to execute resolver config {path}: {exc}") from exc
    return module


def _parse_repository_policy(value: object) -> RepositoryPolicy:
    if not isinstance(value, str):
        raise ResolverConfigError("DEFAULT_REPOSITORY_POLICY must be 'repository' or 'owner'")
    normalized = value.strip().lower()
    if normalized not in VALID_REPOSITORY_POLICIES:
        raise ResolverConfigError("DEFAULT_REPOSITORY_POLICY must be 'repository' or 'owner'")
    return normalized  # type: ignore[return-value]


def _parse_subnet_overrides(value: object) -> dict[int, SubnetOverride]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ResolverConfigError("SUBNET_OVERRIDES must be a mapping of netuid to override definitions")
    overrides: dict[int, SubnetOverride] = {}
    for raw_netuid, raw_override in value.items():
        try:
            netuid = int(raw_netuid)
        except (TypeError, ValueError) as exc:
            raise ResolverConfigError(f"invalid subnet override netuid: {raw_netuid!r}") from exc
        overrides[netuid] = _parse_subnet_override(raw_override)
    return overrides


def _parse_subnet_override(value: object) -> SubnetOverride:
    if isinstance(value, SubnetOverride):
        return value
    if isinstance(value, list | tuple):
        return SubnetOverride(targets=tuple(_parse_target_override(item) for item in value), replace=True)
    if not isinstance(value, dict):
        raise ResolverConfigError("each subnet override must be a dict, list of targets, or SubnetOverride")
    if "registered_at" in value:
        raise ResolverConfigError("subnet override 'registered_at' is not supported")
    replace = _parse_replace(value.get("replace", True))
    raw_targets = value.get("targets", [])
    if not isinstance(raw_targets, list | tuple):
        raise ResolverConfigError("subnet override 'targets' must be a list")
    raw_exclusions = value.get("exclusions", [])
    if not isinstance(raw_exclusions, list | tuple):
        raise ResolverConfigError("subnet override 'exclusions' must be a list")
    return SubnetOverride(
        targets=tuple(_parse_target_override(item) for item in raw_targets),
        replace=replace,
        exclusions=tuple(parse_credit_exclusion(item) for item in raw_exclusions),
    )


def parse_credit_exclusion(value: object) -> CreditExclusion:
    """Validate one reviewed credit exclusion: an exact repository plus a path, a commit, or both."""
    if isinstance(value, CreditExclusion):
        value = value.to_dict()
    if not isinstance(value, dict):
        raise ResolverConfigError("credit exclusion must be an object")
    unsupported = sorted(set(value) - CREDIT_EXCLUSION_KEYS)
    if unsupported:
        raise ResolverConfigError(f"credit exclusion has unsupported keys: {', '.join(unsupported)}")
    repo = value.get("repo")
    if not isinstance(repo, str) or not _REPOSITORY_FULL_NAME_RE.match(repo.strip()):
        raise ResolverConfigError("credit exclusion 'repo' must be an exact 'owner/name' repository")
    reason = value.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ResolverConfigError("credit exclusion 'reason' must explain why the content is not the team's work")
    path = value.get("path")
    if path is not None:
        path = _parse_credit_path(path, "path")
    commit = value.get("commit")
    if commit is not None:
        if not isinstance(commit, str) or not _COMMIT_SHA_RE.match(commit.strip()):
            raise ResolverConfigError("credit exclusion 'commit' must be a 7-40 character hex SHA")
        commit = commit.strip().lower()
    if path is None and commit is None:
        raise ResolverConfigError("credit exclusion needs a 'path', a 'commit', or both")
    raw_except_paths = value.get("except_paths", [])
    if not isinstance(raw_except_paths, list | tuple):
        raise ResolverConfigError("credit exclusion 'except_paths' must be a list")
    except_paths = tuple(_parse_credit_path(item, "except_paths") for item in raw_except_paths)
    if path is not None and any(
        item != path.rstrip("/") and not item.startswith(f"{path.rstrip('/')}/")
        for item in except_paths
    ):
        raise ResolverConfigError("credit exclusion 'except_paths' must be inside its 'path' scope")
    return CreditExclusion(
        repo=repo.strip(), reason=reason.strip(), path=path, commit=commit, except_paths=except_paths
    )


def _parse_credit_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip().strip("/"):
        raise ResolverConfigError(f"credit exclusion '{field}' must be a non-empty repository path")
    path = value.strip().replace("\\", "/").lstrip("/")
    if not path or ".." in path.split("/"):
        raise ResolverConfigError(f"credit exclusion '{field}' must not contain '..' or an empty path")
    return path


def _parse_target_override(value: object) -> TargetOverride:
    if isinstance(value, TargetOverride):
        return value
    if isinstance(value, str):
        return TargetOverride(kind="owner", url=value)
    if not isinstance(value, dict):
        raise ResolverConfigError("target override must be a dict, string, or TargetOverride")
    if "confidence" in value:
        raise ResolverConfigError("target override confidence is not supported")
    kind = _require_string(value, "kind").strip().lower()
    url = _require_string(value, "url")
    return TargetOverride(kind=kind, url=url)  # type: ignore[arg-type]


def _require_string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ResolverConfigError(f"target override {key!r} must be a non-empty string")
    return item.strip()


def _parse_replace(value: object) -> bool:
    if isinstance(value, bool):
        return value
    raise ResolverConfigError("subnet override 'replace' must be a boolean")
