CREATE TABLE http_cache (
    key          text PRIMARY KEY,         -- sha256(method + url + canonical JSON body)
    url          text        NOT NULL,
    body         jsonb       NOT NULL,     -- successful responses only; errors are never cached
    fetched_at   timestamptz NOT NULL,
    ttl_seconds  integer     NOT NULL CHECK (ttl_seconds > 0)
);
