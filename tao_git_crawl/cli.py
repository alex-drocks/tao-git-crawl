from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from dotenv import load_dotenv
from git_crawl.github import token_from_env

from .crawler import crawl_resolved_subnets
from .overrides import ResolverConfig, ResolverConfigError, load_resolver_config
from .providers import (
    DEFAULT_ENDPOINT,
    DEFAULT_NETWORK,
    DEFAULT_NETWORK_ENDPOINTS,
    MAX_REGULAR_SUBNET_NETUID,
    MIN_REGULAR_SUBNET_NETUID,
    JsonSubnetIdentityProvider,
    SubstrateSubnetIdentityProvider,
)
from .registry import RegistryError, load_registry, resolver_config_from_registry
from .resolver import resolve_subnets, write_resolution_outputs


def _add_resolution_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--from-json", type=Path, help="read subnet identity records from a JSON fixture/export")
    parser.add_argument(
        "--network",
        choices=sorted(DEFAULT_NETWORK_ENDPOINTS),
        default=DEFAULT_NETWORK,
        help="Bittensor network endpoint preset for live chain queries (default: finney)",
    )
    parser.add_argument("--endpoint", help=f"override live chain WebSocket endpoint (default: {DEFAULT_ENDPOINT})")
    parser.add_argument(
        "--netuid",
        type=_regular_subnet_netuid,
        action="append",
        help=(
            "limit resolution to one regular subnet netuid "
            f"({MIN_REGULAR_SUBNET_NETUID}-{MAX_REGULAR_SUBNET_NETUID}); repeatable"
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="user-owned Python config.py with DEFAULT_REPOSITORY_POLICY and SUBNET_OVERRIDES",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        help="local JSON registry file with subnet overrides (merged over built-in defaults)",
    )
    parser.add_argument(
        "--registry-url",
        help="remote URL of a JSON registry with subnet overrides (merged over built-in defaults)",
    )
    parser.add_argument(
        "--repository-policy",
        choices=["repository", "owner"],
        help="how to treat exact repository links by default; 'owner' promotes repo links to owner crawls",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tao-git-crawl",
        description="Resolve Bittensor subnet GitHub identity metadata into git-crawl manifests.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve = subparsers.add_parser("resolve", help="resolve subnet GitHub links from JSON or live chain state")
    _add_resolution_arguments(resolve)
    resolve.add_argument("--target", default="bittensor-subnets", help="target label for git-crawl manifest output")
    resolve.add_argument(
        "--output-dir",
        type=Path,
        default=Path("out/tao-git-crawl"),
        help="directory for JSON outputs",
    )

    crawl = subparsers.add_parser("crawl", help="resolve and crawl subnet GitHub targets into per-subnet metrics")
    _add_resolution_arguments(crawl)
    crawl.add_argument("--target", default="bittensor-subnets", help="target label for aggregate resolver output")
    crawl.add_argument(
        "--output-dir",
        type=Path,
        default=Path("out/tao-git-crawl"),
        help="directory for resolver JSON and per-subnet crawl outputs",
    )
    crawl.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".cache/git-crawl"),
        help="directory for bare git mirrors",
    )
    crawl.add_argument(
        "--state-db",
        type=Path,
        help="SQLite state database for git-crawl run metadata and incremental default-branch heads",
    )
    crawl.add_argument("--active-since", help="only crawl repos pushed at or after this ISO timestamp/date")
    crawl.add_argument("--since", help="only include commits authored at or after this ISO timestamp/date")
    crawl.add_argument("--until", help="only include commits authored at or before this ISO timestamp/date")
    crawl.add_argument("--max-repos", type=_positive_int, help="cap number of repos crawled per subnet")
    crawl.add_argument(
        "--include-archived",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="include archived repositories",
    )
    crawl.add_argument(
        "--include-forks",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="include fork repositories",
    )
    crawl.add_argument(
        "--prefer-ssh",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="clone discovered repos via SSH instead of HTTPS",
    )
    crawl.add_argument(
        "--token-env",
        default="GITHUB_TOKEN",
        help="environment variable containing a GitHub token (default: GITHUB_TOKEN)",
    )
    crawl.add_argument(
        "--env-file",
        type=Path,
        help=(
            "dotenv file to load before reading --token-env "
            "(default: .env in the tao-git-crawl repo root when run inside the repo; otherwise ./.env)"
        ),
    )
    crawl.add_argument(
        "--ref-scope",
        choices=["default-branch", "all-refs"],
        default="default-branch",
        help="git refs to inspect (default: default-branch)",
    )
    crawl.add_argument(
        "--workers",
        type=_positive_int,
        default=1,
        help="maximum repos to crawl concurrently per subnet",
    )
    crawl.add_argument("--fail-fast", action="store_true", help="stop after the first subnet/repo failure")
    crawl.add_argument(
        "--commit-changes-filtration-level",
        choices=["all", "non_binary", "source_like"],
        default="source_like",
        help=(
            "how to filter file changes written into aggregate outputs; "
            "'source_like' excludes generated/lockfile/spec/vendored files (default)"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "resolve":
        try:
            config = _resolver_config_from_args(args)
        except ResolverConfigError as exc:
            print(f"failed to load resolver config: {exc}", file=sys.stderr)
            return 1
        provider = _provider_from_args(args)
        try:
            records = list(provider.fetch(netuids=args.netuid))
        except Exception as exc:  # noqa: BLE001 - CLI boundary reports provider failures
            print(f"failed to fetch subnet identity records: {exc}", file=sys.stderr)
            return 1
        try:
            document = resolve_subnets(records, target_label=args.target, config=config)
        except Exception as exc:  # noqa: BLE001 - CLI boundary reports resolver failures
            print(f"failed to resolve subnet GitHub targets: {exc}", file=sys.stderr)
            return 1
        written = write_resolution_outputs(document, args.output_dir)
        print(
            f"Resolved {len(document.repository_targets)} repository targets, "
            f"{len(document.owner_targets)} owner targets, "
            f"{len(document.unresolved)} unresolved subnet records."
        )
        for path in written:
            print(path)
        return 0

    if args.command == "crawl":
        try:
            config = _resolver_config_from_args(args)
        except ResolverConfigError as exc:
            print(f"failed to load resolver config: {exc}", file=sys.stderr)
            return 1
        provider = _provider_from_args(args)
        try:
            records = list(provider.fetch(netuids=args.netuid))
        except Exception as exc:  # noqa: BLE001 - CLI boundary reports provider failures
            print(f"failed to fetch subnet identity records: {exc}", file=sys.stderr)
            return 1
        try:
            document = resolve_subnets(records, target_label=args.target, config=config)
        except Exception as exc:  # noqa: BLE001 - CLI boundary reports resolver failures
            print(f"failed to resolve subnet GitHub targets: {exc}", file=sys.stderr)
            return 1
        written = write_resolution_outputs(document, args.output_dir)
        _load_env_file(args.env_file)
        token = token_from_env(args.token_env)
        report = crawl_resolved_subnets(
            document,
            output_dir=args.output_dir,
            cache_dir=args.cache_dir,
            state_db=args.state_db,
            token=token,
            active_since=args.active_since,
            since=args.since,
            until=args.until,
            include_archived=args.include_archived if args.include_archived is not None else False,
            include_forks=args.include_forks if args.include_forks is not None else False,
            max_repos=args.max_repos,
            prefer_ssh=args.prefer_ssh if args.prefer_ssh is not None else False,
            ref_scope=args.ref_scope,
            workers=args.workers,
            fail_fast=args.fail_fast,
            commit_changes_filtration_level=args.commit_changes_filtration_level,
        )
        skipped_inaccessible = getattr(report, "skipped_inaccessible", [])
        print(
            f"Crawled {len(report.succeeded_netuids)} subnets, "
            f"{len(report.failed)} failed, "
            f"{len(report.skipped_unresolved_netuids)} unresolved skipped, "
            f"{len(skipped_inaccessible)} inaccessible skipped."
        )
        for path in written:
            print(path)
        report_path = getattr(report, "report_path", None)
        if report_path:
            print(report_path)
        return 0 if not report.failed else 1

    parser.error(f"Unknown command {args.command!r}")
    return 2


def _load_env_file(env_file: Path | None) -> None:
    dotenv_path = env_file if env_file is not None else _default_env_file()
    if dotenv_path is None:
        return
    load_dotenv(dotenv_path=dotenv_path, override=False)


def _default_env_file() -> Path | None:
    start = Path.cwd().resolve()
    repo_root = _find_tao_git_crawl_repo_root(start)
    if repo_root is not None:
        candidate = repo_root / ".env"
        return candidate if candidate.exists() else None

    candidate = start / ".env"
    return candidate if candidate.exists() else None


def _find_tao_git_crawl_repo_root(start: Path) -> Path | None:
    for directory in (start, *start.parents):
        pyproject = directory / "pyproject.toml"
        if not pyproject.exists():
            continue
        try:
            pyproject_text = pyproject.read_text(encoding="utf-8")
        except OSError:
            continue
        if 'name = "tao-git-crawl"' in pyproject_text or "name = 'tao-git-crawl'" in pyproject_text:
            return directory
    return None


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def _regular_subnet_netuid(value: str) -> int:
    parsed = int(value)
    if parsed < MIN_REGULAR_SUBNET_NETUID or parsed > MAX_REGULAR_SUBNET_NETUID:
        raise argparse.ArgumentTypeError(
            "use regular subnet netuids "
            f"{MIN_REGULAR_SUBNET_NETUID}-{MAX_REGULAR_SUBNET_NETUID}; netuid 0 is the root network"
        )
    return parsed


def _provider_from_args(args: argparse.Namespace):
    if args.from_json:
        return JsonSubnetIdentityProvider(args.from_json)
    endpoint = args.endpoint or DEFAULT_NETWORK_ENDPOINTS[args.network]
    return SubstrateSubnetIdentityProvider(endpoint=endpoint)


def _resolver_config_from_args(args: argparse.Namespace) -> ResolverConfig:
    try:
        registry = load_registry(
            registry_path=args.registry,
            registry_url=args.registry_url,
            use_built_in=True,
        )
    except RegistryError as exc:
        print(f"failed to load registry: {exc}", file=sys.stderr)
        raise ResolverConfigError(str(exc)) from exc
    config = resolver_config_from_registry(registry)
    if args.config:
        user_config = load_resolver_config(args.config)
        # User config overrides take precedence over registry
        merged_overrides = dict(config.subnet_overrides)
        merged_overrides.update(user_config.subnet_overrides)
        config = replace(
            config,
            default_repository_policy=user_config.default_repository_policy,
            subnet_overrides=merged_overrides,
        )
    if args.repository_policy:
        config = replace(config, default_repository_policy=args.repository_policy)
    return config


if __name__ == "__main__":
    raise SystemExit(main())
