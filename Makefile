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
	make wait-crs

wait-crs:
	@echo "Waiting for CRS deployment to be ready..."
	@if ! kubectl get namespace crs >/dev/null 2>&1; then \
		echo "Error: CRS namespace not found. Deploy first with 'make deploy'."; \
		exit 1; \
	fi
	@while true; do \
		PENDING=$$(kubectl get pods -n crs --no-headers 2>/dev/null | grep -v 'Completed' | grep -v 'Running' | wc -l); \
		if [ "$$PENDING" -eq 0 ]; then \
			echo "All CRS pods are running."; \
			break; \
		else \
			echo "$$PENDING pods are not yet running. Waiting..."; \
			sleep 5; \
		fi \
	done

crs-instance-id:
	@echo "Getting CRS instance ID..."
	@if ! kubectl get namespace crs >/dev/null 2>&1; then \
		echo "Error: CRS namespace not found. Deploy first with 'make deploy'."; \
		exit 1; \
	fi
	echo "CRS instance ID: $$(kubectl get configmap -n crs crs-instance-id -o jsonpath='{.data.crs-instance-id}')"

deploy-local:
	@echo "Deploying to local Minikube environment..."
	@if [ ! -f deployment/env ]; then \
		echo "Error: Configuration file not found. Run 'make setup-local' first."; \
		exit 1; \
	fi
	cd deployment && make up
	make crs-instance-id
	make wait-crs

deploy-production:
	@echo "Deploying to production AKS environment..."
	@if [ ! -f deployment/env ]; then \
		echo "Error: Configuration file not found. Run 'make setup-production' first."; \
		exit 1; \
	fi
	cd deployment && make up
	crs_instance_id=$$(make crs-instance-id)
	echo "CRS instance ID: $$crs_instance_id"
	make wait-crs

status:
	@echo "----------PODS------------"
	@kubectl get pods -n $${BUTTERCUP_NAMESPACE:-crs}
	@echo "----------SERVICES--------"
	@kubectl get services -n $${BUTTERCUP_NAMESPACE:-crs}

# Testing targets
test:
	@echo "Running test task..."
	@if ! kubectl get namespace crs >/dev/null 2>&1; then \
		echo "Error: CRS namespace not found. Deploy first with 'make deploy'."; \
		exit 1; \
	fi
	kubectl port-forward -n crs service/buttercup-ui 31323:1323 &
	@sleep 3
	./orchestrator/scripts/task_integration_test.sh
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
