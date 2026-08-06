from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
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
    stale_shift_days: int = 1200       # day ra ngoai freshness threshold (180)
    truncate_title_chars: int = 18
    duplicate_n: int = 3               # 6. so ban ghi bi nhan doi


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


def _pick(rng: np.random.Generator, pool: list, k: int) -> list:
    """Lay ngau nhien k phan tu tu pool va XOA khoi pool.

    Xoa khoi pool de cac tap bi hong KHONG chong nhau. Nho vay corruption log
    quy duoc moi dong ve dung mot nguyen nhan; neu de chong nhau thi khi metric
    tut, ban khong tach duoc do summary rong hay do title bi cat.
    """
    k = max(0, min(k, len(pool)))
    if k == 0:
        return []
    chosen = list(rng.choice(pool, size=k, replace=False))
    for c in chosen:
        pool.remove(c)
    return chosen


def _inject_noise(rng: np.random.Generator, text: str) -> str:
    """Chen 2 manh rac vao dau va giua doan text."""
    frag_a = str(rng.choice(NOISE_FRAGMENTS))
    frag_b = str(rng.choice(NOISE_FRAGMENTS))
    words = str(text).split()
    if len(words) < 4:
        return f"{frag_a} {text} {frag_b}".strip()
    mid = len(words) // 2
    return " ".join([frag_a, *words[:mid], frag_b, *words[mid:]])


def corrupt_clean_dataframe(
    df: pd.DataFrame,
    output_log_path,
    config: CorruptionConfig | None = None,
    run_date: datetime | None = None,
) -> pd.DataFrame:
    """Chu dong tao loi du lieu tren cleaned dataframe, co seed va co log.

    Tra ve dataframe da hong. Log chi tiet duoc ghi ra `output_log_path` de
    buoc so sanh baseline / corrupted / repaired co bang chung doi chieu.
    """
    config = config or CorruptionConfig()
    rng = np.random.default_rng(config.seed)
    run_dt = (run_date or now_utc()).replace(tzinfo=None)

    corrupted = df.copy(deep=True).reset_index(drop=True)
    rows_before = len(corrupted)
    events: list[dict] = []

    def log(kind: str, paper_ids, detail: str, **extra) -> None:
        ids = [str(p) for p in paper_ids]
        events.append(
            {"type": kind, "count": len(ids), "paper_ids": ids, "detail": detail, **extra}
        )

    if corrupted.empty:
        _write_log(output_log_path, config, rows_before, 0, events)
        return corrupted

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

    # ------------------------------------------------------------------
    # 2. Blank summary o mot so dong
    #    Abstract rong -> chunk gan nhu khong con tin hieu ngu nghia.
    #    Retrieval van tra ve document (khong he loi) nhung context rong,
    #    LLM buoc phai bia -> hit_rate co the giu nguyen ma faithfulness tut.
    # ------------------------------------------------------------------
    blank_idx = _pick(rng, pool, round(n * config.blank_summary_frac))
    if blank_idx:
        corrupted.loc[blank_idx, "summary"] = ""
    log(
        "blank_summary",
        corrupted.loc[blank_idx, "paper_id"],
        "Xoa trang cot summary (abstract mat khi parse).",
    )

    # ------------------------------------------------------------------
    # 3. Inject noise vao text
    #    Tag HTML sot lai, ky tu loi encoding, boilerplate nha xuat ban.
    #    Lam loang embedding: vector bi keo ve phia tu rac, do tuong dong
    #    voi cau hoi that giam -> tut retrieval_hit_rate.
    # ------------------------------------------------------------------
    noise_idx = _pick(rng, pool, round(n * config.noise_frac))
    for i in noise_idx:
        corrupted.at[i, "summary"] = _inject_noise(rng, corrupted.at[i, "summary"])
    log(
        "inject_noise",
        corrupted.loc[noise_idx, "paper_id"],
        "Chen HTML/boilerplate/ky tu loi encoding vao summary.",
        fragments_used=list(NOISE_FRAGMENTS),
    )

    # ------------------------------------------------------------------
    # 4. Lam title bi truncate
    #    Mo phong cot VARCHAR bi gioi han hoac CSV bi cat. Title la tin hieu
    #    manh nhat trong text_for_embedding nen cat title lam lech match rat ro.
    # ------------------------------------------------------------------
    trunc_idx = _pick(rng, pool, round(n * config.truncate_title_frac))
    for i in trunc_idx:
        original = str(corrupted.at[i, "title"])
        corrupted.at[i, "title"] = original[: config.truncate_title_chars].rstrip() + "..."
    log(
        "truncate_title",
        corrupted.loc[trunc_idx, "paper_id"],
        f"Cat title con {config.truncate_title_chars} ky tu.",
    )

    # ------------------------------------------------------------------
    # 5. Lam published date cu di
    #    Day ngay lui {stale_shift_days} ngay, vuot nguong freshness (180).
    #    Noi dung van dung 100%, chi metadata sai -> day la ca chi de chung
    #    minh vi sao can freshness report rieng chu khong chi check null.
    # ------------------------------------------------------------------
    stale_idx = _pick(rng, pool, round(n * config.stale_frac))
    for i in stale_idx:
        for col in ("published", "updated"):
            if col not in corrupted.columns:
                continue
            try:
                old_dt = datetime.strptime(str(corrupted.at[i, col])[:10], "%Y-%m-%d")
            except ValueError:
                continue
            new_dt = old_dt - timedelta(days=config.stale_shift_days)
            corrupted.at[i, col] = new_dt.strftime("%Y-%m-%d")
    log(
        "stale_published_date",
        corrupted.loc[stale_idx, "paper_id"],
        f"Lui published/updated {config.stale_shift_days} ngay.",
    )

    # ------------------------------------------------------------------
    # 6. Add duplicate rows
    #    Mo phong pipeline chay lai ma khong idempotent. Duplicate chiem cho
    #    trong top-k cua retriever: cung mot tai lieu tra ve nhieu lan lam
    #    giam do da dang context -> giam kha nang tra loi dung.
    # ------------------------------------------------------------------
    dup_n = min(config.duplicate_n, len(corrupted))
    dup_idx = list(rng.choice(list(corrupted.index), size=dup_n, replace=False)) if dup_n else []
    if dup_idx:
        duplicates = corrupted.loc[dup_idx].copy()
        corrupted = pd.concat([corrupted, duplicates], ignore_index=True)
    log(
        "duplicate_rows",
        corrupted.loc[dup_idx, "paper_id"] if dup_idx else [],
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
    # 8. Ghi corruption log
    # ------------------------------------------------------------------
    _write_log(output_log_path, config, rows_before, len(corrupted), events)
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
) -> None:
    """Log phai du de tai hien va de doi chieu voi metrics.

    Ghi ca seed + config (tai hien duoc), so dong truoc/sau (kiem tra chenh
    lech), va paper_id cu the cua tung dang loi (truy nguoc duoc cau tra loi
    sai ve dung ban ghi nao bi hong).
    """
    payload = {
        "generated_at": now_utc().isoformat(),
        "config": asdict(config),
        "rows_before": rows_before,
        "rows_after": rows_after,
        "row_delta": rows_after - rows_before,
        "summary": {e["type"]: e["count"] for e in events},
        "events": events,
    }
    write_json(Path(output_log_path), payload)
