from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any, Iterable


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: Any) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(df, path: Path) -> None:
    ensure_parent(path)
    df.to_csv(path, index=False)


def write_text(path: Path, text: str) -> None:
    ensure_parent(path)
    path.write_text(text, encoding="utf-8")


def now_utc() -> datetime:
    return datetime.now(UTC)


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def safe_slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return cleaned or "item"


def compact_join(items: Iterable[str], sep: str = ", ") -> str:
    return sep.join(item for item in items if item)


def first_sentence(text: str) -> str:
    chunks = re.split(r"(?<=[.!?])\s+", normalize_whitespace(text))
    return chunks[0] if chunks else normalize_whitespace(text)


def build_embedding_text(
    title: str,
    authors_joined: str,
    categories_joined: str,
    summary: str,
) -> str:
    """Dung chuoi `text_for_embedding` tu cac field da clean.

    QUAN TRONG: ca `cleaning.py` (baseline) va `corruption.py` (buoc 7 rebuild)
    deu phai goi ham NAY. Neu hai noi tu build chuoi theo format khac nhau thi
    khi so sanh baseline vs corrupted, mot phan chenh lech metric se den tu
    khac format chu khong phai tu du lieu hong -> ket luan cua bai lab sai.
    """
    return (
        f"Title: {title or ''}\n"
        f"Authors: {authors_joined or ''}\n"
        f"Categories: {categories_joined or ''}\n"
        f"Summary: {summary or ''}"
    )
