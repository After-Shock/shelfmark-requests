.PHONY: help install dev build preview typecheck clean up down docker-build refresh restart \
       up-tor down-tor refresh-tor up-extbp down-extbp refresh-extbp

# Frontend directory
FRONTEND_DIR := src/frontend

# Docker compose file
COMPOSE_FILE := docker-compose.dev.yml

# Default target
help:
	@echo "Available targets:"
	@echo ""
	@echo "Frontend:"
	@echo "  install    - Install frontend dependencies"
	@echo "  dev        - Start development server"
	@echo "  build      - Build frontend for production"
	@echo "  preview    - Preview production build"
	@echo "  typecheck  - Run TypeScript type checking"
	@echo "  clean      - Remove node_modules and build artifacts"
	@echo ""
	@echo "Backend (Docker):"
	@echo "  up         - Start backend services"
	@echo "  down       - Stop backend services"
	@echo "  restart    - Restart backend services (no rebuild)"
	@echo "  docker-build - Build Docker image"
	@echo "  refresh    - Rebuild and restart backend services"
	@echo ""
	@echo "Backend variants:"
	@echo "  up-tor     - Start Tor variant"
	@echo "  down-tor   - Stop Tor variant"
	@echo "  refresh-tor - Rebuild and restart Tor variant"
	@echo "  up-extbp   - Start external bypasser variant (lite + flaresolverr)"
	@echo "  down-extbp - Stop external bypasser variant"
	@echo "  refresh-extbp - Rebuild and restart external bypasser variant"

# Install dependencies
install:
	@echo "Installing frontend dependencies..."
	cd $(FRONTEND_DIR) && npm install

# Start development server
dev:
	@echo "Starting development server..."
	cd $(FRONTEND_DIR) && npm run dev

# Build for production
build:
	@echo "Building frontend for production..."
	cd $(FRONTEND_DIR) && npm run build

# Preview production build
preview:
	@echo "Previewing production build..."
	cd $(FRONTEND_DIR) && npm run preview

# Type checking
typecheck:
	@echo "Running TypeScript type checking..."
	cd $(FRONTEND_DIR) && npm run typecheck

# Clean build artifacts and dependencies
clean:
	@echo "Cleaning build artifacts and dependencies..."
	rm -rf $(FRONTEND_DIR)/node_modules
	rm -rf $(FRONTEND_DIR)/dist

# Start backend services
up:
	@echo "Starting backend services..."
	docker compose -f $(COMPOSE_FILE) up -d

# Stop backend services
down:
	@echo "Stopping backend services..."
	docker compose -f $(COMPOSE_FILE) down

# Build Docker image
docker-build:
	@echo "Building Docker image..."
	docker compose -f $(COMPOSE_FILE) build

# Restart backend services (no rebuild)
restart:
	@echo "Restarting backend services..."
	docker compose -f $(COMPOSE_FILE) restart

# Rebuild and restart backend services
refresh:
	@echo "Rebuilding and restarting backend services..."
	docker compose -f $(COMPOSE_FILE) down
	docker compose -f $(COMPOSE_FILE) build
	docker compose -f $(COMPOSE_FILE) up -d

# --- Tor variant ---

up-tor:
	@echo "Starting Tor backend services..."
	docker compose -f $(COMPOSE_FILE) --profile tor up -d

down-tor:
	@echo "Stopping Tor backend services..."
	docker compose -f $(COMPOSE_FILE) --profile tor down

refresh-tor:
	@echo "Rebuilding and restarting Tor backend services..."
	docker compose -f $(COMPOSE_FILE) --profile tor down
	docker compose -f $(COMPOSE_FILE) --profile tor build
	docker compose -f $(COMPOSE_FILE) --profile tor up -d

# --- External bypasser variant ---

up-extbp:
	@echo "Starting external bypasser backend services..."
	docker compose -f $(COMPOSE_FILE) --profile extbp up -d

down-extbp:
	@echo "Stopping external bypasser backend services..."
	docker compose -f $(COMPOSE_FILE) --profile extbp down

refresh-extbp:
	@echo "Rebuilding and restarting external bypasser backend services..."
	docker compose -f $(COMPOSE_FILE) --profile extbp down
	docker compose -f $(COMPOSE_FILE) --profile extbp build
	docker compose -f $(COMPOSE_FILE) --profile extbp up -d
