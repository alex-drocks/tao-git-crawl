from pathlib import Path


def test_ci_workflow_validates_package_build_and_offline_resolve_smoke():
    workflow = Path('.github/workflows/ci.yml')

    content = workflow.read_text(encoding='utf-8')

    assert 'schedule:' not in content
    assert 'python-version: "3.12"' in content
    assert 'python -m pytest tests -q' in content
    assert 'python -m ruff check tao_git_crawl tests' in content
    assert 'python -m build' in content
    assert 'resolve --from-json examples/subnets.sample.json' in content
