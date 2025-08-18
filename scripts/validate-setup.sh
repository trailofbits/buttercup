#!/bin/bash

# Setup Validation Script for Buttercup CRS
# This script validates the current setup and configuration

set -e

# Source common functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

echo "🔍 Validating Buttercup CRS setup..."

# Check if running as root
check_not_root

# Main execution
main() {
    local total_errors=0

    print_status "Starting setup validation..."
    echo

    # Check tools
    check_docker || total_errors=$((total_errors + 1))
    check_kubectl || total_errors=$((total_errors + 1))
    check_helm || total_errors=$((total_errors + 1))
    check_minikube
    check_azure_cli
    check_terraform
    echo

    # Check configuration
    check_config || total_errors=$((total_errors + 1))
    echo

    # Summary
    if [ $total_errors -eq 0 ]; then
        print_success "Setup validation completed successfully!"
        print_status "Your environment is ready for deployment."
    else
        print_error "Setup validation completed with $total_errors error(s)"
        print_status "Please fix the errors above before proceeding."
    fi
}

# Run main function
main "$@"
