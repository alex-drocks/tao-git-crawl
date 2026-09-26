"""Atomic file replacement for outputs the API can read while a crawl is running."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path


def write_json_atomic(path: Path, payload: object) -> None:
    """Write ``payload`` as JSON, replacing ``path`` only once the new file is complete."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    try:
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
