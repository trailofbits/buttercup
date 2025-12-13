# Makefile for Trail of Bits AIxCC Finals CRS

.PHONY: help setup-local setup-azure validate deploy test undeploy install-cscope lint lint-component clean-local wait-crs check-crs crs-instance-id status send-integration-task

# Default target
help:
	@echo "Trail of Bits AIxCC Finals CRS - Available Commands:"
	@echo ""
	@echo "Setup:"
	@echo "  setup-local       - Automated local development setup"
	@echo "  setup-azure       - Automated production AKS setup"
	@echo "  validate          - Validate current setup and configuration"
	@echo ""
	@echo "Deployment:"
	@echo "  deploy            - Deploy to current environment (local or azure)"
	@echo ""
	@echo "Status:"
	@echo "  status              - Check the status of the deployment"
	@echo "  crs-instance-id     - Get the CRS instance ID"
	@echo "  download-artifacts  - Download submitted artifacts from the CRS"
	@echo "  signoz-ui           - Open the SigNoz UI"
	@echo ""
	@echo "Testing:"
	@echo "  send-integration-task  - Run integration-test task"
	@echo "  send-libpng-task  - Run libpng task"
	@echo ""
	@echo "Development:"
	@echo "  install-cscope    - Install cscope tool"
	@echo "  lint              - Lint all Python code"
	@echo "  lint-component    - Lint specific component (e.g., make lint-component COMPONENT=orchestrator)"
	@echo ""
	@echo "Cleanup:"
	@echo "  undeploy          - Remove deployment and clean up resources"
	@echo "  clean-local       - Delete Minikube cluster and remove local config"

# Setup targets
setup-local:
	@echo "Setting up local development environment..."
	./scripts/setup-local.sh

setup-azure:
	@echo "Setting up production AKS environment..."
	./scripts/setup-azure.sh

validate:
	@echo "Validating setup..."
	./scripts/validate-setup.sh

wait-crs:
	@echo "Waiting for CRS deployment to be ready..."
	@if ! kubectl get namespace $${BUTTERCUP_NAMESPACE:-crs} >/dev/null 2>&1; then \
		echo "Error: CRS namespace not found. Deploy first with 'make deploy'."; \
		exit 1; \
	fi
	@while true; do \
		PENDING=$$(kubectl get pods -n $${BUTTERCUP_NAMESPACE:-crs} --no-headers 2>/dev/null | grep -v 'Completed' | grep -v 'Running' | wc -l); \
		if [ "$$PENDING" -eq 0 ]; then \
			echo "All CRS pods are running."; \
			break; \
		else \
			echo "$$PENDING pods are not yet running. Waiting..."; \
			sleep 5; \
		fi \
	done

check-crs:
	@if ! kubectl get namespace $${BUTTERCUP_NAMESPACE:-crs} >/dev/null 2>&1; then \
		echo "Error: CRS namespace not found. Deploy first with 'make deploy'."; \
		exit 1; \
	fi
	@PENDING=$$(kubectl get pods -n $${BUTTERCUP_NAMESPACE:-crs} --no-headers 2>/dev/null | grep -v 'Completed' | grep -v 'Running' | wc -l); \
	if [ "$$PENDING" -eq 0 ]; then \
		echo "All CRS pods up and running."; \
	else \
		echo "$$PENDING pods are not yet running."; \
	fi


crs-instance-id:
	@echo "Getting CRS instance ID..."
	@if ! kubectl get namespace $${BUTTERCUP_NAMESPACE:-crs} >/dev/null 2>&1; then \
		echo "Error: CRS namespace not found. Deploy first with 'make deploy'."; \
		exit 1; \
	fi
	echo "CRS instance ID: $$(kubectl get configmap -n $${BUTTERCUP_NAMESPACE:-crs} crs-instance-id -o jsonpath='{.data.crs-instance-id}')"

deploy:
	@echo "Deploying environment..."
	@if [ ! -f deployment/env ]; then \
		echo "Error: Configuration file not found. Run 'make setup-local' or `make setup-azure` first."; \
		exit 1; \
	fi
	@if [ ! -f external/buttercup-cscope/configure.ac ]; then \
		echo "Error: The git submodules have not been initialized. Run 'git submodule update --init --recursive' first."; \
		exit 1; \
	fi
	@echo "Deployment configuration:"
	@grep 'CLUSTER_TYPE=' deployment/env || echo "CLUSTER_TYPE not set"
	@grep 'K8S_VALUES_TEMPLATE' deployment/env || echo "K8S_VALUES_TEMPLATE not set"
	@if [ "$${FORCE:-false}" != "true" ]; then \
		echo "Are you sure you want to deploy with these settings? Type 'yes' to continue:"; \
		read ans; \
		ans_lc=$$(echo "$$ans" | tr '[:upper:]' '[:lower:]'); \
		if [ "$$ans_lc" != "yes" ] && [ "$$ans_lc" != "y" ]; then \
			echo "Aborted by user."; \
			exit 1; \
		fi; \
	fi
	cd deployment && make up
	make crs-instance-id
	make wait-crs

status:
	@echo "----------PODS------------"
	@kubectl get pods -n $${BUTTERCUP_NAMESPACE:-crs}
	@echo "----------SERVICES--------"
	@kubectl get services -n $${BUTTERCUP_NAMESPACE:-crs}
	@make --no-print-directory check-crs

download-artifacts:
	@echo "Downloading artifacts from the CRS..."
	@if ! kubectl get namespace $${BUTTERCUP_NAMESPACE:-crs} >/dev/null 2>&1; then \
		echo "Error: CRS namespace not found. Deploy first with 'make deploy'."; \
		exit 1; \
	fi
	./scripts/download_artifacts.sh

# Testing targets
send-integration-task:
	@echo "Running integration test task..."
	@if ! kubectl get namespace $${BUTTERCUP_NAMESPACE:-crs} >/dev/null 2>&1; then \
		echo "Error: CRS namespace not found. Deploy first with 'make deploy'."; \
		exit 1; \
	fi
	@kubectl port-forward -n $${BUTTERCUP_NAMESPACE:-crs} service/buttercup-ui 31323:1323 & \
	PORT_FORWARD_PID=$$!; \
	sleep 3; \
	./orchestrator/scripts/task_integration_test.sh; \
	kill $$PORT_FORWARD_PID 2>/dev/null || true

send-libpng-task:
	@echo "Running libpng task..."
	@if ! kubectl get namespace $${BUTTERCUP_NAMESPACE:-crs} >/dev/null 2>&1; then \
		echo "Error: CRS namespace not found. Deploy first with 'make deploy'."; \
		exit 1; \
	fi
	@kubectl port-forward -n $${BUTTERCUP_NAMESPACE:-crs} service/buttercup-ui 31323:1323 & \
	PORT_FORWARD_PID=$$!; \
	sleep 3; \
	./orchestrator/scripts/task_crs.sh; \
	kill $$PORT_FORWARD_PID 2>/dev/null || true

# Development targets
lint:
	@echo "Linting all Python code..."
	@set -e; for component in common orchestrator fuzzer fuzzer_runner program-model seed-gen patcher; do \
		make --no-print-directory lint-component COMPONENT=$$component; \
	done

# Note: common, patcher, orchestrator, program-model, seed-gen run mypy
lint-component:
	@if [ -z "$(COMPONENT)" ]; then \
		echo "Error: COMPONENT not specified. Usage: make lint-component COMPONENT=<component>"; \
		echo "Available components: common, fuzzer, orchestrator, patcher, program-model, seed-gen"; \
		exit 1; \
	fi
	@echo "Linting $(COMPONENT)..."
	@cd $(COMPONENT) && uv sync -q --all-extras && uv run ruff format --check && uv run ruff check
	@if [ "$(COMPONENT)" = "common" ] || [ "$(COMPONENT)" = "patcher" ] || [ "$(COMPONENT)" = "orchestrator" ] || [ "$(COMPONENT)" = "program-model" ] || [ "$(COMPONENT)" = "seed-gen" ] || [ "$(COMPONENT)" = "fuzzer" ]; then \
		cd $(COMPONENT) && uv run mypy; \
	fi

reformat:
	@echo "Reformatting all Python code..."
	@for component in common orchestrator fuzzer fuzzer_runner program-model seed-gen patcher; do \
		make --no-print-directory reformat-component COMPONENT=$$component; \
	done

reformat-component:
	@if [ -z "$(COMPONENT)" ]; then \
		echo "Error: COMPONENT not specified. Usage: make reformat-component COMPONENT=<component>"; \
		echo "Available components: common, fuzzer, orchestrator, patcher, program-model, seed-gen"; \
		exit 1; \
	fi
	@echo "Reformatting $(COMPONENT)..."
	@cd $(COMPONENT) && uv sync -q --all-extras && uv run ruff format && uv run ruff check --fix

# Cleanup targets
undeploy:
	@echo "Cleaning up deployment..."
	cd deployment && make down

undeploy-k8s:
	@echo "Cleaning up kubernetes resources..."
	cd deployment && make down-k8s

clean-local:
	@echo "Cleaning up local environment..."
	minikube delete || true
	rm -f deployment/env

# Additional targets migrated from justfile
install-cscope:
	cd external/buttercup-cscope/ && autoreconf -i -s && ./configure && make && sudo make install

signoz-ui:
	@echo "Opening SigNoz UI..."
	@echo ""
	@echo "NOTE: If you plan to redeploy and access SigNoz, clear your browser cookies for http://localhost:33301 to avoid login issues."
	@echo ""
	@if ! kubectl get namespace $${BUTTERCUP_NAMESPACE:-crs} >/dev/null 2>&1; then \
		echo "Error: CRS namespace not found. Deploy first with 'make deploy'."; \
		exit 1; \
	fi
	@if ! kubectl get service/buttercup-signoz-frontend -n $${BUTTERCUP_NAMESPACE:-crs} >/dev/null 2>&1; then \
		echo "Error: SigNoz is not deployed. Set DEPLOY_SIGNOZ=true in deployment/env and redeploy."; \
		exit 1; \
	fi
	kubectl port-forward -n $${BUTTERCUP_NAMESPACE:-crs} service/buttercup-signoz-frontend 33301:3301 &
	@sleep 3
	@if command -v xdg-open >/dev/null 2>&1; then \
		xdg-open http://localhost:33301; \
	elif command -v open >/dev/null 2>&1; then \
		open http://localhost:33301; \
	else \
		echo "Please open http://localhost:33301 in your browser."; \
	fi

web-ui:
	@./scripts/web_ui.sh
