"""Build a reproducible evaluation set from the cleaned paper corpus.

Owner: Dương Tiến Dũng (2A202602020)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from core.utils import first_sentence, normalize_whitespace, write_json


QUESTION_TYPES = ("summary", "authors", "date", "categories")
REQUIRED_COLUMNS = {
    "paper_id",
    "title",
    "summary",
    "authors_joined",
    "categories_joined",
    "published",
}


def _clean_value(value: Any) -> str:
    """Return a normalized string while treating pandas nulls as empty."""
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return ""
    return normalize_whitespace(str(value))


def build_test_set(df: pd.DataFrame, output_path: str | Path) -> list[dict[str, Any]]:
    """Create a deterministic, auditable test set and persist it as JSON.

    Up to three representative documents are selected after sorting by
    ``paper_id``. Four factual questions are generated per document.  Quoting
    the exact title keeps the question answerable through both semantic search
    and the exact-title lookup supported by the RAG layer.
    """
    missing_columns = sorted(REQUIRED_COLUMNS.difference(df.columns))
    if missing_columns:
        raise ValueError(f"Clean dataframe is missing required columns: {missing_columns}")
    if df.empty:
        raise ValueError("Cannot build an evaluation set from an empty dataframe.")

    candidates = df.copy()
    candidates["paper_id"] = candidates["paper_id"].map(_clean_value)
    candidates["title"] = candidates["title"].map(_clean_value)
    candidates = candidates[
        candidates["paper_id"].ne("") & candidates["title"].ne("")
    ].drop_duplicates(subset=["paper_id"], keep="first")
    if candidates.empty:
        raise ValueError("No document has both a valid paper_id and title.")

    # Stable selection means baseline/corrupted/repaired runs can share the
    # exact same test set regardless of dataframe row order.
    selected = candidates.sort_values("paper_id", kind="stable").head(3)
    samples: list[dict[str, Any]] = []

    for document_number, (_, row) in enumerate(selected.iterrows(), start=1):
        paper_id = _clean_value(row["paper_id"])
        title = _clean_value(row["title"])
        facts = {
            "summary": (
                f"What is the main point of the paper '{title}'?",
                first_sentence(_clean_value(row["summary"])),
            ),
            "authors": (
                f"Who authored the paper '{title}'?",
                _clean_value(row["authors_joined"]),
            ),
            "date": (
                f"When was the paper '{title}' published?",
                _clean_value(row["published"]),
            ),
            "categories": (
                f"What categories are assigned to the paper '{title}'?",
                _clean_value(row["categories_joined"]),
            ),
        }

        for question_type in QUESTION_TYPES:
            question, ground_truth = facts[question_type]
            if not ground_truth:
                # A missing fact cannot form a trustworthy evaluation sample.
                continue
            samples.append(
                {
                    "id": f"eval-{document_number:02d}-{question_type}",
                    "question_type": question_type,
                    "question": question,
                    "ground_truth": ground_truth,
                    "ground_truth_doc_ids": [paper_id],
                }
            )

    if not samples:
        raise ValueError("No evaluation samples could be generated from the dataframe.")

    write_json(Path(output_path), samples)
    return samples
