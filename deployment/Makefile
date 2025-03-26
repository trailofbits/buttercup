# Makefile

# Variables
SCRIPT := crs-architecture.sh
GENERATED_FILES := k8s/base/tailscale-coredns/coredns-custom.yaml \
		   k8s/base/tailscale-operator/operator.yaml \
		   k8s/values-aks.yaml

# Default target when just running `make`
.PHONY: help
help:
	@echo "Usage:"
	@echo "  make up     # Deploys the AKS cluster and resources"
	@echo "  make down   # Destroys the AKS cluster and resources"
	@echo "  make clean  # Removes generated files from templates (optional)"

#check script exists and is executable
.PHONY: check
check:
	@test -f $(SCRIPT) || (echo "Error: $(SCRIPT) not found" && exit 1)
	@test -x $(SCRIPT) || (echo "Error: $(SCRIPT) not executable" && exit 1)

# up target
.PHONY: up
up: check clean
	@bash $(SCRIPT) up

# down target
.PHONY: down
down: check
	@bash $(SCRIPT) down

down-k8s:
	@bash $(SCRIPT) down-k8s

# Clean up generated files (optional)
.PHONY: clean
clean:
	@rm -f $(GENERATED_FILES)
