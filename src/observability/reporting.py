"""Sinh markdown report cho baseline phase va corruption comparison.

Nguyen tac: report chi doc lai cac dict artifact da duoc ghi ra dia
(`metrics`, `quality`, `freshness`) va render lai. Khong tinh toan lai metric
o day, de report luon match artifact thuc te.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.utils import now_utc, write_text

# Cac metric chinh duoc so sanh giua baseline / corrupted / repaired.
METRIC_KEYS = [
    ("retrieval_hit_rate", "Retrieval hit rate"),
    ("mean_token_f1", "Mean token F1"),
    ("judge_accuracy", "Judge accuracy"),
    ("mean_judge_score", "Mean judge score"),
]


def _fmt(value: Any, digits: int = 4) -> str:
    """Format gia tri cho o bang markdown."""
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "PASS" if value else "FAIL"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value) if value else "-"
    if isinstance(value, dict):
        return ", ".join(f"{k}={v}" for k, v in value.items()) if value else "-"
    text = str(value).strip()
    return text if text else "-"


def _delta(current: Any, baseline: Any, digits: int = 4) -> str:
    """Chenh lech so voi baseline, kem dau +/-."""
    if not isinstance(current, (int, float)) or not isinstance(baseline, (int, float)):
        return "n/a"
    if isinstance(current, bool) or isinstance(baseline, bool):
        return "n/a"
    diff = float(current) - float(baseline)
    sign = "+" if diff > 0 else ""
    return f"{sign}{diff:.{digits}f}"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_Khong co du lieu._\n"
    head = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = "\n".join("| " + " | ".join(r) + " |" for r in rows)
    return f"{head}\n{sep}\n{body}\n"


def _kv_table(payload: dict[str, Any], skip: set[str] | None = None) -> str:
    skip = skip or set()
    rows = [[f"`{k}`", _fmt(v)] for k, v in payload.items() if k not in skip]
    return _table(["Field", "Value"], rows)


def _quality_section(quality: dict[str, Any], title: str = "Data quality") -> str:
    if not quality:
        return f"## {title}\n\n_Chua co ket qua quality checks._\n"

    lines = [f"## {title}", ""]
    lines.append(
        _table(
            ["Metric", "Value"],
            [
                ["Overall", "PASS" if quality.get("success") else "FAIL"],
                ["Total rows", _fmt(quality.get("total_rows"))],
                ["Checks passed", f"{quality.get('checks_passed')}/{quality.get('checks_total')}"],
                ["Success rate", _fmt(quality.get("success_rate"))],
                ["Critical failed", _fmt(quality.get("critical_failed"))],
                ["Warning failed", _fmt(quality.get("warning_failed"))],
                ["GX engine", _fmt((quality.get("great_expectations") or {}).get("status"))],
            ],
        )
    )

    checks = quality.get("checks") or []
    if checks:
        lines.append("")
        lines.append("### Chi tiet tung check")
        lines.append("")
        rows = [
            [
                f"`{c.get('name')}`",
                _fmt(c.get("severity")),
                "PASS" if c.get("success") else "FAIL",
                _fmt(c.get("expected")),
                _fmt(c.get("observed")),
                _fmt(c.get("detail")),
            ]
            for c in checks
        ]
        lines.append(_table(["Check", "Severity", "Result", "Expected", "Observed", "Detail"], rows))

    failed = [c for c in checks if not c.get("success")]
    if failed:
        lines.append("")
        lines.append("### Check that bai")
        lines.append("")
        rows = [
            [f"`{c.get('name')}`", _fmt(c.get("severity")), _fmt(c.get("failed_examples"))]
            for c in failed
        ]
        lines.append(_table(["Check", "Severity", "Vi du (paper_id)"], rows))

    return "\n".join(lines) + "\n"


def _freshness_section(freshness: dict[str, Any], title: str = "Freshness") -> str:
    if not freshness:
        return f"## {title}\n\n_Chua co freshness report._\n"

    rows = [
        ["Status", _fmt(freshness.get("status"))],
        ["Is fresh", "yes" if freshness.get("is_fresh") else "no"],
        ["Threshold (days)", _fmt(freshness.get("threshold_days"))],
        ["Total rows", _fmt(freshness.get("total_rows"))],
        ["Stale rows", _fmt(freshness.get("stale_rows"))],
        ["Stale ratio", _fmt(freshness.get("stale_ratio"))],
        ["Latest published", _fmt(freshness.get("latest_published"))],
        ["Oldest published", _fmt(freshness.get("oldest_published"))],
        ["Days since latest", _fmt(freshness.get("days_since_latest"))],
        ["Age min / median / max", " / ".join(
            [
                _fmt(freshness.get("min_age_days")),
                _fmt(freshness.get("median_age_days"), digits=1),
                _fmt(freshness.get("max_age_days")),
            ]
        )],
    ]
    return f"## {title}\n\n" + _table(["Field", "Value"], rows)


def _judge_caveat(metrics: dict[str, Any]) -> str:
    """Canh bao khi diem judge khong den tu LLM.

    `judge_accuracy` va `mean_judge_score` chi co y nghia "LLM cham diem" khi
    `judge_source == "llm"`. Neu roi sang heuristic thi chung chi la ham bac
    thang cua token_f1, khong phai chi so doc lap - phai noi ro truoc khi ai do
    trich dan con so.
    """
    source = metrics.get("judge_source")
    if not source or source == "llm":
        return ""

    fallback = metrics.get("judge_fallback_count")
    samples = metrics.get("samples")
    if source == "heuristic":
        return (
            f"\n> **Luu y:** toan bo {fallback}/{samples} cau dung heuristic judge, "
            "KHONG phai LLM (thuong do het quota hoac thieu API key). "
            "`judge_accuracy` va `mean_judge_score` o day chi la ham bac thang cua "
            "`token_f1` (>=0.95 -> 5, >=0.5 -> 3, con lai -> 1), khong phai danh gia "
            "doc lap. Khong so sanh hai con so nay voi lan chay co LLM that.\n"
        )
    return (
        f"\n> **Luu y:** {fallback}/{samples} cau dung heuristic judge thay vi LLM. "
        "Diem judge trong lan chay nay tron hai nguon khac ban chat.\n"
    )


def _metrics_section(metrics: dict[str, Any]) -> str:
    if not metrics:
        return "## Evaluation metrics\n\n_Chua co metrics._\n"

    rows = [["Samples", _fmt(metrics.get("samples"))]]
    rows += [[label, _fmt(metrics.get(key))] for key, label in METRIC_KEYS]
    out = "## Evaluation metrics\n\n" + _table(["Metric", "Value"], rows)
    out += _judge_caveat(metrics)

    ragas = metrics.get("ragas")
    if isinstance(ragas, dict) and ragas:
        out += "\n### Ragas\n\n" + _table(
            ["Metric", "Value"], [[f"`{k}`", _fmt(v)] for k, v in ragas.items()]
        )
    return out


def _agent_section(agent_metrics: dict[str, Any] | None, baseline: dict[str, Any]) -> str:
    """So sanh duong deterministic (`qa.answer_question`) voi duong LLM agent."""
    if not agent_metrics:
        return (
            "## Agent evaluation\n\n"
            "_Khong chay trong lan nay (RUN_AGENT_EVAL=0 hoac agent loi)._\n"
        )
    if "error" in agent_metrics:
        return f"## Agent evaluation\n\n_That bai: {agent_metrics['error']}_\n"

    errors = agent_metrics.get("agent_errors") or 0
    samples = agent_metrics.get("samples") or 0
    # Hong toan bo -> bang so lieu toan 0, in ra chi gay hieu nham la "agent kem".
    # Bao ly do thay vi bao con so.
    if samples and errors == samples:
        reason = agent_metrics.get("first_error") or "khong ro"
        return (
            "## Agent evaluation\n\n"
            f"**Khong chay duoc.** Ca {errors}/{samples} cau deu loi, nen "
            "`agent_metrics.json` toan gia tri 0 - day la loi ha tang, KHONG phai "
            "ket qua do luong. Khong duoc doc bang nay nhu la agent tra loi sai.\n\n"
            f"Loi dau tien:\n\n```\n{reason}\n```\n\n"
            "Chay lai sau khi quota reset, hoac doi `LLM_PROVIDER` sang provider khac "
            "trong `.env`, roi chay `script/rebuild_reports.py` de cap nhat report.\n"
        )

    rows = [
        [
            label,
            _fmt(baseline.get(key)),
            _fmt(agent_metrics.get(key)),
            _delta(agent_metrics.get(key), baseline.get(key)),
        ]
        for key, label in METRIC_KEYS
    ]
    out = (
        "## Agent evaluation\n\n"
        "Cung test set, cung ground truth, khac cach sinh cau tra loi:\n"
        "`deterministic` di qua `qa.answer_question` (khong goi LLM, dung lam moc "
        "so sanh cho Pha 2), `agent` di qua `create_agent` voi hai tool.\n\n"
        + _table(["Metric", "Deterministic", "Agent", "Δ"], rows)
    )
    if errors:
        out += (
            f"\n> {errors}/{samples} cau agent khong tra loi duoc. "
            "Phan hut nay den tu loi ha tang (rate limit, timeout), khong phai tu chat "
            "luong du lieu.\n"
        )
    out += _judge_caveat(agent_metrics)
    return out


def generate_phase1_report(
    report_path,
    source_summary: dict[str, Any],
    metrics: dict[str, Any],
    quality: dict[str, Any],
    freshness: dict[str, Any],
    agent_metrics: dict[str, Any] | None = None,
) -> None:
    """Viet markdown report cho baseline phase.

    Args:
        report_path: duong dan file .md dich (`data/reports/phase1_report.md`).
        source_summary: dict mo ta nguon du lieu - vi du `source_api`,
            `source_query`, `source_filter`, `raw_records`, `clean_rows`,
            `dropped_rows`, cac path artifact. Key la tu do, tat ca deu duoc render.
        metrics: summary tu `evaluate_pipeline`.
        quality: output cua `run_data_quality_checks`.
        freshness: output cua `build_freshness_report`.
    """
    report_path = Path(report_path)

    sections = [
        "# Phase 1 - Baseline pipeline report",
        "",
        f"_Generated at: {now_utc().isoformat()}_",
        "",
        "## Source",
        "",
        _kv_table(source_summary or {}),
        "",
        _metrics_section(metrics or {}),
        "",
        _agent_section(agent_metrics, metrics or {}),
        "",
        _quality_section(quality or {}),
        "",
        _freshness_section(freshness or {}),
        "",
        "## Ket luan",
        "",
        _phase1_verdict(metrics or {}, quality or {}, freshness or {}),
        "",
    ]
    write_text(report_path, "\n".join(sections))


def _phase1_verdict(
    metrics: dict[str, Any], quality: dict[str, Any], freshness: dict[str, Any]
) -> str:
    bullets = []

    hit_rate = metrics.get("retrieval_hit_rate")
    if isinstance(hit_rate, (int, float)):
        verdict = "tot" if hit_rate >= 0.8 else "trung binh" if hit_rate >= 0.5 else "yeu"
        bullets.append(f"- Retrieval hit rate `{hit_rate:.4f}` -> muc {verdict}.")

    if quality:
        if quality.get("success"):
            bullets.append(
                f"- Data quality PASS ({quality.get('checks_passed')}/{quality.get('checks_total')} checks)."
            )
        else:
            names = ", ".join(f"`{n}`" for n in quality.get("failed_check_names") or [])
            bullets.append(f"- Data quality FAIL. Check that bai: {names or 'n/a'}.")

    if freshness:
        if freshness.get("is_fresh"):
            bullets.append(
                f"- Dataset fresh: khong co dong nao cu hon {freshness.get('threshold_days')} ngay."
            )
        else:
            bullets.append(
                f"- Dataset stale: {freshness.get('stale_rows')}/{freshness.get('total_rows')} dong "
                f"vuot nguong {freshness.get('threshold_days')} ngay."
            )

    return "\n".join(bullets) if bullets else "_Khong du du lieu de ket luan._"


def _judge_provenance_note(
    baseline: dict[str, Any], corrupted: dict[str, Any], repaired: dict[str, Any]
) -> str:
    """Bao nguon diem judge cua ba trang thai va canh bao khi chung khong dong nhat."""
    sources = {
        "baseline": baseline.get("judge_source"),
        "corrupted": corrupted.get("judge_source"),
        "repaired": repaired.get("judge_source"),
    }
    known = {k: v for k, v in sources.items() if v}
    if not known:
        return ""

    listed = ", ".join(f"{k}=`{v}`" for k, v in known.items())
    distinct = set(known.values())

    if distinct == {"llm"}:
        return f"\nNguon diem judge: {listed}.\n"
    if len(distinct) > 1:
        return (
            f"\n> **Canh bao:** nguon diem judge khong dong nhat ({listed}). "
            "`judge_accuracy` va `mean_judge_score` giua cac trang thai KHONG so sanh "
            "duoc - mot phan chenh lech den tu cach cham diem chu khong tu du lieu. "
            "Chi doc `retrieval_hit_rate` va `mean_token_f1` trong bang tren.\n"
        )
    return (
        f"\n> **Luu y:** ca ba trang thai deu dung heuristic judge ({listed}), khong "
        "phai LLM. Vi dung chung mot cach cham nen so sanh van nhat quan, nhung "
        "`judge_accuracy` chi la ham bac thang cua `token_f1` chu khong phai danh gia "
        "doc lap.\n"
    )


def generate_corruption_report(
    report_path,
    baseline_metrics: dict[str, Any],
    corrupted_metrics: dict[str, Any],
    repaired_metrics: dict[str, Any],
    corrupted_quality: dict[str, Any],
    repaired_quality: dict[str, Any],
    corrupted_freshness: dict[str, Any],
    repaired_freshness: dict[str, Any],
) -> None:
    """Viet markdown report so sanh baseline / corrupted / repaired."""
    report_path = Path(report_path)
    baseline = baseline_metrics or {}
    corrupted = corrupted_metrics or {}
    repaired = repaired_metrics or {}

    metric_rows = []
    for key, label in METRIC_KEYS:
        metric_rows.append(
            [
                label,
                _fmt(baseline.get(key)),
                _fmt(corrupted.get(key)),
                _delta(corrupted.get(key), baseline.get(key)),
                _fmt(repaired.get(key)),
                _delta(repaired.get(key), baseline.get(key)),
            ]
        )

    quality_rows = [
        [
            "Overall",
            "PASS" if (corrupted_quality or {}).get("success") else "FAIL",
            "PASS" if (repaired_quality or {}).get("success") else "FAIL",
        ],
        [
            "Checks passed",
            f"{(corrupted_quality or {}).get('checks_passed')}/{(corrupted_quality or {}).get('checks_total')}",
            f"{(repaired_quality or {}).get('checks_passed')}/{(repaired_quality or {}).get('checks_total')}",
        ],
        [
            "Total rows",
            _fmt((corrupted_quality or {}).get("total_rows")),
            _fmt((repaired_quality or {}).get("total_rows")),
        ],
        [
            "Failed checks",
            _fmt((corrupted_quality or {}).get("failed_check_names")),
            _fmt((repaired_quality or {}).get("failed_check_names")),
        ],
    ]

    freshness_rows = [
        [
            "Status",
            _fmt((corrupted_freshness or {}).get("status")),
            _fmt((repaired_freshness or {}).get("status")),
        ],
        [
            "Stale rows",
            _fmt((corrupted_freshness or {}).get("stale_rows")),
            _fmt((repaired_freshness or {}).get("stale_rows")),
        ],
        [
            "Latest published",
            _fmt((corrupted_freshness or {}).get("latest_published")),
            _fmt((repaired_freshness or {}).get("latest_published")),
        ],
        [
            "Max age (days)",
            _fmt((corrupted_freshness or {}).get("max_age_days")),
            _fmt((repaired_freshness or {}).get("max_age_days")),
        ],
    ]

    sections = [
        "# Corruption impact report",
        "",
        f"_Generated at: {now_utc().isoformat()}_",
        "",
        "Ba trang thai dung chung test set, ground truth, evaluator va top-k.",
        "Khac biet metric vi vay den tu chat luong du lieu, khong phai tu cau hinh.",
        "",
        "## Metrics: baseline vs corrupted vs repaired",
        "",
        _table(
            ["Metric", "Baseline", "Corrupted", "Δ vs baseline", "Repaired", "Δ vs baseline"],
            metric_rows,
        ),
        _judge_provenance_note(baseline, corrupted, repaired),
        "",
        "## Data quality",
        "",
        _table(["Field", "Corrupted", "Repaired"], quality_rows),
        "",
        "## Freshness",
        "",
        _table(["Field", "Corrupted", "Repaired"], freshness_rows),
        "",
        "## Phan tich",
        "",
        _corruption_verdict(baseline, corrupted, repaired),
        "",
    ]
    write_text(report_path, "\n".join(sections))


def _corruption_verdict(
    baseline: dict[str, Any], corrupted: dict[str, Any], repaired: dict[str, Any]
) -> str:
    bullets = []

    for key, label in METRIC_KEYS:
        b, c, r = baseline.get(key), corrupted.get(key), repaired.get(key)
        if not all(isinstance(v, (int, float)) for v in (b, c, r)):
            continue
        # Tat ca delta deu tinh theo huong "gia tri moi - gia tri cu",
        # nen dau am = tut giam, dau duong = cai thien.
        corruption_delta = float(c) - float(b)  # corrupted vs baseline
        repair_delta = float(r) - float(c)  # repaired vs corrupted
        residual_gap = float(r) - float(b)  # repaired vs baseline
        bullets.append(
            f"- **{label}**: corrupted `{corruption_delta:+.4f}` so voi baseline; "
            f"repair keo lai `{repair_delta:+.4f}`; "
            f"repaired con lech `{residual_gap:+.4f}` so voi baseline."
        )

    hit_b, hit_c = baseline.get("retrieval_hit_rate"), corrupted.get("retrieval_hit_rate")
    if isinstance(hit_b, (int, float)) and isinstance(hit_c, (int, float)):
        if hit_c < hit_b:
            bullets.append(
                "- Ket luan: du lieu hong lam giam do chinh xac cua retrieval, "
                "keo theo chat luong cau tra loi cua agent."
            )
        else:
            bullets.append(
                "- Luu y: corruption chua lam giam retrieval hit rate. "
                "Can tang cuong do corruption hoac kiem tra lai buoc rebuild index."
            )

    return "\n".join(bullets) if bullets else "_Khong du metric de so sanh._"


