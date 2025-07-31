#!/bin/bash

# Production AKS Deployment Setup Script for Buttercup CRS
# This script helps configure and validate production deployment settings

set -e

# Source common functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

echo "🏭 Setting up Buttercup CRS for production AKS deployment..."

# Check if running as root
check_not_root

# Function to setup service principal
setup_service_principal() {
    print_status "Setting up Azure Service Principal..."
    
    # Get current subscription
    local subscription_id=$(az account show --query id -o tsv)
    local subscription_name=$(az account show --query name -o tsv)
    
    print_status "Current subscription: $subscription_name ($subscription_id)"
    
    read -p "Do you want to create a new service principal? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        local sp_name="ButtercupCRS-$(date +%Y%m%d-%H%M%S)"
        print_status "Creating service principal: $sp_name"
        
        local sp_output=$(az ad sp create-for-rbac --name "$sp_name" --role Contributor --scopes "/subscriptions/$subscription_id" --output json)
        
        local app_id=$(echo "$sp_output" | jq -r '.appId')
        local password=$(echo "$sp_output" | jq -r '.password')
        local tenant_id=$(echo "$sp_output" | jq -r '.tenant')
        
        print_success "Service principal created successfully"
        echo
        print_status "Service Principal Details:"
        echo "  Name: $sp_name"
        echo "  App ID: $app_id"
        echo "  Tenant ID: $tenant_id"
        echo "  Password: $password"
        echo
        print_warning "Save these credentials securely!"
        echo
        
        # Export environment variables
        export TF_ARM_TENANT_ID="$tenant_id"
        export TF_ARM_CLIENT_ID="$app_id"
        export TF_ARM_CLIENT_SECRET="$password"
        export TF_ARM_SUBSCRIPTION_ID="$subscription_id"
        
        print_status "Environment variables exported for current session"
    else
        print_status "Using existing service principal"
        print_status "Please set the following environment variables:"
        echo "  export TF_ARM_TENANT_ID=\"<your-tenant-id>\""
        echo "  export TF_ARM_CLIENT_ID=\"<your-client-id>\""
        echo "  export TF_ARM_CLIENT_SECRET=\"<your-client-secret>\""
        echo "  export TF_ARM_SUBSCRIPTION_ID=\"<your-subscription-id>\""
    fi
}

# Function to setup configuration
setup_config() {
    print_status "Setting up production configuration..."
    
    setup_config_file "true"
    
    # Configure required API keys
    configure_local_api_keys
    
    # Configure LangFuse (optional)
    configure_langfuse
    
    # Configure OTEL telemetry (optional)
    configure_otel
}

# Function to validate configuration
validate_config() {
    print_status "Validating configuration..."
    
    # Use the main Makefile validation target
    if make validate >/dev/null 2>&1; then
        print_success "Configuration validation passed!"
    else
        print_error "Configuration validation failed. Run 'make validate' for details."
        return 1
    fi
}

# Function to setup remote state (optional)
setup_remote_state() {
    print_status "Setting up Terraform remote state..."
    
    read -p "Do you want to configure remote state storage? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_status "This will create Azure resources for remote state storage"
        
        # Get resource group name
        read -p "Enter resource group name for state storage (e.g., buttercup-tfstate-rg): " state_rg
        read -p "Enter storage account name (e.g., buttercuptfstate): " storage_account
        
        # Create resource group
        print_status "Creating resource group: $state_rg"
        az group create --name "$state_rg" --location eastus
        
        # Create storage account
        print_status "Creating storage account: $storage_account"
        az storage account create --resource-group "$state_rg" --name "$storage_account" --sku Standard_LRS --encryption-services blob
        
        # Create container
        print_status "Creating storage container"
        az storage container create --name tfstate --account-name "$storage_account" --auth-mode login
        
        # Update backend.tf
        print_status "Updating backend.tf"
        cat > deployment/backend.tf << EOF
terraform {
  backend "azurerm" {
    resource_group_name  = "$state_rg"
    storage_account_name = "$storage_account"
    container_name       = "tfstate"
    key                  = "terraform.tfstate"
  }
}
EOF
        
        print_success "Remote state storage configured"
    else
        print_status "Skipping remote state setup (using local state)"
    fi
}

# Function to provide deployment instructions
deployment_instructions() {
    print_success "Production setup completed!"
    echo
    print_status "Next steps for deployment:"
    echo "  1. Run: make deploy-azure"
    echo "  2. Monitor deployment: kubectl get pods -A"
    echo "  3. Get cluster credentials: az aks get-credentials --name <cluster-name> --resource-group <rg-name>"
    echo "  4. Access via Tailscale: kubectl get -n crs-webservice ingress"
    echo
    print_status "Useful commands:"
    echo "  - View logs: kubectl logs -n crs <pod-name>"
    echo "  - Scale nodes: Update TF_VAR_usr_node_count and run make deploy-azure"
    echo "  - Cleanup: make clean"
}

# Main execution
main() {
    print_status "Starting production setup..."
    
    check_azure_cli
    check_terraform
    setup_service_principal
    setup_config
    setup_remote_state
    
    print_status "Configuration validation..."
    if validate_config; then
        deployment_instructions
    else
        print_error "Please fix configuration issues before proceeding"
        exit 1
    fi
}

# Run main function
main "$@" 
