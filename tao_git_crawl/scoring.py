from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .resolver import ResolutionDocument

SCORE_SCHEMA_VERSION = "tao-git-crawl-score-v2"

SCORE_WEIGHTS = {
    "avg_credited_commits_per_active_day": 0.25,
    "credited_file_changes": 0.20,
    "active_days": 0.20,
    "credited_lines_added": 0.15,
    "repos_crawled": 0.10,
    "distinct_contributors": 0.10,
}

ZERO_METRICS = {metric: 0.0 for metric in SCORE_WEIGHTS}


@dataclass(frozen=True)
class SubnetScoreInput:
    netuid: int
    status: str
    raw_metrics: dict[str, float]
    reason: str | None = None


def write_score_outputs(document: ResolutionDocument, output_dir: str | Path) -> list[Path]:
    output_path = Path(output_dir)
    score_document = build_score_document(document, output_path)
    written: list[Path] = []
    aggregate_path = output_path / "subnet-scores.json"
    _write_json(aggregate_path, score_document)
    written.append(aggregate_path)

    for score in score_document["scores"]:
        if not isinstance(score, dict):
            continue
        netuid = score.get("netuid")
        if not isinstance(netuid, int):
            continue
        subnet_path = output_path / "subnets" / str(netuid) / "score.json"
        _write_json(subnet_path, score)
        written.append(subnet_path)

    return written


def build_score_document(document: ResolutionDocument, output_dir: str | Path) -> dict[str, object]:
    output_path = Path(output_dir)
    inputs = [_score_input_for_netuid(document, output_path, netuid) for netuid in document.netuids]
    metric_maxima = _metric_maxima(inputs)
    raw_scores = [_score_input(input_item, metric_maxima) for input_item in inputs]
    scores = _with_final_scores_ranks_and_percentiles(raw_scores)
    return {
        "schema_version": SCORE_SCHEMA_VERSION,
        "target": document.target_label,
        "metric_source": (
            "git-crawl output files and path classification; file_changes.jsonl is preferred so binary, lockfile, "
            "generated, vendored, and spec churn are excluded before scoring"
        ),
        "normalization": {
            "metric_method": "global_max",
            "score_method": "max_weighted_composite_to_100",
            "rank_method": "competition_score_desc",
            "metric_maxima": metric_maxima,
        },
        "weights": SCORE_WEIGHTS,
        "scores": scores,
    }


def _score_input_for_netuid(document: ResolutionDocument, output_dir: Path, netuid: int) -> SubnetScoreInput:
    subnet_document = document.for_netuid(netuid)
    if subnet_document.unresolved and not subnet_document.targets:
        unresolved = subnet_document.unresolved[0]
        return SubnetScoreInput(
            netuid=netuid,
            status="unresolved",
            reason=unresolved.reason,
            raw_metrics=dict(ZERO_METRICS),
        )

    subnet_dir = output_dir / "subnets" / str(netuid)
    summary_path = subnet_dir / "crawl" / "summary.json"
    summary = _read_json_optional(summary_path)
    if not isinstance(summary, dict):
        return SubnetScoreInput(
            netuid=netuid,
            status="no_crawl",
            reason="crawl summary not found",
            raw_metrics=dict(ZERO_METRICS),
        )

    crawl_status = str(summary.get("status", ""))
    if crawl_status and crawl_status != "success":
        return SubnetScoreInput(
            netuid=netuid,
            status="crawl_failed",
            reason=f"crawl status {crawl_status}",
            raw_metrics=dict(ZERO_METRICS),
        )

    repositories = _mapping(summary.get("repositories"))
    repos_crawled = _number(repositories.get("crawled"))
    if repos_crawled <= 0:
        return SubnetScoreInput(
            netuid=netuid,
            status="no_crawlable_repositories",
            reason="no repositories crawled",
            raw_metrics=dict(ZERO_METRICS),
        )

    metrics = _credited_metrics_from_outputs(subnet_dir, summary)
    return SubnetScoreInput(netuid=netuid, status="scored", raw_metrics=metrics)


def _credited_metrics_from_outputs(subnet_dir: Path, summary: dict[str, object]) -> dict[str, float]:
    jsonl_metrics = _credited_metrics_from_jsonl(subnet_dir / "crawl", summary)
    if jsonl_metrics is not None:
        return jsonl_metrics

    repositories = _mapping(summary.get("repositories"))
    totals = _mapping(summary.get("totals"))
    fallback_credited_totals = _mapping(summary.get("source_like_totals")) or totals

    commit_metrics = _credited_commit_metrics_from_jsonl(subnet_dir / "crawl" / "commits.jsonl")
    if commit_metrics is None:
        credited_commits = _number(totals.get("commits"))
        active_days = _number(totals.get("active_days"))
        distinct_contributors = _number(totals.get("distinct_contributor_keys"))
    else:
        credited_commits = commit_metrics["credited_commits"]
        active_days = commit_metrics["active_days"]
        distinct_contributors = commit_metrics["distinct_contributors"]

    avg_commits_per_active_day = credited_commits / active_days if active_days > 0 else 0.0
    return {
        "avg_credited_commits_per_active_day": avg_commits_per_active_day,
        "credited_file_changes": _number(fallback_credited_totals.get("file_changes")),
        "active_days": active_days,
        "credited_lines_added": _number(fallback_credited_totals.get("lines_added")),
        "repos_crawled": _number(repositories.get("crawled")),
        "distinct_contributors": distinct_contributors,
    }


def _credited_metrics_from_jsonl(crawl_dir: Path, summary: dict[str, object]) -> dict[str, float] | None:
    commits_path = crawl_dir / "commits.jsonl"
    file_changes_path = crawl_dir / "file_changes.jsonl"
    if not commits_path.exists() or not file_changes_path.exists():
        return None

    credited_commit_keys: set[tuple[str, str]] = set()
    credited_file_changes = 0
    credited_lines_added = 0.0

    with file_changes_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or _is_noise_change(row):
                continue
            credited_file_changes += 1
            credited_lines_added += _number(row.get("additions"))
            repo = str(row.get("repo", ""))
            sha = str(row.get("sha", ""))
            if repo and sha:
                credited_commit_keys.add((repo, sha))

    credited_commits = 0
    active_days: set[str] = set()
    contributors: set[str] = set()
    with commits_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                continue
            repo = str(row.get("repo", ""))
            sha = str(row.get("sha", ""))
            if (repo, sha) not in credited_commit_keys:
                continue
            credited_commits += 1
            authored_day = _authored_day(row.get("authored_at"))
            if authored_day:
                active_days.add(authored_day)
            contributors.add(_contributor_key(row))

    active_day_count = float(len(active_days))
    return {
        "avg_credited_commits_per_active_day": credited_commits / active_day_count if active_day_count > 0 else 0.0,
        "credited_file_changes": float(credited_file_changes),
        "active_days": active_day_count,
        "credited_lines_added": credited_lines_added,
        "repos_crawled": _number(_mapping(summary.get("repositories")).get("crawled")),
        "distinct_contributors": float(len(contributors)),
    }


def _credited_commit_metrics_from_jsonl(path: Path) -> dict[str, float] | None:
    if not path.exists():
        return None

    credited_commits = 0
    active_days: set[str] = set()
    contributors: set[str] = set()

    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                continue
            if _number(row.get("files_changed")) <= 0:
                continue
            credited_commits += 1
            authored_day = _authored_day(row.get("authored_at"))
            if authored_day:
                active_days.add(authored_day)
            contributors.add(_contributor_key(row))

    return {
        "credited_commits": float(credited_commits),
        "active_days": float(len(active_days)),
        "distinct_contributors": float(len(contributors)),
    }


def _is_noise_change(row: dict[str, object]) -> bool:
    if row.get("is_binary") is True or row.get("is_generated_like") is True:
        return True
    return str(row.get("path_class", "")).lower() in {"binary", "lockfile", "generated", "spec", "vendored"}


def _score_input(input_item: SubnetScoreInput, metric_maxima: dict[str, float]) -> dict[str, object]:
    normalized_metrics = {
        metric: _normalize(input_item.raw_metrics.get(metric, 0.0), metric_maxima.get(metric, 0.0))
        for metric in SCORE_WEIGHTS
    }
    weighted_components = {
        metric: normalized_metrics[metric] * weight * 100
        for metric, weight in SCORE_WEIGHTS.items()
    }
    composite_score = sum(weighted_components.values()) if input_item.status == "scored" else 0.0
    payload: dict[str, object] = {
        "schema_version": SCORE_SCHEMA_VERSION,
        "netuid": input_item.netuid,
        "status": input_item.status,
        "score": 0.0,
        "composite_score": round(composite_score, 2),
        "rank": 0,
        "rank_total": 0,
        "percentile": 0.0,
        "raw_metrics": _rounded_metrics(input_item.raw_metrics),
        "normalized_metrics": _rounded_metrics(normalized_metrics),
        "weighted_components": _rounded_metrics(weighted_components),
        "weights": SCORE_WEIGHTS,
    }
    if input_item.reason:
        payload["reason"] = input_item.reason
    return payload


def _with_final_scores_ranks_and_percentiles(scores: list[dict[str, object]]) -> list[dict[str, object]]:
    max_composite = max((float(score["composite_score"]) for score in scores), default=0.0)
    for score in scores:
        composite_score = float(score["composite_score"])
        score["score"] = round((100 * composite_score) / max_composite, 2) if max_composite > 0 else 0.0

    total = len(scores)
    _apply_ranks(scores)
    if total <= 1:
        for score in scores:
            score["percentile"] = 100.0 if float(score["score"]) > 0 else 0.0
        return scores

    numeric_scores = [float(score["score"]) for score in scores]
    for score in scores:
        value = float(score["score"])
        lower_count = sum(1 for other in numeric_scores if other < value)
        score["percentile"] = round((100 * lower_count) / (total - 1), 2)
    return scores


def _apply_ranks(scores: list[dict[str, object]]) -> None:
    total = len(scores)
    ranked_scores = sorted(
        scores,
        key=lambda score: (-float(score["score"]), int(score["netuid"])),
    )
    previous_score: float | None = None
    current_rank = 0
    for position, score in enumerate(ranked_scores, start=1):
        score_value = float(score["score"])
        if previous_score is None or score_value != previous_score:
            current_rank = position
            previous_score = score_value
        score["rank"] = current_rank
        score["rank_total"] = total


def _metric_maxima(inputs: list[SubnetScoreInput]) -> dict[str, float]:
    return {
        metric: max((item.raw_metrics.get(metric, 0.0) for item in inputs), default=0.0)
        for metric in SCORE_WEIGHTS
    }


def _normalize(value: float, maximum: float) -> float:
    if maximum <= 0:
        return 0.0
    return max(value, 0.0) / maximum


def _rounded_metrics(metrics: dict[str, float]) -> dict[str, float]:
    return {metric: round(value, 4) for metric, value in metrics.items()}


def _read_json_optional(path: Path) -> object | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _number(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _authored_day(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        authored_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return authored_at.astimezone(UTC).date().isoformat()
    except ValueError:
        return value[:10] if len(value) >= 10 else None


def _contributor_key(row: dict[str, object]) -> str:
    login = row.get("author_login")
    if isinstance(login, str) and login.strip():
        return f"login:{login.strip().lower()}"
    email = row.get("author_email")
    if isinstance(email, str) and email.strip():
        return f"email:{email.strip().lower()}"
    name = row.get("author_name")
    if isinstance(name, str) and name.strip():
        return f"name:{name.strip()}"
    return "unknown"
