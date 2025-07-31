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
    
    # Configure required API keys
    configure_local_api_keys
    
    # Configure LangFuse (optional)
    configure_langfuse
    
    # Configure OTEL telemetry (optional)
    configure_otel
}

# Function to verify setup
verify_setup() {
    print_status "Verifying setup..."
    
    # Use the main Makefile validation target
    if make validate >/dev/null 2>&1; then
        print_success "Setup verification completed successfully!"
        print_status "Next steps:"
        echo "  1. Run: make deploy-local"
        echo "  2. Test with: make send-integration-task"
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
