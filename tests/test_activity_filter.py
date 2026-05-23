import pytest

from tao_git_crawl.activity_filter import noise_change_class


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
