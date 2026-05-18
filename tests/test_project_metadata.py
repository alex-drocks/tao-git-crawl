import tomllib
from pathlib import Path


def test_runtime_dependencies_are_package_index_compatible_and_reference_git_crawl():
    metadata = tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))

    dependencies = metadata['project']['dependencies']

    assert 'git-crawl>=0.2.0' in dependencies
    assert 'python-dotenv>=1.0,<2' in dependencies
    assert not any('git+' in dependency or ' @ http' in dependency for dependency in dependencies)


def test_local_dotenv_file_is_ignored_and_example_is_tracked():
    metadata = tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))
    gitignore = Path('.gitignore').read_text(encoding='utf-8').splitlines()
    example = Path('.env.example').read_text(encoding='utf-8')

    assert '.env' in gitignore
    assert 'GITHUB_TOKEN=<paste-token-here>' in example
    assert '/.env.example' in metadata['tool']['hatch']['build']['targets']['sdist']['include']


def test_readme_manual_override_and_per_subnet_examples_match_cli_behavior():
    readme = Path('README.md').read_text(encoding='utf-8')

    assert '--config config.py' in readme
    assert '--netuid 64' in readme
    assert 'Do not pass --max-repos if you want full owner coverage.' in readme
    assert 'Add --include-forks or --include-archived if you also want those repos.' in readme
    assert 'excluded repositories do not consume the limit.' in readme
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
        'TAO_CRAWL_STATE_DB',
        'TAO_CRAWL_LOG_DIR',
        'TAO_CRAWL_RUN_ON_START',
        'TAO_CRAWL_REGISTRY_URL',
        'TAO_CRAWL_REGISTRY',
        'TAO_CRAWL_CONFIG',
        'TAO_API_OUTPUT_DIR',
        'TAO_API_HOST',
        'TAO_API_PORT',
        'TAO_API_CORS_ORIGIN',
    ]:
        assert name in readme
        assert name in compose

    assert 'git-crawl.git@v0.2.0' in dockerfile
    assert 'git-crawl.git@v0.2.0' in compose
    assert 'git-crawl.git@main' not in dockerfile
    assert 'git-crawl.git@main' not in compose
    assert 'raw.githubusercontent.com/alex-drocks/tao-git-crawl/main/registry.json' not in readme


def test_docker_compose_uses_single_data_volume_for_persistent_paths():
    readme = Path('README.md').read_text(encoding='utf-8')
    compose = Path('docker-compose.yml').read_text(encoding='utf-8')

    assert 'tao-data:/data' in compose
    assert 'tao-data:' in compose
    for old_volume in ['tao-output', 'tao-cache', 'tao-state', 'tao-logs']:
        assert old_volume not in compose

    assert 'Compose creates one named volume' in readme
    assert 'tao-git-crawl_tao-data' in readme
