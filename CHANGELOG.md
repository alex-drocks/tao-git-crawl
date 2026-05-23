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

[Unreleased]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/alex-drocks/tao-git-crawl/releases/tag/v0.1.0
