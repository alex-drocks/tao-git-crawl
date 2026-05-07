import tomllib
from pathlib import Path


def test_runtime_dependencies_are_package_index_compatible_and_reference_git_crawl():
    metadata = tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))

    dependencies = metadata['project']['dependencies']

    assert 'git-crawl>=0.1.0' in dependencies
    assert not any('git+' in dependency or ' @ http' in dependency for dependency in dependencies)
