import pytest

from tao_git_crawl.activity_filter import (
    REGISTRY_EXCLUSION_CLASS,
    credit_exclusions_from_document,
    has_valid_churn_metrics,
    is_credited_change,
    noise_change_class,
)
from tao_git_crawl.models import CreditExclusion


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/app.py", None),
        ("package.json", None),
        ("tsconfig.json", None),
        ("tri-claw/.secrets.baseline", "generated"),
        ("coverage.xml", "generated"),
        ("reports/junit-tests.xml", "generated"),
        ("overnight_test_results.txt", "generated"),
        ("scripts/pod_eval_vllm.py.bak.1776017973", "generated"),
        ("evaluator/datasets/swebench_verified/swebench_verified.json", "artifact/data"),
        ("web/public/research/paper.pdf", "artifact/data"),
        ("swarm/assets/maps/forest/terrain_cache/forest_hills_v12.obj", "artifact/data"),
        ("external_tools/boltz/msa_files/P23975.a3m", "artifact/data"),
        ("gateway/utils/geo_lookup_fast.json", "artifact/data"),
    ],
)
def test_noise_change_class_filters_artifacts_and_data_paths(path, expected):
    assert noise_change_class({"path": path, "path_class": "source"}) == expected


def test_noise_change_class_uses_filename_when_path_is_absent():
    assert noise_change_class({"filename": "data/leads.json", "path_class": "source"}) == "artifact/data"


@pytest.mark.parametrize("value", [-1, True, "10", float("inf"), float("nan")])
def test_churn_metrics_reject_malformed_or_negative_numbers(value):
    assert has_valid_churn_metrics({"additions": value}) is False


def test_churn_metrics_accept_nonnegative_and_arbitrarily_large_integers():
    assert has_valid_churn_metrics({"additions": 0, "deletions": 10**1000}) is True


@pytest.mark.parametrize(
    "path",
    [
        "sim-testnet/peerreview/evidence/run-1/capture/body.stdout",
        "sim-testnet/peerreview/evidence/run-1/switch.stderr",
        "research/logs/trackM_status.log",
        "mainnet/evidence/source-lock.sha256",
        "dist/SHA256SUMS",
        ".tweet_store.json.bak",
        "albedo/validator/loop.py.bak",
        "src/app.py.orig",
        "corpus/genome.fasta",
        "leadpoet_verifier/identity/public_suffix_list.dat",
        "swarm/assets/maps/kenney/kit/model.mtl",
        "corpus/source.c.txt",
        "validator/corpus/lean.txt",
        "docs/evidence/prod-validate/http_healthz.txt",
        "sim-testnet/peerreview/evidence/run-1/outer.pid",
        "sim-testnet/peerreview/evidence/run-1/switch.exit",
        "sim-testnet/peerreview/evidence/run-1/captures/body.started-at",
        "sim-testnet/peerreview/evidence/run-1/SHA256SUMS",
    ],
)
def test_noise_change_class_filters_run_output_checksums_backups_and_data(path):
    assert noise_change_class({"path": path, "path_class": "source"}) == "artifact/data"


@pytest.mark.parametrize(
    "path",
    [
        "apps/platform/dashboard/src/components/evidence/EvidencePanel.tsx",
        "internal/evidence/evidence.go",
        "internal/evidence/evidence.proto",
        "sim-testnet/peerreview/evidence/run-1/command.sh",
        "mainnet/evidence/current-readiness-checkpoint.md",
        "reliquary/corpus/sampler.py",
        "affine/affine/corpus/__init__.py",
        "ops/coverage/coverage.py",
        "src/backup.py",
        "docs/changelog.md",
    ],
)
def test_noise_change_class_keeps_authored_files_in_output_named_directories(path):
    assert noise_change_class({"path": path, "path_class": "source"}) is None


EXCLUSIONS = (
    CreditExclusion(repo="Acme/Vendored", reason="vendored upstream project", path="third/"),
    CreditExclusion(repo="acme/app", reason="import commit", commit="abc1234", path="lib/"),
    CreditExclusion(repo="acme/app", reason="whole import commit", commit="def5678"),
    CreditExclusion(repo="acme/app", reason="copied reference document", path="docs/API.md"),
)


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"repo": "acme/vendored", "sha": "1111111", "path": "third/x.py"}, REGISTRY_EXCLUSION_CLASS),
        ({"repo": "acme/vendored", "sha": "1111111", "path": "thirdparty/x.py"}, None),
        ({"repo": "acme/app", "sha": "abc1234ffff", "path": "lib/x.py"}, REGISTRY_EXCLUSION_CLASS),
        ({"repo": "acme/app", "sha": "abc1234ffff", "path": "src/x.py"}, None),
        ({"repo": "acme/app", "sha": "9999999", "path": "lib/x.py"}, None),
        ({"repo": "acme/app", "commit_sha": "DEF5678aa", "path": "src/y.py"}, REGISTRY_EXCLUSION_CLASS),
        ({"repo": "acme/app", "sha": "1111111", "path": "docs/API.md"}, REGISTRY_EXCLUSION_CLASS),
        ({"repo": "acme/app", "sha": "1111111", "path": "docs/API.mdx"}, None),
        ({"repo": "other/app", "sha": "abc1234", "path": "lib/x.py"}, None),
        ({"repo": "acme/vendored", "sha": "1111111", "path": "third/run.log"}, "artifact/data"),
    ],
)
def test_registry_exclusions_cover_only_the_reviewed_repo_path_and_commit(row, expected):
    row = {"path_class": "source", **row}
    assert noise_change_class(row, EXCLUSIONS) == expected
    assert is_credited_change(row, EXCLUSIONS) is (expected is None)
    assert is_credited_change(row) is (expected in {None, REGISTRY_EXCLUSION_CLASS})


def test_credit_exclusions_from_document_reads_valid_entries_for_the_netuid():
    document = {
        "credit_exclusions": [
            {"netuid": 23, "repo": "acme/app", "path": "vendor-copy/", "reason": "vendored"},
            {"netuid": 23, "repo": "acme/app", "commit": "abc1234", "reason": "import"},
            {"netuid": 24, "repo": "acme/other", "path": "x/", "reason": "other subnet"},
            {"netuid": 23, "repo": "acme/app", "reason": "no scope"},
            {"netuid": 23, "path": "x/", "reason": "no repo"},
            "not an object",
        ]
    }

    assert credit_exclusions_from_document(document, 23) == (
        CreditExclusion(repo="acme/app", reason="vendored", path="vendor-copy/"),
        CreditExclusion(repo="acme/app", reason="import", commit="abc1234"),
    )
    assert credit_exclusions_from_document({"targets": []}, 23) == ()
    assert credit_exclusions_from_document(None, 23) == ()


def test_exclusion_exceptions_preserve_local_paths_without_overriding_other_rules():
    exclusion = CreditExclusion(
        repo="acme/app", commit="abc1234", path="lib/", reason="import",
        except_paths=("lib/adapter.py", "lib/local/"),
    )
    row = {"repo": "acme/app", "sha": "abc1234ffff", "path": "lib/adapter.py", "additions": 4}
    assert is_credited_change(row, (exclusion,))
    assert is_credited_change({**row, "path": "lib/local/adapter.py"}, (exclusion,))
    assert not is_credited_change({**row, "path": "lib/locality/adapter.py"}, (exclusion,))
    assert not is_credited_change({**row, "path": "lib/upstream.py"}, (exclusion,))
    assert not is_credited_change({**row, "is_binary": True}, (exclusion,))
    other = CreditExclusion(repo="acme/app", path="lib/adapter.py", reason="separate reviewed import")
    assert not is_credited_change(row, (exclusion, other))


def test_credit_exclusion_exceptions_survive_document_round_trip():
    exclusion = CreditExclusion(
        repo="acme/app", path="lib/", reason="import", except_paths=("lib/adapter.py",),
    )
    document = {"credit_exclusions": [{"netuid": 23, **exclusion.to_dict()}]}
    assert document["credit_exclusions"][0]["except_paths"] == ["lib/adapter.py"]
    assert credit_exclusions_from_document(document, 23) == (exclusion,)
    assert "except_paths" not in CreditExclusion(repo="acme/app", path="lib/", reason="import").to_dict()
    malformed = {"credit_exclusions": [{"netuid": 23, **exclusion.to_dict(), "except_paths": [123]}]}
    assert credit_exclusions_from_document(malformed, 23) == ()
