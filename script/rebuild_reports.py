"""Dung lai markdown report tu cac artifact JSON da co tren dia.

KHONG goi LLM, KHONG goi Crossref, KHONG build lai index - chi doc file va
render lai markdown. Dung khi:
  - Vua sua template trong `observability/reporting.py`.
  - Metrics cu thieu truong moi (vi du `judge_source`) can bo sung.
  - Het quota LLM nen khong chay lai duoc `run_phase1.py`.

Chay: `python script/rebuild_reports.py`
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

from core.config import load_settings
from evaluation.metrics import judge_provenance
from observability.reporting import generate_corruption_report, generate_phase1_report


def _read(path: Path) -> dict | list | None:
    if not Path(path).exists():
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"  ! Bo qua {path.name}: JSON hong ({exc})")
        return None


def _enrich(metrics: dict | None, answers_path: Path) -> dict | None:
    """Bo sung `judge_source` cho metrics cu chua co truong nay.

    Metrics sinh truoc khi them `judge_provenance` khong co thong tin nguon
    judge. Ta suy nguoc tu file answers tuong ung thay vi chay lai evaluate.
    """
    if not metrics or "judge_source" in metrics:
        return metrics
    answers = _read(answers_path)
    if isinstance(answers, list) and answers:
        metrics.update(judge_provenance(answers))
        print(f"  + suy ra judge_source={metrics['judge_source']} tu {answers_path.name}")
    return metrics


def main() -> None:
    settings = load_settings()
    paths = settings.paths

    print("Doc artifact...")
    baseline = _enrich(_read(paths.baseline_metrics), paths.baseline_answers)
    agent = _enrich(_read(paths.agent_metrics), paths.agent_answers)
    corrupted = _enrich(_read(paths.corrupted_metrics), paths.corrupted_answers)
    repaired = _enrich(_read(paths.repaired_metrics), paths.repaired_answers)

    quality = _read(paths.quality_dir / "quality_baseline.json")
    freshness = _read(paths.freshness_report)

    written = 0

    if baseline and quality and freshness:
        source_summary = {
            "source_api": settings.source_api,
            "source_query": settings.source_query,
            "source_filter": settings.source_filter,
            "llm_provider": settings.llm_provider,
            "llm_model": settings.model_name,
            "embedding_model": settings.embedding_model,
            "top_k": settings.top_k,
            "note": "Report dung lai tu artifact co san (rebuild_reports.py), khong chay lai pipeline.",
            "baseline_metrics": str(paths.baseline_metrics),
            "agent_metrics": str(paths.agent_metrics) if agent else "khong chay",
        }
        generate_phase1_report(
            paths.baseline_report,
            source_summary=source_summary,
            metrics=baseline,
            quality=quality,
            freshness=freshness,
            agent_metrics=agent,
        )
        print(f"OK  {paths.baseline_report}")
        written += 1
    else:
        missing = [
            name
            for name, value in [
                ("baseline_metrics", baseline),
                ("quality_baseline", quality),
                ("freshness_report", freshness),
            ]
            if not value
        ]
        print(f"BO QUA phase1_report.md - thieu: {', '.join(missing)}")

    if baseline and corrupted:
        generate_corruption_report(
            paths.comparison_report,
            baseline_metrics=baseline,
            corrupted_metrics=corrupted,
            repaired_metrics=repaired or {},
            corrupted_quality=_read(paths.quality_dir / "quality_corrupted.json") or {},
            repaired_quality=_read(paths.quality_dir / "quality_repaired.json") or {},
            corrupted_freshness=_read(paths.quality_dir / "freshness_corrupted.json") or {},
            repaired_freshness=_read(paths.quality_dir / "freshness_repaired.json") or {},
        )
        print(f"OK  {paths.comparison_report}")
        written += 1
    else:
        print("BO QUA corruption_report.md - chua co corrupted_metrics.json")

    if not written:
        sys.exit(1)


if __name__ == "__main__":
    main()
