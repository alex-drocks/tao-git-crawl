from __future__ import annotations

import math
from collections.abc import Iterable

from git_crawl.path_classification import classify_path

from .models import CreditExclusion

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

# Skipped-activity reason for rows a reviewed registry entry marks as not the subnet team's own work.
REGISTRY_EXCLUSION_CLASS = "registry exclusion"

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
    ".bak",
    ".bin",
    ".blend",
    ".bz2",
    ".cif",
    ".ckpt",
    ".csv",
    ".dae",
    ".dat",
    ".db",
    ".fa",
    ".fasta",
    ".fastq",
    ".fbx",
    ".feather",
    ".flac",
    ".gif",
    ".glb",
    ".gltf",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".log",
    ".md5",
    ".mol2",
    ".mov",
    ".mp3",
    ".mp4",
    ".mtl",
    ".npy",
    ".npz",
    ".obj",
    ".onnx",
    ".orig",
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
    ".rej",
    ".safetensors",
    ".sdf",
    ".sha1",
    ".sha256",
    ".sha512",
    ".sqlite",
    ".stderr",
    ".stdout",
    ".stl",
    ".tar",
    ".tar.gz",
    ".tsv",
    ".wav",
    ".webp",
    ".xz",
    ".zip",
)

_CHECKSUM_FILENAMES = {"checksums", "checksums.txt", "md5sums", "sha1sums", "sha256sums", "sha512sums"}

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
    "capture",
    "captures",
    "corpus",
    "data",
    "dataset",
    "datasets",
    "evidence",
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

# Directories of committed run captures (exit codes, pids, timestamps, raw output). Only authored files inside them,
# meaning source code, prose docs, and code-like formats git-crawl does not list as source, receive credit.
_EVIDENCE_PATH_SEGMENTS = {"capture", "captures", "evidence"}
_AUTHORED_EVIDENCE_SUFFIXES = (
    ".adoc", ".cairo", ".cfg", ".circom", ".cu", ".cuh", ".dart", ".diff", ".ex", ".exs", ".gql", ".glsl", ".graphql",
    ".hcl", ".hs", ".ini", ".jl", ".lean", ".md", ".mdx", ".metal", ".ml", ".move", ".nix", ".patch", ".php", ".pl",
    ".proto", ".ps1", ".r", ".rb", ".rst", ".tf", ".thrift", ".toml", ".vy", ".wgsl", ".zig",
)
_COVERAGE_SOURCE_SUFFIXES = (".py", ".js", ".mjs", ".cjs", ".ts", ".go", ".rs", ".rb", ".sh")


def noise_change_class(row: dict[str, object], exclusions: Iterable[CreditExclusion] = ()) -> str | None:
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
    if _is_artifact_or_data_path(path) or _is_evidence_capture(path):
        return "artifact/data"
    if matching_exclusion(row, exclusions) is not None:
        return REGISTRY_EXCLUSION_CLASS
    return None


def is_noise_change(row: dict[str, object], exclusions: Iterable[CreditExclusion] = ()) -> bool:
    return noise_change_class(row, exclusions) is not None


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


def is_credited_change(row: dict[str, object], exclusions: Iterable[CreditExclusion] = ()) -> bool:
    return has_valid_churn_metrics(row) and not is_noise_change(row, exclusions)


def matching_exclusion(row: dict[str, object], exclusions: Iterable[CreditExclusion]) -> CreditExclusion | None:
    """Return the first reviewed exclusion that covers this file-change row."""
    repo = row.get("repo")
    if not isinstance(repo, str) or not repo.strip():
        return None
    repo_key = repo.strip().lower()
    path = _row_path(row).replace("\\", "/").lstrip("/")
    sha = row.get("sha")
    if not isinstance(sha, str) or not sha.strip():
        sha = row.get("commit_sha")
    sha_key = sha.strip().lower() if isinstance(sha, str) else ""
    for exclusion in exclusions:
        if exclusion.repo.lower() != repo_key:
            continue
        if exclusion.commit is not None and not (sha_key and sha_key.startswith(exclusion.commit.lower())):
            continue
        if exclusion.path is not None and not _path_is_within(path, exclusion.path):
            continue
        return exclusion
    return None


def credit_exclusions_from_document(document: object, netuid: int | None = None) -> tuple[CreditExclusion, ...]:
    """Read ``credit_exclusions`` from a written ``subnet-targets.json`` payload, skipping malformed entries."""
    if not isinstance(document, dict):
        return ()
    raw_items = document.get("credit_exclusions")
    if not isinstance(raw_items, list):
        return ()
    exclusions: list[CreditExclusion] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        if netuid is not None and item.get("netuid") != netuid:
            continue
        repo, reason = item.get("repo"), item.get("reason")
        path, commit = item.get("path"), item.get("commit")
        if not isinstance(repo, str) or not repo.strip() or not isinstance(reason, str):
            continue
        if path is not None and not isinstance(path, str):
            continue
        if commit is not None and not isinstance(commit, str):
            continue
        if path is None and commit is None:
            continue
        exclusions.append(CreditExclusion(repo=repo.strip(), reason=reason, path=path, commit=commit))
    return tuple(exclusions)


def _path_is_within(path: str, scope: str) -> bool:
    scope = scope.replace("\\", "/").lstrip("/")
    if scope.endswith("/"):
        return path.startswith(scope)
    return path == scope or path.startswith(f"{scope}/")


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
        (basename.startswith("coverage.") and not basename.endswith(_COVERAGE_SOURCE_SUFFIXES))
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
    if basename in _CHECKSUM_FILENAMES:
        return True
    segments = set(_path_segments(path)[:-1])
    return bool(segments & _DATA_PATH_SEGMENTS) and _has_any_suffix(path, _DATA_PATH_SUFFIXES)


def _is_evidence_capture(path: str) -> bool:
    if not path or not set(_path_segments(path)[:-1]) & _EVIDENCE_PATH_SEGMENTS:
        return False
    if _basename(path).endswith(_AUTHORED_EVIDENCE_SUFFIXES):
        return False
    return classify_path(path).path_class != "source"
