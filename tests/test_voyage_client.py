import json

import httpx
import pytest

from canada_agent.embed.index import batches, estimate_tokens
from canada_agent.embed.voyage import DIMENSIONS, EmbedError, VoyageClient


def body(n, tokens=10):
    data = [
        {"object": "embedding", "index": i, "embedding": [float(i)] * DIMENSIONS} for i in range(n)
    ]
    return {"object": "list", "data": list(reversed(data)), "usage": {"total_tokens": tokens}}


def make(*responses):
    seen: list[httpx.Request] = []
    queue = list(responses)

    def handler(request):
        seen.append(request)
        out = queue.pop(0)
        if isinstance(out, Exception):
            raise out
        return out

    sleeps: list[float] = []
    client = VoyageClient(
        "pa-test", transport=httpx.MockTransport(handler), sleep=sleeps.append, rng=lambda: 0.5
    )
    return client, seen, sleeps


def test_sends_model_type_and_dimension_and_keeps_input_order():
    client, seen, _ = make(httpx.Response(200, json=body(3, tokens=42)))
    out = client.embed(["a", "b", "c"], "document")
    sent = json.loads(seen[0].content)
    assert sent == {
        "input": ["a", "b", "c"],
        "model": "voyage-4",
        "input_type": "document",
        "output_dimension": 1024,
    }
    assert seen[0].headers["authorization"] == "Bearer pa-test"
    assert [v[0] for v in out.vectors] == [0.0, 1.0, 2.0]  # re-sorted by index
    assert out.total_tokens == 42


def test_429_waits_for_retry_after_then_succeeds():
    client, seen, sleeps = make(
        httpx.Response(429, headers={"retry-after": "20"}), httpx.Response(200, json=body(1))
    )
    assert len(client.embed(["a"], "query").vectors) == 1
    assert sleeps == [20.0]
    assert len(seen) == 2


def test_429_without_retry_after_waits_a_full_rate_limit_window():
    client, _, sleeps = make(httpx.Response(429), httpx.Response(200, json=body(1)))
    client.embed(["a"], "query")
    assert sleeps == [60.0]


def test_transport_errors_and_5xx_are_retried_then_give_up():
    client, seen, _ = make(*[httpx.ConnectError("reset")] * 3, *[httpx.Response(503)] * 3)
    with pytest.raises(EmbedError, match="HTTP 503 after 6 attempts"):
        client.embed(["a"], "document")
    assert len(seen) == 6


def test_bad_key_is_not_retried():
    client, seen, _ = make(httpx.Response(401, json={"detail": "Provided API key is invalid."}))
    with pytest.raises(EmbedError, match="HTTP 401"):
        client.embed(["a"], "document")
    assert len(seen) == 1


def test_wrong_vector_count_or_size_is_an_error():
    short = body(1)
    short["data"][0]["embedding"] = [0.0] * 10
    client, _, _ = make(httpx.Response(200, json=short))
    with pytest.raises(EmbedError, match="1024"):
        client.embed(["a"], "document")


def test_the_key_never_leaves_the_voyage_host():
    client, seen, _ = make(httpx.Response(302, headers={"location": "https://evil.example.com/"}))
    client.http.follow_redirects = True
    with pytest.raises(EmbedError, match="evil.example.com"):
        client.embed(["a"], "document")
    assert [r.url.host for r in seen] == ["api.voyageai.com"]


def test_missing_key_fails_fast():
    with pytest.raises(EmbedError, match="VOYAGE_API_KEY"):
        VoyageClient("")


def test_batches_respect_the_token_budget_and_input_cap():
    rows = [(i, "x" * 300) for i in range(10)]  # ~101 estimated tokens each
    by_tokens = list(batches(rows, max_tokens=250))
    assert [len(b) for b in by_tokens] == [2] * 5
    by_inputs = list(batches(rows, max_tokens=10**6, max_inputs=4))
    assert [len(b) for b in by_inputs] == [4, 4, 2]
    assert estimate_tokens("x" * 300) == 101


def test_an_oversized_single_card_still_gets_its_own_batch():
    assert [len(b) for b in batches([(1, "x" * 3000), (2, "y")], max_tokens=10)] == [1, 1]


def test_rerank_returns_input_indices_in_relevance_order():
    out = {
        "object": "list",
        "data": [
            {"index": 2, "relevance_score": 0.9},
            {"index": 0, "relevance_score": 0.5},
            {"index": 1, "relevance_score": 0.1},
        ],
        "usage": {"total_tokens": 99},
    }
    client, seen, _ = make(httpx.Response(200, json=out))
    result = client.rerank("rent?", ["a", "b", "c"])
    assert json.loads(seen[0].content) == {
        "query": "rent?",
        "documents": ["a", "b", "c"],
        "model": "rerank-2.5",
    }
    assert seen[0].url.path == "/v1/rerank"
    assert result.order == [2, 0, 1]
    assert result.total_tokens == 99


def test_rerank_that_drops_or_repeats_a_document_is_an_error():
    out = {"data": [{"index": 0, "relevance_score": 1.0}], "usage": {"total_tokens": 1}}
    client, _, _ = make(httpx.Response(200, json=out))
    with pytest.raises(EmbedError, match="exactly once"):
        client.rerank("q", ["a", "b"])


def test_a_redirect_is_reported_as_such_not_as_a_parse_error():
    client, seen, _ = make(httpx.Response(307, headers={"location": "https://api.voyageai.com/x"}))
    with pytest.raises(EmbedError, match="unexpected redirect: HTTP 307"):
        client.embed(["a"], "document")
    assert len(seen) == 1
