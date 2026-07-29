# Subnet Registry

`overrides.json` is the built-in subnet target override registry used by `tao-git-crawl`.

Use this file for stable, reviewed mappings that cannot be represented safely by on-chain identity metadata alone. Good
examples are:

- a subnet that legitimately spans multiple exact GitHub repositories;
- a subnet whose on-chain metadata points at an organization page but only some repos are subnet-relevant;
- a subnet that should intentionally use owner-level expansion because the account is dedicated to that subnet.

Prefer exact `repository` targets over broad `owner` targets. Owner targets expand all eligible public repositories under
that GitHub account and can inflate activity if the account contains unrelated work.

Subnet teams can propose registry updates by opening a PR that edits `overrides.json`.

Overrides use registry schema v3 and require both a reusable numeric netuid key and the subnet's current positive
`SubtensorModule.NetworkRegisteredAt(netuid)` block in `registered_at`. The resolver ignores an override when that block
does not match the live registration. A recycled slot therefore cannot inherit an old `replace: true` mapping, even if
the registry has not yet been updated. Update `registered_at` only after reviewing the replacement subnet and its target
scope; changing it opts the new lifecycle into the override.
