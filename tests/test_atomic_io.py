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


def test_write_json_atomic_keeps_previous_file_when_replace_fails(monkeypatch, tmp_path):
    path = tmp_path / "crawl-report.json"
    previous_bytes = b'{ "run": 1 }\r\n'
    path.write_bytes(previous_bytes)
    failure = OSError("injected replacement failure")
    failed_paths = []
    original_replace = Path.replace

    def fail_replace(self, target):
        if self.parent == path.parent and self.name.startswith(f".{path.name}.tmp-"):
            assert target == path
            assert json.loads(self.read_text(encoding="utf-8")) == {"run": 2}
            failed_paths.append(self)
            raise failure
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError) as exc_info:
        write_json_atomic(path, {"run": 2})

    assert exc_info.value is failure
    assert len(failed_paths) == 1
    assert path.read_bytes() == previous_bytes
    assert not failed_paths[0].exists()
    assert set(tmp_path.iterdir()) == {path}


def test_write_json_atomic_keeps_previous_file_when_temporary_write_fails(monkeypatch, tmp_path):
    path = tmp_path / "crawl-report.json"
    previous_bytes = b'{ "run": 1 }\r\n'
    path.write_bytes(previous_bytes)
    failure = OSError("injected partial-write failure")
    failed_paths = []
    original_write_text = Path.write_text

    def fail_write_text(self, data, *args, **kwargs):
        if self.parent == path.parent and self.name.startswith(f".{path.name}.tmp-"):
            partial = data[: len(data) // 2]
            assert 0 < len(partial) < len(data)
            original_write_text(self, partial, *args, **kwargs)
            assert self.read_text(encoding="utf-8") == partial
            failed_paths.append(self)
            raise failure
        return original_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_write_text)

    with pytest.raises(OSError) as exc_info:
        write_json_atomic(path, {"run": 2})

    assert exc_info.value is failure
    assert len(failed_paths) == 1
    assert path.read_bytes() == previous_bytes
    assert not failed_paths[0].exists()
    assert set(tmp_path.iterdir()) == {path}
