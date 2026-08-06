from __future__ import annotations

from dataclasses import asdict, dataclass
import html
import json
import logging
from pathlib import Path
import re
import time
import requests

from core.config import Settings

logger = logging.getLogger(__name__)

CROSSREF_API_URL = "https://api.crossref.org/works"


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
    if not text:
        return ""
    # Strip HTML/XML tags
    cleaned = re.sub(r"<[^>]+>", "", str(text))
    # Unescape HTML entities
    cleaned = html.unescape(cleaned)
    # Remove extra spaces
    cleaned = " ".join(cleaned.split())
    return cleaned


def _extract_date(date_dict: dict | str | None) -> str | None:
    if not date_dict:
        return None
    if isinstance(date_dict, str):
        cleaned = date_dict.strip()
        if len(cleaned) >= 10 and cleaned[:4].isdigit():
            return cleaned[:10]
        return None
    if isinstance(date_dict, dict):
        date_parts = date_dict.get("date-parts", [])
        if date_parts and isinstance(date_parts[0], list) and len(date_parts[0]) > 0:
            parts = date_parts[0]
            year = parts[0] if len(parts) > 0 and isinstance(parts[0], int) else 1970
            month = parts[1] if len(parts) > 1 and isinstance(parts[1], int) else 1
            day = parts[2] if len(parts) > 2 and isinstance(parts[2], int) else 1
            return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def parse_crossref_payload(payload: dict) -> list[PaperRecord]:
    """Parse Crossref API payload into a list of PaperRecord objects.

    Handles extracting DOI, title, abstract/summary, authors, subjects,
    dates, and URLs from Crossref JSON response items.
    """
    items = []
    if isinstance(payload, dict):
        if "message" in payload and isinstance(payload["message"], dict):
            items = payload["message"].get("items", [])
        elif "items" in payload:
            items = payload["items"]
    elif isinstance(payload, list):
        items = payload

    records: list[PaperRecord] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        paper_id = item.get("DOI", "").strip() or item.get("paper_id", "").strip() or item.get("id", "").strip()
        if not paper_id:
            continue

        # Title
        raw_title = item.get("title", "")
        if isinstance(raw_title, list):
            raw_title = " ".join([str(t) for t in raw_title if t])
        title = _clean_text(str(raw_title))
        if not title:
            continue

        # Summary / Abstract
        raw_summary = item.get("abstract", "") or item.get("summary", "")
        if isinstance(raw_summary, list):
            raw_summary = " ".join([str(s) for s in raw_summary if s])
        summary = _clean_text(str(raw_summary))

        # Authors
        raw_authors = item.get("author", []) or item.get("authors", [])
        authors: list[str] = []
        if isinstance(raw_authors, list):
            for a in raw_authors:
                if isinstance(a, dict):
                    given = _clean_text(a.get("given", ""))
                    family = _clean_text(a.get("family", ""))
                    name = _clean_text(a.get("name", ""))
                    if given or family:
                        full_name = f"{given} {family}".strip()
                    else:
                        full_name = name
                    if full_name:
                        authors.append(full_name)
                elif isinstance(a, str):
                    clean_a = _clean_text(a)
                    if clean_a:
                        authors.append(clean_a)
        if not authors:
            authors = ["Unknown"]

        # Categories
        raw_subjects = item.get("subject", []) or item.get("categories", [])
        if isinstance(raw_subjects, str):
            raw_subjects = [raw_subjects]
        categories = [_clean_text(str(sub)) for sub in raw_subjects if _clean_text(str(sub))]
        if not categories:
            categories = ["General"]
        primary_category = categories[0]

        # Dates
        pub_date = (
            _extract_date(item.get("published-online"))
            or _extract_date(item.get("published-print"))
            or _extract_date(item.get("issued"))
            or _extract_date(item.get("created"))
            or "1970-01-01"
        )

        upd_date = (
            _extract_date(item.get("updated"))
            or _extract_date(item.get("created"))
            or pub_date
        )

        # URLs
        abs_url = item.get("URL", f"https://doi.org/{paper_id}")
        pdf_url = ""
        links = item.get("link", [])
        if isinstance(links, list):
            for link in links:
                if isinstance(link, dict):
                    link_url = link.get("URL", "")
                    content_type = link.get("content-type", "")
                    if "application/pdf" in content_type or link_url.endswith(".pdf"):
                        pdf_url = link_url
                        break
        if not pdf_url:
            pdf_url = abs_url

        # Comment / Container Title
        raw_container = item.get("container-title", [])
        if isinstance(raw_container, list) and raw_container:
            comment = _clean_text(str(raw_container[0]))
        else:
            comment = _clean_text(str(raw_container))

        record = PaperRecord(
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
        records.append(record)

    return records


def fetch_source_records(settings: Settings) -> list[PaperRecord]:
    """Fetch records from Crossref API, save raw response, and return parsed PaperRecords.

    Includes retry logic with backoff for rate limiting / temporary outages.
    """
    params = {
        "query": settings.source_query,
        "filter": settings.source_filter,
        "rows": settings.max_results,
        "mailto": "student@example.com",
    }

    headers = {
        "User-Agent": "DataObservabilityLab/1.0 (mailto:student@example.com)"
    }

    max_retries = 3
    payload = None

    for attempt in range(1, max_retries + 1):
        try:
            logger.info("Fetching Crossref records (attempt %d/%d)...", attempt, max_retries)
            response = requests.get(CROSSREF_API_URL, params=params, headers=headers, timeout=30)
            if response.status_code == 200:
                payload = response.json()
                break
            logger.warning("Crossref API returned HTTP %d: %s", response.status_code, response.text[:200])
        except Exception as err:
            logger.warning("Attempt %d failed with error: %s", attempt, err)

        if attempt < max_retries:
            time.sleep(2 ** attempt)

    # Save raw API response if fetched
    if payload is not None:
        settings.paths.raw_api_response.parent.mkdir(parents=True, exist_ok=True)
        with open(settings.paths.raw_api_response, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

        records = parse_crossref_payload(payload)

        # Save parsed records JSON
        settings.paths.raw_records_json.parent.mkdir(parents=True, exist_ok=True)
        with open(settings.paths.raw_records_json, "w", encoding="utf-8") as f:
            json.dump([asdict(r) for r in records], f, indent=2, ensure_ascii=False)

        return records

    # Fallback to local cached raw_records_json if API call failed completely
    if settings.paths.raw_records_json.exists():
        logger.info("Loading raw records from local cache: %s", settings.paths.raw_records_json)
        return load_raw_records(settings.paths.raw_records_json)

    raise RuntimeError("Failed to fetch records from Crossref API and no local cache found.")


def load_raw_records(path: Path) -> list[PaperRecord]:
    """Load JSON snapshot and map each dict into a `PaperRecord`."""
    if not path.exists():
        return []

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        return []

    records = []
    for item in data:
        if isinstance(item, dict):
            records.append(PaperRecord(**item))
    return records

