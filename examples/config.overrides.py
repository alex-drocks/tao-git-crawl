"""Example manual target overrides for tao-git-crawl.

Copy this file to your own config.py and edit it for the subnet/company mappings
you trust. Only load config files you control; Python configs execute as local code.
"""

# Keep exact repository URLs as repository crawls unless a subnet override says
# otherwise. Set to "owner" if you want every exact repo URL to be promoted to
# its GitHub owner by default.
DEFAULT_REPOSITORY_POLICY = "repository"

# Subnet 64 (Chutes) is now baked into the default config. You only need to add
# overrides here for other subnets, or to change the default policy.
SUBNET_OVERRIDES = {}
