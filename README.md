# tao-git-crawl

`tao-git-crawl` resolves GitHub targets from Bittensor subnet identity metadata and runs subnet-scoped `git-crawl` metrics.

It does not host data or run a service for you. You provide the chain endpoint or JSON export, GitHub token, storage paths, and schedule.

## What It Does

- Reads `SubtensorModule.SubnetIdentitiesV3(netuid)` from a live chain endpoint, or reads the same fields from JSON.
- Extracts GitHub repository URLs, owner roots, and bare `owner/repo` values from subnet identity text.
- Treats `github_repo` as the highest-confidence field and scans `subnet_url`, `description`, `additional`, and `subnet_contact` as fallback fields.
- Writes aggregate resolver outputs plus split outputs under `subnets/<netuid>/`.
- Crawls each resolved subnet as its own `git-crawl` target.
- Records missing or invalid GitHub metadata in `unresolved.json`.
- Uses a built-in registry entry for subnet 64, Chutes AI, so SN64 resolves to the `https://github.com/chutesai` owner.

## Install

Python 3.12+ is required.

```bash
python3.12 -m pip install -e .
```

Install the chain extra when querying a live Bittensor endpoint:

```bash
python3.12 -m pip install -e '.[chain]'
```

`tao-git-crawl crawl` reads `GITHUB_TOKEN` from the environment. When run inside this repo, it also loads a repo-root `.env` file automatically:

```bash
cp .env.example .env
# Edit .env and set GITHUB_TOKEN=<your GitHub token>
```

Use `--env-file path/to/.env` for another token file.

## Resolve Targets

Resolve from the sample JSON fixture:

```bash
tao-git-crawl resolve \
  --from-json examples/subnets.sample.json \
  --output-dir out/tao
```

Resolve from Finney:

```bash
tao-git-crawl resolve \
  --network finney \
  --output-dir out/tao
```

The default Finney endpoint is `wss://entrypoint-finney.opentensor.ai:443`. Use `--endpoint` for a self-hosted or archive node.

Resolver outputs:

- `subnet-targets.json`: all resolved targets and unresolved records.
- `repository-manifest.json`: exact repository targets for `git-crawl crawl-repos`.
- `owner-targets.json`: GitHub owners that need owner-level expansion.
- `unresolved.json`: subnets with no usable GitHub target.
- `subnets/<netuid>/...`: the same files scoped to one subnet.

## Crawl Subnets

Resolve and crawl every valid subnet independently:

```bash
tao-git-crawl crawl \
  --from-json examples/subnets.sample.json \
  --output-dir out/tao-crawl \
  --cache-dir .cache/git-crawl \
  --state-db .state/git-crawl.sqlite \
  --since 2026-01-01 \
  --workers 4
```

The `--state-db` path should stay stable across scheduled runs so `git-crawl` can persist run metadata and incremental default-branch heads.

Crawl SN64 from the full Chutes owner:

```bash
tao-git-crawl crawl \
  --from-json examples/subnets.sample.json \
  --netuid 64 \
  --output-dir out/tao-chutes \
  --cache-dir .cache/git-crawl \
  --state-db .state/git-crawl.sqlite \
  --since 2026-01-01 \
  --workers 4
```

Do not pass --max-repos if you want full owner coverage. Add --include-forks or --include-archived if you also want those repos.

SN64's `repository-manifest.json` is intentionally empty because Chutes is represented as an owner target, not an exact repository target.

To crawl an exact-repository subnet directly with `git-crawl`:

```bash
git-crawl crawl-repos out/tao/subnets/99/repository-manifest.json \
  --target bittensor-subnet-99 \
  --cache-dir .cache/git-crawl \
  --output-dir out/git-crawl/subnets/99 \
  --workers 4
```

## Overrides

Use overrides when on-chain metadata points at the wrong GitHub scope.

Python config:

```python
DEFAULT_REPOSITORY_POLICY = "repository"

SUBNET_OVERRIDES = {
    99: {
        "replace": True,
        "targets": [
            {"kind": "owner", "url": "https://github.com/RendixNetwork"},
        ],
    },
}
```

Then pass it to `resolve` or `crawl`:

```bash
tao-git-crawl crawl \
  --network finney \
  --config config.py \
  --output-dir out/tao-crawl \
  --cache-dir .cache/git-crawl \
  --state-db .state/git-crawl.sqlite \
  --since 2026-01-01
```

Override order is built-in registry, optional `--registry-url`, optional `--registry`, then `--config`. Later sources win.

Use `--repository-policy owner` when every exact repository link should be crawled at its GitHub owner scope:

```bash
tao-git-crawl crawl \
  --network finney \
  --repository-policy owner \
  --output-dir out/tao-owner-crawl \
  --cache-dir .cache/git-crawl \
  --state-db .state/git-crawl.sqlite \
  --since 2026-01-01
```

Owner crawling gives broader coverage, but can include unrelated repositories when a subnet points into a shared organization or user account.

## Docker

The repo includes a scheduler container. It runs once on start, then repeats every 24 hours by default.

Docker builds install `git-crawl` from `git+https://github.com/alex-drocks/git-crawl.git@v0.2.0` by default.

```bash
cp .env.example .env
# Edit .env and set GITHUB_TOKEN=ghp_...

docker compose up --build -d
docker compose logs -f scheduler
ls $(docker volume inspect -f '{{ .Mountpoint }}' tao-git-crawl_tao-data)
```

Compose creates one named volume, `tao-data`, mounted at `/data`:

- `/data/output`: resolver outputs and per-subnet crawl metrics.
- `/data/cache`: bare git mirrors.
- `/data/state`: SQLite state.
- `/data/logs`: per-run crawl logs.

Scheduler environment:

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `GITHUB_TOKEN` | required | GitHub personal access token |
| `TAO_CRAWL_INTERVAL_SECONDS` | `86400` | Seconds between crawl runs |
| `TAO_CRAWL_NETWORK` | `finney` | Bittensor network preset |
| `TAO_CRAWL_OUTPUT_DIR` | `/data/output` | Output directory |
| `TAO_CRAWL_CACHE_DIR` | `/data/cache` | Bare git mirror cache |
| `TAO_CRAWL_STATE_DB` | `/data/state/db.sqlite` | SQLite state DB |
| `TAO_CRAWL_WORKERS` | `4` | Concurrent repo workers per subnet |
| `TAO_CRAWL_SINCE` | `2025-01-01` | Commit since date |
| `TAO_CRAWL_COMMIT_CHANGES_FILTRATION_LEVEL` | `source_like` | `all`, `non_binary`, or `source_like` |
| `TAO_CRAWL_REGISTRY_URL` | unset | Remote JSON override registry |
| `TAO_CRAWL_REGISTRY` | unset | Local JSON override registry path in the container |
| `TAO_CRAWL_CONFIG` | unset | Python config path in the container |
| `TAO_CRAWL_LOG_DIR` | `/data/logs` | Per-run log directory |
| `TAO_CRAWL_RUN_ON_START` | `true` | Run immediately on container start |

For local registry or config files, mount the file into the container and set `TAO_CRAWL_REGISTRY` or `TAO_CRAWL_CONFIG` to that container path, for example `/data/registry.json`.

Run one crawl manually through Compose:

```bash
docker compose run --rm scheduler \
  python -m tao_git_crawl.cli crawl \
  --network finney \
  --output-dir /data/output \
  --cache-dir /data/cache \
  --state-db /data/state/db.sqlite \
  --since 2026-01-01
```

Build without Compose:

```bash
docker build -t tao-git-crawl:latest .
docker run -d \
  --name tao-scheduler \
  -e GITHUB_TOKEN=$GITHUB_TOKEN \
  -v tao-data:/data \
  tao-git-crawl:latest
```
