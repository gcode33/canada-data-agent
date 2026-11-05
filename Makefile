# pipefail: a failing pg_dump must fail `make dump`, not write an empty file.
SHELL := /bin/bash
.SHELLFLAGS := -eo pipefail -c

.PHONY: up down migrate test live lint fmt index record dump seed verify-golden snapshot

INDEX_DUMP := data/index.sql.zst
DATABASE_URL ?= postgresql://canada:canada@localhost:5432/canada
INDEX_TABLES := --table=table_card --table=member --table=query_embedding --table=rerank_cache

up:  ## start Postgres, apply migrations, and seed the index if a dump exists
	docker compose up -d --wait
	uv run canada-migrate
	@if [ -f $(INDEX_DUMP) ]; then $(MAKE) seed; else echo "no $(INDEX_DUMP) yet; skipping seed"; fi

down:
	docker compose down

migrate:
	uv run canada-migrate

test:
	uv run pytest

live:  ## tests that call real external APIs (never run in CI)
	uv run pytest -m live

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff format .
	uv run ruff check --fix .

index:  ## cards from live StatCan metadata, then embed what's missing (needs VOYAGE_API_KEY)
	uv run canada-build-cards
	uv run canada-embed

record:  ## embed the retrieval questions once, so evals and CI replay them with no key
	uv run canada-eval-retrieval --method vector --record > /dev/null
	uv run canada-eval-retrieval --method hybrid-rerank --record > /dev/null

dump:  ## write the index (cards, members, recorded queries) to $(INDEX_DUMP)
	@mkdir -p data
	docker compose exec -T db pg_dump -U canada -d canada --data-only --no-owner $(INDEX_TABLES) \
		| zstd -19 -q -f -o $(INDEX_DUMP)
	@ls -lh $(INDEX_DUMP)

seed:  ## load $(INDEX_DUMP) into a migrated database; no Voyage key or StatCan call needed
	psql "$(DATABASE_URL)" -q -v ON_ERROR_STOP=1 -c "TRUNCATE table_card, query_embedding, rerank_cache CASCADE"
	zstd -dc $(INDEX_DUMP) | psql "$(DATABASE_URL)" -q -v ON_ERROR_STOP=1 > /dev/null
	@psql "$(DATABASE_URL)" -tA -c "SELECT count(*) || ' cards, ' || count(embedding) || ' embedded' FROM table_card"

verify-golden:  ## recompute every golden value from StatCan's CSV downloads (network, large files)
	uv run python evals/verify_golden.py

snapshot:  ## rebuild snapshots/ for the golden tables from live StatCan
	uv run canada-snapshot
