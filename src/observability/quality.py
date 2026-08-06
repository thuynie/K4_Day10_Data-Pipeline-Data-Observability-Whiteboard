"""Data-quality and freshness signals for pipeline observability.

Owner: Dương Tiến Dũng (2A202602020)
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import re
from typing import Any

import pandas as pd

from core.config import Settings
from core.utils import write_json


MIN_SUMMARY_CHARS = 100
REQUIRED_COLUMNS = ("paper_id", "title", "summary", "published", "age_days")


def _safe_report_name(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value)).strip("._")
    return name or "quality_report"


def _check(name: str, dimension: str, success: bool, observed: Any, expectation: str) -> dict[str, Any]:
    return {
        "name": name,
        "dimension": dimension,
        "success": bool(success),
        "observed": observed,
        "expectation": expectation,
    }


def run_data_quality_checks(df: pd.DataFrame, settings: Settings, report_name: str) -> dict[str, Any]:
    """Evaluate completeness, uniqueness, validity and freshness checks.

    Every failed check remains in the artifact with its observed value.  This
    makes a corrupt dataset diagnosable instead of reducing the result to one
    opaque pass/fail flag.
    """
    row_count = int(len(df))
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    checks: list[dict[str, Any]] = [
        _check("row_count_positive", "volume", row_count > 0, row_count, "> 0 rows"),
        _check(
            "required_columns_present",
            "schema",
            not missing_columns,
            missing_columns,
            f"columns present: {', '.join(REQUIRED_COLUMNS)}",
        ),
    ]

    def text_series(column: str) -> pd.Series:
        if column not in df.columns:
            return pd.Series([""] * row_count, dtype="string")
        return df[column].fillna("").astype(str).str.strip()

    paper_ids = text_series("paper_id")
    titles = text_series("title")
    summaries = text_series("summary")
    missing_paper_ids = int(paper_ids.eq("").sum())
    duplicate_paper_ids = int(paper_ids[paper_ids.ne("")].duplicated().sum())
    missing_titles = int(titles.eq("").sum())
    missing_summaries = int(summaries.eq("").sum())
    short_summaries = int(summaries.str.len().lt(MIN_SUMMARY_CHARS).sum())

    ages = pd.to_numeric(df["age_days"], errors="coerce") if "age_days" in df else pd.Series([float("nan")] * row_count)
    invalid_age_rows = int((ages.isna() | ages.lt(0)).sum())
    stale_rows = int(ages.gt(settings.freshness_threshold_days).sum())

    checks.extend(
        [
            _check("paper_id_not_null", "completeness", missing_paper_ids == 0, missing_paper_ids, "0 missing/blank"),
            _check("paper_id_unique", "uniqueness", duplicate_paper_ids == 0, duplicate_paper_ids, "0 duplicates"),
            _check("title_not_null", "completeness", missing_titles == 0, missing_titles, "0 missing/blank"),
            _check("summary_not_null", "completeness", missing_summaries == 0, missing_summaries, "0 missing/blank"),
            _check(
                "summary_min_length",
                "validity",
                short_summaries == 0,
                short_summaries,
                f"0 summaries shorter than {MIN_SUMMARY_CHARS} characters",
            ),
            _check("age_days_valid", "validity", invalid_age_rows == 0, invalid_age_rows, "0 null, non-numeric or negative values"),
            _check(
                "rows_within_freshness_threshold",
                "freshness",
                stale_rows == 0,
                stale_rows,
                f"0 rows older than {settings.freshness_threshold_days} days",
            ),
        ]
    )

    failed_checks = [item["name"] for item in checks if not item["success"]]
    payload: dict[str, Any] = {
        "report_name": report_name,
        "generated_at": datetime.now(UTC).isoformat(),
        "success": not failed_checks,
        "row_count": row_count,
        "checks_passed": len(checks) - len(failed_checks),
        "checks_failed": len(failed_checks),
        "failed_checks": failed_checks,
        "checks": checks,
    }
    output_path = settings.paths.quality_dir / f"{_safe_report_name(report_name)}.json"
    write_json(output_path, payload)
    return payload


def build_freshness_report(df: pd.DataFrame, settings: Settings, report_path: str | Path) -> dict[str, Any]:
    """Summarize publication-date freshness and persist the JSON artifact."""
    total_rows = int(len(df))
    published = pd.to_datetime(
        df["published"] if "published" in df else pd.Series(dtype="object"),
        format="mixed",
        errors="coerce",
        utc=True,
    )
    invalid_date_rows = int(published.isna().sum()) + max(0, total_rows - len(published))
    valid_dates = published.dropna()

    ages = pd.to_numeric(df["age_days"], errors="coerce") if "age_days" in df else pd.Series([float("nan")] * total_rows)
    stale_rows = int(ages.gt(settings.freshness_threshold_days).sum())
    unknown_age_rows = int(ages.isna().sum())
    latest = valid_dates.max().date().isoformat() if not valid_dates.empty else None
    oldest = valid_dates.min().date().isoformat() if not valid_dates.empty else None

    if total_rows == 0 or valid_dates.empty:
        status = "unknown"
        is_fresh = False
    elif stale_rows or unknown_age_rows or invalid_date_rows:
        status = "stale"
        is_fresh = False
    else:
        status = "fresh"
        is_fresh = True

    payload: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "threshold_days": settings.freshness_threshold_days,
        "latest_published": latest,
        "oldest_published": oldest,
        "stale_rows": stale_rows,
        "invalid_date_rows": invalid_date_rows,
        "unknown_age_rows": unknown_age_rows,
        "total_rows": total_rows,
        "freshness_ratio": round((total_rows - stale_rows - unknown_age_rows) / total_rows, 6) if total_rows else 0.0,
        "status": status,
        "is_fresh": is_fresh,
    }
    write_json(Path(report_path), payload)
    return payload
