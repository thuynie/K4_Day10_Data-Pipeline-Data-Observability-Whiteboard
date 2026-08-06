from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import time

from langchain_core.embeddings import Embeddings
import requests

logger = logging.getLogger(__name__)

GEMINI_EMBED_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"
)
# Gioi han cua endpoint batchEmbedContents.
GEMINI_MAX_BATCH = 100
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_RETRIES = 4

# Task type cua Gemini Embedding - day la diem an sang nhat so voi MiniLM.
# Document va query duoc chieu vao khong gian BAT DOI XUNG, dung cho bai toan
# "cau hoi ngan -> abstract dai" cua lab nay.
TASK_DOCUMENT = "RETRIEVAL_DOCUMENT"
TASK_QUERY = "RETRIEVAL_QUERY"


# ---------------------------------------------------------------------------
# Backend local - giu lai lam fallback khi khong co mang / het quota
# ---------------------------------------------------------------------------
@lru_cache(maxsize=4)
def _load_model(model_name: str):
    # Import ben trong ham de khong phai tai torch khi chi dung Gemini.
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


class MiniLMEmbeddings(Embeddings):
    """SentenceTransformer chay local. 384 chieu, khong phan biet doc/query."""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self.dimensions: int | None = None
        self.model = _load_model(model_name)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        embeddings = self.model.encode(texts, normalize_embeddings=True)
        return embeddings.tolist()

    def embed_query(self, text: str) -> list[float]:
        embedding = self.model.encode([text], normalize_embeddings=True)
        return embedding[0].tolist()


# ---------------------------------------------------------------------------
# Backend Gemini
# ---------------------------------------------------------------------------
def _l2_normalize(vector: list[float]) -> list[float]:
    """Chuan hoa L2.

    BAT BUOC voi `gemini-embedding-001` khi output_dimensionality != 3072:
    vector bi cat theo Matryoshka KHONG con duoc chuan hoa san. Bo qua buoc nay
    thi do dai vector lan vao phep do tuong dong, va moi metric khong phai
    cosine (L2 / inner product) deu cho ket qua sai.
    """
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return vector
    return [v / norm for v in vector]


class GeminiEmbeddings(Embeddings):
    """Goi Gemini Embedding API qua REST.

    Dung REST truc tiep thay vi wrapper langchain de kiem soat duoc task_type,
    output_dimensionality, batching va retry - va de khong phu thuoc vao ten
    tham so von hay doi giua cac phien ban langchain-google-genai.

    Co cache tren dia: baseline va repaired gan nhu trung text hoan toan, cache
    giup khong dot quota ba lan cho cung mot noi dung.
    """

    def __init__(
        self,
        model_name: str = "gemini-embedding-001",
        dimensions: int = 1536,
        api_key: str | None = None,
        cache_path: Path | None = None,
        timeout: int = 60,
    ):
        self.model_name = model_name
        self.dimensions = dimensions
        self.timeout = timeout
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                f"Can GOOGLE_API_KEY trong .env de dung embedding model '{model_name}'. "
                "Hoac dat EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2 "
                "de chay local."
            )
        self.cache_path = Path(cache_path) if cache_path else None
        self._cache: dict[str, list[float]] = {}
        if self.cache_path and self.cache_path.exists():
            try:
                self._cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning("Cache embedding hong, bo qua: %s", self.cache_path)

    # -- cache ---------------------------------------------------------
    def _key(self, text: str, task_type: str) -> str:
        # Model + so chieu + task type deu nam trong key: doi bat ky thu nao
        # cung sinh cache moi, khong bao gio tron vector khac khong gian.
        raw = f"{self.model_name}|{self.dimensions}|{task_type}|{text}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _flush_cache(self) -> None:
        if not self.cache_path:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self._cache), encoding="utf-8")

    # -- goi API -------------------------------------------------------
    def _call_api(self, texts: list[str], task_type: str) -> list[list[float]]:
        payload = {
            "requests": [
                {
                    "model": f"models/{self.model_name}",
                    # API tu choi chuoi rong -> thay bang khoang trang.
                    # Dong summary bi blank o buoc corruption roi vao day.
                    "content": {"parts": [{"text": t if t.strip() else " "}]},
                    "taskType": task_type,
                    "outputDimensionality": self.dimensions,
                }
                for t in texts
            ]
        }
        url = GEMINI_EMBED_URL.format(model=self.model_name)
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}

        last_error = ""
        for attempt in range(1, MAX_RETRIES + 1):
            sleep_s = 2**attempt
            try:
                response = requests.post(
                    url, json=payload, headers=headers, timeout=self.timeout
                )
                if response.status_code == 200:
                    data = response.json()
                    return [
                        _l2_normalize(item["values"])
                        for item in data.get("embeddings", [])
                    ]

                last_error = f"HTTP {response.status_code}: {response.text[:300]}"
                if response.status_code not in RETRYABLE_STATUS:
                    raise RuntimeError(f"Gemini Embedding API loi - {last_error}")

                retry_after = response.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    sleep_s = int(retry_after)
                logger.warning("Gemini Embedding %s", last_error)

            except requests.RequestException as err:
                last_error = f"{type(err).__name__}: {err}"
                logger.warning("Embedding attempt %d that bai - %s", attempt, last_error)

            if attempt < MAX_RETRIES:
                logger.info("Cho %ds roi retry embedding...", sleep_s)
                time.sleep(sleep_s)

        raise RuntimeError(f"Khong goi duoc Gemini Embedding API. Loi cuoi: {last_error}")

    def _embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        results: list[list[float] | None] = [None] * len(texts)
        pending: list[tuple[int, str]] = []

        for i, text in enumerate(texts):
            cached = self._cache.get(self._key(text, task_type))
            if cached is not None:
                results[i] = cached
            else:
                pending.append((i, text))

        if pending:
            logger.info(
                "Embedding %d/%d doan (%d tu cache) - model=%s dim=%d task=%s",
                len(pending),
                len(texts),
                len(texts) - len(pending),
                self.model_name,
                self.dimensions,
                task_type,
            )

        for start in range(0, len(pending), GEMINI_MAX_BATCH):
            chunk = pending[start : start + GEMINI_MAX_BATCH]
            vectors = self._call_api([t for _, t in chunk], task_type)
            if len(vectors) != len(chunk):
                raise RuntimeError(
                    f"API tra ve {len(vectors)} vector cho {len(chunk)} input."
                )
            for (idx, text), vector in zip(chunk, vectors):
                results[idx] = vector
                self._cache[self._key(text, task_type)] = vector

        if pending:
            self._flush_cache()

        missing = [i for i, r in enumerate(results) if r is None]
        if missing:
            raise RuntimeError(f"Thieu embedding cho index {missing[:5]}")
        return results  # type: ignore[return-value]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(list(texts), TASK_DOCUMENT)

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], TASK_QUERY)[0]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def get_embeddings(settings, cache_path: Path | None = None) -> Embeddings:
    """Chon backend theo `settings.embedding_model`.

    - Ten bat dau bang "gemini-" -> GeminiEmbeddings (goi API)
    - Con lai                    -> MiniLMEmbeddings (chay local, offline)
    """
    model_name = settings.embedding_model
    if model_name.lower().startswith("gemini-"):
        if cache_path is None:
            cache_path = settings.paths.embeddings_json.parent / "_embedding_cache.json"
        return GeminiEmbeddings(
            model_name=model_name,
            dimensions=getattr(settings, "embedding_dimensions", 1536),
            api_key=settings.google_api_key,
            cache_path=cache_path,
        )
    return MiniLMEmbeddings(model_name)


def describe_backend(embedder: Embeddings) -> dict:
    """Metadata de ghi vao embedding manifest - phuc vu truy vet.

    Ba trang thai baseline/corrupted/repaired BAT BUOC phai cung model va cung
    so chieu, neu khong thi so sanh metric vo nghia. Ghi lai de kiem chung.
    """
    return {
        "embedding_backend": "gemini-api"
        if isinstance(embedder, GeminiEmbeddings)
        else "sentence-transformers-local",
        "embedding_model": getattr(embedder, "model_name", "unknown"),
        "embedding_dimensions": getattr(embedder, "dimensions", None),
        "task_type_document": TASK_DOCUMENT
        if isinstance(embedder, GeminiEmbeddings)
        else None,
        "task_type_query": TASK_QUERY if isinstance(embedder, GeminiEmbeddings) else None,
    }
