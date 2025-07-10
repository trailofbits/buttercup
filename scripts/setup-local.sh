#!/bin/bash

# Local Development Setup Script for Buttercup CRS
# This script automates the setup process for local development

set -e

# Source common functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

echo "🚀 Setting up Buttercup CRS for local development..."

# Check if running as root
check_not_root

# Function to setup configuration
setup_config() {
    setup_config_file
    
    # Configure LangFuse (optional)
    configure_langfuse
    
    # Configure OTEL telemetry (optional)
    configure_otel
    
    # Check if configuration needs to be updated
    if ! grep -q "BUTTERCUP_K8S_VALUES_TEMPLATE.*minikube" deployment/env; then
        print_warning "Please update deployment/env with local development settings"
        print_status "Key settings to configure:"
        echo "  - OPENAI_API_KEY"
        echo "  - ANTHROPIC_API_KEY"
        echo "  - GHCR_AUTH"
    fi
}

# Function to verify setup
verify_setup() {
    print_status "Verifying setup..."
    
    # Use the main Makefile validation target
    if make validate >/dev/null 2>&1; then
        print_success "Setup verification completed successfully!"
        print_status "Next steps:"
        echo "  1. Update deployment/env with your API keys"
        echo "  2. Run: make deploy-local"
        echo "  3. Test with: make test"
    else
        print_error "Setup verification failed. Run 'make validate' for details."
        exit 1
    fi
}

# Main execution
main() {
    print_status "Starting local development setup..."
    
    install_docker
    install_kubectl
    install_helm
    install_minikube
    install_git_lfs
    setup_config
    
    verify_setup
    
    print_success "Local development setup completed!"
}

# Run main function
main "$@" 
