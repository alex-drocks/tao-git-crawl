import tomllib
from pathlib import Path


def test_runtime_dependencies_are_package_index_compatible_and_reference_git_crawl():
    metadata = tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))

    dependencies = metadata['project']['dependencies']

    assert 'git-crawl>=0.3.2' in dependencies
    assert 'python-dotenv>=1.0,<2' in dependencies
    assert not any('git+' in dependency or ' @ http' in dependency for dependency in dependencies)


def test_local_dotenv_file_is_ignored_and_example_is_tracked():
    metadata = tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))
    gitignore = Path('.gitignore').read_text(encoding='utf-8').splitlines()
    example = Path('.env.example').read_text(encoding='utf-8')

    assert '.env' in gitignore
    assert 'GITHUB_TOKEN=<paste-token-here>' in example
    assert '/.env.example' in metadata['tool']['hatch']['build']['targets']['sdist']['include']


def test_local_runtime_state_paths_are_ignored():
    gitignore = Path('.gitignore').read_text(encoding='utf-8').splitlines()
    dockerignore = Path('.dockerignore').read_text(encoding='utf-8').splitlines()

    assert '.cache/' in gitignore
    assert '.state/' in gitignore
    assert '.cache/' in dockerignore
    assert '.state/' in dockerignore


def test_changelog_is_ready_for_release_notes_and_packaged_in_sdist():
    metadata = tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))
    changelog = Path('CHANGELOG.md').read_text(encoding='utf-8')

    assert metadata['project']['version'] == '1.0.1'
    assert '## [Unreleased]' in changelog
    assert '## [1.0.1] - 2026-07-11' in changelog
    assert '## [1.0.0] - 2026-05-29' in changelog
    assert '## [0.7.1] - 2026-05-26' in changelog
    assert '## [0.7.0] - 2026-05-25' in changelog
    assert '## [0.6.1] - 2026-05-25' in changelog
    assert '## [0.6.0] - 2026-05-24' in changelog
    assert '## [0.5.0] - 2026-05-24' in changelog
    assert '## [0.4.0] - 2026-05-23' in changelog
    assert '## [0.3.0] - 2026-05-23' in changelog
    assert '## [0.2.0] - 2026-05-22' in changelog
    assert '## [0.1.1] - 2026-05-22' in changelog
    assert '## [0.1.0] - 2026-05-22' in changelog
    assert '[Unreleased]: https://github.com/alex-drocks/tao-git-crawl/compare/v1.0.1...HEAD' in changelog
    assert '[1.0.1]: https://github.com/alex-drocks/tao-git-crawl/compare/v1.0.0...v1.0.1' in changelog
    assert '[1.0.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.7.1...v1.0.0' in changelog
    assert '[0.7.1]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.7.0...v0.7.1' in changelog
    assert '[0.7.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.6.1...v0.7.0' in changelog
    assert '[0.6.1]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.6.0...v0.6.1' in changelog
    assert '[0.6.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.5.0...v0.6.0' in changelog
    assert '[0.5.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.4.0...v0.5.0' in changelog
    assert '[0.4.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.3.0...v0.4.0' in changelog
    assert '[0.3.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.2.0...v0.3.0' in changelog
    assert '[0.2.0]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.1.1...v0.2.0' in changelog
    assert '[0.1.1]: https://github.com/alex-drocks/tao-git-crawl/compare/v0.1.0...v0.1.1' in changelog
    assert '[0.1.0]: https://github.com/alex-drocks/tao-git-crawl/releases/tag/v0.1.0' in changelog
    assert '/CHANGELOG.md' in metadata['tool']['hatch']['build']['targets']['sdist']['include']
    assert '/examples' not in metadata['tool']['hatch']['build']['targets']['sdist']['include']
    assert '/registry' in metadata['tool']['hatch']['build']['targets']['sdist']['include']
    assert metadata['tool']['hatch']['build']['targets']['wheel']['force-include'] == {
        'registry/overrides.json': 'tao_git_crawl/registry_overrides.json',
    }
    assert metadata['project']['urls']['Changelog'].endswith('/CHANGELOG.md')


def test_readme_manual_override_and_per_subnet_commands_match_cli_behavior():
    readme = Path('README.md').read_text(encoding='utf-8')

    assert '--config config.py' in readme
    assert '--netuid 64' in readme
    assert 'examples/' not in readme
    assert 'Do not pass --max-repos if you want full owner coverage.' in readme
    assert 'Add --include-forks or --include-archived if you also want those repos.' in readme
    assert 'excluded repositories do not consume the limit.' in readme
    assert '--state-db .state/git-crawl.sqlite' not in readme
    assert '--state-db /data/state/db.sqlite' not in readme
    assert "SN64's `repository-manifest.json` is intentionally empty" in readme
    assert 'out/tao/subnets/99/repository-manifest.json' in readme
    assert 'https://github.com/RendixNetwork' in readme
    assert 'https://github.com/opentensor"},' not in readme
    assert 'out/tao/subnets/64/repository-manifest.json' not in readme


def test_docker_docs_and_compose_pass_documented_scheduler_environment():
    readme = Path('README.md').read_text(encoding='utf-8')
    compose = Path('docker-compose.yml').read_text(encoding='utf-8')
    dockerfile = Path('Dockerfile').read_text(encoding='utf-8')

    for name in [
        'TAO_CRAWL_OUTPUT_DIR',
        'TAO_CRAWL_CACHE_DIR',
        'TAO_CRAWL_IDENTITY_CHECK_SECONDS',
        'TAO_CRAWL_INCREMENTAL',
        'TAO_CRAWL_STATE_DB',
        'TAO_CRAWL_LOG_DIR',
        'TAO_CRAWL_RUN_ON_START',
        'TAO_CRAWL_WINDOW_DAYS',
        'TAO_CRAWL_SINCE',
        'TAO_CRAWL_REGISTRY_URL',
        'TAO_CRAWL_REGISTRY',
        'TAO_CRAWL_CONFIG',
        'TAO_API_OUTPUT_DIR',
        'TAO_API_HOST',
        'TAO_API_BIND_HOST',
        'TAO_API_PORT',
        'TAO_API_CORS_ORIGIN',
        'TAO_API_RATE_LIMIT_REQUESTS',
        'TAO_API_RATE_LIMIT_WINDOW_SECONDS',
    ]:
        assert name in readme
        assert name in compose

    assert 'git-crawl.git@v0.3.2' in dockerfile
    assert 'git-crawl.git@v0.3.2' in compose
    assert 'git-crawl.git@main' not in dockerfile
    assert 'git-crawl.git@main' not in compose
    assert 'COPY registry/ ./registry/' in dockerfile
    assert 'raw.githubusercontent.com/alex-drocks/tao-git-crawl/main/registry.json' not in readme
    assert '${TAO_API_BIND_HOST:-127.0.0.1}:${TAO_API_PORT:-8080}:8080' in compose
    assert 'reverse_proxy 127.0.0.1:8080' in readme
    assert '1200` requests per `60` seconds per TCP peer' in readme
    assert 'GET /api/subnets/<netuid>/activity' in readme
    assert 'one canonical activity model' in readme
    assert 'falls back to `git-crawl` v0.3.2 `activity.json`' in readme
    assert '`skipped`' in readme
    assert 'averages.per_active_day' in readme
    assert 'GET /api/subnets/<netuid>/score' in readme
    assert 'GET /api/scores' in readme
    assert 'Crawl-window average credited commits per active day' in readme
    assert 'Crawl-window credited file changes' in readme
    assert 'trailing 365-day score/activity window by default' in readme
    assert 'rolling-window rankings' in readme
    assert 'TAO_CRAWL_INCREMENTAL=true' in readme
    assert 'tao-git-crawl-api --host 127.0.0.1' in readme
    assert 'do not change `TAO_API_HOST=0.0.0.0` inside the container' in readme
    assert "python3.12 -m pip install -e '.[dev]'" in readme


def test_docker_compose_uses_single_data_volume_for_persistent_paths():
    readme = Path('README.md').read_text(encoding='utf-8')
    compose = Path('docker-compose.yml').read_text(encoding='utf-8')

    assert 'container_name:' not in compose
    assert 'tao-data:/data' in compose
    assert 'tao-data:' in compose
    for old_volume in ['tao-output', 'tao-cache', 'tao-state', 'tao-logs']:
        assert old_volume not in compose

    assert 'Compose creates one named volume' in readme
    assert 'tao-git-crawl_tao-data' in readme


def test_env_example_keeps_api_local_by_default():
    example = Path('.env.example').read_text(encoding='utf-8')

    assert 'TAO_API_BIND_HOST=127.0.0.1' in example
    assert 'TAO_API_BIND_HOST=0.0.0.0' in example
    assert 'TAO_API_RATE_LIMIT_REQUESTS=1200' in example
    assert 'TAO_API_RATE_LIMIT_WINDOW_SECONDS=60' in example
    assert 'TAO_CRAWL_WINDOW_DAYS=365' in example
    assert 'TAO_CRAWL_SINCE=' in example
    assert 'TAO_CRAWL_INCREMENTAL=false' in example
