# tao-git-crawl

`tao-git-crawl` resolves GitHub links from Bittensor subnet identity metadata and emits `git-crawl`-compatible manifests.

The package is intentionally zero-hosting: users run discovery and crawling with their own chain endpoint, GitHub token, storage, and schedule.

## Current scope

This scaffold focuses on resolving subnet identity links from `SubtensorModule.SubnetIdentitiesV3`.

- Exact repository links become high-confidence `repository` targets and are included in `repository-manifest.json` for `git-crawl crawl-repos`.
- GitHub owner roots become lower-confidence `owner` targets in `owner-targets.json`; they are not silently expanded into repositories.
- Missing or invalid metadata becomes structured unresolved output instead of fake zero metrics.

## On-chain source of truth

The canonical subnet identity storage in `opentensor/subtensor` is:

```text
SubtensorModule.SubnetIdentitiesV3(netuid) -> Option<SubnetIdentityV3>
```

`SubnetIdentityV3` includes `github_repo`, `subnet_url`, `description`, `additional`, and related text fields. `tao-git-crawl` treats `github_repo` as the highest-confidence source and scans other text fields as fallback evidence.

## Quick start from an exported JSON fixture

Until `git-crawl` is published to PyPI, install the pinned GitHub dependency first:

```bash
python3.12 -m pip install \
  'git-crawl @ git+https://github.com/alex-drocks/git-crawl.git@e010ecfb71e3b9af778d87caf90cd9629b9fbeda'
```

```bash
tao-git-crawl resolve --from-json examples/subnets.sample.json --output-dir out/tao

git-crawl crawl-repos out/tao/repository-manifest.json \
  --cache-dir .cache/git-crawl \
  --output-dir out/git-crawl \
  --workers 4
```

## Query a live chain endpoint

Install the optional chain extra first:

```bash
python3.12 -m pip install 'tao-git-crawl[chain]'
tao-git-crawl resolve --network finney --output-dir out/tao
```

The default Finney endpoint is `wss://entrypoint-finney.opentensor.ai:443`; pass `--endpoint` to use a self-hosted or archive node.
