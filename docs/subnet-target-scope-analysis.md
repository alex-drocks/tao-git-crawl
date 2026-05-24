# Subnet Target Scope Analysis

Generated from live Finney subnet identities on 2026-05-24, after excluding root netuid `0`. GitHub owner repository
counts were checked against the public GitHub API on the same date.

## Summary

- Regular subnet slots analyzed: `128` (`1` through `128`)
- Resolved target records: `107`
- Exact repository targets: `104`
- Owner-expansion targets: `3`
- Unresolved subnet records: `21`
- GitHub owners shared by more than one subnet: `9`

The main attribution rule is simple: a subnet should receive activity only from repositories explicitly assigned to that
subnet. Sharing a GitHub organization is not enough to share every repository in that organization.

## Representation Policy

Use these target scopes in order of preference:

1. **Exact repository target**: use when on-chain identity names a concrete `owner/repo`. This is the safest default and
   prevents org-wide activity from leaking between subnets.
2. **Curated repository set**: use when a subnet legitimately spans multiple repos under the same owner. Represent it as
   multiple explicit repository targets, usually through the registry or user config. Do not promote the whole owner.
3. **Owner-expansion target**: use only when the GitHub account is effectively dedicated to that subnet, or when a
   manually reviewed registry entry intentionally treats the account as the subnet boundary.
4. **Unresolved / needs review**: use when the only available signal is an org root but the org has unrelated repos or
   multiple subnets. This is preferable to inflated scores.

If the same exact repository is assigned to two active subnets, git history alone cannot split attribution. That should
be treated as a shared-source warning unless there is a path-level or repo-level boundary that can be encoded.

## SN4 / SN5 Manifold

Current live identity resolution is already attribution-safe:

| Netuid | Subnet | Current target | Scope |
| ---: | --- | --- | --- |
| 4 | Targon | `https://github.com/manifold-inc/targon` | exact repo |
| 5 | Hone | `https://github.com/manifold-inc/hone` | exact repo |

The Manifold org has `17` public repos. Recent non-target repos include `hone-api`, `hone-dashboard`, `targon-sdk`,
`openclaw`, `targon-nvidia-attest`, `manifold-sdk`, `taoxyz-wallet`, `periscope`, and `targon-oracle`.

Therefore SN4 and SN5 must not be represented as `https://github.com/manifold-inc` owner targets. That would inflate
both subnets with each other's repos plus unrelated Manifold repos. If SN4 needs `targon-sdk` or `targon-oracle`, add
those as explicit SN4 repository targets. If SN5 needs `hone-api` or `hone-dashboard`, add those as explicit SN5
repository targets. The correct model is a curated per-subnet repo set, not organization expansion.

Example registry shape:

```json
{
  "schema_version": "tao-git-crawl-registry-v1",
  "overrides": {
    "4": {
      "replace": true,
      "targets": [
        {"kind": "repository", "url": "https://github.com/manifold-inc/targon"},
        {"kind": "repository", "url": "https://github.com/manifold-inc/targon-sdk"}
      ],
      "note": "Targon curated repo set; do not expand all manifold-inc repos"
    },
    "5": {
      "replace": true,
      "targets": [
        {"kind": "repository", "url": "https://github.com/manifold-inc/hone"},
        {"kind": "repository", "url": "https://github.com/manifold-inc/hone-api"}
      ],
      "note": "Hone curated repo set; do not expand all manifold-inc repos"
    }
  }
}
```

## Shared GitHub Owners

These owners have targets for more than one subnet. All current targets in this table are exact repository targets, so
they do not create cross-subnet inflation as long as they remain exact repos.

| Owner | Public repos | Current subnet targets | Scope risk |
| --- | ---: | --- | --- |
| `macrocosm-os` | 32 | SN1 `apex`, SN9 `iota`, SN13 `data-universe`, SN25 `mainframe` | safe exact repos; curated additions may be needed for satellite repos |
| `RendixNetwork` | 5 | SN36 `eirel-ai`, SN70 `nexisgen`, SN99 `leoma` | safe exact repos; do not promote owner |
| `backend-developers-ltd` | 30 | SN12 `ComputeHorde`, SN89 `InfiniteHash` | safe exact repos; org has many unrelated/support repos |
| `datura-ai` | 30 | SN22 `desearch`, SN51 `lium-io` | safe exact repos; org has many related and unrelated repos |
| `deprecated` | 8 | SN39 `deprecated`, SN81 `deprecated` | duplicate exact repo; metrics would duplicate if crawled |
| `entrius` | 7 | SN7 `allways`, SN74 `gittensor` | safe exact repos; do not promote owner |
| `manifold-inc` | 17 | SN4 `targon`, SN5 `hone` | safe exact repos; use curated sets for extra repos |
| `qbittensor-labs` | 2 | SN48 `quantum-compute`, SN63 `enigma` | safe exact repos; all public repos are targeted |
| `unarbos` | 18 | SN66 `tau`, SN97 `distil` | safe exact repos; org/user has many unrelated repos |

## Owner-Expansion Targets

Owner targets are where inflation risk is highest because the crawler expands public repositories under the account.

| Netuid | Subnet | Owner target | Public repos | Current read |
| ---: | --- | --- | ---: | --- |
| 64 | Chutes | `https://github.com/chutesai` | 41 | intended built-in override for multi-repo activity; still broad |
| 105 | Beam | `https://github.com/Beam-Network` | 2 | probably acceptable, but should be exact if only one repo is subnet-relevant |
| 118 | Ditto | `https://github.com/ditto-assistant` | 15 | needs review; account includes archived and possibly unrelated assistant repos |

The default registry already uses owner expansion for SN64 intentionally. For SN105 and SN118, the live identity points
to GitHub organization repository pages, so the resolver treats them as owner targets. These are the best candidates for
curated registry overrides if inflated activity is a concern.

## Per-Subnet Target-Scope Inventory

| Netuid | Scope | Target-scope note |
| ---: | --- | --- |
| 1 | exact repo | shared owner `macrocosm-os`; exact repo prevents org inflation |
| 2 | exact repo | low target-scope risk |
| 3 | exact repo | placeholder-looking `username/repo`; needs validation |
| 4 | exact repo | shared owner `manifold-inc`; exact repo prevents org inflation |
| 5 | exact repo | shared owner `manifold-inc`; exact repo prevents org inflation |
| 6 | exact repo | low target-scope risk |
| 7 | exact repo | shared owner `entrius`; exact repo prevents org inflation |
| 8 | exact repo | low target-scope risk |
| 9 | exact repo | shared owner `macrocosm-os`; exact repo prevents org inflation |
| 10 | exact repo | low target-scope risk |
| 11 | exact repo | low target-scope risk |
| 12 | exact repo | shared owner `backend-developers-ltd`; exact repo prevents org inflation |
| 13 | exact repo | shared owner `macrocosm-os`; exact repo prevents org inflation |
| 14 | exact repo | low target-scope risk |
| 15 | exact repo | low target-scope risk |
| 16 | exact repo | low target-scope risk |
| 17 | exact repo | low target-scope risk |
| 18 | exact repo | low target-scope risk |
| 19 | exact repo | low target-scope risk |
| 20 | exact repo | low target-scope risk |
| 21 | unresolved | no GitHub link |
| 22 | exact repo | shared owner `datura-ai`; exact repo prevents org inflation |
| 23 | exact repo | low target-scope risk |
| 24 | exact repo | low target-scope risk |
| 25 | exact repo | shared owner `macrocosm-os`; exact repo prevents org inflation |
| 26 | exact repo | low target-scope risk |
| 27 | exact repo | low target-scope risk |
| 28 | unresolved | no GitHub link |
| 29 | exact repo | low target-scope risk |
| 30 | unresolved | no GitHub link |
| 31 | unresolved | no GitHub link |
| 32 | exact repo | low target-scope risk |
| 33 | exact repo | low target-scope risk |
| 34 | exact repo | low target-scope risk |
| 35 | exact repo | low target-scope risk |
| 36 | exact repo | shared owner `RendixNetwork`; exact repo prevents org inflation |
| 37 | exact repo | low target-scope risk |
| 38 | exact repo | low target-scope risk |
| 39 | exact repo | duplicate `deprecated/deprecated`; metrics would duplicate with SN81 |
| 40 | exact repo | low target-scope risk |
| 41 | exact repo | low target-scope risk |
| 42 | unresolved | no GitHub link |
| 43 | exact repo | low target-scope risk |
| 44 | exact repo | low target-scope risk |
| 45 | exact repo | low target-scope risk |
| 46 | exact repo | low target-scope risk |
| 47 | exact repo | low target-scope risk |
| 48 | exact repo | shared owner `qbittensor-labs`; exact repo prevents org inflation |
| 49 | exact repo | low target-scope risk |
| 50 | exact repo | low target-scope risk |
| 51 | exact repo | shared owner `datura-ai`; exact repo prevents org inflation |
| 52 | exact repo | low target-scope risk |
| 53 | exact repo | low target-scope risk |
| 54 | exact repo | low target-scope risk |
| 55 | exact repo | low target-scope risk |
| 56 | exact repo | low target-scope risk |
| 57 | unresolved | no GitHub link |
| 58 | unresolved | no GitHub link |
| 59 | exact repo | low target-scope risk |
| 60 | exact repo | low target-scope risk |
| 61 | exact repo | low target-scope risk |
| 62 | exact repo | low target-scope risk |
| 63 | exact repo | shared owner `qbittensor-labs`; exact repo prevents org inflation |
| 64 | owner expansion | broad account target; intentional built-in override but still broad |
| 65 | exact repo | low target-scope risk |
| 66 | exact repo | shared owner `unarbos`; exact repo prevents org inflation |
| 67 | exact repo | low target-scope risk |
| 68 | exact repo | low target-scope risk |
| 69 | unresolved | no GitHub link |
| 70 | exact repo | shared owner `RendixNetwork`; exact repo prevents org inflation |
| 71 | exact repo | low target-scope risk |
| 72 | exact repo | low target-scope risk |
| 73 | unresolved | no GitHub link |
| 74 | exact repo | shared owner `entrius`; exact repo prevents org inflation |
| 75 | exact repo | low target-scope risk |
| 76 | unresolved | no GitHub link |
| 77 | exact repo | low target-scope risk |
| 78 | exact repo | low target-scope risk |
| 79 | exact repo | low target-scope risk |
| 80 | exact repo | low target-scope risk |
| 81 | exact repo | duplicate `deprecated/deprecated`; metrics would duplicate with SN39 |
| 82 | exact repo | low target-scope risk |
| 83 | exact repo | low target-scope risk |
| 84 | unresolved | no GitHub link |
| 85 | exact repo | low target-scope risk |
| 86 | unresolved | no GitHub link |
| 87 | unresolved | no GitHub link |
| 88 | exact repo | low target-scope risk |
| 89 | exact repo | shared owner `backend-developers-ltd`; exact repo prevents org inflation |
| 90 | unresolved | no GitHub link |
| 91 | unresolved | no GitHub link |
| 92 | exact repo | low target-scope risk |
| 93 | exact repo | low target-scope risk |
| 94 | exact repo | low target-scope risk |
| 95 | unresolved | no GitHub link |
| 96 | exact repo | low target-scope risk |
| 97 | exact repo | shared owner `unarbos`; exact repo prevents org inflation |
| 98 | exact repo | low target-scope risk |
| 99 | exact repo | shared owner `RendixNetwork`; exact repo prevents org inflation |
| 100 | exact repo | low target-scope risk |
| 101 | unresolved | no GitHub link |
| 102 | exact repo | low target-scope risk |
| 103 | exact repo | low target-scope risk |
| 104 | unresolved | no GitHub link |
| 105 | owner expansion | broad account target; review for curated exact repo set |
| 106 | exact repo | low target-scope risk |
| 107 | exact repo | low target-scope risk |
| 108 | exact repo | low target-scope risk |
| 109 | exact repo | low target-scope risk |
| 110 | unresolved | no GitHub link |
| 111 | exact repo | low target-scope risk |
| 112 | exact repo | low target-scope risk |
| 113 | exact repo | low target-scope risk |
| 114 | exact repo | low target-scope risk |
| 115 | exact repo | low target-scope risk |
| 116 | exact repo | low target-scope risk |
| 117 | exact repo | low target-scope risk |
| 118 | owner expansion | broad account target; review for curated exact repo set |
| 119 | exact repo | low target-scope risk |
| 120 | exact repo | low target-scope risk |
| 121 | exact repo | low target-scope risk |
| 122 | unresolved | no GitHub link |
| 123 | exact repo | low target-scope risk |
| 124 | exact repo | low target-scope risk |
| 125 | unresolved | no GitHub link |
| 126 | exact repo | low target-scope risk |
| 127 | exact repo | low target-scope risk |
| 128 | exact repo | low target-scope risk |
