# Changelog

All notable changes to `tao-git-crawl` will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Use this section for changes that have merged but have not been released yet.
Move entries into a dated version section when cutting the next tag.

### Fixed

- Serve `/api/subnets` from a per-subnet cache that rebuilds a subnet only after its output files or crawl status
  change, and warm it in the background every minute. The endpoint had grown past 15 seconds, the TaoFlows fetch
  timeout. Uncached builds are also about half as slow: path-only noise checks are memoized and use one suffix test.

## [2.4.0] - 2026-10-09

### Added

- Crawl SN28 SayGM across the taostat `gm-miner`, `gm-validator`, `gm-mcp`, and `saygm-cookbook` repositories
  instead of only its on-chain `gm-miner` repository. Exact repository targets keep taostat's unrelated repositories
  out of the subnet's score.
- Crawl SN51 Lium across its own `Datura-ai` repositories: `lium-io`, the `lium` CLI, `computenet-docker-images`,
  `lium-skill`, `shadeform-sdk`, `celium-collateral-contracts`, `lium-localmaxxing`, and `sn51-auditor`. Exact
  repository targets keep forks and former Desearch (SN22) work under `Datura-ai` out of the subnet's score.

## [2.3.0] - 2026-10-07

### Added

- Crawl SN66 Conjectures at the `conjectures-io` owner level, like SN64 Chutes, so its miner, task, and contribution
  repositories are credited alongside the on-chain validator repository.
- Registry overrides accept reviewed credit `exclusions` for content that is not the subnet team's own work. Each names
  an exact repository plus a path, a commit, or both, with the evidence as `reason`. The resolver writes them to
  `subnet-targets.json` as `credit_exclusions`, scoring skips the covered rows, and the API reports them under
  `skipped.by_reason["registry exclusion"]`. Optional `except_paths` preserves reviewed local files in mixed imports.
- Exclude verified third-party and miner content from credit: vendored OpenClaw in SN23's initial commit, Polyhedra
  Expander/ECC in SN2's workspace import, Exercism problems in SN62's two dataset imports, vendored BoltzGen and Boltz
  commits in SN68, terminal-bench tasks in SN100's `live-task-cache`, synced miner champions in SN91, and the
  third-party `impeccable` agent skill in SN118. Evidence includes upstream file snapshot matches and the miner archive
  workflow; matches establish provenance for those snapshots, not every unmatched file in a mixed import.

### Fixed

- Stop crediting committed run output and data as code: `.log`, `.stdout`, `.stderr`, checksum files, trailing
  `.bak`/`.orig`/`.rej` backups, sequence data, `.dat`, and `.mtl` files; text and JSON/YAML data in `corpus`,
  `evidence`, and capture directories; and captured exit codes, pids, and timestamps inside `evidence` and capture
  directories. Source code and supported prose formats in those directories remain eligible. These filename heuristics
  can also exclude authored `.txt` work logs and cannot detect output saved under preserved extensions.
- Preserve SN68's local Boltz/BoltzGen adapters within vendoring and move commits. Scope SN100's task-cache imports and
  SN118's skill imports to their import commits so subsequent maintenance remains eligible.
- Credit hand-written `coverage.py`-style source files that the coverage report guardrail previously skipped.

## [2.2.0] - 2026-09-26

### Changed

- Pin Docker, Compose, and CI installs of `git-crawl` to its v0.3.3 release commit instead of the movable `v0.3.2`
  tag. v0.3.3 stops caching GitHub pull request refs, tolerates non-UTF-8 bytes in repository history, retries
  GitHub and git network calls for about 30 seconds, and writes crawl outputs atomically. Existing `/data/cache`
  mirrors are upgraded in place, and default-branch crawl results are unchanged.
- Document installing `git-crawl` from GitHub before installing this package, since `git-crawl` is not on PyPI.
- `tao-git-crawl crawl` exits `3` when a completed run published scores but some subnets failed, keeping `1` for fatal
  snapshot, reconciliation, or config errors, `--fail-fast` aborts, and runs where every crawled subnet failed.

### Fixed

- Write `crawl-report.json`, score files, resolver outputs, and identity epoch files atomically so the API never
  reads a partially written file while a crawl is running.
- With `TAO_CRAWL_INCREMENTAL=true`, advance incremental repository state only after a subnet's crawl outputs are
  written, so a failed output write no longer drops those commits from the next incremental delta.
- Credit only `github_repo` targets when that field resolves, scanning `subnet_url`, `description`, `additional`, and
  `subnet_contact` only as documented fallbacks. Links to dependencies, other projects, or contact profiles no longer add
  repositories or owner-wide expansions to a subnet's score.
- Keep the Docker scheduler's fail-closed sentinel for fatal guarded crawls only. A crawl with per-subnet failures no
  longer hides every subnet's score and activity or fails `/health` until the next scheduled run.
- Correct stale built-in registry targets: SN5 now credits `hone-subnet-org/hone-subnet` instead of the deleted
  `manifold-inc/hone`; SN100 credits `CortexLM/cortex`, where `BaseIntelligence/base` was moved; SN50 credits
  `synthdataco/synth-subnet`, the transferred repository its on-chain `github_repo` still names by its old URL.

## [2.1.0] - 2026-09-02

### Fixed

- Include credited `top_repositories` and `top_paths` in the summaries embedded in `/api/subnets` and
  `/api/subnets/<netuid>`, matching `/api/subnets/<netuid>/summary`.

## [2.0.0] - 2026-07-29

### Added

- Poll live subnet identity fields every 15 minutes while the Docker scheduler is idle and trigger an early crawl when
  a recycled netuid changes identity or GitHub metadata; retry up to two times when identity changes during a crawl.
- Use the on-chain `NetworkRegisteredAt` block as an immutable subnet identity epoch, archive ended or legacy-unbound
  live histories outside the API path, expose the current epoch and history audit, scope incremental state by epoch,
  and fail closed at the API while reconciliation is in progress or failed.

### Changed

- Keep registry and Python-config overrides as simple, manually maintained target mappings without lifecycle fields.
- Advance resolver output to `tao-git-crawl-resolution-v3`, including per-netuid identity epochs.

### Fixed

- Reject every target owned by `opentensor` or `RaoFoundation` from regular-subnet scoring while preserving credit from
  a separately accepted target when the current crawl confirms that it succeeded.
- Require each credited file-change row to join a valid, in-window commit; deduplicate repeated commit paths and reject
  orphan, malformed-date, out-of-window, or negative-addition rows from score and API totals.
- Fail closed when any crawl snapshot lacks registration epochs or a guarded crawl exits unsuccessfully, propagate live
  subnet-discovery failures instead of treating the network as empty, and suppress scores if on-chain attribution does
  not stabilize after repeated crawl reconciliation.
- Pin active-netuid, identity, and registration-map reads to one chain head so a rollover cannot create a mixed
  attribution snapshot from multiple blocks.
- Reject exact repository redirects/transfers and owner-expansion rows whose canonical GitHub identity differs from the
  explicit subnet target, report them as `attribution_rejected`, and hide any stale crawl datasets for those netuids.

## [1.0.1] - 2026-07-11

### Changed

- Require `git-crawl` 0.3.2 and pin Docker and CI installs to its `v0.3.2` release.

### Fixed

- Reject malformed GitHub owner URLs and percent-encoded unsupported repository routes instead of accepting truncated
  targets or aborting subnet resolution.
- Reject boolean and fractional JSON netuids instead of silently coercing them to the wrong subnet number.

## [1.0.0] - 2026-05-29

### Added

- Expose each subnet's 30-day momentum as top-level `score_momentum` in score outputs for frontend table columns.

### Changed

- Reweight subnet scoring to keep 365-day active days as a 35% sustained-activity anchor, increase credited file changes
  to 30%, add a 15% nested 30-day momentum component, and reduce commits-per-active-day and distinct contributors to
  5% supporting signals.
- Compute 30-day momentum over a half-open `[score_until - 30 days, score_until)` day range to avoid double-counting the
  upper boundary date, while including the current UTC day when a crawl has no explicit `history_until`.
- Keep aggregate-only score fallbacks at zero 30-day momentum for crawl windows wider than 30 days, since aggregate
  outputs cannot reconstruct recent activity from row-level commit dates.

## [0.7.1] - 2026-05-26

### Added

- Add a curated SN23 TrishoolAI repository override set.
- Preserve identity-derived fallback targets in resolver outputs when `replace: true` overrides mask on-chain metadata.
- Report successful fallback usage in `crawl-report.json`.

### Fixed

- Retry preserved on-chain identity targets when every primary `replace: true` override target is inaccessible with a
  GitHub HTTP 404, avoiding deadlocked subnet discovery without broadening normal curated crawls.

## [0.7.0] - 2026-05-25

### Added

- Add an opt-in Docker API end-to-end test that starts the real container service and exercises mounted crawl outputs
  over HTTP.

### Changed

- Remove CSV crawl output support; `tao-git-crawl` now writes the JSON and JSONL files required by its scorer and API
  as the single official output contract.

## [0.6.1] - 2026-05-25

### Fixed

- Keep API file-change, commit, day-rollup, and top-activity churn totals consistent with aggregate activity by using
  raw `git-crawl` `additions`/`deletions` fields before public `lines_added`/`lines_deleted` aliases.

## [0.6.0] - 2026-05-24

### Changed

- Prepare package metadata for the v0.6.0 release.
- Move the built-in subnet override registry into tracked `registry/overrides.json` so subnet teams can propose repo-scope
  updates by PR.
- Add curated SN4 Targon and SN5 Hone Manifold repository override sets to avoid shared-org owner expansion.
- Remove target `confidence` metadata from registry/config parsing and resolved target outputs, and bump the registry
  schema to `tao-git-crawl-registry-v2`.
- Remove the obsolete user-facing `examples/` folder; the sample subnet JSON is now an internal test fixture.

## [0.5.0] - 2026-05-24

### Changed

- Prepare package metadata for the v0.5.0 release.
- Restrict live and JSON subnet identity inputs to regular subnet slots `1` through `128`, excluding netuid `0`, the
  Bittensor root network.

## [0.4.0] - 2026-05-23

### Changed

- Prepare package metadata for the v0.4.0 release.
- Make Docker scheduler crawls use a trailing 365-day score/activity window by default, with `TAO_CRAWL_SINCE`
  remaining as an advanced fixed-date override.
- Add explicit `TAO_CRAWL_INCREMENTAL=true` opt-in for operators who want git-crawl state DB incremental outputs.
- Expose score window metadata (`score_since`, `score_until`, and `scoring_window_days`) in score outputs.
- Prefer detailed file-change rows over aggregate `activity.json` when computing public activity and scores, so local
  artifact/data guardrails are applied consistently.
- Remove repository count from weighted scoring and reallocate that weight toward sustained activity and contributor
  signals.

### Fixed

- Keep investor-facing subnet rankings from being dominated by the most recent scheduled crawl day when a persistent
  state DB is present.
- Ignore stale per-subnet crawl summaries in scores and public API activity when the latest crawl report marks a subnet
  unresolved, failed, inaccessible, or not yet crawled.
- Count detailed score repository breadth from repositories with credited code changes, instead of all crawled
  repositories.
- Exclude obvious non-code artifacts and data files such as PDFs, 3D assets, coverage reports, datasets, and model/data
  formats from credited activity metrics.

## [0.3.0] - 2026-05-23

### Changed

- Make public activity and summary API payloads expose one canonical code-change model: `totals` now means
  filtered real code changes, and skipped noisy changes are reported under `skipped`.
- Remove raw/filter implementation fields such as `activity_scope`, `calculation_source`, `churn_filter`,
  `source_like_totals`, `generated_like_totals`, and `path_classes` from normal public API summary/activity payloads.
- Filter `/api/subnets/<netuid>/file-changes` to code-change rows and `/api/subnets/<netuid>/commits` to commits
  with credited code changes when detailed file-change rows are available.
- Standardize public row payload naming on `file_changes`, `lines_added`, and `lines_deleted`, and document
  `/contributor-days` as the canonical contributor-day endpoint.
- Recompute repo-day, contributor-day, org-day, top-repository, and top-path API payloads from credited code-change
  rows when detailed rows are available.
- Remove static skipped-class policy metadata from activity payloads; skipped breakdowns now appear only as observed
  `by_reason` data.
- Require `git-crawl` 0.3.0 and use its canonical `activity.json` output as the aggregate source of truth when
  available.

### Fixed

- Avoid importing crawler-only `git-crawl` dependencies when loading API-only modules.
- Keep `/health` from parsing subnet crawl payloads so malformed output cannot break service health checks.
- Avoid falling back to raw summary top-repository/top-path rankings when credited file-change rows are unavailable.
- Count detailed scoring rows consistently when commit hashes are exposed as `commit_sha`, and avoid inflating commit
  counts from duplicate detailed commit rows.

## [0.2.0] - 2026-05-22

### Added

- Add a frontend-facing `activity` payload and `/api/subnets/<netuid>/activity` endpoint with code-change totals,
  per-active-day averages, per-calendar day/week/month averages, repository counts, and explicit churn filter metadata.

### Changed

- Make subnet detail and summary responses expose the same `activity` payload so consumers no longer need to infer
  filtered activity metrics from raw git-crawl summary fields.
- Derive activity commit, active-day, repo-day, and contributor counts from filtered JSONL rows when they are available.
- Keep public activity and score metrics from falling back to raw churn totals when filtered source-like data is missing.
- Only credit crawled repositories in scores when they have credited code activity in the scoring window.

## [0.1.1] - 2026-05-22

### Added

- Add `rank` and `rank_total` fields to subnet score payloads so frontend consumers can display a simple
  top-to-bottom subnet rank alongside the numeric score.

### Fixed

- Publish crawl reports and subnet score outputs incrementally during long scheduler runs so the API can serve
  `/api/crawl-report`, `/api/scores`, and per-subnet score files before the full crawl finishes.

## [0.1.0] - 2026-05-22

### Added

- Resolve Bittensor subnet identity metadata into GitHub repository and owner targets.
- Support live chain reads, JSON fixture reads, manual overrides, local registries, and remote registries.
- Crawl each resolved subnet as a separate `git-crawl` target with per-subnet outputs.
- Score subnets from credited git activity and expose score details in generated output.
- Provide a read-only HTTP API for crawl outputs, scores, pagination, health checks, CORS, and rate limiting.
- Provide Docker and Docker Compose deployment with persistent output, cache, state, and log paths.
- Include CI coverage for resolver behavior, crawling orchestration, scoring, API endpoints, Docker metadata, and package builds.

### Fixed

- Keep local runtime state directories out of git and Docker build contexts.

[Unreleased]: https://github.com/alex-drocks/tao-git-crawl/compare/v2.4.0...HEAD
[2.4.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v2.3.0...v2.4.0
[2.3.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v2.2.0...v2.3.0
[2.2.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v1.0.1...v2.0.0
[1.0.1]: https://github.com/alex-drocks/tao-git-crawl/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.7.1...v1.0.0
[0.7.1]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.6.1...v0.7.0
[0.6.1]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/alex-drocks/tao-git-crawl/releases/tag/v0.1.0
