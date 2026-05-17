# tao-git-crawl

`tao-git-crawl` resolves GitHub links from Bittensor subnet identity metadata and runs subnet-scoped `git-crawl` metrics.

The package is intentionally zero-hosting: users run discovery and crawling with their own chain endpoint, GitHub token, storage, and schedule.

## Current scope

This package resolves subnet identity links from `SubtensorModule.SubnetIdentitiesV3`, produces subnet-scoped crawl inputs, and can run `git-crawl` once per subnet so each subnet is reported like a separate company.

- Exact repository links become high-confidence `repository` targets and are included in `repository-manifest.json` for `git-crawl crawl-repos`.
- GitHub owner roots become `owner` targets in `owner-targets.json`.
- SN64 (Chutes) is baked into the default resolver config — it resolves to the `chutesai` GitHub owner instead of one on-chain repo link.
- Manual config overrides can replace wrong or too-narrow on-chain links for any other subnet.
- `--repository-policy owner` promotes *every* exact repository link to its parent owner when you want old `git-crawler`-style owner/org crawling.
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

The sample fixture keeps the no-override path live-smokeable for subnets other than 64. SN64 is baked into the default config — no `--config` needed for Chutes.

For authenticated GitHub API rate limits, keep a local repo-root `.env` file. It is ignored by git and loaded automatically by `tao-git-crawl crawl` before reading `GITHUB_TOKEN`:

```bash
cp .env.example .env
# Edit .env and set GITHUB_TOKEN=<your GitHub token>
```

Use `--env-file path/to/.env` if you keep the token file somewhere else.

```bash
tao-git-crawl resolve --from-json examples/subnets.sample.json --output-dir out/tao

# Resolve + crawl each valid subnet as its own company-like target.
# (No --config needed; SN64 override is baked into the default.)
tao-git-crawl crawl \
  --from-json examples/subnets.sample.json \
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

On-chain metadata is not always the best company-level crawl target. For example, a subnet may point to one repo even though the meaningful engineering activity spans the full GitHub owner.

Subnet 64 (Chutes) is already baked into the default config, so no override is needed there. To override a different subnet, create a user-owned `config.py`:

```python
DEFAULT_REPOSITORY_POLICY = "repository"

# Add overrides for subnets other than 64.
SUBNET_OVERRIDES = {
    42: {
        "replace": True,
        "targets": [
            {"kind": "owner", "url": "https://github.com/example-org"},
        ],
    },
}
```

Then resolve with the override:

```bash
tao-git-crawl resolve \
  --from-json examples/subnets.sample.json \
  --output-dir out/tao
```

Or resolve and crawl each subnet immediately:

```bash
tao-git-crawl crawl \
  --from-json examples/subnets.sample.json \
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
