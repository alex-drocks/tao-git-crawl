from __future__ import annotations

import math

CODE_ACTIVITY_EXCLUDED_CHURN_CLASSES = (
    "binary",
    "lockfile",
    "generated",
    "vendored",
    "spec/schema-like",
    "artifact/data",
)

_PATH_CLASS_ALIASES = {
    **{path_class: path_class for path_class in CODE_ACTIVITY_EXCLUDED_CHURN_CLASSES},
    "spec": "spec/schema-like",
    "asset": "artifact/data",
    "assets": "artifact/data",
    "artifact": "artifact/data",
    "data": "artifact/data",
    "dataset": "artifact/data",
    "datasets": "artifact/data",
}

_GENERATED_REPORT_FILENAMES = {
    ".secrets.baseline",
    "coverage-final.json",
    "coverage.json",
    "coverage.xml",
    "junit.xml",
    "lcov.info",
    "test-results.json",
    "test-results.xml",
}

_ARTIFACT_DATA_SUFFIXES = (
    ".7z",
    ".a3m",
    ".avi",
    ".bin",
    ".blend",
    ".bz2",
    ".cif",
    ".ckpt",
    ".csv",
    ".dae",
    ".db",
    ".feather",
    ".fbx",
    ".flac",
    ".gif",
    ".glb",
    ".gltf",
    ".gz",
    ".ico",
    ".jpg",
    ".jpeg",
    ".mol2",
    ".mov",
    ".mp3",
    ".mp4",
    ".npy",
    ".npz",
    ".obj",
    ".onnx",
    ".parquet",
    ".pdb",
    ".pdf",
    ".pickle",
    ".pkl",
    ".ply",
    ".png",
    ".pt",
    ".pth",
    ".rar",
    ".safetensors",
    ".sdf",
    ".sqlite",
    ".stl",
    ".tar",
    ".tar.gz",
    ".tsv",
    ".wav",
    ".webp",
    ".xz",
    ".zip",
)

_JSON_CONFIG_FILENAMES = {
    "biome.json",
    "bunfig.json",
    "composer.json",
    "deno.json",
    "devcontainer.json",
    "jsconfig.json",
    "package.json",
    "pyrightconfig.json",
    "tsconfig.json",
    "typedoc.json",
    "wrangler.json",
}

_DATA_PATH_SEGMENTS = {
    "asset",
    "assets",
    "benchmark",
    "benchmarks",
    "data",
    "dataset",
    "datasets",
    "fixture",
    "fixtures",
    "logs",
    "msa_files",
    "public",
    "report",
    "reports",
    "results",
    "terrain_cache",
}

_DATA_PATH_SUFFIXES = (".json", ".jsonl", ".ndjson", ".txt", ".xml", ".yaml", ".yml")


def noise_change_class(row: dict[str, object]) -> str | None:
    path_class = str(row.get("path_class", "")).strip().lower()
    path_class_alias = _PATH_CLASS_ALIASES.get(path_class)
    if path_class_alias is not None:
        return path_class_alias
    if row.get("is_lockfile") is True:
        return "lockfile"
    if row.get("is_binary") is True:
        return "binary"
    if row.get("is_generated_like") is True:
        return "generated"
    path = _row_path(row)
    if _is_generated_report(path):
        return "generated"
    if _is_artifact_or_data_path(path):
        return "artifact/data"
    return None


def is_noise_change(row: dict[str, object]) -> bool:
    return noise_change_class(row) is not None


def has_valid_churn_metrics(row: dict[str, object]) -> bool:
    """Reject malformed churn values before a file-change row can receive credit."""
    for key in ("additions", "lines_added", "deletions", "lines_deleted"):
        if key not in row or row[key] is None:
            continue
        value = row[key]
        if isinstance(value, bool) or not isinstance(value, int | float):
            return False
        if (isinstance(value, float) and not math.isfinite(value)) or value < 0:
            return False
    return True


def is_credited_change(row: dict[str, object]) -> bool:
    return has_valid_churn_metrics(row) and not is_noise_change(row)


def _row_path(row: dict[str, object]) -> str:
    path = row.get("path")
    if not isinstance(path, str) or not path.strip():
        path = row.get("filename")
    return path.strip() if isinstance(path, str) else ""


def _normalized_path(path: str) -> str:
    return path.replace("\\", "/").strip().lower()


def _path_segments(path: str) -> list[str]:
    return [segment for segment in _normalized_path(path).strip("/").split("/") if segment]


def _basename(path: str) -> str:
    segments = _path_segments(path)
    return segments[-1] if segments else ""


def _has_any_suffix(path: str, suffixes: tuple[str, ...]) -> bool:
    normalized = _normalized_path(path)
    return any(normalized.endswith(suffix) for suffix in suffixes)


def _is_generated_report(path: str) -> bool:
    basename = _basename(path)
    if basename in _GENERATED_REPORT_FILENAMES:
        return True
    if ".bak." in basename:
        return True
    return (
        basename.startswith("coverage.")
        or basename.startswith("junit-")
        or basename.startswith("test-results.")
        or basename.endswith("_test_results.txt")
    )


def _is_artifact_or_data_path(path: str) -> bool:
    if not path:
        return False
    basename = _basename(path)
    if _has_any_suffix(path, _ARTIFACT_DATA_SUFFIXES):
        return True
    if basename.endswith((".json", ".jsonl", ".ndjson")) and basename not in _JSON_CONFIG_FILENAMES:
        return True
    segments = set(_path_segments(path)[:-1])
    return bool(segments & _DATA_PATH_SEGMENTS) and _has_any_suffix(path, _DATA_PATH_SUFFIXES)
