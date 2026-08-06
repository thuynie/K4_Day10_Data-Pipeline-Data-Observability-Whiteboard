from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

import numpy as np
import pandas as pd

# Duoi nguong nay thi eval set khong con y nghia thong ke: voi corpus qua nho,
# top_k cua retriever gan bang toan bo corpus nen hit_rate luon ~1.0 du index
# tot hay xau. Ngua truong hop "pipeline chay xong ma metric vo nghia".
MIN_DOCUMENTS = 5

# So paper duoc chon lam dai dien. 8 paper x 4 loai cau hoi = 32 cau, du de
# mot cau doi ket qua chi lam metric xe dich ~3% thay vi ~8% nhu khi chi co 3
# paper (12 cau) - quan trong vi ca bai lab dua tren viec SO SANH metric.
DEFAULT_SAMPLE_SIZE = 8

# Do dai toi da cua ground_truth cho cau hoi summary (tinh theo cau).
SUMMARY_SENTENCES = 2


def _stringify(value: Any) -> str:
    """Ep mot o cua dataframe ve chuoi mot cach an toan.

    Ly do phai co ham nay: cot `authors` va `categories` chua LIST. Neu goi
    thang `pd.notna(value)` tren list, pandas tra ve mang boolean chu khong
    phai mot bool -> `if <mang>` nem ValueError "truth value of an array is
    ambiguous". Bug nay chi phat khi thieu cot `authors_joined`, tuc la rat de
    lot qua test roi chet luc chay that.
    """
    if value is None:
        return ""
    # Xu ly list/tuple/ndarray TRUOC khi dung den pd.notna.
    if isinstance(value, (list, tuple, np.ndarray)):
        return ", ".join(str(v).strip() for v in value if str(v).strip())
    # Scalar: pd.notna moi dung duoc o day (bat NaN, None, NaT).
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _first_value(row: pd.Series, *column_names: str) -> str:
    """Lay gia tri khong rong dau tien trong danh sach cot uu tien."""
    for column_name in column_names:
        text = _stringify(row.get(column_name))
        if text:
            return text
    return ""


def _shorten_summary(summary: str, max_sentences: int = SUMMARY_SENTENCES) -> str:
    """Cat abstract con vai cau dau lam ground_truth.

    Ly do: `mean_token_f1` so khop token giua cau tra loi va ground_truth. Neu
    de nguyen abstract 200 tu lam dap an, mot ban tom tat NGAN va DUNG van bi
    cham diem thap chi vi it token trung -> metric do do dai chu khong do chat
    luong. Vai cau dau cua abstract thuong da chua luan diem chinh.
    """
    sentences = re.split(r"(?<=[.!?])\s+", summary.strip())
    kept = " ".join(s for s in sentences[:max_sentences] if s).strip()
    return kept or summary.strip()


def _select_representative(df: pd.DataFrame, sample_size: int) -> pd.DataFrame:
    """Chon paper dai dien RAI DEU corpus thay vi lay tu dau.

    Day la sua loi quan trong nhat cua file nay.

    `cleaning.py` sort `published` giam dan, nen `df.head(n)` = n bai MOI NHAT.
    Nhung buoc 1 cua `corruption.py` lai co tinh xoa cac ban ghi moi nhat. Neu
    eval set chi gom cac bai moi nhat thi sang Pha 2, 100% cau hoi tro toi
    document da bi xoa -> hit_rate ve 0 -> tac dong rieng cua blank_summary,
    inject_noise, truncate_title, stale_date bi che lap hoan toan va bang so
    sanh baseline/corrupted/repaired mat y nghia.

    `np.linspace` lay chi muc cach deu tu dau den cuoi: van co vai bai moi nhat
    (can, de do tac dong cua viec drop) nhung phan lon eval set nam ngoai vung
    bi xoa nen cac dang loi khac van do duoc.
    """
    sample_size = min(sample_size, len(df))
    positions = np.linspace(0, len(df) - 1, sample_size)
    # np.unique vua lam tron vua khu trung, phong khi sample_size gan len(df).
    indices = np.unique(np.round(positions).astype(int))
    return df.iloc[indices].copy()


def build_test_set(
    df: pd.DataFrame,
    output_path,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    min_documents: int = MIN_DOCUMENTS,
) -> list[dict[str, Any]]:
    """Tao bo evaluation set tu cleaned dataframe.

    Bo cau hoi nay duoc dung LAI Y NGUYEN cho ca ba trang thai baseline,
    corrupted va repaired. Vi vay no phai sinh tu du lieu SACH va duoc ghi ra
    file mot lan: neu build lai tren du lieu da hong thi ground_truth cung hong
    theo va phep so sanh khong con co so.

    Pseudo-code:
    1. Kiem tra so luong document toi thieu.
    2. Chon mot so paper dai dien.
    3. Tao nhieu loai cau hoi: summary / authors / date / categories.
    4. Moi row co: id, question_type, question, ground_truth, ground_truth_doc_ids.
    5. Ghi file JSON vao output_path.
    """
    # --- Buoc 1: kiem tra so luong document toi thieu -------------------
    if df is None or df.empty:
        raise ValueError("Can it nhat mot document de tao test set.")

    if len(df) < min_documents:
        # Raise chu khong warning: eval set qua nho se cho ra metric trong
        # nhu that (vi du hit_rate = 1.0) va lam ca bao cao sai huong.
        # `min_documents` ha duoc trong unit test, nhung khi chay pipeline that
        # thi giu mac dinh.
        raise ValueError(
            f"Chi co {len(df)} document, can toi thieu {min_documents}. "
            "Corpus qua nho thi hit_rate luon ~1.0 va metric mat y nghia. "
            "Kiem tra lai buoc fetch/cleaning (co the filter da loai qua nhieu row)."
        )

    df = df.copy().reset_index(drop=True)

    # Neu thieu paper_id thi sinh id thay the, de van chay duoc voi dataframe
    # rut gon trong unit test.
    if "paper_id" not in df.columns:
        df["paper_id"] = [f"paper-{i + 1}" for i in range(len(df))]

    # --- Buoc 2: chon paper dai dien ------------------------------------
    sample_df = _select_representative(df, sample_size)

    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for _, row in sample_df.iterrows():
        # `_first_value` doc theo thu tu uu tien cot, tra "" neu deu rong.
        paper_id = _first_value(row, "paper_id", "id")
        if not paper_id or paper_id in seen_ids:
            # Bo qua paper trung hoac khong co id: `ground_truth_doc_ids` phai
            # tro toi dung mot document co that thi metric retrieval moi dung.
            continue
        seen_ids.add(paper_id)

        title = _first_value(row, "title") or f"paper {paper_id}"
        authors = _first_value(row, "authors_joined", "authors")
        published = _first_value(row, "published", "publication_date")
        categories = _first_value(row, "categories_joined", "categories")
        summary = _first_value(row, "summary")

        # --- Buoc 3: sinh 4 loai cau hoi --------------------------------
        # Moi loai cham vao mot mat khac nhau cua chat luong du lieu:
        #   summary    -> bat loi blank_summary va inject_noise
        #   authors    -> bat loi mat/sai metadata tac gia
        #   date       -> bat loi stale_published_date
        #   categories -> bat loi mat phan loai
        # Nho tach question_type, bao cao co the tach metric theo tung loai va
        # chi ro dang corruption nao gay hai nhat.
        question_specs: list[tuple[str, str, str]] = [
            (
                "summary",
                f"Summarize the paper '{title}'.",
                _shorten_summary(summary) if summary else "No summary available.",
            ),
            (
                "authors",
                f"Who authored the paper '{title}'?",
                authors or "unknown",
            ),
            (
                "date",
                f"When was the paper '{title}' published?",
                published or "unknown",
            ),
            (
                "categories",
                f"What categories are associated with the paper '{title}'?",
                categories or "unknown",
            ),
        ]

        # --- Buoc 4: dung row theo dung schema --------------------------
        for question_type, question, ground_truth in question_specs:
            items.append(
                {
                    # id duy nhat, doc duoc bang mat -> de tra nguoc khi debug.
                    "id": f"{paper_id}-{question_type}",
                    # Cho phep nhom metric theo loai cau hoi.
                    "question_type": question_type,
                    "question": question,
                    "ground_truth": ground_truth,
                    # List (khong phai string): metrics tinh hit_rate bang cach
                    # kiem tra giao giua doc id retriever tra ve va list nay.
                    "ground_truth_doc_ids": [paper_id],
                }
            )

    if not items:
        raise ValueError("Khong tao duoc cau hoi nao - kiem tra cot paper_id cua cleaned data.")

    # --- Buoc 5: ghi JSON -----------------------------------------------
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # ensure_ascii=False de giu nguyen tieu de/ten tac gia co dau.
    output_path.write_text(
        json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return items
