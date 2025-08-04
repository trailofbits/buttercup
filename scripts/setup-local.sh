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

    # Configure LLM Budget
    configure_llm_budget

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
}

# Function to check if Homebrew exists
check_brew() {
    if ! command_exists brew; then
        print_error "Homebrew (brew) is not installed!"
        print_error "Please install Homebrew first: https://brew.sh/"
        exit 1
    fi
}

install_docker_mac() {
    if command_exists docker; then
        print_success "Docker is already installed"
    else
        print_status "Installing Docker..."
        brew install --cask docker
    fi
}

install_helm_mac() {
    if command_exists helm; then
        print_success "Helm is already installed"
    else
        print_status "Installing Helm..."
        brew install helm
    fi
}

install_minikube_mac() {
    if command_exists minikube; then
        print_success "Minikube is already installed"
    else
        print_status "Installing Minikube..."
        brew install minikube
    fi
}

install_git_lfs_mac() {
    if command_exists git-lfs; then
        print_success "Git LFS is already installed"
    else
        print_status "Installing Git LFS..."
        brew install git-lfs
    fi
}

install_macos() {
    check_brew
    install_docker_mac
    install_helm_mac
    install_minikube_mac
    install_git_lfs_mac
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
