# Subnet Registry

`default.json` is the built-in subnet target override registry used by `tao-git-crawl`.

Use this file for stable, reviewed mappings that cannot be represented safely by on-chain identity metadata alone. Good
examples are:

- a subnet that legitimately spans multiple exact GitHub repositories;
- a subnet whose on-chain metadata points at an organization page but only some repos are subnet-relevant;
- a subnet that should intentionally use owner-level expansion because the account is dedicated to that subnet.

Prefer exact `repository` targets over broad `owner` targets. Owner targets expand all eligible public repositories under
that GitHub account and can inflate activity if the account contains unrelated work.

Subnet teams can propose registry updates by opening a PR that edits `default.json`.
