from __future__ import annotations

CODE_ACTIVITY_EXCLUDED_CHURN_CLASSES = ("binary", "lockfile", "generated", "vendored", "spec/schema-like")

_EXCLUDED_PATH_CLASS_ALIASES = set(CODE_ACTIVITY_EXCLUDED_CHURN_CLASSES) | {"spec"}


def noise_change_class(row: dict[str, object]) -> str | None:
    path_class = str(row.get("path_class", "")).strip().lower()
    if path_class in _EXCLUDED_PATH_CLASS_ALIASES:
        return "spec/schema-like" if path_class == "spec" else path_class
    if row.get("is_lockfile") is True:
        return "lockfile"
    if row.get("is_binary") is True:
        return "binary"
    if row.get("is_generated_like") is True:
        return "generated"
    return None


def is_noise_change(row: dict[str, object]) -> bool:
    return noise_change_class(row) is not None
