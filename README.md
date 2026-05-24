# tao-git-crawl

`tao-git-crawl` resolves GitHub targets from Bittensor subnet identity metadata and runs subnet-scoped `git-crawl` metrics.

It is self-hosted. You provide the chain endpoint or JSON export, GitHub token, storage paths, and schedule.

## What It Does

- Reads `SubtensorModule.SubnetIdentitiesV3(netuid)` from a live chain endpoint, or reads the same fields from JSON.
- Restricts subnet resolution to regular subnet slots `1` through `128`, excluding netuid `0`, the Bittensor root
  network.
- Extracts GitHub repository URLs, owner roots, and bare `owner/repo` values from subnet identity text.
- Treats `github_repo` as the primary GitHub metadata field and scans `subnet_url`, `description`, `additional`, and `subnet_contact` as fallback fields.
- Writes aggregate resolver outputs plus split outputs under `subnets/<netuid>/`.
- Crawls each resolved subnet as its own `git-crawl` target.
- Scores each subnet from credited git activity and writes score details into the API summaries.
- Records missing or invalid GitHub metadata in `unresolved.json`.
- Uses a built-in registry entry for subnet 64, Chutes AI, so SN64 resolves to the `https://github.com/chutesai` owner.

## Run With Docker

Docker Compose is the main way to run `tao-git-crawl` as a scheduled crawler. The scheduler runs once on start, then repeats every 24 hours by default.

Docker builds install `git-crawl` from `git+https://github.com/alex-drocks/git-crawl.git@v0.3.0` by default.

```bash
cp .env.example .env
# Edit .env and set GITHUB_TOKEN=ghp_...

docker compose build
docker compose up -d
docker compose logs -f scheduler
curl http://localhost:8080/health
ls $(docker volume inspect -f '{{ .Mountpoint }}' tao-git-crawl_tao-data)
```

By default, Compose publishes the API on `127.0.0.1:8080`, so it is reachable from the same server but not directly from other machines. This keeps clone-and-run deployments useful for local dashboards, reverse proxies, notebooks, or backend services without accidentally exposing a public unauthenticated API.

On hosts with legacy Compose, use `docker-compose build` and `docker-compose up -d`.

Compose creates one named volume, `tao-data`, mounted at `/data`:

- `/data/output`: resolver outputs and per-subnet crawl metrics.
- `/data/cache`: bare git mirrors.
- `/data/state`: optional SQLite state for explicit incremental crawls.
- `/data/logs`: per-run crawl logs.

Docker Compose environment:

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `GITHUB_TOKEN` | required | GitHub personal access token |
| `TAO_CRAWL_INTERVAL_SECONDS` | `86400` | Seconds between crawl runs |
| `TAO_CRAWL_NETWORK` | `finney` | Bittensor network preset |
| `TAO_CRAWL_OUTPUT_DIR` | `/data/output` | Output directory |
| `TAO_CRAWL_CACHE_DIR` | `/data/cache` | Bare git mirror cache |
| `TAO_CRAWL_INCREMENTAL` | `false` | Set `true` to use git-crawl incremental state instead of full-window outputs |
| `TAO_CRAWL_STATE_DB` | `/data/state/db.sqlite` | SQLite state DB used only when `TAO_CRAWL_INCREMENTAL=true` |
| `TAO_CRAWL_WORKERS` | `4` | Concurrent repo workers per subnet |
| `TAO_CRAWL_WINDOW_DAYS` | `365` | Rolling score/activity window in days when `TAO_CRAWL_SINCE` is unset |
| `TAO_CRAWL_SINCE` | unset | Advanced fixed commit since date override |
| `TAO_CRAWL_COMMIT_CHANGES_FILTRATION_LEVEL` | `source_like` | `all`, `non_binary`, or `source_like` |
| `TAO_CRAWL_REGISTRY_URL` | unset | Remote JSON override registry |
| `TAO_CRAWL_REGISTRY` | unset | Local JSON override registry path in the container |
| `TAO_CRAWL_CONFIG` | unset | Python config path in the container |
| `TAO_CRAWL_LOG_DIR` | `/data/logs` | Per-run log directory |
| `TAO_CRAWL_RUN_ON_START` | `true` | Run immediately on container start |
| `TAO_API_OUTPUT_DIR` | `/data/output` | Output directory served by the read-only API |
| `TAO_API_HOST` | `0.0.0.0` | API bind host inside the container |
| `TAO_API_BIND_HOST` | `127.0.0.1` | Host interface where Docker publishes the API |
| `TAO_API_PORT` | `8080` | Host port for the API; container port stays `8080` |
| `TAO_API_CORS_ORIGIN` | `*` | CORS origin for frontend requests |
| `TAO_API_RATE_LIMIT_REQUESTS` | `1200` | Requests allowed per TCP peer in the API rate-limit window; set `0` to disable |
| `TAO_API_RATE_LIMIT_WINDOW_SECONDS` | `60` | API rate-limit window in seconds; set `0` to disable |

For local registry or config files, mount the file into the container and set `TAO_CRAWL_REGISTRY` or `TAO_CRAWL_CONFIG` to that container path, for example `/data/registry.json`.

Docker scheduler runs use a trailing 365-day score/activity window by default: when `TAO_CRAWL_SINCE` is unset, each
scheduled crawl computes `--since` from the current UTC date minus `TAO_CRAWL_WINDOW_DAYS`. Bare git mirrors still
persist under `/data/cache`, so repeat runs reuse local clones and fetch current refs before recomputing the rolling
window. This default keeps investor-facing rankings focused on sustained recent shipping, not ancient history or only
the repositories that changed since the previous scheduler run.

Set `TAO_CRAWL_INCREMENTAL=true` only for operator diagnostics where latest-delta output is intentional. Incremental
mode uses `TAO_CRAWL_STATE_DB` to crawl only changes since the previously stored default-branch head, so API activity
and scores from that output are not comparable to rolling-window rankings.

The API service mounts the same `tao-data` volume read-only and exposes frontend-friendly JSON endpoints:

- `GET /health`
- `GET /api/subnets`
- `GET /api/subnets/<netuid>`
- `GET /api/subnets/<netuid>/summary`
- `GET /api/subnets/<netuid>/activity`
- `GET /api/subnets/<netuid>/score`
- `GET /api/subnets/<netuid>/repositories?limit=100&offset=0`
- `GET /api/subnets/<netuid>/commits?limit=100&offset=0`
- `GET /api/subnets/<netuid>/contributor-days?limit=100&offset=0`
- `GET /api/subnets/<netuid>/repo-days?limit=100&offset=0`
- `GET /api/subnets/<netuid>/org-days?limit=100&offset=0`
- `GET /api/subnets/<netuid>/file-changes?limit=100&offset=0`
- `GET /api/crawl-report`
- `GET /api/scores`

Diagnostic crawl-file endpoints such as `/failures`, `/excluded`, and `/crawl-runs` remain available per subnet, but they are not part of the normal frontend activity contract.

When `crawl-report.json` is present, the API treats it as the current-run source of truth. If the latest run marks a
subnet as unresolved, failed, inaccessible, or not yet crawled, subnet detail payloads expose `current_crawl` plus the
current score/target metadata, but crawl-derived summary, activity, and JSONL datasets are not served from stale files.
Those dataset endpoints return a JSON `404` instead of leaking activity from an older crawl.

### Subnet Activity

Use `/api/subnets/<netuid>/activity` for frontend display of code-change git activity. The same `activity` object is also embedded in `/api/subnets`, `/api/subnets/<netuid>`, and `/api/subnets/<netuid>/summary`.

The activity payload exposes:

- `totals`: commits, file changes, lines added/deleted, active days, repo days, contributor days, and distinct contributors for real code changes only.
- `averages.per_active_day`: commits, file changes, and line churn divided by active days.
- `averages.per_calendar_day`, `per_calendar_week`, and `per_calendar_month`: the same metrics divided by the crawl calendar span.
- `skipped`: file-change and line totals skipped because they were binary, lockfile, generated, vendored,
  spec/schema-like, or artifact/data changes. When reason details are available, `by_reason` breaks those totals down.

The normal API presents one canonical activity model: totals and averages are real code/docs changes only.
`/api/subnets/<netuid>/summary` uses those same totals and exposes skipped noisy changes under `skipped`; raw crawl
summary fields such as unfiltered churn totals remain implementation artifacts on disk. When `file_changes.jsonl` is
available, the API recomputes activity from row-level changes so local artifact/data guardrails are applied consistently;
otherwise it falls back to `git-crawl` v0.3.0 `activity.json` or filtered summary totals. These are git change metrics,
not current source lines of code.

When detailed rows are available, `/api/subnets/<netuid>/file-changes` returns code-change rows only and `/api/subnets/<netuid>/commits` returns only commits with credited code changes. Commit, file-change, repo-day, contributor-day, and org-day row payloads use the same public names as aggregate totals: `file_changes`, `lines_added`, and `lines_deleted`.

### Subnet Scores

Each crawl writes `subnet-scores.json` plus `subnets/<netuid>/score.json`. The API also embeds the same score object in `/api/subnets`, `/api/subnets/<netuid>`, and `/api/subnets/<netuid>/summary`.

Scores first use raw global-max normalization per metric across the full subnet population. The weighted metric composite is then rescaled so the top subnet score is `100.00`; the pre-rescale value is retained as `composite_score` for inspection. Each score also includes `rank` and `rank_total` fields for frontend display, where rank `1` is the top subnet and equal scores share the same rank. Unresolved GitHub metadata, missing crawl output, failed crawls, and subnets with no crawlable repositories score `0`.

The weighted score is:

| Metric | Weight |
| ------ | ------ |
| Active days | `40%` |
| Credited file changes | `20%` |
| Average credited commits per active day | `15%` |
| Distinct contributors | `15%` |
| Credited lines added | `10%` |

Credited activity uses `git-crawl` path classification plus local artifact/data guardrails. When `file_changes.jsonl` is
available, the scorer excludes rows marked binary, lockfile, generated, vendored, spec/schema-like, or artifact/data
before counting file changes, lines, active days, contributors, and commits-per-active-day. If detailed rows are
unavailable, it falls back to `git-crawl` `activity.json` or already-filtered source-like aggregate totals and does not
fall back to raw churn totals. Repository breadth is reported only for repositories with credited activity in the
scoring window. The default `source_like` crawl filter reduces upstream noise before outputs are written;
`tao-git-crawl` then rechecks detailed rows for investor-facing scoring and API activity.

`repos_crawled` remains in `raw_metrics` for context, but it is not a weighted score input. Repo count reflects project
layout too much to be a reliable investor-facing activity signal.

Score payloads include `scoring_window.score_since`, `scoring_window.score_until`, and `scoring_window.scoring_window_days` so consumers can show the exact rolling window behind a rank.

Percentile rank is still computed across every subnet after final scores are calculated for consumers that need it.

### API Exposure

The recommended default is same-server access:

```bash
curl http://127.0.0.1:8080/api/subnets
```

To serve a public read-only API, keep Docker bound to `127.0.0.1` and put a reverse proxy such as Caddy, nginx, Traefik, or Cloudflare Tunnel in front of it. The API includes a generous in-memory guardrail of `1200` requests per `60` seconds per TCP peer and returns `429` with `Retry-After` when exceeded. This is enough to stop accidental or blunt direct abuse, but the proxy should still handle TLS, compression, caching, stricter public request limits, and any authentication or allowlists you want. Because Docker sees a reverse proxy as one peer, high-traffic public deployments should enforce request limits at the proxy and raise or disable the backend limit if needed. For browser frontends on another origin, set `TAO_API_CORS_ORIGIN` to that website origin, or leave the default `*` only when you intentionally want an open public API.

Example Caddy site:

```caddyfile
api.example.com {
  encode zstd gzip
  reverse_proxy 127.0.0.1:8080
}
```

If you intentionally want Docker itself to listen on every host interface, opt in explicitly:

```bash
TAO_API_BIND_HOST=0.0.0.0 docker compose up -d api
```

The API is read-only and does not expose `GITHUB_TOKEN`, but it has no built-in authentication. Avoid direct public exposure unless the surrounding network or proxy is meant to absorb public traffic.

Run one crawl manually through Compose:

```bash
docker compose run --rm --entrypoint python scheduler \
  -m tao_git_crawl.cli crawl \
  --network finney \
  --output-dir /data/output \
  --cache-dir /data/cache \
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

## Local CLI

Use the local Python CLI for one-off runs outside Docker.

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

Serve existing output locally:

```bash
tao-git-crawl-api --output-dir out/tao-crawl --port 8080
```

## Resolve Targets

Resolve from Finney:

```bash
tao-git-crawl resolve \
  --network finney \
  --output-dir out/tao
```

Resolve from an exported subnet identity JSON payload:

```bash
tao-git-crawl resolve \
  --from-json path/to/subnets.json \
  --output-dir out/tao
```

The default Finney endpoint is `wss://entrypoint-finney.opentensor.ai:443`. Use `--endpoint` for a self-hosted or archive node.
Live and JSON resolution only consider regular subnet slots, netuids `1` through `128`. Netuid `0` is the root network,
not a regular subnet.

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
  --network finney \
  --output-dir out/tao-crawl \
  --cache-dir .cache/git-crawl \
  --since 2026-01-01 \
  --workers 4
```

For investor-facing score output, omit `--state-db` so each crawl output covers the complete selected `--since` window.
Use `--state-db` only when you intentionally want incremental default-branch output from the previous stored heads.

Crawl SN64 from the full Chutes owner:

```bash
tao-git-crawl crawl \
  --network finney \
  --netuid 64 \
  --output-dir out/tao-chutes \
  --cache-dir .cache/git-crawl \
  --since 2026-01-01 \
  --workers 4
```

Do not pass --max-repos if you want full owner coverage. Add --include-forks or --include-archived if you also want those repos.

When `--max-repos` is set, the cap applies to crawlable repositories after private, archived, fork, and `--active-since` exclusions. Discovery may inspect extra GitHub candidates so excluded repositories do not consume the limit.

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

The built-in registry is tracked at `registry/overrides.json` so subnet teams can open PRs to update their own target
scope. Prefer exact `repository` targets unless the whole GitHub account is intentionally dedicated to one subnet.

Registry JSON:

```json
{
  "schema_version": "tao-git-crawl-registry-v1",
  "overrides": {
    "4": {
      "replace": true,
      "targets": [
        {"kind": "repository", "url": "https://github.com/manifold-inc/targon"},
        {"kind": "repository", "url": "https://github.com/manifold-inc/targon-sdk"},
        {"kind": "repository", "url": "https://github.com/manifold-inc/targon-nvidia-attest"}
      ],
      "note": "Targon curated repo set; do not expand all manifold-inc repos"
    }
  }
}
```

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
  --since 2026-01-01
```

Owner crawling gives broader coverage, but can include unrelated repositories when a subnet points into a shared organization or user account.
