from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .providers import (
    DEFAULT_ENDPOINT,
    DEFAULT_NETWORK,
    DEFAULT_NETWORK_ENDPOINTS,
    JsonSubnetIdentityProvider,
    SubstrateSubnetIdentityProvider,
)
from .resolver import resolve_subnets, write_resolution_outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tao-git-crawl",
        description="Resolve Bittensor subnet GitHub identity metadata into git-crawl manifests.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve = subparsers.add_parser("resolve", help="resolve subnet GitHub links from JSON or live chain state")
    resolve.add_argument("--from-json", type=Path, help="read subnet identity records from a JSON fixture/export")
    resolve.add_argument(
        "--network",
        choices=sorted(DEFAULT_NETWORK_ENDPOINTS),
        default=DEFAULT_NETWORK,
        help="Bittensor network endpoint preset for live chain queries (default: finney)",
    )
    resolve.add_argument("--endpoint", help=f"override live chain WebSocket endpoint (default: {DEFAULT_ENDPOINT})")
    resolve.add_argument("--netuid", type=int, action="append", help="limit resolution to one netuid; repeatable")
    resolve.add_argument("--target", default="bittensor-subnets", help="target label for git-crawl manifest output")
    resolve.add_argument(
        "--output-dir",
        type=Path,
        default=Path("out/tao-git-crawl"),
        help="directory for JSON outputs",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "resolve":
        provider = _provider_from_args(args)
        try:
            records = list(provider.fetch(netuids=args.netuid))
        except Exception as exc:  # noqa: BLE001 - CLI boundary reports provider failures
            print(f"failed to fetch subnet identity records: {exc}", file=sys.stderr)
            return 1
        document = resolve_subnets(records, target_label=args.target)
        written = write_resolution_outputs(document, args.output_dir)
        print(
            f"Resolved {len(document.repository_targets)} repository targets, "
            f"{len(document.owner_targets)} owner targets, "
            f"{len(document.unresolved)} unresolved subnet records."
        )
        for path in written:
            print(path)
        return 0

    parser.error(f"Unknown command {args.command!r}")
    return 2


def _provider_from_args(args: argparse.Namespace):
    if args.from_json:
        return JsonSubnetIdentityProvider(args.from_json)
    endpoint = args.endpoint or DEFAULT_NETWORK_ENDPOINTS[args.network]
    return SubstrateSubnetIdentityProvider(endpoint=endpoint)


if __name__ == "__main__":
    raise SystemExit(main())
