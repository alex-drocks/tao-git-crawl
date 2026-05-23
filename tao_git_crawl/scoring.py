from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .activity_filter import is_noise_change
from .resolver import ResolutionDocument

SCORE_SCHEMA_VERSION = "tao-git-crawl-score-v2"
GIT_CRAWL_ACTIVITY_SCHEMA_VERSION = "git-crawl-activity-v1"

SCORE_WEIGHTS = {
    "active_days": 0.40,
    "credited_file_changes": 0.20,
    "avg_credited_commits_per_active_day": 0.15,
    "distinct_contributors": 0.15,
    "credited_lines_added": 0.10,
}

RAW_METRICS = tuple(SCORE_WEIGHTS) + ("repos_crawled",)
ZERO_METRICS = {metric: 0.0 for metric in RAW_METRICS}


@dataclass(frozen=True)
class SubnetScoreInput:
    netuid: int
    status: str
    raw_metrics: dict[str, float]
    reason: str | None = None


@dataclass(frozen=True)
class CrawlReportState:
    succeeded: set[int]
    failed_reasons: dict[int, str]
    inaccessible_reasons: dict[int, list[str]]


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
    report_state = _crawl_report_state(output_path)
    inputs = [
        _score_input_for_netuid(document, output_path, netuid, report_state=report_state)
        for netuid in document.netuids
    ]
    metric_maxima = _metric_maxima(inputs)
    raw_scores = [_score_input(input_item, metric_maxima) for input_item in inputs]
    scores = _with_final_scores_ranks_and_percentiles(raw_scores)
    scoring_window = _scoring_window_from_outputs(inputs, output_path)
    for score in scores:
        score["scoring_window"] = dict(scoring_window)
    return {
        "schema_version": SCORE_SCHEMA_VERSION,
        "target": document.target_label,
        "scoring_window": scoring_window,
        "metric_source": (
            "git-crawl output files and path classification; file_changes.jsonl is preferred so binary, lockfile, "
            "generated, vendored, spec, and artifact/data churn are excluded before scoring"
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


def _scoring_window_from_outputs(inputs: list[SubnetScoreInput], output_dir: Path) -> dict[str, object]:
    since_values: set[str] = set()
    until_values: set[str] = set()
    summary_count = 0
    missing_since_count = 0
    missing_until_count = 0
    for input_item in inputs:
        if input_item.status not in {"scored", "no_crawlable_repositories"}:
            continue
        crawl_dir = output_dir / "subnets" / str(input_item.netuid) / "crawl"
        summary = _read_json_optional(crawl_dir / "summary.json")
        if not isinstance(summary, dict):
            continue
        summary_count += 1
        activity = _read_json_optional(crawl_dir / "activity.json")
        activity_dict = activity if isinstance(activity, dict) else None
        history_since = _date_string(_activity_metadata(summary, activity_dict, "history_since"))
        history_until = _date_string(_activity_metadata(summary, activity_dict, "history_until"))
        if history_since:
            since_values.add(history_since)
        else:
            missing_since_count += 1
        if history_until:
            until_values.add(history_until)
        else:
            missing_until_count += 1

    source = _scoring_window_source(
        summary_count,
        since_values,
        until_values,
        missing_since_count=missing_since_count,
        missing_until_count=missing_until_count,
    )
    score_since = _single_value(since_values) if source == "crawl_history" else None
    explicit_until = _single_value(until_values) if source == "crawl_history" else None
    score_until = explicit_until if explicit_until is not None else None
    if score_since is not None and score_until is None:
        score_until = _today_utc().isoformat()

    return {
        "scoring_window_days": _days_between_dates(score_since, score_until),
        "score_since": score_since,
        "score_until": score_until,
        "source": source,
    }


def _score_input_for_netuid(
    document: ResolutionDocument,
    output_dir: Path,
    netuid: int,
    *,
    report_state: CrawlReportState | None,
) -> SubnetScoreInput:
    subnet_document = document.for_netuid(netuid)
    if subnet_document.unresolved and not subnet_document.targets:
        unresolved = subnet_document.unresolved[0]
        return SubnetScoreInput(
            netuid=netuid,
            status="unresolved",
            reason=unresolved.reason,
            raw_metrics=dict(ZERO_METRICS),
        )

    if report_state is not None and netuid not in report_state.succeeded:
        failed_reason = report_state.failed_reasons.get(netuid)
        if failed_reason:
            return SubnetScoreInput(
                netuid=netuid,
                status="crawl_failed",
                reason=failed_reason,
                raw_metrics=dict(ZERO_METRICS),
            )
        inaccessible_reasons = report_state.inaccessible_reasons.get(netuid)
        if inaccessible_reasons:
            return SubnetScoreInput(
                netuid=netuid,
                status="crawl_failed",
                reason=f"GitHub target inaccessible: {'; '.join(inaccessible_reasons[:3])}",
                raw_metrics=dict(ZERO_METRICS),
            )
        return SubnetScoreInput(
            netuid=netuid,
            status="no_crawl",
            reason="not crawled in current report",
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

    activity_metrics = _credited_metrics_from_activity_json(subnet_dir / "crawl", summary)
    if activity_metrics is not None:
        return activity_metrics

    fallback_credited_totals = _mapping(summary.get("source_like_totals"))
    credited_commits = _number(fallback_credited_totals.get("commits"))
    active_days = _number(fallback_credited_totals.get("active_days"))
    distinct_contributors = _number_from_keys(
        fallback_credited_totals,
        "distinct_contributors",
        "distinct_contributor_keys",
    )
    has_credited_activity = any(
        value > 0
        for value in (
            credited_commits,
            _number(fallback_credited_totals.get("file_changes")),
            _number(fallback_credited_totals.get("lines_added")),
            active_days,
            distinct_contributors,
        )
    )

    avg_commits_per_active_day = credited_commits / active_days if active_days > 0 else 0.0
    return {
        "avg_credited_commits_per_active_day": avg_commits_per_active_day,
        "credited_file_changes": _number(fallback_credited_totals.get("file_changes")),
        "active_days": active_days,
        "credited_lines_added": _number(fallback_credited_totals.get("lines_added")),
        "repos_crawled": _summary_repo_count_with_credited_activity(summary, has_credited_activity),
        "distinct_contributors": distinct_contributors,
    }


def _credited_metrics_from_activity_json(crawl_dir: Path, summary: dict[str, object]) -> dict[str, float] | None:
    activity = _read_json_optional(crawl_dir / "activity.json")
    if not isinstance(activity, dict) or activity.get("schema_version") != GIT_CRAWL_ACTIVITY_SCHEMA_VERSION:
        return None

    totals = _mapping(activity.get("totals"))
    credited_commits = _number(totals.get("commits"))
    active_days = _number(totals.get("active_days"))
    credited_file_changes = _number(totals.get("file_changes"))
    credited_lines_added = _number(totals.get("lines_added"))
    distinct_contributors = _number(totals.get("distinct_contributors"))
    has_credited_activity = any(
        value > 0
        for value in (
            credited_commits,
            credited_file_changes,
            credited_lines_added,
            active_days,
            distinct_contributors,
        )
    )
    credited_repo_count = _credited_repo_count_from_file_changes(crawl_dir)
    if credited_repo_count is None:
        credited_repo_count = _credited_repo_count_from_repo_days(crawl_dir)
    return {
        "avg_credited_commits_per_active_day": credited_commits / active_days if active_days > 0 else 0.0,
        "credited_file_changes": credited_file_changes,
        "active_days": active_days,
        "credited_lines_added": credited_lines_added,
        "repos_crawled": _repo_count_with_credited_activity(summary, has_credited_activity, credited_repo_count),
        "distinct_contributors": distinct_contributors,
    }


def _credited_metrics_from_jsonl(crawl_dir: Path, summary: dict[str, object]) -> dict[str, float] | None:
    commits_path = crawl_dir / "commits.jsonl"
    file_changes_path = crawl_dir / "file_changes.jsonl"
    if not commits_path.exists() or not file_changes_path.exists():
        return None

    credited_commit_keys: set[tuple[str, str]] = set()
    credited_repos: set[str] = set()
    credited_file_changes = 0
    credited_lines_added = 0.0

    with file_changes_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or is_noise_change(row):
                continue
            credited_file_changes += 1
            credited_lines_added += _number_from_keys(row, "additions", "lines_added")
            repo = _text_key(row.get("repo")).lower()
            if repo:
                credited_repos.add(repo)
            commit_key = _commit_key(row)
            if commit_key is not None:
                credited_commit_keys.add(commit_key)

    credited_commits = 0
    active_days: set[str] = set()
    contributors: set[str] = set()
    seen_commits: set[tuple[str, str]] = set()
    with commits_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                continue
            commit_key = _commit_key(row)
            if commit_key is None or commit_key not in credited_commit_keys or commit_key in seen_commits:
                continue
            seen_commits.add(commit_key)
            credited_commits += 1
            authored_day = _authored_day(row.get("authored_at"))
            if authored_day:
                active_days.add(authored_day)
            contributors.add(_contributor_key(row))

    active_day_count = float(len(active_days))
    has_credited_activity = credited_file_changes > 0 or credited_commits > 0 or credited_lines_added > 0
    return {
        "avg_credited_commits_per_active_day": credited_commits / active_day_count if active_day_count > 0 else 0.0,
        "credited_file_changes": float(credited_file_changes),
        "active_days": active_day_count,
        "credited_lines_added": credited_lines_added,
        "repos_crawled": _repo_count_with_credited_activity(
            summary,
            has_credited_activity,
            float(len(credited_repos)) if credited_repos else None,
        ),
        "distinct_contributors": float(len(contributors)),
    }


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


def _crawl_report_state(output_dir: Path) -> CrawlReportState | None:
    report = _read_json_optional(output_dir / "crawl-report.json")
    if not isinstance(report, dict):
        return None

    succeeded = _netuid_set(report.get("succeeded"))
    failed_reasons = _netuid_reasons(report.get("failed"))
    inaccessible_reasons: dict[int, list[str]] = {}
    for item in _object_rows(report.get("skipped_inaccessible")):
        netuid = _row_netuid(item)
        if netuid is None:
            continue
        reason = item.get("reason")
        inaccessible_reasons.setdefault(netuid, []).append(str(reason) if reason is not None else "inaccessible")

    return CrawlReportState(
        succeeded=succeeded,
        failed_reasons=failed_reasons,
        inaccessible_reasons=inaccessible_reasons,
    )


def _netuid_set(value: object) -> set[int]:
    netuids: set[int] = set()
    for item in _object_rows(value):
        netuid = _row_netuid(item)
        if netuid is not None:
            netuids.add(netuid)
    return netuids


def _netuid_reasons(value: object) -> dict[int, str]:
    reasons: dict[int, str] = {}
    for item in _object_rows(value):
        netuid = _row_netuid(item)
        if netuid is None:
            continue
        reason = item.get("reason")
        reasons[netuid] = str(reason) if reason is not None else "crawl failed"
    return reasons


def _object_rows(value: object) -> list[dict[str, object]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _row_netuid(row: dict[str, object]) -> int | None:
    value = row.get("netuid")
    if isinstance(value, bool):
        return None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


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


def _today_utc() -> date:
    return datetime.now(UTC).date()


def _activity_metadata(
    summary: dict[str, object],
    upstream_activity: dict[str, object] | None,
    key: str,
) -> object:
    if upstream_activity is not None and upstream_activity.get(key) is not None:
        return upstream_activity.get(key)
    return summary.get(key)


def _single_value(values: set[str]) -> str | None:
    if len(values) != 1:
        return None
    return next(iter(values))


def _scoring_window_source(
    summary_count: int,
    since_values: set[str],
    until_values: set[str],
    *,
    missing_since_count: int,
    missing_until_count: int,
) -> str:
    if summary_count <= 0:
        return "no_crawl_summary"
    has_mixed_until = len(until_values) > 1 or (bool(until_values) and missing_until_count > 0)
    if missing_since_count > 0 or len(since_values) != 1 or has_mixed_until:
        return "mixed_crawl_history"
    return "crawl_history"


def _date_string(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        timestamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            return date.fromisoformat(text[:10]).isoformat()
        except ValueError:
            return None
    if timestamp.tzinfo is not None and timestamp.utcoffset() is not None:
        timestamp = timestamp.astimezone(UTC)
    return timestamp.date().isoformat()


def _days_between_dates(since: str | None, until: str | None) -> int | None:
    if since is None or until is None:
        return None
    try:
        days = (date.fromisoformat(until) - date.fromisoformat(since)).days
    except ValueError:
        return None
    return days if days >= 0 else None


def _credited_repo_count_from_file_changes(crawl_dir: Path) -> float | None:
    file_changes_path = crawl_dir / "file_changes.jsonl"
    if not file_changes_path.exists():
        return None

    credited_repos: set[str] = set()
    with file_changes_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or is_noise_change(row):
                continue
            repo = _text_key(row.get("repo")).lower()
            if repo:
                credited_repos.add(repo)
    return float(len(credited_repos)) if credited_repos else None


def _credited_repo_count_from_repo_days(crawl_dir: Path) -> float | None:
    repo_days_path = crawl_dir / "repo_days.jsonl"
    if not repo_days_path.exists():
        return None

    credited_repos: set[str] = set()
    with repo_days_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                continue
            repo = _text_key(row.get("repo")).lower()
            if repo:
                credited_repos.add(repo)
    return float(len(credited_repos)) if credited_repos else None


def _repo_count_with_credited_activity(
    summary: dict[str, object],
    has_credited_activity: bool,
    credited_repo_count: float | None,
) -> float:
    if not has_credited_activity:
        return 0.0
    if credited_repo_count is not None:
        return credited_repo_count
    return _summary_repo_count_with_credited_activity(summary, has_credited_activity)


def _summary_repo_count_with_credited_activity(summary: dict[str, object], has_credited_activity: bool) -> float:
    if not has_credited_activity:
        return 0.0
    return _number(_mapping(summary.get("repositories")).get("crawled"))


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


def _number_from_keys(values: dict[str, Any], *keys: str) -> float:
    for key in keys:
        if key in values:
            return _number(values.get(key))
    return 0.0


def _commit_key(row: dict[str, object]) -> tuple[str, str] | None:
    repo = _text_key(row.get("repo"))
    sha = _text_key(row.get("sha"))
    if not sha:
        sha = _text_key(row.get("commit_sha"))
    if not repo or not sha:
        return None
    return repo, sha


def _text_key(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _authored_day(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        authored_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if authored_at.tzinfo is None or authored_at.utcoffset() is None:
            authored_at = authored_at.replace(tzinfo=UTC)
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
