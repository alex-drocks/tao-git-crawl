from importlib import import_module
from importlib.metadata import version as _version

from .models import GitHubTarget, SubnetIdentityRecord, UnresolvedSubnetRecord
from .overrides import ResolverConfig, SubnetOverride, TargetOverride, load_resolver_config

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


def __getattr__(name: str) -> object:
    if name in {"SubnetCrawlReport", "crawl_resolved_subnets"}:
        module = import_module(".crawler", __name__)
        value = getattr(module, name)
        globals()[name] = value
        return value
    if name == "resolve_subnets":
        module = import_module(".resolver", __name__)
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
