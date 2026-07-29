# Changelog

All notable changes to `tao-git-crawl` will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Use this section for changes that have merged but have not been released yet.
Move entries into a dated version section when cutting the next tag.

### Added

- Poll live subnet identity fields every 15 minutes while the Docker scheduler is idle and trigger an early crawl when
  a recycled netuid changes identity or GitHub metadata; repeat once when identity changes during a crawl.
- Use the on-chain `NetworkRegisteredAt` block as an immutable subnet identity epoch, archive ended or legacy-unbound
  live histories outside the API path, expose the current epoch and history audit, scope incremental state by epoch,
  and fail closed at the API while reconciliation is in progress or failed.

### Fixed

- Reject every target owned by `opentensor` or `RaoFoundation` from regular-subnet scoring.
- Require each credited file-change row to join a valid, in-window commit; deduplicate repeated commit paths and reject
  orphan, malformed-date, out-of-window, or negative-addition rows from score and API totals.
- Fail closed when any crawl snapshot lacks registration epochs, propagate live subnet-discovery failures instead of
  treating the network as empty, and suppress scores if on-chain attribution does not stabilize after repeated crawl
  reconciliation.
- Reject exact repository redirects/transfers and owner-expansion rows whose canonical GitHub identity differs from the
  explicit subnet target, report them as `attribution_rejected`, and hide any stale crawl datasets for those netuids.
- Require registry/config overrides to bind to the current `NetworkRegisteredAt` block, bump the registry schema to v3,
  and ignore mismatched overrides so recycled subnets cannot inherit curated targets from a previous occupant.

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

[Unreleased]: https://github.com/alex-drocks/tao-git-crawl/compare/v1.0.1...HEAD
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
