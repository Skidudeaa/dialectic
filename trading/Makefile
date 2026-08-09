.PHONY: dev dev-backend dev-frontend build test docker-up docker-down install

# Development — starts both backend and frontend
dev:
	@echo "Starting backend on :8000 and frontend on :5173..."
	@make dev-backend &
	@make dev-frontend

dev-backend:
	python3 -m uvicorn web.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev

# Install dependencies
install:
	pip install -r requirements.txt
	cd frontend && npm install

# Build frontend for production
build:
	cd frontend && npm run build

# Run all tests (223 existing + any new)
test:
	python3 -m pytest tools/thesis-graph/test_export.py tools/bridge/test_diff.py \
		tools/bridge/test_push.py tools/bridge/test_run_all.py \
		tools/data-fetch/test_polymarket.py tools/validation/e2e_test.py -q

# Docker
docker-up:
	docker compose up -d --build

docker-down:
	docker compose down
