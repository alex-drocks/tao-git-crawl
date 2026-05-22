from importlib.metadata import version as _version

from .crawler import SubnetCrawlReport, crawl_resolved_subnets
from .models import GitHubTarget, SubnetIdentityRecord, UnresolvedSubnetRecord
from .overrides import ResolverConfig, SubnetOverride, TargetOverride, load_resolver_config
from .resolver import resolve_subnets

__all__ = [
    "GitHubTarget",
    "ResolverConfig",
    "SubnetCrawlReport",
    "SubnetIdentityRecord",
    "SubnetOverride",
    "TargetOverride",
    "UnresolvedSubnetRecord",
    "load_resolver_config",
    "crawl_resolved_subnets",
    "resolve_subnets",
]
try:
    __version__ = _version("tao-git-crawl")
except Exception:  # pragma: no cover
    __version__ = "0.0.0"
