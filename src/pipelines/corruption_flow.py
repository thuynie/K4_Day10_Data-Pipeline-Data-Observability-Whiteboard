from __future__ import annotations

import logging

import pandas as pd

from core.config import load_settings, require_llm_credentials
from core.utils import now_utc, read_json
from evaluation.metrics import evaluate_pipeline
from ingestion.cleaning import build_clean_dataframe, save_clean_dataframe
from ingestion.corruption import corrupt_clean_dataframe, load_test_set_doc_ids
from ingestion.crossref import fetch_source_records
from observability.quality import build_freshness_report, run_data_quality_checks
from observability.reporting import generate_corruption_report
from retrieval.index import LocalEmbeddingIndex

logger = logging.getLogger(__name__)


def main() -> None:
    """Corruption -> evaluate -> repair -> compare flow (Pha 2).

    Ba trang thai baseline / corrupted / repaired chi duoc phep khac nhau o
    CHAT LUONG DU LIEU. Vi vay flow nay tai su dung nguyen xi tu Pha 1:
      - `data/eval/test_set.json` (KHONG build lai - build lai tren du lieu hong
        thi ground_truth hong theo va phep so sanh mat co so)
      - cung `evaluate_pipeline` deterministic (khong dung agent eval: agent
        khong deterministic nen chenh lech metric se lan voi noise cua LLM)
      - cung embedding model / so chieu / top_k tu settings
    Moi trang thai dung mot Chroma collection rieng, suy ra tu duong dan
    embeddings manifest, nen khong de len nhau.
    """
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s"
    )
    run_date = now_utc()

    # --- 1. Load settings + artifact cua Pha 1 --------------------------
    settings = load_settings()
    paths = settings.paths

    # Fail fast: `_judge_answer` co fallback heuristic khi khong goi duoc LLM
    # nen thieu key se KHONG lam pipeline crash, no chay xong va cho ra
    # judge_accuracy tinh bang heuristic - so sanh voi baseline se sai.
    require_llm_credentials(settings)

    logger.info("Project dir: %s", paths.project_dir)
    logger.info("Embedding: %s (%dd)", settings.embedding_model, settings.embedding_dimensions)

    if not paths.baseline_metrics.exists():
        raise RuntimeError(
            f"Chua co baseline metrics ({paths.baseline_metrics}). "
            "Chay script/run_phase1.py truoc - Pha 2 khong co moc so sanh thi vo nghia."
        )
    if not paths.clean_csv.exists():
        raise RuntimeError(
            f"Chua co cleaned dataset ({paths.clean_csv}). Chay script/run_phase1.py truoc."
        )
    if not paths.eval_testset.exists():
        raise RuntimeError(
            f"Chua co frozen test set ({paths.eval_testset}). Chay script/run_phase1.py truoc. "
            "TUYET DOI khong build lai test set o Pha 2."
        )

    baseline_metrics = read_json(paths.baseline_metrics)
    # Doc lai CHINH file baseline da sinh ra baseline_metrics, khong rebuild tu
    # raw: neu snapshot raw doi giua hai lan chay thi corrupted se lech baseline
    # vi ly do khac chu khong phai vi corruption.
    clean_df = pd.read_csv(paths.clean_csv)
    logger.info("Baseline: %d dong, hit_rate=%.4f", len(clean_df), baseline_metrics["retrieval_hit_rate"])

    testset_doc_ids = load_test_set_doc_ids(paths.eval_testset)
    logger.info("Frozen test set: %d tai lieu duoc hoi toi", len(testset_doc_ids))

    # --- 2 + 3. Tao corrupted dataframe va ghi artifact -----------------
    # `corrupt_clean_dataframe` tu ghi CSV/JSON/log khi duoc truyen path.
    # Truyen `test_set_doc_ids` de moi kich ban corruption dung trung it nhat
    # mot tai lieu nam trong bo cau hoi - neu khong, metric se khong doi.
    corrupted_df = corrupt_clean_dataframe(
        clean_df,
        paths.corruption_log,
        run_date=run_date,
        test_set_doc_ids=testset_doc_ids,
        output_csv_path=paths.corrupted_clean_csv,
        output_json_path=paths.corrupted_clean_json,
    )
    corruption_log = read_json(paths.corruption_log)
    overlap = corruption_log["testset_overlap"]
    logger.info(
        "Corrupted: %d -> %d dong | %s",
        corruption_log["rows_before"],
        corruption_log["rows_after"],
        ", ".join(f"{k}={v}" for k, v in corruption_log["summary"].items()),
    )
    logger.info(
        "Overlap voi test set: %d/%d tai lieu bi hong -> %s",
        overlap["corrupted_testset_doc_count"],
        overlap["testset_doc_count"],
        "OK" if overlap["ok"] else "THIEU",
    )
    if not overlap["ok"]:
        # Canh bao chu khong raise: pipeline van chay duoc, nhung nguoi doc
        # report phai biet vi sao metric co the khong nhuc nhich.
        logger.warning(
            "Cac kich ban KHONG cham vao test set: %s. Metric cua chung se khong "
            "the hien trong bang so sanh. Tang cuong do corruption hoac kiem tra "
            "lai test_set.json.",
            overlap["scenarios_without_testset_hit"] or "(test set rong)",
        )
    logger.info("Corrupted artifacts: %s | %s", paths.corrupted_clean_csv, paths.corruption_log)

    # --- 4. Rebuild index tren du lieu hong va evaluate ------------------
    # Bat buoc phai build lai embedding tu `text_for_embedding` da hong. Neu
    # dung lai index baseline thi retrieval van chay tren vector SACH va toan
    # bo Pha 2 do nghia.
    corrupted_metrics = _index_and_evaluate(
        settings,
        corrupted_df,
        label="corrupted",
        embeddings_path=paths.corrupted_embeddings_json,
        metrics_path=paths.corrupted_metrics,
        answers_path=paths.corrupted_answers,
    )

    # --- 5. Quality checks + freshness tren corrupted --------------------
    corrupted_quality = run_data_quality_checks(corrupted_df, settings, report_name="corrupted")
    corrupted_freshness = build_freshness_report(
        corrupted_df, settings, paths.quality_dir / "freshness_corrupted.json"
    )
    _log_observability("corrupted", corrupted_quality, corrupted_freshness)

    # --- 6. Repair: dung lai toan bo ingestion tu raw records ------------
    # "Sua" o day khong phai va tung cot, ma la chay lai dung pipeline sach tu
    # snapshot `data/raw/crossref_records.json`. Do la ly do Pha 1 giu snapshot.
    records = fetch_source_records(settings)
    if not records:
        raise RuntimeError(
            "Khong co raw record de repair. Kiem tra data/raw/crossref_records.json "
            "hoac chay lai voi REFRESH_SOURCE=1."
        )
    repaired_df = build_clean_dataframe(records, run_date=run_date)
    save_clean_dataframe(repaired_df, paths.repaired_clean_csv, paths.repaired_clean_json)
    logger.info("Repaired: %d dong tu %d raw records -> %s", len(repaired_df), len(records), paths.repaired_clean_csv)
    if len(repaired_df) != len(clean_df):
        # Repair phai dua dataset ve dung kich thuoc baseline. Lech o day nghia
        # la snapshot raw da thay doi -> cot "Repaired" trong report khong con
        # so sanh duoc sat voi baseline.
        logger.warning(
            "Repaired co %d dong nhung baseline co %d dong. Snapshot raw da doi "
            "giua hai lan chay - doc cot Repaired trong report voi luu y nay.",
            len(repaired_df),
            len(clean_df),
        )

    # --- 7. Evaluate repaired -------------------------------------------
    repaired_metrics = _index_and_evaluate(
        settings,
        repaired_df,
        label="repaired",
        embeddings_path=paths.repaired_embeddings_json,
        metrics_path=paths.repaired_metrics,
        answers_path=paths.repaired_answers,
    )

    repaired_quality = run_data_quality_checks(repaired_df, settings, report_name="repaired")
    repaired_freshness = build_freshness_report(
        repaired_df, settings, paths.quality_dir / "freshness_repaired.json"
    )
    _log_observability("repaired", repaired_quality, repaired_freshness)

    # --- 8. Comparison report -------------------------------------------
    generate_corruption_report(
        paths.comparison_report,
        baseline_metrics=baseline_metrics,
        corrupted_metrics=corrupted_metrics,
        repaired_metrics=repaired_metrics,
        corrupted_quality=corrupted_quality,
        repaired_quality=repaired_quality,
        corrupted_freshness=corrupted_freshness,
        repaired_freshness=repaired_freshness,
    )
    logger.info("Report: %s", paths.comparison_report)

    _log_verdict(baseline_metrics, corrupted_metrics, repaired_metrics)
    logger.info("Phase 2 hoan tat.")


def _index_and_evaluate(
    settings,
    df: pd.DataFrame,
    label: str,
    embeddings_path,
    metrics_path,
    answers_path,
) -> dict:
    """Build index rieng cho mot trang thai roi chay evaluate tren frozen test set."""
    index = LocalEmbeddingIndex.build(df, settings, embeddings_output_path=embeddings_path)
    logger.info("[%s] Index xong: collection=%s (%d docs)", label, index.collection_name, len(df))

    bundle = evaluate_pipeline(
        settings,
        index,
        test_set_path=settings.paths.eval_testset,
        metrics_output_path=metrics_path,
        answers_output_path=answers_path,
    )
    summary = bundle.summary
    logger.info(
        "[%s] hit_rate=%.4f token_f1=%.4f judge_acc=%.4f",
        label,
        summary["retrieval_hit_rate"],
        summary["mean_token_f1"],
        summary["judge_accuracy"],
    )

    # Judge im lang doi sang heuristic khi khong goi duoc LLM (vd het quota).
    # Neu mot trang thai dung LLM that ma trang thai kia dung heuristic thi
    # judge_accuracy giua hai cot KHONG so sanh duoc - phai bao ra.
    fallback = sum(
        1 for item in bundle.answers if "Fallback heuristic judge" in item["judge"]["reasoning"]
    )
    if fallback:
        logger.warning(
            "[%s] %d/%d cau dung heuristic judge (LLM khong goi duoc). "
            "judge_accuracy/mean_judge_score cua cot nay khong so sanh duoc voi "
            "cot chay bang LLM that.",
            label,
            fallback,
            len(bundle.answers),
        )
    return summary


def _log_observability(label: str, quality: dict, freshness: dict) -> None:
    logger.info(
        "[%s] Quality: %s (%d/%d checks pass) | failed=%s",
        label,
        "PASS" if quality["success"] else "FAIL",
        quality["checks_passed"],
        quality["checks_total"],
        quality["failed_check_names"] or "-",
    )
    logger.info(
        "[%s] Freshness: %s (%d/%d dong stale, max_age=%s ngay)",
        label,
        freshness["status"],
        freshness["stale_rows"],
        freshness["total_rows"],
        freshness["max_age_days"],
    )


def _log_verdict(baseline: dict, corrupted: dict, repaired: dict) -> None:
    """In ket luan ngan ra console de khong phai mo file report moi biet ket qua."""
    for key in ("retrieval_hit_rate", "mean_token_f1", "judge_accuracy"):
        b, c, r = baseline.get(key), corrupted.get(key), repaired.get(key)
        if not all(isinstance(v, (int, float)) for v in (b, c, r)):
            continue
        logger.info(
            "%-20s baseline=%.4f corrupted=%.4f (%+.4f) repaired=%.4f (%+.4f vs baseline)",
            key, b, c, c - b, r, r - b,
        )

    hit_b, hit_c = baseline.get("retrieval_hit_rate"), corrupted.get("retrieval_hit_rate")
    if isinstance(hit_b, (int, float)) and isinstance(hit_c, (int, float)) and hit_c >= hit_b:
        logger.warning(
            "Corruption KHONG lam giam retrieval hit rate. Kiem tra: index da rebuild "
            "tu text_for_embedding hong chua, va corruption co dung trung test set chua."
        )
