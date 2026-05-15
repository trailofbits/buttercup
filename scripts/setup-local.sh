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

    # Generate a secure master key for LiteLLM
    generate_litellm_master_key

    # Generate key ID/token for CRS
    generate_crs_key_id_token
    
    # Configure required API keys
    configure_local_api_keys

    # Configure LLM Budget
    configure_llm_budget

    # Configure LangFuse (optional)
    configure_langfuse
    
    # Configure SigNoz deployment (optional)
    configure_otel
}

# Function to verify setup
verify_setup() {
    print_status "Verifying setup..."
    
    # Use the main Makefile validation target
    if make validate >/dev/null 2>&1; then
        print_success "Setup verification completed successfully!"
        print_status "Next steps:"
        echo "  1. Run: make deploy"
        echo "  2. Test with: make send-libpng-task"
    else
        print_error "Setup verification failed. Run 'make validate' for details."
        exit 1
    fi
}

install_linux() {
    install_docker
    install_kubectl
    install_helm
    install_minikube
    install_git_lfs
    install_uv
}

install_macos() {
    check_brew
    install_docker_mac
    install_helm_mac
    install_minikube_mac
    install_git_lfs_mac
    install_uv_mac
}

# Main execution
main() {
    print_status "Starting local development setup..."

    # Detect operating system and install dependencies
    OS="$(uname -s)"
    case "$OS" in
        Linux*)
            print_status "Detected Linux - installing Linux dependencies..."
            install_linux
            ;;
        Darwin*)
            print_status "Detected macOS - installing macOS dependencies..."
            install_macos
            ;;
        *)
            print_error "Unsupported operating system: $OS"
            print_error "This script supports Linux and macOS only."
            exit 1
            ;;
    esac

    setup_config
    
    verify_setup
    
    print_success "Local development setup completed!"
}

# Run main function
main "$@" 
