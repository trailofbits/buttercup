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
    local subscription_id
    local subscription_name
    subscription_id=$(az account show --query id -o tsv)
    subscription_name=$(az account show --query name -o tsv)
    
    print_status "Current subscription: $subscription_name ($subscription_id)"

    # Source deployment/env to get existing RESOURCE_GROUP_NAME if set
    if [ -f "deployment/env" ]; then
        source deployment/env
    fi

    RESOURCE_GROUP_NAME="${TF_VAR_resource_group_name:-}"
    if [ -z "$RESOURCE_GROUP_NAME" ] || [ "$RESOURCE_GROUP_NAME" = "<your-resource-group-name>" ]; then
        print_status "Please specify the resource group where all Azure resources will be deployed:"
        read -r -p "Enter resource group name (e.g., buttercup-crs-rg): " RESOURCE_GROUP_NAME

        if [ -z "$RESOURCE_GROUP_NAME" ]; then
            print_error "Resource group name is required"
            exit 1
        fi
    else
        print_success "Using RESOURCE_GROUP_NAME from deployment/env: $RESOURCE_GROUP_NAME"
    fi
    RESOURCE_GROUP_LOCATION="${TF_VAR_resource_group_location:-}"
    if [ -z "$RESOURCE_GROUP_LOCATION" ] || [ "$RESOURCE_GROUP_LOCATION" = "<your-resource-group-location>" ]; then
        read -r -p "Enter resource group location (default: eastus): " RESOURCE_GROUP_LOCATION
        if [ -z "$RESOURCE_GROUP_LOCATION" ]; then
            RESOURCE_GROUP_LOCATION="eastus"
            print_status "No value provided. Using default: $RESOURCE_GROUP_LOCATION"
        fi
    else
        print_success "Using RESOURCE_GROUP_LOCATION from deployment/env: $RESOURCE_GROUP_LOCATION"
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
        az group create --name "$RESOURCE_GROUP_NAME" --location "$RESOURCE_GROUP_LOCATION"
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

    # Write RESOURCE_GROUP_LOCATION to deployment/env (uncomment or add line)
    if grep -q '^[# ]*export TF_VAR_resource_group_location=' deployment/env; then
        portable_sed "s|^[# ]*export TF_VAR_resource_group_location=.*|export TF_VAR_resource_group_location=\"$RESOURCE_GROUP_LOCATION\"|" deployment/env
    else
        echo "export TF_VAR_resource_group_location=\"$RESOURCE_GROUP_LOCATION\"" >> deployment/env
    fi

    # Only prompt to create a new service principal if TF_VAR_ARM_CLIENT_ID and TF_VAR_ARM_CLIENT_SECRET are not set
    if [ -z "$TF_VAR_ARM_CLIENT_ID" ] || [ "$TF_VAR_ARM_CLIENT_ID" = "<your-client-id>" ] || [ -z "$TF_VAR_ARM_CLIENT_SECRET" ] || [ "$TF_VAR_ARM_CLIENT_SECRET" = "<your-client-secret>" ]; then
        read -r -p "Do you want to create a new service principal? (y/N): " -n 1
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            local sp_name
            sp_name="ButtercupCRS-$(date +%Y%m%d-%H%M%S)"
            print_status "Creating service principal: $sp_name"

            local sp_output
            sp_output=$(az ad sp create-for-rbac --name "$sp_name" --role Contributor --scopes "/subscriptions/$subscription_id/resourceGroups/$RESOURCE_GROUP_NAME" --output json)

            local app_id
            local password
            local tenant_id
            app_id=$(echo "$sp_output" | jq -r '.appId')
            password=$(echo "$sp_output" | jq -r '.password')
            tenant_id=$(echo "$sp_output" | jq -r '.tenant')

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
    
    # TODO: For production, we don't deploy SigNoz, as it needs to be done properly
    #       Just allow to configure access to an existing SigNoz instance
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
        local rand_suffix
        rand_suffix=$(LC_CTYPE=C tr -dc 'a-z0-9' </dev/urandom | head -c 4)
        local default_storage_account="buttercuptf${rand_suffix}"
        read -r -p "Enter storage account name (default: $default_storage_account): " storage_account
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

    # Set VM size
    read -r -p "Enter the VM size for the AKS cluster (default: Standard_L8s): " vm_size
    if [[ -z "$vm_size" ]]; then
        vm_size="Standard_L8s"
        print_status "No value provided. Using default: $vm_size"
    fi
    if grep -q '^[# ]*export TF_VAR_vm_size=' deployment/env; then
        portable_sed "s|^[# ]*export TF_VAR_vm_size=.*|export TF_VAR_vm_size=\"$vm_size\"|" deployment/env
    else
        echo "export TF_VAR_vm_size=\"$vm_size\"" >> deployment/env
    fi
    print_success "Set TF_VAR_vm_size to $vm_size in deployment/env"

    # Register resource providers
    az provider register --namespace Microsoft.ContainerService
    az provider register --namespace Microsoft.Storage
    az provider register --namespace Microsoft.Network
    az provider register --namespace Microsoft.Compute

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
    read -r -p "Enter the number of user nodes for the AKS cluster (default: 3): " usr_node_count
    if [[ -z "$usr_node_count" ]]; then
        usr_node_count=3
        print_status "No value provided. Using default: $usr_node_count"
    fi

    # Update or add TF_VAR_usr_node_count in the env file
    portable_sed "s|^[# ]*export TF_VAR_usr_node_count=.*|export TF_VAR_usr_node_count=\"$usr_node_count\"|" deployment/env
    print_success "Set TF_VAR_usr_node_count to $usr_node_count in deployment/env"
}

setup_tailscale() {
    print_status "Setting up Tailscale..."
    read -p "Do you want to setup Tailscale? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_status "Setting up Tailscale..."
        print_status "Configure a OAuth Client at https://login.tailscale.com/admin/settings/oauth"
        print_status "Make sure to configure Tailscale DNS and to enable HTTPS Certificates at https://login.tailscale.com/admin/dns"

        read -r -p "Enter the OAuth Client ID: " oauth_client_id
        read -rs -p "Enter the OAuth Client Secret: " oauth_client_secret
        echo
        read -r -p "Enter the Tailscale Operator Tag: " tailscale_op_tag
        read -r -p "Enter the Tailscale Domain: " tailscale_domain

        portable_sed "s|^[# ]*export TAILSCALE_ENABLED=.*|export TAILSCALE_ENABLED=\"true\"|" deployment/env
        portable_sed "s|^[# ]*export TS_CLIENT_ID=.*|export TS_CLIENT_ID=\"$oauth_client_id\"|" deployment/env
        portable_sed "s|^[# ]*export TS_CLIENT_SECRET=.*|export TS_CLIENT_SECRET=\"$oauth_client_secret\"|" deployment/env
        portable_sed "s|^[# ]*export TS_OP_TAG=.*|export TS_OP_TAG=\"$tailscale_op_tag\"|" deployment/env
        portable_sed "s|^[# ]*export TAILSCALE_DOMAIN=.*|export TAILSCALE_DOMAIN=\"$tailscale_domain\"|" deployment/env

        print_success "Set TAILSCALE_ENABLED to true in deployment/env"
    else
        portable_sed "s|^[# ]*export TAILSCALE_ENABLED=.*|export TAILSCALE_ENABLED=\"false\"|" deployment/env
        print_success "Set TAILSCALE_ENABLED to false in deployment/env"
    fi
}

# Function to provide deployment instructions
deployment_instructions() {
    print_success "Production setup completed!"
    echo
    print_status "Next steps for deployment:"
    echo "  1. Run: make deploy"
    echo "  2. Monitor deployment: kubectl get pods -A"
    echo "  3. Get cluster credentials: az aks get-credentials --name <cluster-name> --resource-group <rg-name>"
    echo
    print_status "Useful commands:"
    echo "  - View logs: kubectl logs -n crs <pod-name>"
    echo "  - Scale nodes: Update TF_VAR_usr_node_count and run make deploy"
    echo "  - Cleanup: make clean"
}

install_linux() {
    install_kubectl
    install_helm
    install_uv
    install_azcli
    install_terraform
}

install_macos() {
    check_brew
    install_kubectl_mac
    install_helm_mac
    install_uv_mac
    install_azcli_mac
    install_terraform_mac
}

# Main execution
main() {
    print_status "Starting production setup..."

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
    
    check_azure_cli
    check_terraform
    setup_config
    setup_service_principal
    setup_remote_state
    setup_aks_resources
    setup_tailscale
    
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
