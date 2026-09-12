# BAROGROOVE — local dev harness.
#
# `make demo` is the 60-second path: no credentials, no network, a real
# explained playlist. Start there.

SHELL := /bin/bash
PY    := .venv/bin/python
PIP   := .venv/bin/pip
PORT  ?= 8000

.DEFAULT_GOAL := help
.PHONY: help venv install dev run test lint typecheck fmt demo clean docker-build docker-run deploy

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[1m%-14s\033[0m %s\n", $$1, $$2}'

venv:  ## Create the local virtualenv
	python3.13 -m venv .venv || python3 -m venv .venv
	$(PIP) install --quiet --upgrade pip

install: venv  ## Install runtime + dev dependencies
	$(PIP) install -r requirements.txt
	$(PIP) install pytest pytest-asyncio pytest-cov ruff mypy

dev: run  ## Alias for run

run:  ## Serve locally with reload. Works with a completely empty environment.
	BG_ENVIRONMENT=local $(PY) -m uvicorn app:app --reload --port $(PORT)

offline:  ## Serve with fixture weather and the offline oracle. No network at all.
	BG_ENVIRONMENT=local BG_WEATHER_OFFLINE=1 BG_LASTFM_ENABLED=0 \
	  $(PY) -m uvicorn app:app --reload --port $(PORT)

test:  ## Run the test suite (no network required, none permitted)
	$(PY) -m pytest

lint:  ## Ruff
	$(PY) -m ruff check backend tests app.py

fmt:  ## Ruff format
	$(PY) -m ruff format backend tests app.py

typecheck:  ## mypy
	$(PY) -m mypy backend app.py

demo:  ## The 60-second demo: forge a playlist from fixture weather, no credentials
	@BG_ENVIRONMENT=local BG_WEATHER_OFFLINE=1 $(PY) -m scripts.demo

docker-build:  ## Build the Cloud Run image
	docker build -t barogroove:local .

docker-run: docker-build  ## Run the container locally on :8080
	docker run --rm -p 8080:8080 -e PORT=8080 barogroove:local

deploy:  ## Deploy to Cloud Run (europe-west1) + Firebase Hosting
	./deploy/deploy.sh

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .mypy_cache
