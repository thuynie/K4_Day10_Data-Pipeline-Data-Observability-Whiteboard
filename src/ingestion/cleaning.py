from __future__ import annotations

from datetime import datetime, timezone
import html
import re

import pandas as pd

from ingestion.crossref import PaperRecord


def _clean_str(text: str | None) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"<[^>]+>", "", str(text))
    cleaned = html.unescape(cleaned)
    cleaned = " ".join(cleaned.split())
    return cleaned


def build_clean_dataframe(records: list[PaperRecord], run_date: datetime) -> pd.DataFrame:
    """Clean raw records into a structured DataFrame ready for embedding.

    Performs normalization, date parsing, age calculation, text formatting,
    deduplication, and quality filtering.
    """
    if not records:
        return pd.DataFrame(
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

        published_str = r.published.strip() if r.published else "1970-01-01"
        updated_str = r.updated.strip() if r.updated else published_str

        # Parse date and calculate age_days
        try:
            pub_dt = datetime.strptime(published_str[:10], "%Y-%m-%d")
        except ValueError:
            pub_dt = datetime(1970, 1, 1)

        age_days = (run_dt_naive - pub_dt).days
        if age_days < 0:
            age_days = 0

        summary_chars = len(summary)

        text_for_embedding = (
            f"Title: {title}\n"
            f"Authors: {authors_joined}\n"
            f"Categories: {categories_joined}\n"
            f"Summary: {summary}"
        )

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
        return df

    # Drop duplicates by paper_id
    df = df.drop_duplicates(subset=["paper_id"], keep="first")

    # Filter out invalid rows (missing title or missing/too short summary)
    df = df[(df["title"].str.len() > 0) & (df["summary_chars"] >= 10)]

    # Sort dataframe by published date descending, then paper_id
    df = df.sort_values(by=["published", "paper_id"], ascending=[False, True]).reset_index(drop=True)

    return df

