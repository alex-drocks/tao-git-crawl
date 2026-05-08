# tao-git-crawl

`tao-git-crawl` resolves GitHub links from Bittensor subnet identity metadata and runs subnet-scoped `git-crawl` metrics.

The package is intentionally zero-hosting: users run discovery and crawling with their own chain endpoint, GitHub token, storage, and schedule.

## Current scope

This package resolves subnet identity links from `SubtensorModule.SubnetIdentitiesV3`, produces subnet-scoped crawl inputs, and can run `git-crawl` once per subnet so each subnet is reported like a separate company.

- Exact repository links become high-confidence `repository` targets and are included in `repository-manifest.json` for `git-crawl crawl-repos`.
- GitHub owner roots become `owner` targets in `owner-targets.json`.
- Manual config overrides can replace wrong or too-narrow on-chain links, for example SN64 Chutes resolving to the `chutesai` owner instead of one repo.
- `--repository-policy owner` can promote exact repository links to owner targets when you intentionally want old `git-crawler`-style owner/org crawling.
- Missing or invalid metadata becomes structured unresolved output instead of fake zero metrics.
- Outputs are also split under `subnets/<netuid>/` so each subnet can be crawled and reported like a separate company.
- `tao-git-crawl crawl` resolves targets, writes the manifests, then writes per-subnet metrics under `subnets/<netuid>/crawl/`.

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
  'git-crawl @ git+https://github.com/alex-drocks/git-crawl.git@v0.1.0'
```

The sample fixture keeps the no-override path live-smokeable by using a public Chutes repository for SN64. Use the override example below when a subnet's exact repository metadata is private, inaccessible, or too narrow for company-level metrics.

```bash
tao-git-crawl resolve --from-json examples/subnets.sample.json --output-dir out/tao

# Resolve + crawl each valid subnet as its own company-like target.
tao-git-crawl crawl \
  --from-json examples/subnets.sample.json \
  --config examples/config.overrides.py \
  --output-dir out/tao-crawl \
  --cache-dir .cache/git-crawl \
  --state-db .state/git-crawl.sqlite \
  --since 2026-01-01 \
  --workers 4

# Aggregate exact repository targets across all resolved subnets.
git-crawl crawl-repos out/tao/repository-manifest.json \
  --cache-dir .cache/git-crawl \
  --output-dir out/git-crawl \
  --workers 4

# Or crawl one subnet as its own company-like target.
git-crawl crawl-repos out/tao/subnets/64/repository-manifest.json \
  --target bittensor-subnet-64 \
  --cache-dir .cache/git-crawl \
  --output-dir out/git-crawl/subnets/64 \
  --workers 4
```

The `--state-db` path should be stable across scheduled runs so `git-crawl` can persist run metadata and incremental default-branch heads.

## Manual target overrides

On-chain metadata is not always the best company-level crawl target. For example, SN64 may point to one Chutes repo even though the meaningful engineering activity spans the `chutesai` GitHub owner.

Create a user-owned `config.py`:

```python
DEFAULT_REPOSITORY_POLICY = "repository"

SUBNET_OVERRIDES = {
    64: {
        "replace": True,
        "targets": [
            {"kind": "owner", "url": "https://github.com/chutesai"},
        ],
    },
}
```

Then resolve with the override:

```bash
tao-git-crawl resolve \
  --from-json examples/subnets.sample.json \
  --config examples/config.overrides.py \
  --output-dir out/tao
```

Or resolve and crawl each subnet immediately:

```bash
tao-git-crawl crawl \
  --from-json examples/subnets.sample.json \
  --config examples/config.overrides.py \
  --output-dir out/tao-crawl \
  --cache-dir .cache/git-crawl \
  --state-db .state/git-crawl.sqlite \
  --since 2026-01-01
```

The effective crawl target for subnet 64 becomes the `chutesai` owner in both top-level `owner-targets.json` and `subnets/64/owner-targets.json`.

If you want old `git-crawler`-style owner crawling for every exact GitHub repo link, use:

```bash
tao-git-crawl resolve \
  --network finney \
  --repository-policy owner \
  --output-dir out/tao-owner-policy

# Or crawl each subnet with owner-promoted targets.
tao-git-crawl crawl \
  --network finney \
  --repository-policy owner \
  --output-dir out/tao-owner-crawl \
  --cache-dir .cache/git-crawl \
  --state-db .state/git-crawl.sqlite \
  --since 2026-01-01
```

Use this deliberately: owner crawling gives better company-level coverage for cases like Chutes, but can overcount when a subnet links to a repo inside a broad shared foundation or user account.

## Query a live chain endpoint

Install the optional chain extra first:

```bash
python3.12 -m pip install 'tao-git-crawl[chain]'
tao-git-crawl resolve --network finney --output-dir out/tao
```

The default Finney endpoint is `wss://entrypoint-finney.opentensor.ai:443`; pass `--endpoint` to use a self-hosted or archive node.
