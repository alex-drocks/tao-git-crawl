# tao-git-crawl

`tao-git-crawl` resolves GitHub targets from Bittensor subnet identity metadata and runs subnet-scoped `git-crawl` metrics.

It is self-hosted. You provide the chain endpoint or JSON export, GitHub token, storage paths, and schedule.

## What It Does

- Reads `SubtensorModule.SubnetIdentitiesV3(netuid)` and the authoritative
  `SubtensorModule.NetworkRegisteredAt(netuid)` lifecycle block from a live chain endpoint, or reads equivalent fields
  from JSON.
- Restricts subnet resolution to regular subnet slots `1` through `128`, excluding netuid `0`, the Bittensor root
  network.
- Extracts GitHub repository URLs, owner roots, and bare `owner/repo` values from subnet identity text.
- Treats `github_repo` as the primary GitHub metadata field and scans `subnet_url`, `description`, `additional`, and `subnet_contact` as fallback fields.
- Writes aggregate resolver outputs plus split outputs under `subnets/<netuid>/`.
- Crawls each resolved subnet as its own `git-crawl` target.
- Rejects every repository and owner target under `opentensor` or `RaoFoundation`, plus repository redirects/transfers
  that no longer match the explicit subnet target, instead of crediting unrelated history.
- Treats each `(netuid, NetworkRegisteredAt)` pair as an immutable identity epoch. A recycled slot archives the old
  live output and starts with no inherited score, crawl rows, or incremental state.
- Scores each subnet from credited git activity and writes score details into the API summaries.
- Records missing or invalid GitHub metadata in `unresolved.json`.
- Uses a built-in registry entry for subnet 64, Chutes AI, so SN64 resolves to the `https://github.com/chutesai` owner.

## Run With Docker

Docker Compose is the main way to run `tao-git-crawl` as a scheduled crawler. The scheduler runs once on start, then
repeats every 24 hours by default. While idle it checks live subnet identity fields every 15 minutes and starts an early
reconciliation crawl when a netuid's identity or GitHub metadata changes.

Docker builds install `git-crawl` from `git+https://github.com/alex-drocks/git-crawl.git@v0.3.2` by default.

```bash
cp .env.example .env
# Edit .env and set GITHUB_TOKEN=ghp_...

docker compose build
docker compose up -d
docker compose logs -f scheduler
curl http://localhost:8080/health
docker compose exec scheduler ls /data
```

By default, Compose publishes the API on `127.0.0.1:8080`, so it is reachable from the same server but not directly from other machines. This keeps clone-and-run deployments useful for local dashboards, reverse proxies, notebooks, or backend services without accidentally exposing a public unauthenticated API.

On hosts with legacy Compose, use `docker-compose build` and `docker-compose up -d`.

Compose creates one named volume, `tao-data`, mounted at `/data`:

- `/data/output`: resolver outputs and per-subnet crawl metrics.
- `/data/output/subnet-history`: read-only audit archives for ended subnet identity epochs; these are outside the live
  `subnets/<netuid>` API path.
- `/data/cache`: bare git mirrors.
- `/data/state`: optional SQLite state for explicit incremental crawls.
- `/data/logs`: per-run crawl logs.

Docker prefixes named volumes with the Compose project name. If the project name is `tao-git-crawl`, the host volume
name is `tao-git-crawl_tao-data`; otherwise use `docker volume ls` or inspect paths from inside the container.

Docker Compose environment:

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `GITHUB_TOKEN` | required | GitHub personal access token |
| `TAO_CRAWL_INTERVAL_SECONDS` | `86400` | Seconds between crawl runs |
| `TAO_CRAWL_IDENTITY_CHECK_SECONDS` | `900` | Poll interval for live identity changes; `0` disables early reconciliation |
| `TAO_CRAWL_NETWORK` | `finney` | Bittensor network preset |
| `TAO_CRAWL_OUTPUT_DIR` | `/data/output` | Fixed Compose container path for crawl output |
| `TAO_CRAWL_CACHE_DIR` | `/data/cache` | Fixed Compose container path for the bare git mirror cache |
| `TAO_CRAWL_INCREMENTAL` | `false` | Set `true` to use git-crawl incremental state instead of full-window outputs |
| `TAO_CRAWL_STATE_DB` | `/data/state/db.sqlite` | SQLite state DB used only when `TAO_CRAWL_INCREMENTAL=true` |
| `TAO_CRAWL_WORKERS` | `4` | Concurrent repo workers per subnet |
| `TAO_CRAWL_WINDOW_DAYS` | `365` | Rolling score/activity window in days when `TAO_CRAWL_SINCE` is unset |
| `TAO_CRAWL_SINCE` | unset | Advanced fixed commit since date override |
| `TAO_CRAWL_COMMIT_CHANGES_FILTRATION_LEVEL` | `source_like` | `all`, `non_binary`, or `source_like` |
| `TAO_CRAWL_REGISTRY_URL` | unset | Remote JSON override registry |
| `TAO_CRAWL_REGISTRY` | unset | Local JSON override registry path in the container |
| `TAO_CRAWL_CONFIG` | unset | Python config path in the container |
| `TAO_CRAWL_LOG_DIR` | `/data/logs` | Fixed Compose container path for per-run logs |
| `TAO_CRAWL_RUN_ON_START` | `true` | Run immediately on container start |
| `TAO_API_OUTPUT_DIR` | `/data/output` | Fixed Compose container path served by the read-only API |
| `TAO_API_HOST` | `0.0.0.0` | Fixed container bind host required for Docker port forwarding |
| `TAO_API_BIND_HOST` | `127.0.0.1` | Host interface where Docker publishes the API |
| `TAO_API_PORT` | `8080` | Host port for the API; container port stays `8080` |
| `TAO_API_CORS_ORIGIN` | `*` | CORS origin for frontend requests |
| `TAO_API_RATE_LIMIT_REQUESTS` | `1200` | Requests allowed per TCP peer in the API rate-limit window; set `0` to disable |
| `TAO_API_RATE_LIMIT_WINDOW_SECONDS` | `60` | API rate-limit window in seconds; set `0` to disable |

For local registry or config files, mount the file into the container and set `TAO_CRAWL_REGISTRY` or `TAO_CRAWL_CONFIG` to that container path, for example `/data/registry.json`.

Compose intentionally fixes its output, cache, log, and API input paths under the shared `/data` volume. Configure the
host-facing API with `TAO_API_BIND_HOST` and `TAO_API_PORT`; do not change `TAO_API_HOST=0.0.0.0` inside the container,
because Docker must be able to reach the API process before publishing it on the host's loopback interface.

Docker scheduler runs use a trailing 365-day score/activity window by default: when `TAO_CRAWL_SINCE` is unset, each
scheduled crawl computes `--since` from the current UTC date minus `TAO_CRAWL_WINDOW_DAYS`. Bare git mirrors still
persist under `/data/cache`, so repeat runs reuse local clones and fetch current refs before recomputing the rolling
window. This default keeps investor-facing rankings focused on sustained recent shipping, not ancient history or only
the repositories that changed since the previous scheduler run.

The identity poll limits recycled-netuid drift: it reads every active slot and its `NetworkRegisteredAt` block in bulk.
If a registration block, subnet name, or GitHub discovery field changes between daily runs, the scheduler starts a
crawl early. If an identity changes while a crawl is running, it performs one immediate reconciliation crawl.

`NetworkRegisteredAt` is the hard history boundary. Before crawling a changed registration, the crawler moves the
entire prior `subnets/<netuid>` directory to `subnet-history/<netuid>/`, deletes reproducible live aggregate files, and
writes a new `identity-epoch.json` marker. On first deployment of this policy, legacy live directories without an epoch
marker are also archived before being rebuilt. A full crawl similarly archives output for deregistered slots. The audit
trail is written to `identity-history.json`; archived rows are never read by live scoring or subnet API endpoints.
Incremental git-crawl target labels contain the epoch ID, so SQLite heads from two registrations cannot merge. Set
`TAO_CRAWL_IDENTITY_CHECK_SECONDS=0` only when another operator process already guarantees prompt reconciliation.

While directories are being reconciled, `identity-reconciliation.json` acts as a fail-closed API sentinel: aggregate
score and health requests return `503`, and per-subnet scores and crawl rows are hidden. The sentinel is removed only after a
successful reconciliation. If archival fails, it remains with `status: failed` so stale output cannot become live again
without operator recovery or a successful subsequent crawl.

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
- `GET /api/subnets/<netuid>/identity-epoch`
- `GET /api/identity-history`
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
subnet as unresolved, failed, inaccessible, attribution-rejected, or not yet crawled, subnet detail payloads expose
`current_crawl` plus the current score/target metadata, but crawl-derived summary, activity, and JSONL datasets are not
served from stale files.
Those dataset endpoints return a JSON `404` instead of leaking activity from an older crawl.

### Subnet Activity

Use `/api/subnets/<netuid>/activity` for frontend display of code-change git activity. The same `activity` object is also embedded in `/api/subnets`, `/api/subnets/<netuid>`, and `/api/subnets/<netuid>/summary`.

The activity payload exposes:

- `totals`: commits, file changes, lines added/deleted, active days, repo days, contributor days, and distinct contributors for credited code/docs changes only.
- `averages.per_active_day`: commits, file changes, and line churn divided by active days.
- `averages.per_calendar_day`, `per_calendar_week`, and `per_calendar_month`: the same metrics divided by the crawl calendar span.
- `skipped`: file-change and line totals skipped because they were binary, lockfile, generated, vendored,
  spec/schema-like, or artifact/data changes. When reason details are available, `by_reason` breaks those totals down.

The normal API presents one canonical activity model: totals and averages are real code/docs changes only.
`/api/subnets/<netuid>/summary` uses those same totals and exposes skipped noisy changes under `skipped`; raw crawl
summary fields such as unfiltered churn totals remain implementation artifacts on disk. When `file_changes.jsonl` is
available, the API recomputes activity from row-level changes so local artifact/data guardrails are applied consistently;
otherwise it falls back to `git-crawl` v0.3.2 `activity.json` or filtered summary totals. These are git change metrics,
not current source lines of code.

When detailed rows are available, `/api/subnets/<netuid>/file-changes` returns code-change rows only and `/api/subnets/<netuid>/commits` returns only commits with credited code changes. Commit, file-change, repo-day, contributor-day, and org-day row payloads use the same public names as aggregate totals: `file_changes`, `lines_added`, and `lines_deleted`.

### Subnet Scores

Each crawl writes `subnet-scores.json` plus `subnets/<netuid>/score.json`. The API also embeds the same score object in `/api/subnets`, `/api/subnets/<netuid>`, and `/api/subnets/<netuid>/summary`.
Score outputs use schema version `tao-git-crawl-score-v3`.

Scores first use raw global-max normalization for metrics covering the selected crawl window and for 30-day momentum
sub-metrics. Scheduled Docker crawls use a 365-day window by default, while manual `--since` and `--until` values can
select a different period. For a full Finney crawl, the comparison population is the full regular subnet population.
For `--netuid`, partial JSON exports, or otherwise filtered runs, `score`, `rank`, `rank_total`, and `percentile` are
local to that subset and are not comparable to a full-network ranking. The weighted metric composite is then rescaled
so the top subnet score is `100.00`; the pre-rescale value is retained as `composite_score` for inspection. Each score
also includes `score_momentum`, a 0-100 frontend-friendly 30-day momentum score, plus `rank` and `rank_total` fields for
frontend display, where rank `1` is the top subnet and equal scores share the same rank. Unresolved GitHub metadata,
missing crawl output, failed crawls, attribution-rejected targets, and subnets with no crawlable repositories score `0`.
`raw_metrics` contains source counts and 30-day momentum sub-metric counts; the derived 30-day display score is exposed
only as top-level `score_momentum`.

The weighted score is:

| Metric | Weight |
| ------ | ------ |
| Crawl-window active days | `35%` |
| Crawl-window credited file changes | `30%` |
| 30d Momentum | `15%` |
| Crawl-window average credited commits per active day | `5%` |
| Crawl-window credited lines added | `10%` |
| Crawl-window distinct contributors | `5%` |

The 30d momentum component is a nested score over credited activity authored in the final 30 days of the crawl window,
using a half-open `[score_until - 30 days, score_until)` day range when the crawl has an explicit `history_until`.
Default scheduler crawls omit `history_until`, so the scorer uses tomorrow's UTC date as the exclusive bound and includes
commits authored today.

| Momentum metric | Momentum weight |
| --------------- | --------------- |
| 30d Credited file changes | `40%` |
| 30d Active days | `30%` |
| 30d Average credited commits per active day | `15%` |
| 30d Credited lines added | `15%` |

Credited activity uses `git-crawl` path classification plus local artifact/data guardrails. When `file_changes.jsonl` is
available, the scorer excludes rows marked binary, lockfile, generated, vendored, spec/schema-like, or artifact/data
before counting file changes, lines, active days, contributors, commits-per-active-day, and momentum. If detailed rows
are unavailable, it falls back to `git-crawl` `activity.json` or already-filtered source-like aggregate totals and does
not fall back to raw churn totals. Aggregate fallbacks cannot reconstruct 30-day momentum unless the aggregate crawl
window itself is 30 days or shorter. Repository breadth is reported only for repositories with credited activity in the
scoring window. The default `source_like` crawl filter reduces upstream noise before outputs are written;
`tao-git-crawl` then rechecks detailed rows for investor-facing scoring and API activity.

Regular subnets cannot receive credit for any repository or owner target under `opentensor` or `RaoFoundation`; the
owner-wide deny rule applies regardless of repository name. Exact targets must also resolve through GitHub to the same canonical `owner/repo`, and
owner expansion must return repositories under that same owner. A rename or transfer is rejected with status
`attribution_rejected` until on-chain metadata or a reviewed override names the canonical target explicitly. Rejected
targets are recorded under `skipped_attribution` in `crawl-report.json`, and stale crawl datasets for that netuid are
not served by the API.

`repos_crawled` remains in `raw_metrics` for context, but it is not a weighted score input. Repo count reflects project
layout too much to be a reliable investor-facing activity signal.

Score payloads include `scoring_window.score_since`, `scoring_window.score_until`, and `scoring_window.scoring_window_days` so consumers can show the exact rolling window behind a rank.

Percentile rank is still computed across every subnet after final scores are calculated for consumers that need it.

### API Exposure

The recommended default is same-server access:

```bash
curl http://127.0.0.1:8080/api/subnets
```

For a same-host consumer service, keep the Docker host binding on loopback and configure the consumer with the published
API URL, such as `http://127.0.0.1:8080`. The stable aggregate integration endpoints are `/api/scores` and
`/api/subnets`; the consumer does not need the crawler's `GITHUB_TOKEN`. If you set another `TAO_API_PORT`, use that
host port in the consumer URL.

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
  --env-file .env \
  -v tao-data:/data \
  tao-git-crawl:latest
```

That starts the scheduler only. To serve the read-only API without Compose, run a second container against the same
volume:

```bash
docker run -d \
  --name tao-api \
  -p 127.0.0.1:8080:8080 \
  -v tao-data:/data:ro \
  --entrypoint python \
  tao-git-crawl:latest \
  -m tao_git_crawl.api
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
tao-git-crawl-api --host 127.0.0.1 --output-dir out/tao-crawl --port 8080
```

The explicit loopback host keeps this unauthenticated development server off other network interfaces.

## Development and Testing

Install the development tools in an editable environment:

```bash
python3.12 -m pip install -e '.[dev]'
```

Add the `chain` extra as well when development or testing needs a live Bittensor endpoint:

```bash
python3.12 -m pip install -e '.[dev,chain]'
```

Run the regular verification checks with:

```bash
python -m pytest tests -q
python -m ruff check tao_git_crawl tests
python -m compileall -q tao_git_crawl
python -m build
```

The Docker API end-to-end test is opt-in because it builds and starts a real container service:

```bash
TAO_GIT_CRAWL_DOCKER_E2E=1 python -m pytest tests/test_docker_e2e.py -q
```

The test builds the Docker image by default. Set `TAO_GIT_CRAWL_DOCKER_IMAGE=<image>` to test an existing image instead.

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

For authoritative lifecycle separation and registration-bound overrides, each JSON row should include the positive
top-level `registered_at` block from `NetworkRegisteredAt`. If it is absent, the crawler uses a conservative identity
fingerprint epoch and ignores every registration-bound override for that row. JSON inputs are not assumed to be a full
active-network snapshot, so omitted netuids are not archived as deregistered.

The default Finney endpoint is `wss://entrypoint-finney.opentensor.ai:443`. Use `--endpoint` for a self-hosted or archive node.
Live and JSON resolution only consider regular subnet slots, netuids `1` through `128`. Netuid `0` is the root network,
not a regular subnet.

Resolver outputs:

- `subnet-targets.json`: all resolved targets and unresolved records.
- `repository-manifest.json`: exact repository targets for `git-crawl crawl-repos`.
- `owner-targets.json`: GitHub owners that need owner-level expansion.
- `unresolved.json`: subnets with no usable GitHub target.
- `subnets/<netuid>/...`: the same files scoped to one subnet.

Crawler output additionally contains `subnets/<netuid>/identity-epoch.json`, with the current registration block and
epoch ID, and `identity-history.json`, the audit index for any quarantined prior epochs.

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
  "schema_version": "tao-git-crawl-registry-v3",
  "overrides": {
    "4": {
      "registered_at": 1411451,
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
        "registered_at": 1234567,
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

Every registry or Python-config override must include the current positive `NetworkRegisteredAt` block. The resolver
ignores an override when its block does not equal the live subnet's block and records it under `stale_overrides` in
`subnet-targets.json`. This deliberately makes every netuid-keyed override expire on recycle. Registry v2 files are
rejected rather than silently applying unbound overrides.

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
