from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

IDENTITY_FIELDS = (
    "subnet_name",
    "github_repo",
    "subnet_url",
    "description",
    "additional",
    "subnet_contact",
    "discord",
    "logo_url",
)
GITHUB_DISCOVERY_FIELDS = ("github_repo", "subnet_url", "description", "additional", "subnet_contact")

TargetKind = Literal["repository", "owner"]


@dataclass(frozen=True)
class SubnetIdentityRecord:
    netuid: int
    registered_at: int | None = None
    subnet_name: str = ""
    github_repo: str = ""
    subnet_url: str = ""
    description: str = ""
    additional: str = ""
    subnet_contact: str = ""
    discord: str = ""
    logo_url: str = ""

    @classmethod
    def from_mapping(cls, netuid: int, mapping: dict[str, object] | None) -> SubnetIdentityRecord:
        payload = mapping or {}
        values = {field: _to_text(payload.get(field, "")) for field in IDENTITY_FIELDS}
        registered_at = _to_positive_int(
            payload.get("registered_at", payload.get("registration_block"))
        )
        return cls(netuid=int(netuid), registered_at=registered_at, **values)

    def discovery_fields(self) -> dict[str, str]:
        return {field: getattr(self, field) for field in GITHUB_DISCOVERY_FIELDS}

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class GitHubTarget:
    netuid: int
    kind: TargetKind
    url: str
    owner: str
    repo: str | None
    repo_full_name: str | None
    source_field: str
    raw_value: str
    subnet_name: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class UnresolvedSubnetRecord:
    netuid: int
    subnet_name: str
    reason: str
    fields_checked: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _to_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return str(value).strip()


def _to_positive_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    else:
        return None
    return parsed if parsed > 0 else None
