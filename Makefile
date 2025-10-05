# Bol.com Scraper - Docker Commands

.PHONY: help build up down logs clean dev prod backup restore

# Default target
help:
	@echo "🐳 Bol.com Scraper - Docker Commands"
	@echo ""
	@echo "Development:"
	@echo "  make dev     - Start development environment"
	@echo "  make build   - Build Docker image"
	@echo "  make up      - Start containers"
	@echo "  make down    - Stop containers"
	@echo "  make logs    - Show logs"
	@echo ""
	@echo "Production:"
	@echo "  make prod    - Start production environment (with Nginx)"
	@echo ""
	@echo "Maintenance:"
	@echo "  make clean   - Clean up containers and images"
	@echo "  make backup  - Backup data"
	@echo "  make restore - Restore data from backup"
	@echo ""
	@echo "Utilities:"
	@echo "  make shell   - Open shell in container"
	@echo "  make test    - Test application"

# Development
dev: build up

build:
	@echo "🔨 Building Docker image..."
	docker compose build

up:
	@echo "🚀 Starting development environment..."
	docker compose up -d

down:
	@echo "🛑 Stopping containers..."
	docker compose down

logs:
	@echo "📋 Showing logs..."
	docker compose logs -f

# Production
prod:
	@echo "🚀 Starting production environment..."
	docker compose --profile production up -d --build

# Maintenance
clean:
	@echo "🧹 Cleaning up..."
	docker compose down -v
	docker system prune -f
	docker volume prune -f

backup:
	@echo "💾 Creating backup..."
	@mkdir -p backups
	@tar -czf backups/backup-$(shell date +%Y%m%d-%H%M%S).tar.gz data/ static/ bol_scraper/
	@echo "✅ Backup created in backups/ directory"

restore:
	@echo "📦 Available backups:"
	@ls -la backups/*.tar.gz 2>/dev/null || echo "No backups found"
	@echo "To restore, run: tar -xzf backups/backup-YYYYMMDD-HHMMSS.tar.gz"

# Utilities
shell:
	@echo "🐚 Opening shell in container..."
	docker compose exec bol-scraper bash

test:
	@echo "🧪 Testing application..."
	@curl -f http://localhost:5000/ || echo "❌ Application not responding"
	@curl -f http://localhost:5000/health 2>/dev/null && echo "✅ Health check passed" || echo "⚠️  Health check not available"

# Install playwright browsers
playwright:
	@echo "📦 Installing Playwright browsers..."
	docker compose exec bol-scraper python -m playwright install chromium
	docker compose exec bol-scraper python -m playwright install-deps chromium

# Quick setup
setup: build up playwright
	@echo "✅ Setup complete! Application available at http://localhost:5000"
