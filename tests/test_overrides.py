import pytest

from tao_git_crawl.overrides import ResolverConfigError, load_resolver_config


def test_load_resolver_config_accepts_target_only_override(tmp_path):
    config_path = tmp_path / "config.py"
    config_path.write_text(
        """
SUBNET_OVERRIDES = {
    64: {
        "targets": [{"kind": "owner", "url": "https://github.com/chutesai"}],
    }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    config = load_resolver_config(config_path)
    assert config.subnet_overrides[64].targets[0].url == "https://github.com/chutesai"


def test_load_resolver_config_rejects_removed_registered_at_field(tmp_path):
    config_path = tmp_path / "config.py"
    config_path.write_text(
        'SUBNET_OVERRIDES = {64: {"registered_at": 123, "targets": []}}\n',
        encoding="utf-8",
    )

    with pytest.raises(ResolverConfigError, match="registered_at.*not supported"):
        load_resolver_config(config_path)


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


def test_load_resolver_config_rejects_confidence(tmp_path):
    config_path = tmp_path / "config.py"
    config_path.write_text(
        """
SUBNET_OVERRIDES = {
    64: {
        "replace": True,
        "targets": [{"kind": "owner", "url": "https://github.com/chutesai", "confidence": "high"}],
    }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ResolverConfigError, match="confidence is not supported"):
        load_resolver_config(config_path)
