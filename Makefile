.PHONY: up down migrate test live lint fmt

INDEX_DUMP := data/index.sql.zst

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
