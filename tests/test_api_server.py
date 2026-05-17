"""Tests for tao_git_crawl.api_server."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tao_git_crawl.api_server import app, _read_jsonl


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TAO_API_OUTPUT_DIR", str(tmp_path / "output"))
    # Re-import to pick up the patched env var
    from tao_git_crawl import api_server as mod

    mod._OUTPUT_DIR = Path(str(tmp_path / "output"))
    mod._OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return TestClient(app)


class TestHealth:
    def test_health_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.text == "ok"


class TestListSubnets:
    def test_empty(self, client):
        response = client.get("/api/v1/subnets")
        assert response.status_code == 200
        assert response.json() == {"subnets": [], "count": 0}

    def test_two_subnets(self, client, tmp_path):
        subnets_dir = tmp_path / "output" / "subnets"

        # Subnet 64: Chutes
        s64 = subnets_dir / "64"
        s64.mkdir(parents=True)
        (s64 / "subnet-targets.json").write_text(
            json.dumps({"target": "bittensor-subnet-64", "targets": [{"kind": "owner", "url": "https://github.com/chutesai"}]}),
            encoding="utf-8",
        )
        crawl64 = s64 / "crawl"
        crawl64.mkdir()
        (crawl64 / "summary.json").write_text(
            json.dumps({"run": {"status": "success", "run_id": "r1"}, "repositories": [{"full_name": "chutesai/api"}]}),
            encoding="utf-8",
        )

        # Subnet 12: OpenTensor
        s12 = subnets_dir / "12"
        s12.mkdir(parents=True)
        (s12 / "subnet-targets.json").write_text(
            json.dumps({"target": "bittensor-subnet-12", "targets": [{"kind": "owner", "url": "https://github.com/opentensor"}]}),
            encoding="utf-8",
        )

        response = client.get("/api/v1/subnets")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        uids = [s["netuid"] for s in data["subnets"]]
        assert uids == [12, 64]

        chutes = [s for s in data["subnets"] if s["netuid"] == 64][0]
        assert chutes["crawl_status"] == "success"
        assert chutes["crawl_run_id"] == "r1"

        ot = [s for s in data["subnets"] if s["netuid"] == 12][0]
        assert ot["crawl_status"] is None


class TestGetSubnet:
    def test_found(self, client, tmp_path):
        subnets_dir = tmp_path / "output" / "subnets"
        s64 = subnets_dir / "64"
        s64.mkdir(parents=True)
        (s64 / "subnet-targets.json").write_text(
            json.dumps(
                {
                    "target": "bittensor-subnet-64",
                    "targets": [{"kind": "owner", "url": "https://github.com/chutesai"}],
                    "unresolved": [],
                }
            ),
            encoding="utf-8",
        )
        (s64 / "crawl").mkdir()
        (s64 / "crawl" / "summary.json").write_text(
            json.dumps({"run": {"status": "success", "run_id": "r1"}}),
            encoding="utf-8",
        )

        response = client.get("/api/v1/subnets/64")
        assert response.status_code == 200
        data = response.json()
        assert data["netuid"] == 64
        assert data["target_label"] == "bittensor-subnet-64"
        assert len(data["targets"]) == 1

    def test_not_found(self, client):
        response = client.get("/api/v1/subnets/999")
        assert response.status_code == 404


class TestGetSubnetSummary:
    def test_found(self, client, tmp_path):
        crawl_dir = tmp_path / "output" / "subnets" / "64" / "crawl"
        crawl_dir.mkdir(parents=True)
        (crawl_dir / "summary.json").write_text(
            json.dumps({"run": {"status": "success"}, "repositories": 3}),
            encoding="utf-8",
        )

        response = client.get("/api/v1/subnets/64/metrics/summary")
        assert response.status_code == 200
        assert response.json()["repositories"] == 3

    def test_not_found(self, client):
        response = client.get("/api/v1/subnets/64/metrics/summary")
        assert response.status_code == 404


class TestGetSubnetMetrics:
    def test_dataset_found(self, client, tmp_path):
        crawl_dir = tmp_path / "output" / "subnets" / "64" / "crawl"
        crawl_dir.mkdir(parents=True)
        rows = [
            {"date": "2026-01-01", "commits": 5},
            {"date": "2026-01-02", "commits": 3},
            {"date": "2026-01-03", "commits": 8},
        ]
        (crawl_dir / "org_days.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n",
            encoding="utf-8",
        )

        response = client.get("/api/v1/subnets/64/metrics/org_days")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 3
        assert data["dataset"] == "org_days"

    def test_dataset_filter_since_until(self, client, tmp_path):
        crawl_dir = tmp_path / "output" / "subnets" / "64" / "crawl"
        crawl_dir.mkdir(parents=True)
        rows = [
            {"date": "2026-01-01", "commits": 5},
            {"date": "2026-01-15", "commits": 3},
            {"date": "2026-02-01", "commits": 8},
        ]
        (crawl_dir / "org_days.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n",
            encoding="utf-8",
        )

        response = client.get("/api/v1/subnets/64/metrics/org_days?since=2026-01-10&until=2026-01-31")
        data = response.json()
        assert data["count"] == 1
        assert data["rows"][0]["date"] == "2026-01-15"

    def test_dataset_limit(self, client, tmp_path):
        crawl_dir = tmp_path / "output" / "subnets" / "64" / "crawl"
        crawl_dir.mkdir(parents=True)
        rows = [{"date": "2026-01-01", "commits": i} for i in range(100)]
        (crawl_dir / "org_days.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n",
            encoding="utf-8",
        )

        response = client.get("/api/v1/subnets/64/metrics/org_days?limit=10")
        assert response.json()["count"] == 10

    def test_missing_dataset(self, client):
        response = client.get("/api/v1/subnets/64/metrics/org_days")
        assert response.status_code == 200
        assert response.json()["count"] == 0


class TestAggregateSummary:
    def test_empty(self, client):
        response = client.get("/api/v1/aggregate/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["total_targets"] == 0
        assert data["succeeded_subnets"] == 0

    def test_with_data(self, client, tmp_path):
        output_dir = tmp_path / "output"
        (output_dir / "subnet-targets.json").write_text(
            json.dumps({"target": "tao", "targets": [{"kind": "repository", "url": "https://github.com/a/b"}], "unresolved": []}),
            encoding="utf-8",
        )
        (output_dir / "crawl-report.json").write_text(
            json.dumps({"succeeded": [{"netuid": 64}], "failed": [], "skipped_unresolved_netuids": []}),
            encoding="utf-8",
        )

        response = client.get("/api/v1/aggregate/summary")
        data = response.json()
        assert data["total_targets"] == 1
        assert data["succeeded_subnets"] == 1


class TestReadJsonl:
    def test_since_filter(self, tmp_path):
        path = tmp_path / "rows.jsonl"
        rows = [{"date": "2026-01-01"}, {"date": "2026-01-15"}, {"date": "2026-02-01"}]
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

        result = _read_jsonl(path, since="2026-01-10", until="2026-01-31")
        assert len(result) == 1
        assert result[0]["date"] == "2026-01-15"

    def test_limit(self, tmp_path):
        path = tmp_path / "rows.jsonl"
        rows = [{"n": i} for i in range(100)]
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

        result = _read_jsonl(path, limit=5)
        assert len(result) == 5
