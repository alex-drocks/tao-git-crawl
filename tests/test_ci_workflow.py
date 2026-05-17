from pathlib import Path


def test_ci_workflow_validates_package_build_and_offline_resolve_smoke():
    workflow = Path('.github/workflows/ci.yml')

    content = workflow.read_text(encoding='utf-8')

    assert 'schedule:' not in content
    assert 'python-version: "3.12"' in content
    assert 'python -m pytest tests -q' in content
    assert 'python -m ruff check tao_git_crawl tests' in content
    assert 'python -m build' in content
    assert 'git-crawl @ git+https://github.com/alex-drocks/git-crawl.git@v0.2.0' in content
    assert '0f2eb881296e591a81e806c0689797c65cfdde77' not in content
    assert '72b2b5941a9c6d8313ffa637d3c46d16d99f4ad3' not in content
    assert 'resolve --from-json examples/subnets.sample.json' in content
    assert 'tao-git-crawl" crawl --help' in content
    assert 'subnets/64/owner-targets.json' in content


def test_public_sample_fixture_avoids_inaccessible_chutes_repository():
    sample = Path('examples/subnets.sample.json').read_text(encoding='utf-8')
    readme = Path('README.md').read_text(encoding='utf-8')

    assert 'Chutes AI' in sample
    assert 'https://github.com/chutesai/sek8s' in sample
    assert 'https://github.com/RendixNetwork/nexisgen' in sample
    assert 'https://github.com/opentensor/subtensor' not in sample
    assert 'https://github.com/chutesai/api' not in sample
    assert '@v0.2.0' in readme
