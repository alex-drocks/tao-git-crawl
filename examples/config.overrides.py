"""Example manual target overrides for tao-git-crawl.

Copy this file to your own config.py and edit it for the subnet/company mappings
you trust. Only load config files you control; Python configs execute as local code.
"""

# Keep exact repository URLs as repository crawls unless a subnet override says
# otherwise. Set to "owner" if you want every exact repo URL to be promoted to
# its GitHub owner by default.
DEFAULT_REPOSITORY_POLICY = "repository"

SUBNET_OVERRIDES = {
    # Chutes subnet identity currently points at one repo, but the company-level
    # activity lives across the chutesai GitHub owner.
    64: {
        "replace": True,
        "targets": [
            {"kind": "owner", "url": "https://github.com/chutesai"},
        ],
    },
}
