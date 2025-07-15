# Buttercup CRS - Local Deployment Makefile

# Variables
COMPOSE_FILE := ../compose.yaml
ENV_FILE := ../env.dev.compose

# Default target
.PHONY: help
help:
	@echo "Buttercup CRS - Local Docker Compose Deployment"
	@echo ""
	@echo "Usage:"
	@echo "  make up       # Start all services"
	@echo "  make down     # Stop all services"
	@echo "  make restart  # Restart all services"
	@echo "  make logs     # View logs for all services"
	@echo "  make status   # Show status of all services"
	@echo "  make clean    # Remove volumes and clean up"
	@echo ""
	@echo "Service-specific commands:"
	@echo "  make logs-<service>  # View logs for specific service"
	@echo "  make restart-<service>  # Restart specific service"

# Check if compose file exists
.PHONY: check-compose
check-compose:
	@test -f $(COMPOSE_FILE) || (echo "Error: $(COMPOSE_FILE) not found" && exit 1)

# Start all services
.PHONY: up
up: check-compose
	@echo "Starting Buttercup CRS services..."
	@cd .. && docker compose up -d
	@echo "Services started. Run 'make status' to check their status."

# Stop all services
.PHONY: down
down: check-compose
	@echo "Stopping Buttercup CRS services..."
	@cd .. && docker compose down
	@echo "Services stopped."

# Restart all services
.PHONY: restart
restart: down up

# View logs for all services
.PHONY: logs
logs: check-compose
	@cd .. && docker compose logs -f

# Show status of all services
.PHONY: status
status: check-compose
	@cd .. && docker compose ps

# Clean up volumes and containers
.PHONY: clean
clean: down
	@echo "Cleaning up volumes and containers..."
	@cd .. && docker compose down -v
	@echo "Clean up complete."

# Service-specific targets
.PHONY: logs-%
logs-%: check-compose
	@cd .. && docker compose logs -f $*

.PHONY: restart-%
restart-%: check-compose
	@cd .. && docker compose restart $*

# Quick access to common services
.PHONY: logs-redis
logs-redis: logs-redis

.PHONY: logs-scheduler
logs-scheduler: logs-scheduler

.PHONY: logs-patcher
logs-patcher: logs-patcher

.PHONY: logs-fuzzer
logs-fuzzer: logs-fuzzer-bot

.PHONY: logs-task-server
logs-task-server: logs-task-server