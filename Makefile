# rtl-sdr-channel-detector — Makefile
#
# Thin, discoverable wrappers around docker compose, the helper scripts, and the
# ESP32 (PlatformIO) firmware build. Run `make` or `make help` for the list.

# Use bash with strict flags for recipe lines.
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

# Compose command (v2 plugin syntax).
COMPOSE ?= docker compose

# ESP32 firmware lives under firmware/. The PlatformIO project (the directory
# containing platformio.ini) may be nested (e.g. firmware/<board>/), so we
# auto-discover it at recipe time. Override with FIRMWARE_DIR=... if needed.
FIRMWARE_DIR ?=
# Shell snippet that resolves the pio project dir, honoring FIRMWARE_DIR override.
define _find_pio_dir
d="$(FIRMWARE_DIR)"; \
if [ -z "$$d" ]; then \
  ini=$$(find firmware -name platformio.ini 2>/dev/null | head -n1); \
  if [ -n "$$ini" ]; then d=$$(dirname "$$ini"); else d=firmware; fi; \
fi
endef

.DEFAULT_GOAL := help

.PHONY: help bootstrap build up down logs restart sim test-backend test-frontend \
        build-frontend lint fmt esp32-build esp32-upload esp32-monitor reset-data clean

help: ## Show this help
	@echo "rtl-sdr-channel-detector — available targets:"
	@echo ""
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Quickstart: make bootstrap && make up   ->   http://localhost:8080"

bootstrap: ## First-time setup: create dirs, .env, detect SDR
	@bash scripts/bootstrap.sh

build: ## Build the Docker image
	@$(COMPOSE) build

up: ## Start the app (detached) and print the URL
	@bash scripts/start.sh

down: ## Stop the app
	@bash scripts/stop.sh

logs: ## Follow application logs
	@$(COMPOSE) logs -f --tail=200

restart: ## Restart the app
	@$(COMPOSE) restart

sim: ## Run in simulation mode (no dongle) in the foreground
	@SIMULATION_MODE=true SDR_BACKEND=sim $(COMPOSE) up --build

test-backend: ## Run backend tests inside the image
	@$(COMPOSE) run --rm --no-deps app python -m pytest -q || \
		{ echo "Falling back to local pytest (needs a local venv)"; cd backend && python -m pytest -q; }

test-frontend: ## Run frontend unit tests
	@cd frontend && npm test --silent

build-frontend: ## Build the frontend bundle locally
	@cd frontend && npm ci && npm run build

lint: ## Lint backend (ruff) and frontend (eslint)
	@echo "== ruff (backend) =="; cd backend && (ruff check . || true)
	@echo "== eslint (frontend) =="; cd frontend && (npm run lint || true)

fmt: ## Format backend (ruff format) and frontend (prettier)
	@echo "== ruff format (backend) =="; cd backend && (ruff format . || true)
	@echo "== prettier (frontend) =="; cd frontend && (npm run format || npx prettier --write . || true)

# --- ESP32 firmware (PlatformIO) -------------------------------------------
# These guard on `pio` being installed and the firmware dir existing so the
# Makefile is usable even when firmware tooling is absent.
esp32-build: ## Build ESP32 firmware (PlatformIO)
	@if ! command -v pio >/dev/null 2>&1; then \
		echo "PlatformIO 'pio' not found. Install: pip install platformio"; exit 1; fi
	@$(_find_pio_dir); \
	if [ ! -f "$$d/platformio.ini" ]; then \
		echo "No platformio.ini found under firmware/ (owned by the firmware agent)."; exit 1; fi; \
	echo "Using PlatformIO project: $$d"; cd "$$d" && pio run

esp32-upload: ## Build + flash ESP32 firmware over serial
	@if ! command -v pio >/dev/null 2>&1; then \
		echo "PlatformIO 'pio' not found. Install: pip install platformio"; exit 1; fi
	@$(_find_pio_dir); \
	if [ ! -f "$$d/platformio.ini" ]; then \
		echo "No platformio.ini found under firmware/ (owned by the firmware agent)."; exit 1; fi; \
	echo "Using PlatformIO project: $$d"; cd "$$d" && pio run --target upload

esp32-monitor: ## Open the ESP32 serial monitor
	@if ! command -v pio >/dev/null 2>&1; then \
		echo "PlatformIO 'pio' not found. Install: pip install platformio"; exit 1; fi
	@$(_find_pio_dir); \
	if [ ! -f "$$d/platformio.ini" ]; then \
		echo "No platformio.ini found under firmware/ (owned by the firmware agent)."; exit 1; fi; \
	echo "Using PlatformIO project: $$d"; cd "$$d" && pio device monitor

# --- Data / cleanup ---------------------------------------------------------
reset-data: ## Delete DB/recordings/logs (keeps dirs), with confirmation
	@bash scripts/reset_data.sh

clean: ## Remove build artifacts and containers/volumes
	@$(COMPOSE) down --remove-orphans || true
	@rm -rf frontend/dist frontend/node_modules/.vite
	@find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	@echo "Cleaned build artifacts."
