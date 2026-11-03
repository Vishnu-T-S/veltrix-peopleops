.PHONY: test run

test:
	uv run pytest -q

run:
	uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
