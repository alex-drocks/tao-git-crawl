# On-chain source notes

Primary source inspected: `opentensor/subtensor`.

The canonical subnet identity map is:

```text
SubtensorModule.SubnetIdentitiesV3(netuid) -> Option<SubnetIdentityV3>
```

`SubnetIdentityV3` fields relevant for GitHub discovery:

- `github_repo`
- `subnet_url`
- `description`
- `additional`
- `subnet_contact`

Implementation stance for this scaffold:

- Query `SubtensorModule.SubnetIdentitiesV3` directly through runtime metadata using a substrate client.
- Treat `github_repo` as the highest-confidence field.
- Accept exact repository URLs and bare `owner/repo` values because ecosystem tooling has used both forms.
- Preserve GitHub owner roots as owner targets, but do not silently expand them into repositories.
- Emit unresolved subnet records when identity metadata has no usable GitHub target.

Tooling comparison:

- The Python `bittensor` SDK exposes subnet identity through dynamic subnet info, but is heavier than needed as a required dependency.
- `agcli` has Rust code that reads `SubtensorModule.SubnetIdentitiesV3`, but its CLI does not expose subnet identity as a JSON read command suitable for this package.
- This package therefore owns a small provider layer and keeps chain access behind an optional `chain` extra.
