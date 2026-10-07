# Subnet Registry

`overrides.json` is the built-in subnet target override registry used by `tao-git-crawl`.

Use this file for stable, reviewed mappings that cannot be represented safely by on-chain identity metadata alone. Good
examples are:

- a subnet that legitimately spans multiple exact GitHub repositories;
- a subnet whose on-chain metadata points at an organization page but only some repos are subnet-relevant;
- a subnet that should intentionally use owner-level expansion because the account is dedicated to that subnet.

Prefer exact `repository` targets over broad `owner` targets. Owner targets expand all eligible public repositories under
that GitHub account and can inflate activity if the account contains unrelated work.

Subnet teams propose registry updates by opening a PR that edits only `overrides.json`. No lifecycle block, generated
provenance, or helper command is required.

The registry is intentionally maintained by review. When a netuid is recycled, review that entry and update or remove
targets left by the previous occupant. The live crawl identity-epoch system still quarantines old crawl output, but it
does not automatically rewrite or disable registry mappings.

## Credit Exclusions

An override can also list `exclusions`: reviewed content in a crawled repository that is not the subnet team's own work,
such as a vendored third-party project, copied upstream documentation, or archived miner submissions. Excluded rows are
skipped by scoring and API activity and reported under `skipped.by_reason["registry exclusion"]`.

```json
"23": {
  "replace": true,
  "targets": [{"kind": "repository", "url": "https://github.com/TrishoolAI/trishool-phase2"}],
  "exclusions": [
    {
      "repo": "TrishoolAI/trishool-phase2",
      "commit": "fdd3eb5f4e04d3a764c23c37326cdcc2231b9e05",
      "path": "tri-claw/",
      "reason": "Initial commit vendors openclaw/openclaw; 99% of tri-claw files are byte-identical to upstream history"
    }
  ]
}
```

- `repo` is the exact `owner/name` repository. `reason` is required and should state the evidence.
- `path` excludes a file, or a directory when it ends with `/`, in every commit. `commit` excludes one commit by SHA.
  With both, only that path in that commit is excluded, so the team's later edits to imported code stay credited.
  Prefer `commit` plus `path` for imports the team keeps developing; use `path` alone for content that is never the
  team's work, such as a directory a bot syncs from miners.
- Use full 40-character commit SHAs for built-in entries.
- An entry that only adds exclusions must set `"replace": false` and `"targets": []` so the subnet keeps its on-chain
  targets.

Only add an exclusion with direct evidence, for example most files being byte-identical to an upstream repository's
history. Large commits, initial releases of the team's own private code, and monorepo migrations are real work and stay
credited.
