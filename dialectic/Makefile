.PHONY: setup python-setup run frontend frontend-install frontend-dev \
	frontend-build frontend-lint db-setup db-reset clean

VENV := venv
PYTHON := $(VENV)/bin/python3
PIP := $(VENV)/bin/pip
VENV_STAMP := $(VENV)/.dialectic-installed
FRONTEND_DIR := frontend/app
FRONTEND_STAMP := $(FRONTEND_DIR)/node_modules/.package-lock.json
DB_NAME := dialectic
DB_USER := postgres
DB_OWNER := $(DB_USER)
PSQL := sudo -u $(DB_USER) psql --no-psqlrc --set=ON_ERROR_STOP=1
BASELINE_SQL := schema.sql migrations/001_llm_self_model.sql migrations/add_indexes.sql

setup: python-setup frontend-install db-setup
	@echo "Setup complete. Run 'make run' and 'make frontend-dev' in separate terminals."

python-setup: $(VENV_STAMP)

$(VENV_STAMP): requirements.txt
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@touch $(VENV_STAMP)

run: $(VENV_STAMP)
	$(PYTHON) run.py

frontend: frontend-dev

frontend-install: $(FRONTEND_STAMP)

$(FRONTEND_STAMP): $(FRONTEND_DIR)/package-lock.json
	cd $(FRONTEND_DIR) && npm ci

frontend-dev: frontend-install
	cd $(FRONTEND_DIR) && npm run dev

frontend-build: frontend-install
	cd $(FRONTEND_DIR) && npm run build

frontend-lint: frontend-install
	cd $(FRONTEND_DIR) && npm run lint

db-setup:
	@echo "WARNING: db-setup is a fresh-database baseline, not a migration runner."
	@echo "schema.sql already includes migrations 002, 003, 004, and cross_session_memories."
	@echo "Existing databases require a reviewed migration applied with ON_ERROR_STOP."
	@set -eu; \
		exists="$$(sudo -u $(DB_USER) psql --no-psqlrc --set=ON_ERROR_STOP=1 \
			--dbname=postgres --tuples-only --no-align \
			--command="SELECT 1 FROM pg_database WHERE datname = '$(DB_NAME)'")"; \
		if [ "$$exists" = "1" ]; then \
			echo "Refusing to baseline existing database '$(DB_NAME)'." >&2; \
			echo "Use a reviewed migration file; do not replay schema.sql." >&2; \
			exit 2; \
		fi; \
		sudo -u $(DB_USER) createdb --owner=$(DB_OWNER) $(DB_NAME)
	@echo "Enabling pgvector extension..."
	$(PSQL) --dbname=$(DB_NAME) --command="CREATE EXTENSION IF NOT EXISTS vector;"
	@echo "Applying the fresh baseline in one transaction: $(BASELINE_SQL)"
	$(PSQL) --single-transaction --dbname=$(DB_NAME) \
		--command='SET ROLE "$(DB_OWNER)";' \
		$(foreach file,$(BASELINE_SQL),--file=$(file))
	@echo "Database setup complete."

db-reset:
	@echo "WARNING: dropping database '$(DB_NAME)' and all of its data."
	sudo -u $(DB_USER) dropdb --if-exists $(DB_NAME)
	$(MAKE) db-setup

clean:
	rm -rf $(VENV)
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "Cleaned."
