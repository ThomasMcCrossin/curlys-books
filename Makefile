.PHONY: help up down logs restart clean test lint format migrate seed backup restore

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

up: ## Start all services
	@echo "🚀 Starting Curly's Books..."
	docker compose up -d
	@echo "✅ Services started:"
	@echo "   📊 API:  http://localhost:8000"
	@echo "   🌐 Web:  http://localhost:3000"
	@echo "   💾 DB:   localhost:5432"

down: ## Stop all services
	@echo "🛑 Stopping Curly's Books..."
	docker compose down

logs: ## Show logs (use ARGS="service_name" for specific service)
	docker compose logs -f $(ARGS)

restart: down up ## Restart all services

clean: ## Remove all containers, volumes, and caches
	@echo "🧹 Cleaning up..."
	docker compose down -v
	rm -rf .next .pytest_cache __pycache__
	find . -type d -name "__pycache__" -exec rm -rf {} +
	@echo "✅ Cleanup complete"

test: ## Run all tests
	@echo "🧪 Running tests..."
	docker compose exec api pytest tests/ -v --cov=packages --cov=apps/api --cov-report=term-missing --cov-report=html
	@echo "📊 Coverage report: htmlcov/index.html"

test-unit: ## Run unit tests only
	docker compose exec api pytest tests/unit/ -v

test-integration: ## Run integration tests only
	docker compose exec api pytest tests/integration/ -v

test-golden: ## Run golden receipt tests
	docker compose exec worker pytest tests/fixtures/golden_receipts/ -v

lint: ## Run linters (Python + TypeScript)
	@echo "🔍 Linting Python..."
	docker compose exec api ruff check .
	docker compose exec api mypy apps/api packages/
	@echo "🔍 Linting TypeScript..."
	docker compose exec web npm run lint

format: ## Format code (Python + TypeScript)
	@echo "✨ Formatting Python..."
	docker compose exec api black .
	docker compose exec api isort .
	docker compose exec api ruff check --fix .
	@echo "✨ Formatting TypeScript..."
	docker compose exec web npm run format

migrate: ## Run database migrations
	@echo "🗄️  Running migrations..."
	docker compose exec api alembic upgrade head
	@echo "✅ Migrations complete"

migrate-create: ## Create new migration (use ARGS="migration_message")
	@echo "📝 Creating migration..."
	docker compose exec api alembic revision --autogenerate -m "$(ARGS)"

migrate-down: ## Rollback one migration
	docker compose exec api alembic downgrade -1

seed: ## Seed database with initial data
	@echo "🌱 Seeding database..."
	docker compose exec api python scripts/seed_database.py
	@echo "✅ Database seeded"

import-csv: ## Import CSV statements (use ARGS="path/to/file.csv entity_name")
	@echo "📥 Importing CSV..."
	docker compose exec api python scripts/import_statements.py $(ARGS)

backup: ## Backup database and objects
	@echo "💾 Creating backup..."
	./infra/ops/backup_restore.sh backup
	@echo "✅ Backup complete"

restore: ## Restore from backup (use ARGS="backup_timestamp")
	@echo "♻️  Restoring from backup..."
	./infra/ops/backup_restore.sh restore $(ARGS)
	@echo "✅ Restore complete"

shell-api: ## Open shell in API container
	docker compose exec api /bin/bash

shell-worker: ## Open shell in worker container
	docker compose exec worker /bin/bash

shell-db: ## Open PostgreSQL shell
	docker compose exec postgres psql -U curlys_admin -d curlys_books

build: ## Rebuild all Docker images
	@echo "🔨 Building images..."
	docker compose build
	@echo "✅ Build complete"

pre-commit-install: ## Install pre-commit hooks
	pip install pre-commit
	pre-commit install
	@echo "✅ Pre-commit hooks installed"

check-imports: ## Verify no illegal cross-imports
	@echo "🔍 Checking import boundaries..."
	docker compose exec api import-linter --config .import-linter.toml
	@echo "✅ Import boundaries clean"

dev-setup: ## Initial development setup
	@echo "🛠️  Setting up development environment..."
	cp .env.example .env
	@echo "📝 Edit .env with your configuration"
	@echo "Then run: make build && make up && make migrate && make seed"

health: ## Check health of all services
	@echo "🏥 Checking service health..."
	@curl -f http://localhost:8000/health || echo "❌ API unhealthy"
	@curl -f http://localhost:3000/api/health || echo "❌ Web unhealthy"
	@docker compose exec postgres pg_isready -U curlys_admin || echo "❌ DB unhealthy"
	@docker compose exec redis redis-cli ping || echo "❌ Redis unhealthy"
	@echo "✅ Health check complete"

stats: ## Show container stats
	docker stats --no-stream curlys-books-api curlys-books-worker curlys-books-web curlys-books-db curlys-books-redis