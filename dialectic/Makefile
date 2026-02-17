.PHONY: setup run frontend db-setup db-reset clean

VENV := venv
PYTHON := $(VENV)/bin/python3
PIP := $(VENV)/bin/pip
DB_NAME := dialectic
DB_USER := postgres
DATABASE_URL := postgresql://$(DB_USER)@localhost/$(DB_NAME)

setup: $(VENV) db-setup
	@echo "Setup complete. Run 'make run' to start the backend."

$(VENV): requirements.txt
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@touch $(VENV)

run: $(VENV)
	DATABASE_URL=$(DATABASE_URL) $(PYTHON) run.py

frontend:
	python3 -m http.server 3000 --directory frontend

db-setup:
	@echo "Ensuring database '$(DB_NAME)' exists..."
	sudo -u $(DB_USER) psql -tc "SELECT 1 FROM pg_database WHERE datname = '$(DB_NAME)'" | grep -q 1 \
		|| sudo -u $(DB_USER) createdb $(DB_NAME)
	@echo "Enabling pgvector extension..."
	sudo -u $(DB_USER) psql $(DB_NAME) -c "CREATE EXTENSION IF NOT EXISTS vector;"
	@echo "Applying schema (idempotent)..."
	sudo -u $(DB_USER) psql $(DB_NAME) -f schema.sql 2>&1 | grep -v "already exists" || true
	@echo "Applying migrations..."
	@for f in migrations/*.sql; do \
		echo "  -> $$f"; \
		sudo -u $(DB_USER) psql $(DB_NAME) -f "$$f" 2>&1 | grep -v "already exists" || true; \
	done
	@echo "Database setup complete."

db-reset:
	@echo "Dropping and recreating database '$(DB_NAME)'..."
	sudo -u $(DB_USER) dropdb --if-exists $(DB_NAME)
	sudo -u $(DB_USER) createdb $(DB_NAME)
	$(MAKE) db-setup

clean:
	rm -rf $(VENV)
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "Cleaned."
