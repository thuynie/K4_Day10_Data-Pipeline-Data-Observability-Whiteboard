from __future__ import annotations

import logging

from core.config import load_settings, require_llm_credentials
from core.utils import now_utc, write_json
from evaluation.metrics import evaluate_agent_pipeline, evaluate_pipeline
from evaluation.testset import build_test_set
from ingestion.cleaning import build_clean_dataframe
from ingestion.crossref import fetch_source_records
from observability.quality import build_freshness_report, run_data_quality_checks
from observability.reporting import generate_phase1_report
from retrieval.index import LocalEmbeddingIndex

logger = logging.getLogger(__name__)


def main() -> None:
    """Baseline pipeline end-to-end tren du lieu SACH.

    Toan bo artifact sinh ra o day la moc so sanh cho Pha 2. Ba thu bat buoc
    phai on dinh giua ba trang thai baseline / corrupted / repaired:
      - `data/eval/test_set.json`  (cung bo cau hoi)
      - cau hinh embedding          (cung model + so chieu)
      - cach tinh metric            (cung `evaluate_pipeline`)
    Neu mot trong ba thu do doi giua cac lan chay thi bang so sanh cuoi bai
    khong con y nghia.
    """
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s"
    )
    run_date = now_utc()

    # --- 1. Load settings -----------------------------------------------
    settings = load_settings()
    paths = settings.paths

    # Fail fast ngay tu dau thay vi chet o buoc evaluate. Ly do quan trong hon
    # la: `_judge_answer` co fallback heuristic khi khong goi duoc LLM, nen
    # thieu key se KHONG lam pipeline crash - no chay xong va cho ra
    # judge_accuracy tinh bang heuristic. Diem do khong so sanh duoc voi lan
    # chay co LLM that, ma nhin vao file metrics thi khong biet.
    require_llm_credentials(settings)

    logger.info("Project dir: %s", paths.project_dir)
    logger.info("LLM: %s / %s", settings.llm_provider, settings.model_name)
    logger.info("Embedding: %s (%dd)", settings.embedding_model, settings.embedding_dimensions)

    # --- 2. Load hoac fetch raw records ---------------------------------
    # `fetch_source_records` tu quyet dinh: REFRESH_SOURCE=1 thi goi API, nguoc
    # lai dung snapshot `data/raw/crossref_records.json` neu co. Giu snapshot la
    # co chu dich - buoc repair o Pha 2 phuc hoi tu chinh file raw nay.
    records = fetch_source_records(settings)
    logger.info("Raw records: %d", len(records))
    if not records:
        raise RuntimeError(
            "Khong lay duoc record nao tu Crossref va cung khong co snapshot. "
            "Kiem tra ket noi mang hoac chay lai voi REFRESH_SOURCE=1."
        )

    # --- 3 + 4. Clean data va ghi CSV/JSON ------------------------------
    # `build_clean_dataframe` tu ghi ra file khi duoc truyen path.
    clean_df = build_clean_dataframe(
        records,
        run_date=run_date,
        clean_csv_path=paths.clean_csv,
        clean_json_path=paths.clean_json,
    )
    dropped = len(records) - len(clean_df)
    logger.info("Clean rows: %d (drop %d ban ghi rac)", len(clean_df), dropped)
    if clean_df.empty:
        raise RuntimeError(
            "Cleaning loai het ban ghi. Kiem tra lai nguong loc trong cleaning.py "
            "(vi du yeu cau summary >= 100 ky tu) va chat luong abstract tu Crossref."
        )

    # --- 5. Build Chroma index ------------------------------------------
    # Truyen `embeddings_json` de index tu suy ra collection name "papers-baseline".
    # Pha 2 dung path khac -> collection khac -> ba trang thai khong de len nhau
    # trong cung mot Chroma store.
    index = LocalEmbeddingIndex.build(
        clean_df, settings, embeddings_output_path=paths.embeddings_json
    )
    logger.info("Index xong: collection=%s", index.collection_name)

    # --- 6. Tao hoac load evaluation set --------------------------------
    # Chi build khi chua co file hoac khi REFRESH_TEST_SET=1. Test set PHAI sinh
    # tu du lieu sach va giu nguyen cho ca ba trang thai: neu Pha 2 build lai
    # tren du lieu da hong thi ground_truth hong theo va phep so sanh mat co so.
    if settings.refresh_test_set or not paths.eval_testset.exists():
        test_set = build_test_set(clean_df, paths.eval_testset)
        logger.info("Tao test set moi: %d cau hoi -> %s", len(test_set), paths.eval_testset)
    else:
        logger.info("Dung lai test set san co: %s", paths.eval_testset)
        logger.info("(Dat REFRESH_TEST_SET=1 neu muon sinh lai.)")

    # --- 7. Evaluate -----------------------------------------------------
    bundle = evaluate_pipeline(
        settings,
        index,
        test_set_path=paths.eval_testset,
        metrics_output_path=paths.baseline_metrics,
        answers_output_path=paths.baseline_answers,
    )
    metrics = bundle.summary
    logger.info(
        "Baseline: hit_rate=%.4f token_f1=%.4f judge_acc=%.4f",
        metrics["retrieval_hit_rate"],
        metrics["mean_token_f1"],
        metrics["judge_accuracy"],
    )

    # `_judge_answer` KHONG nem loi khi khong goi duoc LLM - no lang le doi sang
    # heuristic token-overlap. Nhin vao metrics.json thi khong phan biet duoc.
    # Dem lai va bao to, vi judge_accuracy tinh bang heuristic khong so sanh
    # duoc voi lan chay co LLM that (het quota la roi vao truong hop nay).
    fallback_judges = sum(
        1 for item in bundle.answers if "Fallback heuristic judge" in item["judge"]["reasoning"]
    )
    if fallback_judges:
        logger.warning(
            "%d/%d cau dung heuristic judge (LLM khong goi duoc - vd het quota). "
            "judge_accuracy/mean_judge_score lan nay KHONG so sanh duoc voi lan "
            "chay co LLM. Chay lai sau khi quota reset neu can so lieu that.",
            fallback_judges,
            len(bundle.answers),
        )

    # --- 7b. Evaluate bang LLM agent -------------------------------------
    # Duong do thu hai tren CUNG test set. `evaluate_pipeline` o tren la
    # deterministic (khong goi LLM khi sinh cau tra loi) nen dung lam moc so
    # sanh cho Pha 2; con day moi tra loi duoc "agent that co lam duoc khong".
    agent_metrics = _run_agent_eval(settings, index, paths)

    # --- 8. Data quality checks va freshness report ---------------------
    quality = run_data_quality_checks(clean_df, settings, report_name="baseline")
    logger.info(
        "Quality: %s (%d/%d checks pass)",
        "PASS" if quality["success"] else "FAIL",
        quality["checks_passed"],
        quality["checks_total"],
    )

    freshness = build_freshness_report(clean_df, settings, paths.freshness_report)
    logger.info(
        "Freshness: %s (%d/%d dong stale)",
        freshness["status"],
        freshness["stale_rows"],
        freshness["total_rows"],
    )

    # --- 9. Markdown report ---------------------------------------------
    source_summary = {
        "source_api": settings.source_api,
        "source_query": settings.source_query,
        "source_filter": settings.source_filter,
        "max_results": settings.max_results,
        "raw_records": len(records),
        "clean_rows": len(clean_df),
        "dropped_rows": dropped,
        "embedding_model": settings.embedding_model,
        "embedding_dimensions": settings.embedding_dimensions,
        "collection_name": index.collection_name,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.model_name,
        "top_k": settings.top_k,
        # Ghi thang vao report: nguoi doc phai biet diem judge den tu LLM hay
        # tu heuristic fallback truoc khi trich dan con so.
        "judge_fallback_count": f"{fallback_judges}/{len(bundle.answers)}",
        "clean_csv": str(paths.clean_csv),
        "clean_json": str(paths.clean_json),
        "embeddings_manifest": str(paths.embeddings_json),
        "eval_testset": str(paths.eval_testset),
        "baseline_metrics": str(paths.baseline_metrics),
        "agent_metrics": str(paths.agent_metrics) if agent_metrics else "khong chay",
    }
    generate_phase1_report(
        paths.baseline_report,
        source_summary=source_summary,
        metrics=metrics,
        quality=quality,
        freshness=freshness,
        agent_metrics=agent_metrics,
    )
    logger.info("Report: %s", paths.baseline_report)
    logger.info("Phase 1 hoan tat.")


def _run_agent_eval(settings, index, paths) -> dict | None:
    """Chay agent tren toan bo test set. Khong duoc lam vo pipeline.

    Metric va report chinh da ghi ra file truoc buoc nay. Agent goi LLM nhieu
    vong tren moi cau nen de dinh rate limit hon han cac buoc khac - bat
    exception, ghi lai loi, roi di tiep.
    """
    if not settings.run_agent_eval:
        logger.info("Bo qua agent eval (RUN_AGENT_EVAL=0).")
        return None

    try:
        bundle = evaluate_agent_pipeline(
            settings,
            index,
            test_set_path=paths.eval_testset,
            metrics_output_path=paths.agent_metrics,
            answers_output_path=paths.agent_answers,
        )
    except Exception as exc:
        logger.warning("Agent eval that bai: %s: %s", type(exc).__name__, exc)
        write_json(paths.agent_metrics, {"error": f"{type(exc).__name__}: {exc}"})
        return None

    summary = bundle.summary
    logger.info(
        "Agent: hit_rate=%.4f token_f1=%.4f judge_acc=%.4f (%d cau loi)",
        summary["retrieval_hit_rate"],
        summary["mean_token_f1"],
        summary["judge_accuracy"],
        summary["agent_errors"],
    )
    if summary["agent_errors"]:
        logger.warning(
            "%d/%d cau agent khong tra loi duoc - metric agent lan nay bi keo xuong "
            "boi loi ha tang, khong phai boi chat luong du lieu.",
            summary["agent_errors"],
            summary["samples"],
        )
    return summary


