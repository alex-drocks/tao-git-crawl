from __future__ import annotations

CODE_ACTIVITY_EXCLUDED_CHURN_CLASSES = ("binary", "lockfile", "generated", "vendored", "spec/schema-like")

_EXCLUDED_PATH_CLASS_ALIASES = set(CODE_ACTIVITY_EXCLUDED_CHURN_CLASSES) | {"spec"}


def is_noise_change(row: dict[str, object]) -> bool:
    if row.get("is_binary") is True or row.get("is_generated_like") is True:
        return True
    return str(row.get("path_class", "")).strip().lower() in _EXCLUDED_PATH_CLASS_ALIASES
