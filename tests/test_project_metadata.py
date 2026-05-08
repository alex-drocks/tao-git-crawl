import tomllib
from pathlib import Path


def test_runtime_dependencies_are_package_index_compatible_and_reference_git_crawl():
    metadata = tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))

    dependencies = metadata['project']['dependencies']

    assert 'git-crawl>=0.1.0' in dependencies
    assert 'python-dotenv>=1.0,<2' in dependencies
    assert not any('git+' in dependency or ' @ http' in dependency for dependency in dependencies)


def test_local_dotenv_file_is_ignored_and_example_is_tracked():
    metadata = tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))
    gitignore = Path('.gitignore').read_text(encoding='utf-8').splitlines()
    example = Path('.env.example').read_text(encoding='utf-8')

    assert '.env' in gitignore
    assert 'GITHUB_TOKEN=<paste-token-here>' in example
    assert '/.env.example' in metadata['tool']['hatch']['build']['targets']['sdist']['include']
