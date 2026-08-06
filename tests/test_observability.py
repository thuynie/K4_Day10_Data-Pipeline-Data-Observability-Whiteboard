"""Unit test cho data quality checks, freshness va markdown reporting.

Chay: `uv run pytest tests/test_observability.py -v`
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from core.config import load_settings
from observability.quality import (
    MIN_SUMMARY_CHARS,
    build_freshness_report,
    run_data_quality_checks,
)
from observability.reporting import generate_corruption_report, generate_phase1_report


@pytest.fixture
def settings(tmp_path):
    """Settings tro vao tmp_path de test khong ghi de artifact that."""
    return load_settings(tmp_path)


def _row(idx: int, age_days: int = 10) -> dict:
    published = (datetime.now(UTC).date() - timedelta(days=age_days)).isoformat()
    summary = "Nghien cuu ve retrieval augmented generation. " * 5
    return {
        "paper_id": f"10.1234/paper-{idx}",
        "title": f"A study on retrieval augmented generation number {idx}",
        "summary": summary,
        "published": published,
        "age_days": age_days,
        "text_for_embedding": f"Title: paper {idx} | Summary: {summary}",
    }


@pytest.fixture
def clean_df() -> pd.DataFrame:
    return pd.DataFrame([_row(i) for i in range(10)])


def test_clean_dataframe_passes_all_checks(clean_df, settings):
    result = run_data_quality_checks(clean_df, settings, "baseline")

    assert result["success"] is True
    assert result["checks_failed"] == 0
    assert result["critical_failed"] == 0
    assert result["success_rate"] == 1.0
    assert result["total_rows"] == 10
    # Artifact phai ton tai tren dia, khong chi tra ve trong memory.
    assert (settings.paths.quality_dir / "quality_baseline.json").exists()


def test_blank_summary_is_caught(clean_df, settings):
    df = clean_df.copy()
    df.loc[0, "summary"] = ""
    result = run_data_quality_checks(df, settings, "corrupted")

    assert result["success"] is False
    assert "summary_not_null" in result["failed_check_names"]
    assert "summary_min_length" in result["failed_check_names"]


def test_short_summary_is_caught(clean_df, settings):
    df = clean_df.copy()
    df.loc[0, "summary"] = "x" * (MIN_SUMMARY_CHARS - 1)
    result = run_data_quality_checks(df, settings, "corrupted")

    assert "summary_min_length" in result["failed_check_names"]
    assert "summary_not_null" not in result["failed_check_names"]


def test_duplicate_paper_id_is_caught(clean_df, settings):
    df = pd.concat([clean_df, clean_df.iloc[[0]]], ignore_index=True)
    result = run_data_quality_checks(df, settings, "corrupted")

    assert result["success"] is False
    assert "paper_id_unique" in result["failed_check_names"]
    assert "title_no_duplicates" in result["failed_check_names"]


def test_bad_date_format_is_caught(clean_df, settings):
    df = clean_df.copy()
    df.loc[0, "published"] = "2026/01/01"
    result = run_data_quality_checks(df, settings, "corrupted")

    assert "published_format" in result["failed_check_names"]


def test_stale_row_is_warning_not_failure(clean_df, settings):
    """Freshness la canh bao: no khong duoc lam fail ca run."""
    df = clean_df.copy()
    df.loc[0, "age_days"] = settings.freshness_threshold_days + 1
    result = run_data_quality_checks(df, settings, "corrupted")

    assert "freshness_within_threshold" in result["failed_check_names"]
    assert result["critical_failed"] == 0
    assert result["success"] is True


def test_missing_column_does_not_crash(settings):
    df = pd.DataFrame([{"paper_id": "10.1/a", "title": "x" * 20}] * 6)
    result = run_data_quality_checks(df, settings, "partial")

    assert result["success"] is False
    assert "summary_not_null" in result["failed_check_names"]


def test_empty_dataframe_is_handled(settings):
    result = run_data_quality_checks(pd.DataFrame(), settings, "empty")

    assert result["total_rows"] == 0
    assert result["success"] is False
    assert "row_count_min" in result["failed_check_names"]


def test_freshness_report_on_fresh_data(clean_df, settings):
    report = build_freshness_report(clean_df, settings, settings.paths.freshness_report)

    assert report["status"] == "fresh"
    assert report["is_fresh"] is True
    assert report["stale_rows"] == 0
    assert report["total_rows"] == 10
    assert report["max_age_days"] == 10
    assert settings.paths.freshness_report.exists()


def test_freshness_report_detects_stale_rows(clean_df, settings):
    df = clean_df.copy()
    df.loc[0, "age_days"] = settings.freshness_threshold_days + 100
    report = build_freshness_report(df, settings, settings.paths.freshness_report)

    assert report["status"] == "stale"
    assert report["is_fresh"] is False
    assert report["stale_rows"] == 1
    assert report["stale_ratio"] == 0.1


def test_freshness_report_on_empty_dataframe(settings):
    report = build_freshness_report(pd.DataFrame(), settings, settings.paths.freshness_report)

    assert report["status"] == "empty"
    assert report["total_rows"] == 0
    assert report["is_fresh"] is False


def test_phase1_report_is_written(clean_df, settings):
    quality = run_data_quality_checks(clean_df, settings, "baseline")
    freshness = build_freshness_report(clean_df, settings, settings.paths.freshness_report)
    metrics = {
        "samples": 10,
        "retrieval_hit_rate": 0.9,
        "mean_token_f1": 0.42,
        "judge_accuracy": 0.8,
        "mean_judge_score": 4.1,
    }
    generate_phase1_report(
        settings.paths.baseline_report,
        {"source_api": settings.source_api, "clean_rows": len(clean_df)},
        metrics,
        quality,
        freshness,
    )

    text = settings.paths.baseline_report.read_text(encoding="utf-8")
    assert "# Phase 1" in text
    assert "Retrieval hit rate" in text
    assert "0.9000" in text
    assert "Data quality" in text
    assert "Freshness" in text


def test_corruption_report_shows_signed_deltas(clean_df, settings):
    quality = run_data_quality_checks(clean_df, settings, "baseline")
    freshness = build_freshness_report(clean_df, settings, settings.paths.freshness_report)
    baseline = {"retrieval_hit_rate": 0.9, "mean_token_f1": 0.4, "judge_accuracy": 0.8, "mean_judge_score": 4.0}
    corrupted = {"retrieval_hit_rate": 0.5, "mean_token_f1": 0.2, "judge_accuracy": 0.4, "mean_judge_score": 2.0}
    repaired = dict(baseline)

    generate_corruption_report(
        settings.paths.comparison_report,
        baseline, corrupted, repaired,
        quality, quality, freshness, freshness,
    )

    text = settings.paths.comparison_report.read_text(encoding="utf-8")
    assert "Corruption impact report" in text
    # Corrupted tut xuong -> delta phai am.
    assert "-0.4000" in text
    # Repaired bang baseline -> khong con lech.
    assert "+0.0000" in text
