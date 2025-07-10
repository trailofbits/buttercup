# Makefile for Trail of Bits AIxCC Finals CRS

.PHONY: help setup-local setup-production validate deploy deploy-local deploy-production test clean

# Default target
help:
	@echo "Trail of Bits AIxCC Finals CRS - Available Commands:"
	@echo ""
	@echo "Setup:"
	@echo "  setup-local       - Automated local development setup"
	@echo "  setup-production  - Automated production AKS setup"
	@echo "  validate          - Validate current setup and configuration"
	@echo ""
	@echo "Deployment:"
	@echo "  deploy            - Deploy to current environment (local or production)"
	@echo "  deploy-local      - Deploy to local Minikube environment"
	@echo "  deploy-production - Deploy to production AKS environment"
	@echo ""
	@echo "Testing:"
	@echo "  test              - Run test task"
	@echo "  test-challenge    - Run unscored challenge"
	@echo ""
	@echo "Development:"
	@echo "  lint              - Lint all Python code"
	@echo "  lint-component    - Lint specific component (e.g., make lint-component COMPONENT=orchestrator)"
	@echo ""
	@echo "Cleanup:"
	@echo "  clean             - Clean up deployment"
	@echo "  clean-local       - Clean up local environment"

# Setup targets
setup-local:
	@echo "Setting up local development environment..."
	./scripts/setup-local.sh

setup-production:
	@echo "Setting up production AKS environment..."
	./scripts/setup-production.sh

validate:
	@echo "Validating setup..."
	./scripts/validate-setup.sh

# Deployment targets
deploy:
	@echo "Deploying to current environment..."
	cd deployment && make up

deploy-local:
	@echo "Deploying to local Minikube environment..."
	@if [ ! -f deployment/env ]; then \
		echo "Error: Configuration file not found. Run 'make setup-local' first."; \
		exit 1; \
	fi
	cd deployment && make up

deploy-production:
	@echo "Deploying to production AKS environment..."
	@if [ ! -f deployment/env ]; then \
		echo "Error: Configuration file not found. Run 'make setup-production' first."; \
		exit 1; \
	fi
	cd deployment && make up

# Testing targets
test:
	@echo "Running test task..."
	@if ! kubectl get namespace crs >/dev/null 2>&1; then \
		echo "Error: CRS namespace not found. Deploy first with 'make deploy'."; \
		exit 1; \
	fi
	kubectl port-forward -n crs service/buttercup-competition-api 31323:1323 &
	@sleep 3
	./orchestrator/scripts/task_crs.sh
	@pkill -f "kubectl port-forward" || true

# Development targets
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
	@echo "Cleaning up deployment..."
	cd deployment && make down

clean-local:
	@echo "Cleaning up local environment..."
	minikube delete || true
	rm -f deployment/env
