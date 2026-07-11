# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

# Always install git — git-crawl clones bare repositories at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Build arguments let operators pin the git-crawl source without editing files.
ARG GIT_CRAWL_URL="git+https://github.com/alex-drocks/git-crawl.git@v0.3.2"
ARG INSTALL_EXTRAS="[chain]"

# Install git-crawl first (from GitHub) so tao-git-crawl's dependency is met.
# If the operator already cloned tao-git-crawl locally, we still reinstall in
# editable mode below so the working tree is live.
RUN pip install --no-cache-dir \
    "git-crawl @ ${GIT_CRAWL_URL}"

# Copy the package and install in editable mode so code changes are reflected
# on rebuild without layer invalidation from git-crawl.
COPY pyproject.toml README.md ./
COPY registry/ ./registry/
COPY tao_git_crawl/ ./tao_git_crawl/
RUN pip install --no-cache-dir -e ".${INSTALL_EXTRAS}"

# Create mount points for persistent data.
RUN mkdir -p /data/output /data/cache /data/state /data/logs

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Default interval: 86400 s = 24 h.
ENV TAO_CRAWL_INTERVAL_SECONDS=86400
ENV TAO_CRAWL_NETWORK=finney
ENV TAO_CRAWL_OUTPUT_DIR=/data/output
ENV TAO_CRAWL_CACHE_DIR=/data/cache
ENV TAO_CRAWL_INCREMENTAL=false
ENV TAO_CRAWL_WORKERS=4
ENV TAO_CRAWL_WINDOW_DAYS=365
ENV TAO_CRAWL_COMMIT_CHANGES_FILTRATION_LEVEL=source_like
ENV TAO_CRAWL_LOG_DIR=/data/logs

ENTRYPOINT ["python", "-m", "tao_git_crawl.scheduler"]
