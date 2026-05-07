import json

from tao_git_crawl.cli import main


def test_resolve_cli_writes_resolution_manifest_owner_targets_and_unresolved(tmp_path, capsys):
    input_path = tmp_path / "subnets.json"
    input_path.write_text(
        json.dumps(
            {
                "subnets": [
                    {"netuid": 1, "subnet_identity": {"github_repo": "github.com/alice/api"}},
                    {"netuid": 2, "subnet_identity": {"github_repo": "https://github.com/bob"}},
                    {"netuid": 3, "subnet_identity": {"description": "no code here"}},
                ]
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"

    exit_code = main(["resolve", "--from-json", str(input_path), "--output-dir", str(output_dir), "--target", "tao"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Resolved 1 repository targets, 1 owner targets, 1 unresolved subnet records." in captured.out
    manifest = json.loads((output_dir / "repository-manifest.json").read_text(encoding="utf-8"))
    assert manifest == {
        "target": "tao",
        "repositories": [
            {"url": "https://github.com/alice/api", "netuids": [1], "source": "subnet_identity.github_repo"}
        ],
    }
    owner_targets = json.loads((output_dir / "owner-targets.json").read_text(encoding="utf-8"))
    assert owner_targets[0]["owner"] == "bob"
    unresolved = json.loads((output_dir / "unresolved.json").read_text(encoding="utf-8"))
    assert unresolved == [
        {
            "netuid": 3,
            "subnet_name": "",
            "reason": "no_github_link",
            "fields_checked": [
                "github_repo",
                "subnet_url",
                "description",
                "additional",
                "subnet_contact",
            ],
        }
    ]
