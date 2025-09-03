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

    # Source deployment/env to get existing RESOURCE_GROUP_NAME if set
    if [ -f "deployment/env" ]; then
        source deployment/env
    fi

    RESOURCE_GROUP_NAME="${TF_VAR_resource_group_name:-}"
    if [ -z "$RESOURCE_GROUP_NAME" ] || [ "$RESOURCE_GROUP_NAME" = "<your-resource-group-name>" ]; then
        print_status "Please specify the resource group where all Azure resources will be deployed:"
        read -p "Enter resource group name (e.g., buttercup-crs-rg): " RESOURCE_GROUP_NAME

        if [ -z "$RESOURCE_GROUP_NAME" ]; then
            print_error "Resource group name is required"
            exit 1
        fi
    else
        print_success "Using RESOURCE_GROUP_NAME from deployment/env: $RESOURCE_GROUP_NAME"
    fi

    # Check if resource group exists, if not ask to create it
    if ! az group show --name "$RESOURCE_GROUP_NAME" >/dev/null 2>&1; then
        print_status "Resource group '$RESOURCE_GROUP_NAME' does not exist"
        read -p "Do you want to create it? (Y/n): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Nn]$ ]]; then
            print_error "Resource group must exist before proceeding"
            exit 1
        fi

        print_status "Creating resource group: $RESOURCE_GROUP_NAME"
        az group create --name "$RESOURCE_GROUP_NAME" --location eastus
        print_success "Resource group created successfully"
    else
        print_success "Using existing resource group: $RESOURCE_GROUP_NAME"
    fi

    # Write RESOURCE_GROUP_NAME to deployment/env (uncomment or add line)
    if grep -q '^[# ]*export TF_VAR_resource_group_name=' deployment/env; then
        portable_sed "s|^[# ]*export TF_VAR_resource_group_name=.*|export TF_VAR_resource_group_name=\"$RESOURCE_GROUP_NAME\"|" deployment/env
    else
        echo "export TF_VAR_resource_group_name=\"$RESOURCE_GROUP_NAME\"" >> deployment/env
    fi

    # Only prompt to create a new service principal if TF_VAR_ARM_CLIENT_ID and TF_VAR_ARM_CLIENT_SECRET are not set
    if [ -z "$TF_VAR_ARM_CLIENT_ID" ] || [ "$TF_VAR_ARM_CLIENT_ID" = "<your-client-id>" ] || [ -z "$TF_VAR_ARM_CLIENT_SECRET" ] || [ "$TF_VAR_ARM_CLIENT_SECRET" = "<your-client-secret>" ]; then
        read -p "Do you want to create a new service principal? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            local sp_name="ButtercupCRS-$(date +%Y%m%d-%H%M%S)"
            print_status "Creating service principal: $sp_name"

            local sp_output=$(az ad sp create-for-rbac --name "$sp_name" --role Contributor --scopes "/subscriptions/$subscription_id/resourceGroups/$RESOURCE_GROUP_NAME" --output json)

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

            # Write environment variables to deployment/env (uncomment or add line)
            portable_sed "s|^[# ]*export TF_VAR_ARM_TENANT_ID=.*|export TF_VAR_ARM_TENANT_ID=\"$tenant_id\"|" deployment/env || echo "export TF_VAR_ARM_TENANT_ID=\"$tenant_id\"" >> deployment/env
            portable_sed "s|^[# ]*export TF_VAR_ARM_CLIENT_ID=.*|export TF_VAR_ARM_CLIENT_ID=\"$app_id\"|" deployment/env || echo "export TF_VAR_ARM_CLIENT_ID=\"$app_id\"" >> deployment/env
            portable_sed "s|^[# ]*export TF_VAR_ARM_CLIENT_SECRET=.*|export TF_VAR_ARM_CLIENT_SECRET=\"$password\"|" deployment/env || echo "export TF_VAR_ARM_CLIENT_SECRET=\"$password\"" >> deployment/env
            portable_sed "s|^[# ]*export TF_VAR_ARM_SUBSCRIPTION_ID=.*|export TF_VAR_ARM_SUBSCRIPTION_ID=\"$subscription_id\"|" deployment/env || echo "export TF_VAR_ARM_SUBSCRIPTION_ID=\"$subscription_id\"" >> deployment/env

            print_status "Service principal credentials written to deployment/env"
        else
            print_status "Using existing service principal"
            print_status "Please set the following environment variables:"
            echo "  export TF_VAR_ARM_TENANT_ID=\"<your-tenant-id>\""
            echo "  export TF_VAR_ARM_CLIENT_ID=\"<your-client-id>\""
            echo "  export TF_VAR_ARM_CLIENT_SECRET=\"<your-client-secret>\""
            echo "  export TF_VAR_ARM_SUBSCRIPTION_ID=\"<your-subscription-id>\""
            exit 1
        fi
    else
        print_success "Using existing service principal credentials from deployment/env"
    fi
}

# Function to setup configuration
setup_config() {
    print_status "Setting up production configuration..."
    
    setup_config_file "true"
    
    # Set the Kubernetes values template for AKS deployment
    print_status "Setting Kubernetes values template for AKS deployment..."
    portable_sed "s|.*export BUTTERCUP_K8S_VALUES_TEMPLATE=.*|export BUTTERCUP_K8S_VALUES_TEMPLATE=\"k8s/values-upstream-aks.template\"|" deployment/env
    print_success "Kubernetes values template set to: k8s/values-upstream-aks.template"

    # Configure required API keys
    configure_local_api_keys

    # Configure LLM Budget
    configure_llm_budget
    
    # Configure LangFuse (optional)
    configure_langfuse
    
    # Configure SigNoz deployment (optional)
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
    
    read -p "Do you want to configure remote state storage? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_status "This will create Azure resources for remote state storage in resource group: $RESOURCE_GROUP_NAME"
        
        # Use the same resource group as specified in setup_service_principal
        local state_rg="$RESOURCE_GROUP_NAME"
        # Generate a short random suffix (4 alphanumeric chars)
        local rand_suffix=$(LC_CTYPE=C tr -dc 'a-z0-9' </dev/urandom | head -c 4)
        local default_storage_account="buttercuptf${rand_suffix}"
        read -p "Enter storage account name (default: $default_storage_account): " storage_account
        if [[ -z "$storage_account" ]]; then
            storage_account="$default_storage_account"
            print_status "No storage account name provided. Using default: $storage_account"
        fi

        # Create storage account in the existing resource group
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

setup_aks_resources() {
    # Load existing value from env file if present
    if [[ -f "deployment/env" ]]; then
        source "deployment/env"
    fi

    # Set cluster type to aks
    portable_sed "s|^[# ]*export CLUSTER_TYPE=.*|export CLUSTER_TYPE=\"aks\"|" deployment/env

    print_warning "Please note that number of nodes, pods, storage sizes, and other resources are correlated, so if you change one, you may need to change the others. Review the Kubernetes values.yaml template (e.g. k8s/values-upstream-aks.template) for more details."

    # Set TF_VAR_usr_node_count
    current_value="${TF_VAR_usr_node_count:-}"
    if [[ -n "$current_value" ]]; then
        print_status "Current TF_VAR_usr_node_count is set to: $current_value"
        read -p "Do you want to modify the number of user nodes? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_status "Keeping existing TF_VAR_usr_node_count: $current_value"
            return
        fi
    fi

    # Prompt for number of user nodes, default to 3
    read -p "Enter the number of user nodes for the AKS cluster (default: 3): " usr_node_count
    if [[ -z "$usr_node_count" ]]; then
        usr_node_count=3
        print_status "No value provided. Using default: $usr_node_count"
    fi

    # Update or add TF_VAR_usr_node_count in the env file
    portable_sed "s|^[# ]*export TF_VAR_usr_node_count=.*|export TF_VAR_usr_node_count=\"$usr_node_count\"|" deployment/env
    print_success "Set TF_VAR_usr_node_count to $usr_node_count in deployment/env"
}

# Function to provide deployment instructions
deployment_instructions() {
    print_success "Production setup completed!"
    echo
    print_status "Next steps for deployment:"
    echo "  1. Run: make deploy-azure"
    echo "  2. Monitor deployment: kubectl get pods -A"
    echo "  3. Get cluster credentials: az aks get-credentials --name <cluster-name> --resource-group <rg-name>"
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
    setup_config
    setup_service_principal
    setup_remote_state
    setup_aks_resources
    
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
