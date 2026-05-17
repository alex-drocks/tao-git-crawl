import pytest

from tao_git_crawl.overrides import ResolverConfigError, load_resolver_config


def test_load_resolver_config_rejects_non_boolean_replace(tmp_path):
    config_path = tmp_path / "config.py"
    config_path.write_text(
        """
SUBNET_OVERRIDES = {
    64: {
        "replace": "false",
        "targets": [{"kind": "owner", "url": "https://github.com/chutesai"}],
    }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ResolverConfigError, match="'replace' must be a boolean"):
        load_resolver_config(config_path)
