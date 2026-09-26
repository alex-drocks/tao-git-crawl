from pathlib import Path

GIT_CRAWL_PIN = "git+https://github.com/alex-drocks/git-crawl.git@38617b3343ca4b91f15a2c6e3ffa07f810b3e332"


def test_ci_workflow_validates_package_build_and_offline_resolve_smoke():
    workflow = Path('.github/workflows/ci.yml')

    content = workflow.read_text(encoding='utf-8')

    assert 'schedule:' not in content
    assert 'python-version: "3.12"' in content
    assert 'python -m pytest tests -q' in content
    assert 'python -m ruff check tao_git_crawl tests' in content
    assert 'python -m build' in content
    assert f"git-crawl @ {GIT_CRAWL_PIN}" in content
    assert 'git-crawl.git@v' not in content
    assert '0f2eb881296e591a81e806c0689797c65cfdde77' not in content
    assert '72b2b5941a9c6d8313ffa637d3c46d16d99f4ad3' not in content
    assert 'resolve --from-json tests/fixtures/subnets.sample.json' in content
    assert 'tao-git-crawl" crawl --help' in content
    assert 'subnets/64/owner-targets.json' in content


def test_public_sample_fixture_avoids_inaccessible_chutes_repository():
    sample = Path('tests/fixtures/subnets.sample.json').read_text(encoding='utf-8')
    readme = Path('README.md').read_text(encoding='utf-8')

    assert 'Chutes AI' in sample
    assert 'https://github.com/chutesai/sek8s' in sample
    assert 'https://github.com/RendixNetwork/nexisgen' in sample
    assert 'https://github.com/opentensor/subtensor' not in sample
    assert 'https://github.com/chutesai/api' not in sample
    assert GIT_CRAWL_PIN in readme
    assert 'examples/subnets.sample.json' not in readme
