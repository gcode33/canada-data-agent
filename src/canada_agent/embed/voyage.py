"""Voyage embeddings and rerank client: batching limits, 429/5xx retries, and a host allowlist.

Same shape as the WDS client: every outcome is vectors or an `EmbedError`, never a raw
httpx exception. The key is sent only to `api.voyageai.com` (checked on every hop).
"""

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import httpx

ALLOWED_HOST = "api.voyageai.com"
MODEL = "voyage-4"
RERANK_MODEL = "rerank-2.5"  # PLAN said rerank-3, which doesn't exist (docs, 2026-11-01)
DIMENSIONS = 1024
MAX_INPUTS = 1000  # API limit per request (docs, checked 2026-11-01)
MAX_TOKENS = 320_000  # API limit per request for voyage-4
BACKOFF_BASE_S = 2.0
MAX_WAIT_S = 90.0
# Voyage's limits are per minute; a 429 without Retry-After means "wait for the window".
RATE_LIMIT_WINDOW_S = 60.0

InputType = Literal["document", "query"]


class EmbedError(Exception):
    pass


@dataclass(frozen=True)
class Reranked:
    order: list[int]  # input indices, most relevant first
    scores: list[float]
    total_tokens: int


@dataclass(frozen=True)
class Embeddings:
    vectors: list[list[float]]
    total_tokens: int


def _enforce_host(request: httpx.Request) -> None:
    url = request.url
    if url.scheme != "https" or url.host != ALLOWED_HOST or url.port not in (None, 443):
        raise EmbedError(f"refusing to send the Voyage key to {url.host!r}")


def _retry_after(response: httpx.Response) -> float:
    try:
        return min(max(float(response.headers.get("retry-after", 0)), 0.0), MAX_WAIT_S)
    except ValueError:
        return 0.0


class VoyageClient:
    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        max_attempts: int = 6,
        sleep: Callable[[float], None] = time.sleep,
        rng: Callable[[], float] = random.random,
    ) -> None:
        if not api_key:
            raise EmbedError("VOYAGE_API_KEY is not set")
        self.http = httpx.Client(
            base_url=f"https://{ALLOWED_HOST}/v1/",
            transport=transport,
            timeout=60.0,
            headers={"Authorization": f"Bearer {api_key}"},
            event_hooks={"request": [_enforce_host]},
        )
        self.max_attempts = max_attempts
        self._sleep = sleep
        self._rng = rng

    def embed(self, texts: list[str], input_type: InputType) -> Embeddings:
        if not texts:
            return Embeddings([], 0)
        if len(texts) > MAX_INPUTS:
            raise EmbedError(f"{len(texts)} inputs exceeds the per-request limit {MAX_INPUTS}")
        body = {
            "input": texts,
            "model": MODEL,
            "input_type": input_type,
            "output_dimension": DIMENSIONS,
        }
        return self._parse(self._post("embeddings", body), len(texts))

    def rerank(self, query: str, documents: list[str]) -> Reranked:
        """Indices of `documents`, most relevant first, with Voyage's relevance scores."""
        if not documents:
            return Reranked([], [], 0)
        if len(documents) > MAX_INPUTS:
            raise EmbedError(f"{len(documents)} documents exceeds the limit {MAX_INPUTS}")
        response = self._post(
            "rerank", {"query": query, "documents": documents, "model": RERANK_MODEL}
        )
        try:
            out = response.json()
            rows = out["data"]  # sorted by descending relevance
            order = [int(r["index"]) for r in rows]
            scores = [float(r["relevance_score"]) for r in rows]
            tokens = int(out["usage"]["total_tokens"])
        except (ValueError, KeyError, TypeError) as exc:
            raise EmbedError("unexpected rerank response shape") from exc
        if sorted(order) != list(range(len(documents))):
            raise EmbedError("rerank did not return every document exactly once")
        return Reranked(order, scores, tokens)

    def _post(self, path: str, body: dict) -> httpx.Response:
        wait = 0.0
        last = ""
        for attempt in range(self.max_attempts):
            if attempt:
                backoff = BACKOFF_BASE_S * 2 ** (attempt - 1) * (0.5 + self._rng())
                self._sleep(min(max(backoff, wait), MAX_WAIT_S))
            try:
                response = self.http.post(path, json=body)
            except httpx.RequestError as exc:
                wait, last = 0.0, type(exc).__name__
                continue
            if response.status_code == 429:
                wait, last = _retry_after(response) or RATE_LIMIT_WINDOW_S, "HTTP 429"
                continue
            if response.status_code >= 500:
                wait, last = _retry_after(response), f"HTTP {response.status_code}"
                continue
            if 300 <= response.status_code < 400:
                # Redirects aren't followed (the key must not travel); say so plainly.
                raise EmbedError(f"unexpected redirect: HTTP {response.status_code}")
            if response.status_code >= 400:
                # 401 bad key, 400 too many tokens, ...: retrying won't help. The body is
                # Voyage's error message, which never contains the key.
                raise EmbedError(f"HTTP {response.status_code}: {response.text[:300]}")
            return response
        raise EmbedError(f"{last} after {self.max_attempts} attempts")

    @staticmethod
    def _parse(response: httpx.Response, n: int) -> Embeddings:
        try:
            out = response.json()
            rows = sorted(out["data"], key=lambda d: d["index"])
            vectors = [row["embedding"] for row in rows]
            tokens = int(out["usage"]["total_tokens"])
        except (ValueError, KeyError, TypeError) as exc:
            raise EmbedError("unexpected response shape") from exc
        if len(vectors) != n or any(len(v) != DIMENSIONS for v in vectors):
            raise EmbedError(f"expected {n} vectors of {DIMENSIONS} dims")
        return Embeddings(vectors, tokens)
