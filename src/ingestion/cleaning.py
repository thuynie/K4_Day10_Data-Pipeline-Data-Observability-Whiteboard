from __future__ import annotations

from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re

import pandas as pd

from core.utils import build_embedding_text
from ingestion.crossref import PaperRecord


def _clean_str(text: str | None) -> str:
    if not text:
        return ""
    # Strip HTML/XML tags (e.g. <jats:p>, <b>, <i>, <p>, etc.)
    cleaned = re.sub(r"<[^>]+>", "", str(text))
    cleaned = html.unescape(cleaned)
    cleaned = " ".join(cleaned.split())
    return cleaned


def save_clean_dataframe(df: pd.DataFrame, csv_path: Path, json_path: Path) -> None:
    """Save cleaned DataFrame to CSV and JSON files."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    # Save to CSV
    df.to_csv(csv_path, index=False, encoding="utf-8")

    # Save to JSON
    df.to_json(json_path, orient="records", indent=2, force_ascii=False)


def build_clean_dataframe(
    records: list[PaperRecord],
    run_date: datetime,
    clean_csv_path: Path | None = None,
    clean_json_path: Path | None = None,
) -> pd.DataFrame:
    """Clean raw records into a structured DataFrame ready for embedding.

    Rules applied:
    1. Drop records missing title or with summary under 100 characters.
    2. Strip XML/HTML tags from title and summary.
    3. Join authors into authors_joined and categories into categories_joined with commas.
    4. Format published date to YYYY-MM-DD and compute age_days.
    5. Build text_for_embedding via core.utils.build_embedding_text (shared with
       corruption.py's rebuild step so baseline/corrupted embeddings stay comparable).
    6. Deduplicate by paper_id, sort by published date descending.
    7. Optionally save to clean_csv_path and clean_json_path if provided.
    """
    if not records:
        empty_df = pd.DataFrame(
            columns=[
                "paper_id",
                "title",
                "summary",
                "authors",
                "categories",
                "primary_category",
                "published",
                "updated",
                "abs_url",
                "pdf_url",
                "comment",
                "authors_joined",
                "categories_joined",
                "summary_chars",
                "age_days",
                "text_for_embedding",
            ]
        )
        if clean_csv_path and clean_json_path:
            save_clean_dataframe(empty_df, clean_csv_path, clean_json_path)
        return empty_df

    rows = []
    run_dt_naive = run_date.replace(tzinfo=None) if run_date else datetime.now(timezone.utc).replace(tzinfo=None)

    for r in records:
        paper_id = r.paper_id.strip() if r.paper_id else ""
        if not paper_id:
            continue

        title = _clean_str(r.title)
        summary = _clean_str(r.summary)

        # Normalize authors & categories
        authors = [_clean_str(a) for a in (r.authors or []) if _clean_str(a)]
        if not authors:
            authors = ["Unknown"]
        authors_joined = ", ".join(authors)

        categories = [_clean_str(c) for c in (r.categories or []) if _clean_str(c)]
        if not categories:
            categories = ["General"]
        categories_joined = ", ".join(categories)

        primary_category = _clean_str(r.primary_category) or categories[0]

        published_raw = r.published.strip() if r.published else "1970-01-01"
        updated_raw = r.updated.strip() if r.updated else published_raw

        # Parse and normalize dates to YYYY-MM-DD; compute age_days from run_date
        try:
            pub_dt = datetime.strptime(published_raw[:10], "%Y-%m-%d")
        except ValueError:
            pub_dt = datetime(1970, 1, 1)
        try:
            upd_dt = datetime.strptime(updated_raw[:10], "%Y-%m-%d")
        except ValueError:
            upd_dt = pub_dt

        published_str = pub_dt.strftime("%Y-%m-%d")
        updated_str = upd_dt.strftime("%Y-%m-%d")

        age_days = (run_dt_naive - pub_dt).days
        if age_days < 0:
            age_days = 0

        summary_chars = len(summary)

        text_for_embedding = build_embedding_text(title, authors_joined, categories_joined, summary)

        row = {
            "paper_id": paper_id,
            "title": title,
            "summary": summary,
            "authors": authors,
            "categories": categories,
            "primary_category": primary_category,
            "published": published_str,
            "updated": updated_str,
            "abs_url": r.abs_url or f"https://doi.org/{paper_id}",
            "pdf_url": r.pdf_url or r.abs_url or f"https://doi.org/{paper_id}",
            "comment": _clean_str(r.comment),
            "authors_joined": authors_joined,
            "categories_joined": categories_joined,
            "summary_chars": summary_chars,
            "age_days": age_days,
            "text_for_embedding": text_for_embedding,
        }
        rows.append(row)

    df = pd.DataFrame(rows)

    if df.empty:
        if clean_csv_path and clean_json_path:
            save_clean_dataframe(df, clean_csv_path, clean_json_path)
        return df

    # Drop duplicates by paper_id
    df = df.drop_duplicates(subset=["paper_id"], keep="first")

    # Filter out trash records: missing title OR summary under 100 characters
    df = df[(df["title"].str.len() > 0) & (df["summary_chars"] >= 100)]

    # Sort dataframe by published date descending, then paper_id
    df = df.sort_values(by=["published", "paper_id"], ascending=[False, True]).reset_index(drop=True)

    if clean_csv_path and clean_json_path:
        save_clean_dataframe(df, clean_csv_path, clean_json_path)

    return df


