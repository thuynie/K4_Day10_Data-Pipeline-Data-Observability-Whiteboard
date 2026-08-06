from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
import html
import json
import logging
import os
from pathlib import Path
import re
import time
import requests

from core.config import Settings

logger = logging.getLogger(__name__)

CROSSREF_API_URL = "https://api.crossref.org/works"

# Only retry temporary status codes (429, 5xx)
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_RETRIES = 3


@dataclass(frozen=True)
class PaperRecord:
    paper_id: str
    title: str
    summary: str
    authors: list[str]
    categories: list[str]
    primary_category: str
    published: str
    updated: str
    abs_url: str
    pdf_url: str
    comment: str


def _clean_text(text: str | None) -> str:
    """Strip XML/HTML tags (e.g. <jats:p>), unescape entities, and normalize whitespace."""
    if not text:
        return ""
    cleaned = html.unescape(str(text))
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    # Handle double escaped HTML entities if present
    cleaned = html.unescape(cleaned)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    return " ".join(cleaned.split())


def _extract_date(node: dict | str | None) -> str:
    """Standardize Crossref date to 'YYYY-MM-DD'."""
    if not node:
        return ""

    if isinstance(node, str):
        m = re.match(r"^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", node.strip())
        if not m:
            return ""
        year = int(m.group(1))
        month = int(m.group(2) or 1)
        day = int(m.group(3) or 1)
    elif isinstance(node, dict):
        date_parts = node.get("date-parts") or []
        if not date_parts or not isinstance(date_parts[0], list):
            return ""
        parts = [p for p in date_parts[0] if isinstance(p, int)]
        if not parts:
            return ""
        year = parts[0]
        month = parts[1] if len(parts) > 1 else 1
        day = parts[2] if len(parts) > 2 else 1
    else:
        return ""

    month = min(max(month, 1), 12)
    day = min(max(day, 1), 31)
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        try:
            return datetime(year, month, 1).strftime("%Y-%m-%d")
        except ValueError:
            return ""


def _join_str(value) -> str:
    if isinstance(value, list):
        return " ".join(str(v) for v in value if v)
    if value is None:
        return ""
    return str(value)


def parse_crossref_payload(payload: dict) -> list[PaperRecord]:
    """Parse Crossref payload into a list of PaperRecord objects.

    Filters out records without DOI or title, cleans HTML/XML tags,
    and extracts authors, categories, dates, and URLs.
    """
    items: list = []
    if isinstance(payload, dict):
        message = payload.get("message")
        if isinstance(message, dict):
            items = message.get("items") or []
        elif isinstance(payload.get("items"), list):
            items = payload["items"]
    elif isinstance(payload, list):
        items = payload

    records: list[PaperRecord] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        # --- Identifier ---
        paper_id = str(
            item.get("DOI") or item.get("paper_id") or item.get("id") or ""
        ).strip()
        if not paper_id:
            continue

        # --- Title ---
        title = _clean_text(_join_str(item.get("title")))
        if not title:
            continue

        # --- Abstract ---
        summary = _clean_text(_join_str(item.get("abstract") or item.get("summary")))

        # --- Authors ---
        raw_authors = item.get("author") or item.get("authors") or []
        authors: list[str] = []
        if isinstance(raw_authors, list):
            for a in raw_authors:
                if isinstance(a, dict):
                    given = _clean_text(a.get("given"))
                    family = _clean_text(a.get("family"))
                    full_name = f"{given} {family}".strip() or _clean_text(a.get("name"))
                elif isinstance(a, str):
                    full_name = _clean_text(a)
                else:
                    full_name = ""
                if full_name:
                    authors.append(full_name)
        if not authors:
            authors = ["Unknown"]

        # --- Categories ---
        raw_subjects = item.get("subject") or item.get("categories") or []
        if isinstance(raw_subjects, str):
            raw_subjects = [raw_subjects]
        categories: list[str] = []
        if isinstance(raw_subjects, list):
            categories = [_clean_text(sub) for sub in raw_subjects if _clean_text(sub)]
        if not categories:
            categories = ["General"]
        primary_category = categories[0]

        # --- Dates ---
        pub_date = (
            _extract_date(item.get("published"))
            or _extract_date(item.get("published-online"))
            or _extract_date(item.get("published-print"))
            or _extract_date(item.get("issued"))
            or _extract_date(item.get("created"))
            or "1970-01-01"
        )
        upd_date = (
            _extract_date(item.get("updated"))
            or _extract_date(item.get("deposited"))
            or _extract_date(item.get("created"))
            or pub_date
        )

        # --- URLs ---
        abs_url = item.get("URL") or f"https://doi.org/{paper_id}"
        pdf_url = ""
        links = item.get("link") or []
        if isinstance(links, list):
            for link in links:
                if not isinstance(link, dict):
                    continue
                link_url = link.get("URL") or ""
                content_type = link.get("content-type") or ""
                if "application/pdf" in content_type or link_url.lower().endswith(".pdf"):
                    pdf_url = link_url
                    break
        if not pdf_url:
            pdf_url = abs_url

        # --- Comment: journal / container title ---
        container = item.get("container-title")
        if isinstance(container, list):
            container = container[0] if container else ""
        comment = _clean_text(container)

        records.append(
            PaperRecord(
                paper_id=paper_id,
                title=title,
                summary=summary,
                authors=authors,
                categories=categories,
                primary_category=primary_category,
                published=pub_date,
                updated=upd_date,
                abs_url=abs_url,
                pdf_url=pdf_url,
                comment=comment,
            )
        )

    return records


def _write_fetch_metadata(settings: Settings, status: str, detail: dict) -> None:
    """Write fetch metadata to raw_fetch_metadata.json for observability."""
    meta_path = settings.paths.raw_api_response.parent / "raw_fetch_metadata.json"
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "source_api": settings.source_api,
        "source_query": settings.source_query,
        "source_filter": settings.source_filter,
        "max_results": settings.max_results,
        "source_status": status,
        **detail,
    }
    meta_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def fetch_source_records(settings: Settings) -> list[PaperRecord]:
    """Fetch Crossref API records, save raw response, and return parsed PaperRecords.

    Includes retry logic with backoff and metadata tracing.
    """
    raw_records_path = settings.paths.raw_records_json

    if not settings.refresh_source and raw_records_path.exists():
        logger.info("REFRESH_SOURCE is disabled -> using existing snapshot: %s", raw_records_path)
        return load_raw_records(raw_records_path)

    mailto = os.getenv("CROSSREF_MAILTO", "").strip() or "student@example.com"

    params: dict = {
        "query": settings.source_query,
        "filter": settings.source_filter,
        "rows": min(settings.max_results, 1000),
        "mailto": mailto,
    }

    headers = {"User-Agent": f"DataObservabilityLab/1.0 (mailto:{mailto})"}

    payload = None
    last_error = ""

    for attempt in range(1, MAX_RETRIES + 1):
        sleep_s = 2**attempt
        try:
            logger.info("Fetching Crossref (attempt %d/%d)...", attempt, MAX_RETRIES)
            response = requests.get(
                CROSSREF_API_URL, params=params, headers=headers, timeout=30
            )

            if response.status_code == 200:
                payload = response.json()
                break

            last_error = f"HTTP {response.status_code}: {response.text[:200]}"

            if response.status_code not in RETRYABLE_STATUS:
                _write_fetch_metadata(
                    settings, "failed", {"error": last_error, "attempts": attempt}
                )
                raise RuntimeError(f"Crossref non-retryable response: {last_error}")

            logger.warning("Crossref warning: %s", last_error)
            retry_after = response.headers.get("Retry-After", "")
            if retry_after.isdigit():
                sleep_s = int(retry_after)

        except requests.RequestException as err:
            last_error = f"{type(err).__name__}: {err}"
            logger.warning("Attempt %d failed: %s", attempt, last_error)

        if attempt < MAX_RETRIES:
            logger.info("Waiting %ds before retry...", sleep_s)
            time.sleep(sleep_s)

    if payload is not None:
        settings.paths.raw_api_response.parent.mkdir(parents=True, exist_ok=True)
        settings.paths.raw_api_response.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        records = parse_crossref_payload(payload)

        raw_records_path.parent.mkdir(parents=True, exist_ok=True)
        raw_records_path.write_text(
            json.dumps([asdict(r) for r in records], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        total_items = 0
        if isinstance(payload, dict):
            total_items = len((payload.get("message") or {}).get("items") or [])
        _write_fetch_metadata(
            settings,
            "ok",
            {"items_returned": total_items, "records_parsed": len(records)},
        )
        logger.info("Fetch OK: %d items -> %d records", total_items, len(records))
        return records

    if raw_records_path.exists():
        logger.error(
            "Could not fetch Crossref (%s). Falling back to local cache: %s",
            last_error,
            raw_records_path,
        )
        _write_fetch_metadata(
            settings,
            "degraded_cache",
            {"error": last_error, "cache_path": str(raw_records_path)},
        )
        return load_raw_records(raw_records_path)

    _write_fetch_metadata(settings, "failed", {"error": last_error})
    raise RuntimeError(
        f"Failed to fetch from Crossref and no local cache available. Last error: {last_error}"
    )


def load_raw_records(path: Path) -> list[PaperRecord]:
    """Load JSON snapshot and map each dict into a PaperRecord."""
    path = Path(path)
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    if not isinstance(data, list):
        return []

    allowed = {f.name for f in fields(PaperRecord)}
    records: list[PaperRecord] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        kwargs = {k: v for k, v in item.items() if k in allowed}
        for name in allowed - kwargs.keys():
            kwargs[name] = [] if name in {"authors", "categories"} else ""
        records.append(PaperRecord(**kwargs))
    return records
