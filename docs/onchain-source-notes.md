# On-Chain Source

`tao-git-crawl` reads subnet identity metadata from:

```text
SubtensorModule.SubnetIdentitiesV3(netuid) -> Option<SubnetIdentityV3>
```

Regular subnet slots are netuids `1` through `128`. Netuid `0` is the Bittensor root network and is excluded from
resolver/crawler input.

GitHub discovery uses these `SubnetIdentityV3` fields:

- `github_repo`
- `subnet_url`
- `description`
- `additional`
- `subnet_contact`

`github_repo` is the primary source. The other fields are fallback text sources.

Exact repository URLs and bare `owner/repo` values become repository targets. GitHub owner roots become owner targets. Subnets with no usable GitHub target are written to `unresolved.json`.

Live chain reads use the optional `chain` extra:

```bash
python3.12 -m pip install -e '.[chain]'
tao-git-crawl resolve --network finney --output-dir out/tao
```

The default Finney endpoint is `wss://entrypoint-finney.opentensor.ai:443`. Use `--endpoint` to query another node.
