# Changelog

All notable changes to `tao-git-crawl` will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Use this section for changes that have merged but have not been released yet.
Move entries into a dated version section when cutting the next tag.

### Added

### Changed

### Fixed

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

[Unreleased]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.7.0...HEAD
[0.7.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.6.1...v0.7.0
[0.6.1]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/alex-drocks/tao-git-crawl/releases/tag/v0.1.0
