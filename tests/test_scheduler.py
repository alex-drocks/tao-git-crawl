import os
import subprocess
from types import SimpleNamespace

import pytest

from tao_git_crawl.scheduler import build_crawl_command, healthcheck, run_crawl


class TestBuildCrawlCommand:
    def test_default_args(self, monkeypatch):
        monkeypatch.delenv("TAO_CRAWL_REGISTRY_URL", raising=False)
        monkeypatch.delenv("TAO_CRAWL_REGISTRY", raising=False)
        monkeypatch.delenv("TAO_CRAWL_CONFIG", raising=False)

        cmd = build_crawl_command()

        # sys.executable may be a full path in a venv
        assert cmd[1:4] == ["-m", "tao_git_crawl.cli", "crawl"]
        assert cmd[0].endswith("python") or cmd[0].endswith("python3")
        assert "--network" in cmd
        assert "finney" in cmd
        assert "--output-dir" in cmd
        assert "/data/output" in cmd
        assert "--cache-dir" in cmd
        assert "/data/cache" in cmd
        assert "--state-db" in cmd
        assert "/data/state/db.sqlite" in cmd
        assert "--workers" in cmd
        assert "4" in cmd
        assert "--since" in cmd
        assert "2025-01-01" in cmd
        assert "--commit-changes-filtration-level" in cmd
        assert "source_like" in cmd

    def test_registry_url_appended(self, monkeypatch):
        monkeypatch.setenv("TAO_CRAWL_REGISTRY_URL", "https://example.com/registry.json")
        monkeypatch.delenv("TAO_CRAWL_REGISTRY", raising=False)
        monkeypatch.delenv("TAO_CRAWL_CONFIG", raising=False)

        cmd = build_crawl_command()

        assert "--registry-url" in cmd
        idx = cmd.index("--registry-url")
        assert cmd[idx + 1] == "https://example.com/registry.json"

    def test_registry_file_appended(self, monkeypatch):
        monkeypatch.delenv("TAO_CRAWL_REGISTRY_URL", raising=False)
        monkeypatch.setenv("TAO_CRAWL_REGISTRY", "/data/registry.json")
        monkeypatch.delenv("TAO_CRAWL_CONFIG", raising=False)

        cmd = build_crawl_command()

        assert "--registry" in cmd
        idx = cmd.index("--registry")
        assert cmd[idx + 1] == "/data/registry.json"

    def test_config_file_appended(self, monkeypatch):
        monkeypatch.delenv("TAO_CRAWL_REGISTRY_URL", raising=False)
        monkeypatch.delenv("TAO_CRAWL_REGISTRY", raising=False)
        monkeypatch.setenv("TAO_CRAWL_CONFIG", "/data/config.py")

        cmd = build_crawl_command()

        assert "--config" in cmd
        idx = cmd.index("--config")
        assert cmd[idx + 1] == "/data/config.py"

    def test_all_optional_env_vars_together(self, monkeypatch):
        monkeypatch.setenv("TAO_CRAWL_REGISTRY_URL", "https://example.com/registry.json")
        monkeypatch.setenv("TAO_CRAWL_REGISTRY", "/data/registry.json")
        monkeypatch.setenv("TAO_CRAWL_CONFIG", "/data/config.py")

        cmd = build_crawl_command()

        assert "--registry-url" in cmd
        assert "--registry" in cmd
        assert "--config" in cmd


class TestRunCrawl:
    def test_successful_run(self, tmp_path, monkeypatch):
        log_dir = tmp_path / "logs"
        calls = []

        def fake_run(cmd, stdout, stderr):
            calls.append(cmd)
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(subprocess, "run", fake_run)

        exit_code = run_crawl(log_dir)

        assert exit_code == 0
        assert len(calls) == 1
        assert calls[0][1:4] == ["-m", "tao_git_crawl.cli", "crawl"]
        assert log_dir.exists()
        log_files = list(log_dir.glob("crawl_*.log"))
        assert len(log_files) == 1

    def test_failed_run(self, tmp_path, monkeypatch):
        log_dir = tmp_path / "logs"

        def fake_run(cmd, stdout, stderr):
            return SimpleNamespace(returncode=1)

        monkeypatch.setattr(subprocess, "run", fake_run)

        exit_code = run_crawl(log_dir)

        assert exit_code == 1


class TestHealthcheck:
    def test_passes_when_writable(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("TAO_CRAWL_OUTPUT_DIR", str(tmp_path / "output"))
        healthcheck()
        captured = capsys.readouterr()
        assert "HEALTHCHECK OK" in captured.out

    def test_fails_when_not_writable(self, tmp_path, monkeypatch, capsys):
        if os.getuid() == 0:
            pytest.skip("running as root; read-only restrictions are bypassed")

        output_dir = tmp_path / "output"
        output_dir.mkdir()
        output_dir.chmod(0o555)  # read-only
        monkeypatch.setenv("TAO_CRAWL_OUTPUT_DIR", str(output_dir))

        with pytest.raises(SystemExit) as exc_info:
            healthcheck()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "HEALTHCHECK FAIL" in captured.err

        output_dir.chmod(0o755)


class TestSchedulerMain:
    def test_exits_without_github_token(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("TAO_CRAWL_RUN_ON_START", "false")

        from tao_git_crawl.scheduler import main

        exit_code = main()
        assert exit_code == 1

    def test_single_run_when_run_on_start_true(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
        monkeypatch.setenv("TAO_CRAWL_RUN_ON_START", "true")
        monkeypatch.setenv("TAO_CRAWL_INTERVAL_SECONDS", "86400")
        monkeypatch.setenv("TAO_CRAWL_LOG_DIR", str(tmp_path / "logs"))

        calls = []

        def fake_run_crawl(log_dir):
            calls.append(log_dir)
            return 0

        def fake_sleep(seconds):
            raise KeyboardInterrupt("stop the loop")

        monkeypatch.setattr("tao_git_crawl.scheduler.run_crawl", fake_run_crawl)
        monkeypatch.setattr("tao_git_crawl.scheduler.time.sleep", fake_sleep)

        from tao_git_crawl.scheduler import main

        with pytest.raises(KeyboardInterrupt):
            main()

        assert len(calls) == 1

    def test_no_run_when_run_on_start_false(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
        monkeypatch.setenv("TAO_CRAWL_RUN_ON_START", "false")
        monkeypatch.setenv("TAO_CRAWL_INTERVAL_SECONDS", "10")
        monkeypatch.setenv("TAO_CRAWL_LOG_DIR", str(tmp_path / "logs"))

        calls = []

        def fake_run_crawl(log_dir):
            calls.append(log_dir)
            return 0

        def fake_sleep(seconds):
            raise KeyboardInterrupt("stop the loop")

        monkeypatch.setattr("tao_git_crawl.scheduler.run_crawl", fake_run_crawl)
        monkeypatch.setattr("tao_git_crawl.scheduler.time.sleep", fake_sleep)

        from tao_git_crawl.scheduler import main

        with pytest.raises(KeyboardInterrupt):
            main()

        assert len(calls) == 0
