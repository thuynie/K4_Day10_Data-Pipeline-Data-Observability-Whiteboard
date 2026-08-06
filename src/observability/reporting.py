"""Markdown reporting for evaluation and observability artifacts.

Owner: Dương Tiến Dũng (2A202602020)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.utils import write_text


METRIC_NAMES = (
    "retrieval_hit_rate",
    "mean_token_f1",
    "judge_accuracy",
    "mean_judge_score",
)


def _display(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, bool):
        return "PASS" if value else "FAIL"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _quality_status(payload: dict[str, Any]) -> str:
    return "PASS" if payload.get("success") else "FAIL"


def _freshness_status(payload: dict[str, Any]) -> str:
    return str(payload.get("status") or ("fresh" if payload.get("is_fresh") else "stale")).upper()


def _quality_table(quality: dict[str, Any]) -> list[str]:
    lines = [
        "| Check | Dimension | Observed | Expectation | Result |",
        "|---|---|---:|---|:---:|",
    ]
    for check in quality.get("checks", []):
        lines.append(
            f"| {_display(check.get('name'))} | {_display(check.get('dimension'))} "
            f"| {_display(check.get('observed'))} | {_display(check.get('expectation'))} "
            f"| {'PASS' if check.get('success') else 'FAIL'} |"
        )
    if not quality.get("checks"):
        lines.append("| N/A | N/A | N/A | No check details supplied | N/A |")
    return lines


def generate_phase1_report(
    report_path: str | Path,
    source_summary: dict[str, Any],
    metrics: dict[str, Any],
    quality: dict[str, Any],
    freshness: dict[str, Any],
) -> None:
    """Write a baseline report whose values come only from supplied artifacts."""
    source_rows = [
        ("Source", source_summary.get("source_api", source_summary.get("source", "N/A"))),
        ("Query", source_summary.get("source_query", source_summary.get("query", "N/A"))),
        ("Filter", source_summary.get("source_filter", source_summary.get("filter", "N/A"))),
        ("Raw records", source_summary.get("raw_records", source_summary.get("records_parsed", "N/A"))),
        ("Clean records", source_summary.get("clean_records", source_summary.get("record_count", "N/A"))),
    ]
    lines = [
        "# Baseline Pipeline Report",
        "",
        "## Source and dataset",
        "",
        "| Item | Value |",
        "|---|---|",
        *[f"| {label} | {_display(value)} |" for label, value in source_rows],
        "",
        "## Evaluation metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
        *[f"| `{name}` | {_display(metrics.get(name))} |" for name in METRIC_NAMES],
        f"| Samples | {_display(metrics.get('samples'))} |",
        f"| Ragas | {_display(metrics.get('ragas'))} |",
        "",
        "## Data quality",
        "",
        f"Overall status: **{_quality_status(quality)}** "
        f"({quality.get('checks_passed', 0)} passed, {quality.get('checks_failed', 0)} failed).",
        "",
        *_quality_table(quality),
        "",
        "## Freshness",
        "",
        "| Signal | Value |",
        "|---|---:|",
        f"| Status | **{_freshness_status(freshness)}** |",
        f"| Latest publication | {_display(freshness.get('latest_published'))} |",
        f"| Oldest publication | {_display(freshness.get('oldest_published'))} |",
        f"| Stale rows | {_display(freshness.get('stale_rows'))} / {_display(freshness.get('total_rows'))} |",
        f"| Threshold (days) | {_display(freshness.get('threshold_days'))} |",
        "",
        "## Interpretation",
        "",
        (
            "The baseline is ready for comparison when evaluation artifacts exist, all quality checks pass, "
            "and freshness is FRESH. Any failed signal above must be investigated before attributing later "
            "metric changes to corruption."
        ),
        "",
    ]
    write_text(Path(report_path), "\n".join(lines))


def generate_corruption_report(
    report_path: str | Path,
    baseline_metrics: dict[str, Any],
    corrupted_metrics: dict[str, Any],
    repaired_metrics: dict[str, Any],
    corrupted_quality: dict[str, Any],
    repaired_quality: dict[str, Any],
    corrupted_freshness: dict[str, Any],
    repaired_freshness: dict[str, Any],
) -> None:
    """Write a baseline/corrupted/repaired comparison with explicit deltas."""
    lines = [
        "# Corruption and Repair Comparison Report",
        "",
        "## Evaluation comparison",
        "",
        "| Metric | Baseline | Corrupted | Repaired | Corruption delta | Repair delta |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in METRIC_NAMES:
        baseline = baseline_metrics.get(name)
        corrupted = corrupted_metrics.get(name)
        repaired = repaired_metrics.get(name)
        corruption_delta = corrupted - baseline if isinstance(baseline, (int, float)) and isinstance(corrupted, (int, float)) else None
        repair_delta = repaired - corrupted if isinstance(repaired, (int, float)) and isinstance(corrupted, (int, float)) else None
        lines.append(
            f"| `{name}` | {_display(baseline)} | {_display(corrupted)} | {_display(repaired)} "
            f"| {_display(corruption_delta)} | {_display(repair_delta)} |"
        )

    lines.extend(
        [
            "",
            "## Observability comparison",
            "",
            "| Signal | Corrupted | Repaired |",
            "|---|---:|---:|",
            f"| Quality status | **{_quality_status(corrupted_quality)}** | **{_quality_status(repaired_quality)}** |",
            f"| Failed quality checks | {_display(corrupted_quality.get('checks_failed'))} | {_display(repaired_quality.get('checks_failed'))} |",
            f"| Freshness status | **{_freshness_status(corrupted_freshness)}** | **{_freshness_status(repaired_freshness)}** |",
            f"| Stale rows | {_display(corrupted_freshness.get('stale_rows'))} | {_display(repaired_freshness.get('stale_rows'))} |",
            f"| Total rows | {_display(corrupted_freshness.get('total_rows'))} | {_display(repaired_freshness.get('total_rows'))} |",
            "",
            "## Evidence-based interpretation",
            "",
        ]
    )

    regressed = [
        name for name in METRIC_NAMES
        if isinstance(baseline_metrics.get(name), (int, float))
        and isinstance(corrupted_metrics.get(name), (int, float))
        and corrupted_metrics[name] < baseline_metrics[name]
    ]
    recovered = [
        name for name in METRIC_NAMES
        if isinstance(corrupted_metrics.get(name), (int, float))
        and isinstance(repaired_metrics.get(name), (int, float))
        and repaired_metrics[name] > corrupted_metrics[name]
    ]
    lines.extend(
        [
            f"- Metrics that decreased after corruption: {_display(', '.join(regressed) if regressed else 'none observed')}.",
            f"- Metrics that improved after repair: {_display(', '.join(recovered) if recovered else 'none observed')}.",
            (
                f"- Quality changed from {_quality_status(corrupted_quality)} after corruption to "
                f"{_quality_status(repaired_quality)} after repair; freshness changed from "
                f"{_freshness_status(corrupted_freshness)} to {_freshness_status(repaired_freshness)}."
            ),
            "",
            "A causal impact should only be claimed for changes supported by both the generated artifacts and the table above.",
            "",
        ]
    )
    write_text(Path(report_path), "\n".join(lines))
