from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path

import numpy as np
import pandas as pd

from core.utils import build_embedding_text, now_utc, write_json


@dataclass(frozen=True)
class CorruptionConfig:
    """Tham so cua tung dang corruption.

    De o mot cho de bao cao co the trich dan chinh xac "da hong bao nhieu, kieu
    gi", va de thay doi cuong do ma khong phai sua logic.
    """

    seed: int = 42
    drop_latest_n: int = 4          # 1. thieu ban ghi moi nhat
    blank_summary_frac: float = 0.20  # 2. summary rong
    noise_frac: float = 0.20          # 3. text nhieu
    truncate_title_frac: float = 0.15  # 4. title bi cat
    stale_frac: float = 0.20           # 5. ngay bi lam cu
    stale_year: int = 2000             # doi published ve nam 2000 (yeu cau de bai)
    truncate_title_chars: int = 18
    duplicate_n: int = 3               # 6. so ban ghi bi nhan doi
    # BAT BUOC theo de bai: moi kich ban phai dung trung it nhat ngan nay tai
    # lieu nam trong frozen test set. Neu chi lam hong nhung tai lieu khong bao
    # gio duoc hoi toi, metric se khong nhuc nhich va ca Pha 2 vo nghia.
    min_testset_hits: int = 1


# Cac manh "rac" mo phong loi that: tag HTML sot lai, ky tu loi encoding,
# boilerplate cua nha xuat ban, ky tu dieu khien.
NOISE_FRAGMENTS = (
    "<div class='ltx_para'>",
    "&amp;#x2028;",
    "���",
    "COPYRIGHT (C) PUBLISHER. ALL RIGHTS RESERVED. DOWNLOADED FROM PROXY 10.0.0.1",
    "|||| OCR_CONFIDENCE=0.12 ||||",
    "Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod.",
)

# Bang ky tu de sinh chuoi rac ngau nhien (de bai: "chen cac ky tu ngau nhien").
NOISE_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#@$%^&*~"


def load_test_set_doc_ids(test_set_path) -> set[str]:
    """Doc paper_id cua frozen test set (C2).

    Dung de dam bao corruption va bo cau hoi CO GIAO NHAU. Neu file khong ton
    tai thi tra ve set rong - corruption van chay duoc (huu ich cho unit test),
    chi la mat bao dam overlap va log se ghi ro dieu do.
    """
    path = Path(test_set_path)
    if not path.exists():
        return set()
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    doc_ids: set[str] = set()
    for item in items or []:
        for doc_id in item.get("ground_truth_doc_ids") or []:
            if str(doc_id).strip():
                doc_ids.add(str(doc_id).strip())
    return doc_ids


def _pick(
    rng: np.random.Generator,
    pool: list,
    k: int,
    priority: set | None = None,
    min_priority: int = 0,
) -> list:
    """Lay ngau nhien k phan tu tu pool va XOA khoi pool.

    Xoa khoi pool de cac tap bi hong KHONG chong nhau. Nho vay corruption log
    quy duoc moi dong ve dung mot nguyen nhan; neu de chong nhau thi khi metric
    tut, ban khong tach duoc do summary rong hay do title bi cat.

    `priority` la tap chi muc cua cac dong nam trong frozen test set. Lay
    `min_priority` phan tu tu do TRUOC roi moi boc ngau nhien phan con lai, nen
    kich ban chac chan cham vao it nhat mot tai lieu se bi hoi toi luc eval.
    """
    k = max(0, min(k, len(pool)))
    if k == 0:
        return []

    chosen: list = []
    if priority and min_priority > 0:
        candidates = [i for i in pool if i in priority]
        take = min(min_priority, k, len(candidates))
        if take:
            chosen = [int(c) for c in rng.choice(candidates, size=take, replace=False)]
            for c in chosen:
                pool.remove(c)

    remaining = k - len(chosen)
    if remaining > 0 and pool:
        more = [
            int(c)
            for c in rng.choice(pool, size=min(remaining, len(pool)), replace=False)
        ]
        for c in more:
            pool.remove(c)
        chosen.extend(more)
    return chosen


def _pick_newest(
    pool: list,
    k: int,
    recency_order: list,
    priority: set | None = None,
    min_priority: int = 0,
) -> list:
    """Chon k dong MOI NHAT con lai trong pool (khong dung rng).

    De bai yeu cau lam cu "cac tai lieu moi", nen buoc stale phai boc theo do
    moi chu khong boc ngau nhien. `recency_order` la danh sach chi muc da sap
    xep published giam dan. Van giu bao dam overlap voi test set.
    """
    k = max(0, min(k, len(pool)))
    if k == 0:
        return []

    pool_set = set(pool)
    ordered = [i for i in recency_order if i in pool_set]

    chosen: list = []
    if priority and min_priority > 0:
        for i in ordered:
            if len(chosen) >= min(min_priority, k):
                break
            if i in priority:
                chosen.append(i)

    for i in ordered:
        if len(chosen) >= k:
            break
        if i not in chosen:
            chosen.append(i)

    for c in chosen:
        pool.remove(c)
    return chosen


def _random_garbage(rng: np.random.Generator, length: int = 24) -> str:
    """Sinh mot chuoi ky tu ngau nhien khong co nghia."""
    chars = rng.choice(list(NOISE_ALPHABET), size=length, replace=True)
    return "".join(str(c) for c in chars)


def _inject_noise(rng: np.random.Generator, text: str) -> str:
    """Chen manh rac + ky tu ngau nhien vao dau va giua doan text."""
    frag_a = str(rng.choice(NOISE_FRAGMENTS))
    frag_b = f"{rng.choice(NOISE_FRAGMENTS)} {_random_garbage(rng)}"
    words = str(text).split()
    if len(words) < 4:
        return f"{frag_a} {text} {frag_b}".strip()
    mid = len(words) // 2
    return " ".join([frag_a, *words[:mid], frag_b, *words[mid:]])


def _to_stale_year(value: str, year: int) -> str | None:
    """Doi nam cua mot ngay YYYY-MM-DD ve `year`, giu nguyen thang/ngay."""
    try:
        old_dt = datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None
    try:
        new_dt = old_dt.replace(year=year)
    except ValueError:
        # 29/02 cua nam nhuan doi ve nam khong nhuan -> lui ve 28/02.
        new_dt = old_dt.replace(year=year, day=28)
    return new_dt.strftime("%Y-%m-%d")


def corrupt_clean_dataframe(
    df: pd.DataFrame,
    output_log_path,
    config: CorruptionConfig | None = None,
    run_date: datetime | None = None,
    test_set_path=None,
    test_set_doc_ids: set[str] | None = None,
    output_csv_path=None,
    output_json_path=None,
) -> pd.DataFrame:
    """Chu dong tao loi du lieu tren cleaned dataframe, co seed va co log.

    Tra ve dataframe da hong. Log chi tiet duoc ghi ra `output_log_path` de
    buoc so sanh baseline / corrupted / repaired co bang chung doi chieu.

    `test_set_path` / `test_set_doc_ids`: frozen test set (C2). Moi kich ban se
    uu tien lam hong cac tai lieu nam trong do (>= `config.min_testset_hits`),
    dam bao yeu cau "corruption phai overlap voi bo cau hoi test".
    """
    config = config or CorruptionConfig()
    rng = np.random.default_rng(config.seed)
    run_dt = (run_date or now_utc()).replace(tzinfo=None)

    target_ids = set(test_set_doc_ids or set())
    if not target_ids and test_set_path is not None:
        target_ids = load_test_set_doc_ids(test_set_path)

    corrupted = df.copy(deep=True).reset_index(drop=True)
    rows_before = len(corrupted)
    events: list[dict] = []

    def id_of(index_list) -> list[str]:
        if len(index_list) == 0:
            return []
        return [str(v) for v in corrupted.loc[list(index_list), "paper_id"].tolist()]

    def log(kind: str, paper_ids, detail: str, **extra) -> None:
        ids = [str(p) for p in paper_ids]
        hits = sorted(set(ids) & target_ids)
        events.append(
            {
                "type": kind,
                "count": len(ids),
                "paper_ids": ids,
                # Bang chung cho yeu cau overlap: kich ban nay cham vao nhung
                # tai lieu nao cua frozen test set.
                "testset_hits": hits,
                "testset_hit_count": len(hits),
                "detail": detail,
                **extra,
            }
        )

    if corrupted.empty:
        _write_log(output_log_path, config, rows_before, 0, events, target_ids)
        return corrupted

    # Chi muc cac dong nam trong frozen test set, tinh trong khong gian chi muc
    # cua `corrupted` (da reset_index) - dung lam `priority` cho moi buoc pick.
    def testset_indices(frame: pd.DataFrame) -> set[int]:
        if not target_ids:
            return set()
        mask = frame["paper_id"].astype(str).isin(target_ids)
        return {int(i) for i in frame.index[mask]}

    # ------------------------------------------------------------------
    # 1. Drop mot so latest records
    #    Mo phong ingestion job chet giua chung / API tra thieu trang cuoi.
    #    Co tinh chon ban MOI NHAT vi day la loi doc nhat: dataset van "day"
    #    va van pass moi check ve null, nhung agent tra loi sai o dung nhung
    #    cau hoi ve nghien cuu moi -> chi freshness check moi bat duoc.
    # ------------------------------------------------------------------
    ordered = corrupted.sort_values("published", ascending=False)
    drop_idx = list(ordered.head(config.drop_latest_n).index)
    dropped_ids = corrupted.loc[drop_idx, "paper_id"].tolist()
    dropped_dates = corrupted.loc[drop_idx, "published"].astype(str).tolist()
    corrupted = corrupted.drop(index=drop_idx).reset_index(drop=True)
    log(
        "drop_latest_records",
        dropped_ids,
        f"Xoa {len(dropped_ids)} ban ghi co published moi nhat.",
        dropped_published=dropped_dates,
    )

    # Pool chi muc con lai; cac buoc 2-5 boc tu pool nay va khong chong nhau.
    pool = list(corrupted.index)
    n = len(pool)
    priority = testset_indices(corrupted)
    # Thu tu do moi cua phan con lai - buoc 5 (stale) boc tu day.
    recency_order = list(corrupted.sort_values("published", ascending=False).index)

    # ------------------------------------------------------------------
    # 5. Lam published date ve nam 2000  (chay TRUOC cac buoc boc ngau nhien)
    #    De bai: "thay doi ngay xuat ban cua cac tai lieu MOI ve nam 2000".
    #    Vi vay phai boc theo do moi, va phai boc truoc khi pool bi cac buoc
    #    ngau nhien an mat cac dong moi nhat.
    #    Noi dung van dung 100%, chi metadata sai -> day la ca chi de chung
    #    minh vi sao can freshness report rieng chu khong chi check null.
    # ------------------------------------------------------------------
    stale_idx = _pick_newest(
        pool,
        round(n * config.stale_frac),
        recency_order,
        priority=priority,
        min_priority=config.min_testset_hits,
    )
    stale_before: list[str] = []
    for i in stale_idx:
        stale_before.append(str(corrupted.at[i, "published"]))
        for col in ("published", "updated"):
            if col not in corrupted.columns:
                continue
            new_value = _to_stale_year(corrupted.at[i, col], config.stale_year)
            if new_value is not None:
                corrupted.at[i, col] = new_value
    log(
        "stale_published_date",
        id_of(stale_idx),
        f"Doi published/updated cua cac ban ghi moi nhat ve nam {config.stale_year}.",
        published_before=stale_before,
        published_after=[str(corrupted.at[i, "published"]) for i in stale_idx],
    )

    # ------------------------------------------------------------------
    # 2. Blank summary o mot so dong
    #    Abstract rong -> chunk gan nhu khong con tin hieu ngu nghia.
    #    Retrieval van tra ve document (khong he loi) nhung context rong,
    #    LLM buoc phai bia -> hit_rate co the giu nguyen ma faithfulness tut.
    # ------------------------------------------------------------------
    blank_idx = _pick(
        rng,
        pool,
        round(n * config.blank_summary_frac),
        priority=priority,
        min_priority=config.min_testset_hits,
    )
    if blank_idx:
        corrupted.loc[blank_idx, "summary"] = ""
    log(
        "blank_summary",
        id_of(blank_idx),
        "Xoa trang cot summary (abstract mat khi parse).",
    )

    # ------------------------------------------------------------------
    # 3. Inject noise vao text
    #    Tag HTML sot lai, ky tu ngau nhien, boilerplate nha xuat ban. Noise
    #    di vao `summary` roi buoc 7 rebuild lai `text_for_embedding`, nen rac
    #    nam dung trong chuoi duoc dem di embed.
    #    Lam loang embedding: vector bi keo ve phia tu rac, do tuong dong
    #    voi cau hoi that giam -> tut retrieval_hit_rate.
    # ------------------------------------------------------------------
    noise_idx = _pick(
        rng,
        pool,
        round(n * config.noise_frac),
        priority=priority,
        min_priority=config.min_testset_hits,
    )
    for i in noise_idx:
        corrupted.at[i, "summary"] = _inject_noise(rng, corrupted.at[i, "summary"])
    log(
        "inject_noise",
        id_of(noise_idx),
        "Chen HTML/boilerplate/ky tu ngau nhien vao summary -> text_for_embedding.",
        fragments_used=list(NOISE_FRAGMENTS),
    )

    # ------------------------------------------------------------------
    # 4. Lam title bi truncate
    #    Mo phong cot VARCHAR bi gioi han hoac CSV bi cat. Title la tin hieu
    #    manh nhat trong text_for_embedding nen cat title lam lech match rat ro.
    # ------------------------------------------------------------------
    trunc_idx = _pick(
        rng,
        pool,
        round(n * config.truncate_title_frac),
        priority=priority,
        min_priority=config.min_testset_hits,
    )
    for i in trunc_idx:
        original = str(corrupted.at[i, "title"])
        corrupted.at[i, "title"] = original[: config.truncate_title_chars].rstrip() + "..."
    log(
        "truncate_title",
        id_of(trunc_idx),
        f"Cat title con {config.truncate_title_chars} ky tu.",
    )

    # ------------------------------------------------------------------
    # 6. Add duplicate rows
    #    Mo phong pipeline chay lai ma khong idempotent. Duplicate chiem cho
    #    trong top-k cua retriever: cung mot tai lieu tra ve nhieu lan lam
    #    giam do da dang context -> giam kha nang tra loi dung.
    #    Uu tien nhan doi tai lieu trong test set de kich ban nay cung do duoc.
    # ------------------------------------------------------------------
    dup_pool = list(corrupted.index)
    dup_idx = _pick(
        rng,
        dup_pool,
        min(config.duplicate_n, len(corrupted)),
        priority=testset_indices(corrupted),
        min_priority=config.min_testset_hits,
    )
    dup_ids = id_of(dup_idx)
    if dup_idx:
        duplicates = corrupted.loc[dup_idx].copy()
        corrupted = pd.concat([corrupted, duplicates], ignore_index=True)
    log(
        "duplicate_rows",
        dup_ids,
        "Nhan doi ban ghi, giu nguyen paper_id (vi pham unique key).",
    )

    # ------------------------------------------------------------------
    # 7. Rebuild `text_for_embedding` + cac cot dan xuat
    #    Bat buoc: neu khong rebuild, embedding van sinh tu text SACH cu va
    #    toan bo Pha 2 do nghia - metric se khong nhuc nhich va ban khong
    #    chung minh duoc gi. Dung chung `build_embedding_text` voi cleaning.py
    #    de format hai ben giong het nhau.
    # ------------------------------------------------------------------
    corrupted = corrupted.reset_index(drop=True)
    corrupted["summary"] = corrupted["summary"].fillna("").astype(str)
    corrupted["title"] = corrupted["title"].fillna("").astype(str)
    corrupted["summary_chars"] = corrupted["summary"].str.len()
    corrupted["age_days"] = corrupted["published"].map(
        lambda v: _age_days(str(v), run_dt)
    )
    corrupted["text_for_embedding"] = corrupted.apply(
        lambda r: build_embedding_text(
            r.get("title", ""),
            r.get("authors_joined", ""),
            r.get("categories_joined", ""),
            r.get("summary", ""),
        ),
        axis=1,
    )

    # ------------------------------------------------------------------
    # 8. Ghi artifact: corrupted dataset + corruption log
    # ------------------------------------------------------------------
    if output_csv_path is not None:
        path = Path(output_csv_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        corrupted.to_csv(path, index=False, encoding="utf-8")
    if output_json_path is not None:
        path = Path(output_json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        corrupted.to_json(path, orient="records", indent=2, force_ascii=False)

    _write_log(output_log_path, config, rows_before, len(corrupted), events, target_ids)
    return corrupted


def _age_days(published: str, run_dt: datetime) -> int:
    try:
        pub = datetime.strptime(published[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return -1  # -1 = khong parse duoc, khac han voi "rat cu"
    return (run_dt - pub).days


def _write_log(
    output_log_path,
    config: CorruptionConfig,
    rows_before: int,
    rows_after: int,
    events: list[dict],
    testset_doc_ids: set[str] | None = None,
) -> None:
    """Log phai du de tai hien va de doi chieu voi metrics.

    Ghi ca seed + config (tai hien duoc), so dong truoc/sau (kiem tra chenh
    lech), paper_id cu the cua tung dang loi (truy nguoc duoc cau tra loi sai
    ve dung ban ghi nao bi hong), va bang chung overlap voi frozen test set.
    """
    testset_doc_ids = testset_doc_ids or set()
    touched = sorted({pid for e in events for pid in e["testset_hits"]})
    scenarios_without_hit = [
        e["type"] for e in events if e["count"] > 0 and e["testset_hit_count"] == 0
    ]
    payload = {
        "generated_at": now_utc().isoformat(),
        "config": asdict(config),
        "rows_before": rows_before,
        "rows_after": rows_after,
        "row_delta": rows_after - rows_before,
        "summary": {e["type"]: e["count"] for e in events},
        # Kiem chung yeu cau: corruption phai dung trung frozen test set (C2).
        "testset_overlap": {
            "testset_doc_ids": sorted(testset_doc_ids),
            "testset_doc_count": len(testset_doc_ids),
            "corrupted_testset_doc_ids": touched,
            "corrupted_testset_doc_count": len(touched),
            "scenarios_without_testset_hit": scenarios_without_hit,
            "ok": bool(testset_doc_ids) and not scenarios_without_hit,
        },
        "events": events,
    }
    write_json(Path(output_log_path), payload)
