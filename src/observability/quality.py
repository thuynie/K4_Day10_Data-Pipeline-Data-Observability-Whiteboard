"""Data quality & freshness checks cho pipeline.

Thiet ke:
- Engine chinh la pandas (deterministic, khong phu thuoc version GX) -> luon chay duoc.
- Engine phu la Great Expectations, chay trong try/except va KHONG BAO GIO raise.
  Ket qua GX duoc ghi rieng vao `data/quality/gx/` de audit.

Moi check tra ve cung mot schema, nho vay baseline / corrupted / repaired
so sanh duoc truc tiep voi nhau trong comparison report.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
from typing import Any

import pandas as pd

from core.config import Settings
from core.utils import now_utc, write_json

# Nguong toi thieu. Giu o day de report va check dung chung mot nguon su that.
MIN_ROWS = 5
MIN_TITLE_CHARS = 10
MIN_SUMMARY_CHARS = 100  # phai khop rule trong ingestion/cleaning.py
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Check `critical` fail -> ca run bi danh dau that bai.
# Check `warning` fail -> chi ghi nhan, khong lam do run.
CRITICAL = "critical"
WARNING = "warning"


@dataclass
class CheckResult:
    name: str
    column: str | None
    severity: str
    success: bool
    expected: str
    observed: Any
    detail: str = ""
    failed_examples: list[Any] = field(default_factory=list)


def _series(df: pd.DataFrame, column: str) -> pd.Series | None:
    """Lay cot duoi dang Series, tra None neu cot khong ton tai."""
    if column not in df.columns:
        return None
    return df[column]


def _as_text(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def _missing_column(name: str, column: str, severity: str = CRITICAL) -> CheckResult:
    return CheckResult(
        name=name,
        column=column,
        severity=severity,
        success=False,
        expected=f"column `{column}` exists",
        observed=None,
        detail=f"Column `{column}` khong ton tai trong dataframe.",
    )


def _check_row_count(df: pd.DataFrame) -> CheckResult:
    n = int(len(df))
    return CheckResult(
        name="row_count_min",
        column=None,
        severity=CRITICAL,
        success=n >= MIN_ROWS,
        expected=f">= {MIN_ROWS} rows",
        observed=n,
        detail="" if n >= MIN_ROWS else f"Dataset chi con {n} dong, duoi nguong toi thieu.",
    )


def _check_not_null(df: pd.DataFrame, column: str, severity: str = CRITICAL) -> CheckResult:
    s = _series(df, column)
    if s is None:
        return _missing_column(f"{column}_not_null", column, severity)
    text = _as_text(s)
    bad = df.loc[text == ""]
    return CheckResult(
        name=f"{column}_not_null",
        column=column,
        severity=severity,
        success=bad.empty,
        expected=f"`{column}` khong rong o moi dong",
        observed=int(len(bad)),
        detail="" if bad.empty else f"{len(bad)} dong co `{column}` rong.",
        failed_examples=_examples(bad),
    )


def _check_unique(df: pd.DataFrame, column: str, severity: str = CRITICAL) -> CheckResult:
    s = _series(df, column)
    if s is None:
        return _missing_column(f"{column}_unique", column, severity)
    dupes = s[s.duplicated(keep=False)]
    unique_dupes = sorted({str(v) for v in dupes.tolist()})
    return CheckResult(
        name=f"{column}_unique",
        column=column,
        severity=severity,
        success=dupes.empty,
        expected=f"`{column}` unique",
        observed=int(len(unique_dupes)),
        detail="" if dupes.empty else f"{len(unique_dupes)} gia tri `{column}` bi lap.",
        failed_examples=unique_dupes[:5],
    )


def _check_min_length(
    df: pd.DataFrame, column: str, min_chars: int, severity: str = CRITICAL
) -> CheckResult:
    s = _series(df, column)
    if s is None:
        return _missing_column(f"{column}_min_length", column, severity)
    lengths = _as_text(s).str.len()
    bad = df.loc[lengths < min_chars]
    return CheckResult(
        name=f"{column}_min_length",
        column=column,
        severity=severity,
        success=bad.empty,
        expected=f"len(`{column}`) >= {min_chars}",
        observed=int(len(bad)),
        detail="" if bad.empty else f"{len(bad)} dong co `{column}` ngan hon {min_chars} ky tu.",
        failed_examples=_examples(bad),
    )


def _check_date_format(df: pd.DataFrame, column: str, severity: str = CRITICAL) -> CheckResult:
    s = _series(df, column)
    if s is None:
        return _missing_column(f"{column}_format", column, severity)
    text = _as_text(s)
    bad = df.loc[~text.str.match(DATE_PATTERN)]
    return CheckResult(
        name=f"{column}_format",
        column=column,
        severity=severity,
        success=bad.empty,
        expected=f"`{column}` theo dinh dang YYYY-MM-DD",
        observed=int(len(bad)),
        detail="" if bad.empty else f"{len(bad)} dong co `{column}` sai dinh dang.",
        failed_examples=_examples(bad),
    )


def _check_non_negative(df: pd.DataFrame, column: str, severity: str = CRITICAL) -> CheckResult:
    s = _series(df, column)
    if s is None:
        return _missing_column(f"{column}_non_negative", column, severity)
    numeric = pd.to_numeric(s, errors="coerce")
    bad = df.loc[numeric.isna() | (numeric < 0)]
    return CheckResult(
        name=f"{column}_non_negative",
        column=column,
        severity=severity,
        success=bad.empty,
        expected=f"`{column}` la so >= 0",
        observed=int(len(bad)),
        detail="" if bad.empty else f"{len(bad)} dong co `{column}` am hoac khong phai so.",
        failed_examples=_examples(bad),
    )


def _check_freshness(df: pd.DataFrame, threshold_days: int) -> CheckResult:
    s = _series(df, "age_days")
    if s is None:
        return _missing_column("freshness_within_threshold", "age_days", WARNING)
    ages = pd.to_numeric(s, errors="coerce")
    stale = df.loc[ages > threshold_days]
    return CheckResult(
        name="freshness_within_threshold",
        column="age_days",
        severity=WARNING,
        success=stale.empty,
        expected=f"age_days <= {threshold_days}",
        observed=int(len(stale)),
        detail="" if stale.empty else f"{len(stale)} dong cu hon {threshold_days} ngay.",
        failed_examples=_examples(stale),
    )


def _check_no_duplicate_titles(df: pd.DataFrame) -> CheckResult:
    s = _series(df, "title")
    if s is None:
        return _missing_column("title_no_duplicates", "title", WARNING)
    normalized = _as_text(s).str.lower()
    dupes = normalized[normalized.duplicated(keep=False)]
    return CheckResult(
        name="title_no_duplicates",
        column="title",
        severity=WARNING,
        success=dupes.empty,
        expected="khong co title trung lap (case-insensitive)",
        observed=int(dupes.nunique()),
        detail="" if dupes.empty else f"{dupes.nunique()} title xuat hien nhieu lan.",
        failed_examples=sorted({v[:80] for v in dupes.tolist()})[:5],
    )


def _examples(bad_rows: pd.DataFrame, limit: int = 5) -> list[Any]:
    """Lay vai `paper_id` lam vi du de debug, tranh dump ca dataframe vao JSON."""
    if bad_rows.empty:
        return []
    if "paper_id" in bad_rows.columns:
        return [str(v) for v in bad_rows["paper_id"].head(limit).tolist()]
    return [int(i) for i in bad_rows.index[:limit].tolist()]


def _run_great_expectations(
    df: pd.DataFrame, gx_dir: Path, report_name: str
) -> dict[str, Any]:
    """Chay them mot lop validation bang Great Expectations (optional).

    Toan bo khoi nay duoc bao ve: GX loi hoac doi API deu khong lam vo pipeline.
    """
    try:
        import json

        import great_expectations as gx
        from great_expectations import expectations as gxe
        from great_expectations.core.expectation_suite import ExpectationSuite

        context = gx.get_context(mode="ephemeral")
        source = context.data_sources.add_pandas(f"papers_{report_name}")
        asset = source.add_dataframe_asset(name=report_name)
        batch_definition = asset.add_batch_definition_whole_dataframe("whole_frame")
        batch = batch_definition.get_batch(batch_parameters={"dataframe": df})

        suite = context.suites.add(ExpectationSuite(name=f"{report_name}_suite"))
        suite.add_expectation(gxe.ExpectTableRowCountToBeBetween(min_value=MIN_ROWS))
        suite.add_expectation(gxe.ExpectColumnValuesToNotBeNull(column="paper_id"))
        suite.add_expectation(gxe.ExpectColumnValuesToBeUnique(column="paper_id"))
        suite.add_expectation(gxe.ExpectColumnValuesToNotBeNull(column="title"))
        suite.add_expectation(
            gxe.ExpectColumnValueLengthsToBeBetween(
                column="summary", min_value=MIN_SUMMARY_CHARS
            )
        )

        result = batch.validate(suite)

        # API serialize doi ten giua cac minor version -> thu lan luot.
        if hasattr(result, "describe_dict"):
            payload = result.describe_dict()
        elif hasattr(result, "to_json_dict"):
            payload = result.to_json_dict()
        else:
            payload = json.loads(result.describe())

        gx_dir.mkdir(parents=True, exist_ok=True)
        result_path = gx_dir / f"{report_name}_gx_result.json"
        write_json(result_path, payload)
        return {
            "status": "ok",
            "success": bool(result.success),
            "result_path": str(result_path),
        }
    except Exception as exc:  # pragma: no cover - phu thuoc version GX
        # GX chi la lop kiem tra bo sung. Loi o day khong duoc lam vo pipeline.
        return {"status": "skipped", "reason": f"{type(exc).__name__}: {exc}"}


def run_data_quality_checks(
    df: pd.DataFrame, settings: Settings, report_name: str
) -> dict[str, Any]:
    """Chay bo data quality checks tren cleaned dataframe.

    Args:
        df: cleaned dataframe (output cua `build_clean_dataframe`).
        settings: settings da load, dung de lay nguong freshness va thu muc output.
        report_name: nhan cua lan chay - `baseline`, `corrupted`, `repaired`.

    Returns:
        dict ket qua; dong thoi ghi ra `data/quality/quality_{report_name}.json`.
    """
    threshold = settings.freshness_threshold_days

    checks: list[CheckResult] = [
        _check_row_count(df),
        _check_not_null(df, "paper_id"),
        _check_unique(df, "paper_id"),
        _check_not_null(df, "title"),
        _check_min_length(df, "title", MIN_TITLE_CHARS),
        _check_not_null(df, "summary"),
        _check_min_length(df, "summary", MIN_SUMMARY_CHARS),
        _check_not_null(df, "text_for_embedding"),
        _check_date_format(df, "published"),
        _check_non_negative(df, "age_days"),
        _check_freshness(df, threshold),
        _check_no_duplicate_titles(df),
    ]

    failed = [c for c in checks if not c.success]
    critical_failed = [c for c in failed if c.severity == CRITICAL]
    passed = len(checks) - len(failed)

    payload: dict[str, Any] = {
        "report_name": report_name,
        "generated_at": now_utc().isoformat(),
        "engine": "pandas",
        "total_rows": int(len(df)),
        "checks_total": len(checks),
        "checks_passed": passed,
        "checks_failed": len(failed),
        "critical_failed": len(critical_failed),
        "warning_failed": len(failed) - len(critical_failed),
        "success_rate": round(passed / len(checks), 4) if checks else 0.0,
        # `success` chi false khi co check critical fail.
        "success": not critical_failed,
        "thresholds": {
            "min_rows": MIN_ROWS,
            "min_title_chars": MIN_TITLE_CHARS,
            "min_summary_chars": MIN_SUMMARY_CHARS,
            "freshness_threshold_days": threshold,
        },
        "failed_check_names": [c.name for c in failed],
        "checks": [asdict(c) for c in checks],
    }

    payload["great_expectations"] = _run_great_expectations(
        df, settings.paths.gx_dir, report_name
    )

    output_path = settings.paths.quality_dir / f"quality_{report_name}.json"
    write_json(output_path, payload)
    payload["report_path"] = str(output_path)
    return payload


def build_freshness_report(
    df: pd.DataFrame, settings: Settings, report_path
) -> dict[str, Any]:
    """Tong hop freshness cua dataset va ghi JSON report.

    Dataset duoc coi la `fresh` khi khong con dong nao cu hon
    `settings.freshness_threshold_days`.
    """
    report_path = Path(report_path)
    threshold = settings.freshness_threshold_days
    total_rows = int(len(df))

    payload: dict[str, Any] = {
        "generated_at": now_utc().isoformat(),
        "threshold_days": threshold,
        "total_rows": total_rows,
        "latest_published": None,
        "oldest_published": None,
        "stale_rows": 0,
        "stale_ratio": 0.0,
        "fresh_rows": 0,
        "min_age_days": None,
        "max_age_days": None,
        "median_age_days": None,
        "days_since_latest": None,
        "stale_examples": [],
        "is_fresh": False,
        "status": "empty",
    }

    if total_rows == 0:
        write_json(report_path, payload)
        payload["report_path"] = str(report_path)
        return payload

    published = _as_text(df["published"]) if "published" in df.columns else pd.Series(dtype=str)
    parsed = pd.to_datetime(published, errors="coerce", format="%Y-%m-%d")
    valid_dates = parsed.dropna()

    if not valid_dates.empty:
        payload["latest_published"] = valid_dates.max().strftime("%Y-%m-%d")
        payload["oldest_published"] = valid_dates.min().strftime("%Y-%m-%d")
        payload["days_since_latest"] = int(
            (now_utc().replace(tzinfo=None) - valid_dates.max()).days
        )

    ages = (
        pd.to_numeric(df["age_days"], errors="coerce")
        if "age_days" in df.columns
        else pd.Series(dtype=float)
    )
    valid_ages = ages.dropna()

    if not valid_ages.empty:
        stale_mask = valid_ages > threshold
        stale_rows = int(stale_mask.sum())
        payload.update(
            {
                "stale_rows": stale_rows,
                "fresh_rows": total_rows - stale_rows,
                "stale_ratio": round(stale_rows / total_rows, 4),
                "min_age_days": int(valid_ages.min()),
                "max_age_days": int(valid_ages.max()),
                "median_age_days": float(valid_ages.median()),
                "stale_examples": _examples(df.loc[stale_mask[stale_mask].index]),
                "is_fresh": stale_rows == 0,
                "status": "fresh" if stale_rows == 0 else "stale",
            }
        )

    write_json(report_path, payload)
    payload["report_path"] = str(report_path)
    return payload
