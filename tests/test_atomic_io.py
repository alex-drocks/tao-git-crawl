import json
from pathlib import Path

import pytest

from tao_git_crawl.atomic_io import write_json_atomic


def test_write_json_atomic_swaps_a_complete_file_into_place(monkeypatch, tmp_path):
    path = tmp_path / "subnet-scores.json"
    write_json_atomic(path, {"run": 1})
    swaps = []
    original_replace = Path.replace

    def spy_replace(self, target):
        swaps.append(
            (
                self.name,
                json.loads(Path(target).read_text(encoding="utf-8")),
                json.loads(self.read_text(encoding="utf-8")),
            )
        )
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", spy_replace)

    write_json_atomic(path, {"run": 2})

    staged_name, visible_before_swap, staged_payload = swaps[0]
    assert staged_name.startswith(".subnet-scores.json.tmp-")
    # API readers keep seeing the previous complete file until the swap.
    assert visible_before_swap == {"run": 1}
    assert staged_payload == {"run": 2}
    assert json.loads(path.read_text(encoding="utf-8")) == {"run": 2}
    assert [child.name for child in tmp_path.iterdir()] == ["subnet-scores.json"]


def test_write_json_atomic_keeps_previous_file_when_serialization_fails(tmp_path):
    path = tmp_path / "out" / "crawl-report.json"
    write_json_atomic(path, {"succeeded": [1]})

    with pytest.raises(TypeError):
        write_json_atomic(path, {"succeeded": [object()]})

    assert json.loads(path.read_text(encoding="utf-8")) == {"succeeded": [1]}
    assert [child.name for child in path.parent.iterdir()] == ["crawl-report.json"]
