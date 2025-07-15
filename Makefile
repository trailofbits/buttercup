# Makefile for Trail of Bits AIxCC Finals CRS

.PHONY: help setup deploy test clean status logs lint lint-component

# Default target
help:
	@echo "Trail of Bits AIxCC Finals CRS - Available Commands:"
	@echo ""
	@echo "Setup:"
	@echo "  setup             - Set up local development environment"
	@echo "  validate          - Validate current setup and configuration"
	@echo ""
	@echo "Deployment:"
	@echo "  deploy            - Start all services with Docker Compose"
	@echo "  stop              - Stop all services"
	@echo "  restart           - Restart all services"
	@echo ""
	@echo "Testing:"
	@echo "  test              - Run integration test"
	@echo "  test-api          - Test API endpoints"
	@echo ""
	@echo "Development:"
	@echo "  status            - Show service status"
	@echo "  logs              - View all logs"
	@echo "  lint              - Lint all Python code"
	@echo "  lint-component    - Lint specific component (e.g., make lint-component COMPONENT=orchestrator)"
	@echo ""
	@echo "Cleanup:"
	@echo "  clean             - Stop services and remove volumes"
	@echo "  clean-all         - Full cleanup including Docker images"

# Setup targets
setup:
	@echo "Setting up local development environment..."
	@if [ -f ./scripts/setup-local.sh ]; then \
		./scripts/setup-local.sh; \
	else \
		./local-dev.sh setup; \
	fi

validate:
	@echo "Validating setup..."
	@echo "Checking Docker..."
	@docker info > /dev/null 2>&1 || (echo "Error: Docker is not running" && exit 1)
	@echo "✓ Docker is running"
	@echo ""
	@echo "Checking environment file..."
	@if [ -f env.dev.compose ]; then \
		echo "✓ env.dev.compose exists"; \
		grep -q "OPENAI_API_KEY" env.dev.compose && echo "✓ OpenAI API key configured" || echo "⚠ OpenAI API key not set"; \
		grep -q "ANTHROPIC_API_KEY" env.dev.compose && echo "✓ Anthropic API key configured" || echo "⚠ Anthropic API key not set"; \
	else \
		echo "✗ env.dev.compose not found. Run 'make setup' first."; \
		exit 1; \
	fi
	@echo ""
	@echo "Checking ports..."
	@lsof -i :8000 > /dev/null 2>&1 && echo "⚠ Port 8000 is in use" || echo "✓ Port 8000 is available"
	@lsof -i :6379 > /dev/null 2>&1 && echo "⚠ Port 6379 is in use" || echo "✓ Port 6379 is available"
	@lsof -i :8080 > /dev/null 2>&1 && echo "⚠ Port 8080 is in use" || echo "✓ Port 8080 is available"

# Deployment targets
deploy:
	@echo "Starting services with Docker Compose..."
	./local-dev.sh up

stop:
	@echo "Stopping services..."
	./local-dev.sh down

restart:
	@echo "Restarting services..."
	./local-dev.sh restart

# Testing targets
test:
	@echo "Running integration test..."
	@echo "Waiting for services to be ready..."
	@sleep 10
	./orchestrator/scripts/task_integration_test.sh

test-api:
	@echo "Testing API endpoints..."
	@echo "Task Server:" && curl -s http://localhost:8000/health | jq . || echo "Failed"
	@echo "LiteLLM:" && curl -s http://localhost:8080/health | jq . || echo "Failed"
	@echo "Competition API:" && curl -s http://localhost:31323/ping || echo "Failed"

# Development targets
status:
	@echo "Checking service status..."
	./local-dev.sh status

logs:
	@echo "Viewing logs (Ctrl+C to stop)..."
	./local-dev.sh logs -f

lint:
	@echo "Linting all Python code..."
	just lint-python-all

lint-component:
	@if [ -z "$(COMPONENT)" ]; then \
		echo "Error: COMPONENT not specified. Usage: make lint-component COMPONENT=<component>"; \
		echo "Available components: common, fuzzer, orchestrator, patcher, program-model, seed-gen"; \
		exit 1; \
	fi
	@echo "Linting $(COMPONENT)..."
	just lint-python $(COMPONENT)

# Cleanup targets
clean:
	@echo "Cleaning up services and volumes..."
	./local-dev.sh clean

clean-all:
	@echo "Full cleanup including Docker images..."
	./local-dev.sh down
	docker compose down -v --remove-orphans
	docker system prune -a --volumes -f
	rm -rf ./crs_scratch ./tasks_storage ./node_data_storage