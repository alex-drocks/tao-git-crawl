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

[Unreleased]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/alex-drocks/tao-git-crawl/releases/tag/v0.1.0
