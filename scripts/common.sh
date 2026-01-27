#!/bin/bash

# Common functions and variables for Buttercup CRS setup scripts
# This script should be sourced by other setup scripts

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_linebreak() {
    echo "----------------------"
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to check if running as root
check_not_root() {
    if [[ $EUID -eq 0 ]]; then
        print_error "This script should not be run as root"
        exit 1
    fi
}

# Portable sed in-place editing function
# Usage: portable_sed "pattern" "file"
portable_sed() {
    local pattern="$1"
    local file="$2"

    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS requires empty string after -i
        sed -i '' "$pattern" "$file"
    else
        # Linux doesn't accept backup extension
        sed -i "$pattern" "$file"
    fi
}

# Function to install Docker
install_docker() {
    print_status "Installing Docker..."
    if ! command_exists docker; then
        curl -fsSL https://get.docker.com | sh
        print_status "Adding user to Docker group (sudo required)..."
        sudo usermod -aG docker "$USER"
        print_success "Docker installed successfully"
        print_warning "You need to log out and back in for Docker group changes to take effect"
    else
        print_success "Docker is already installed"
    fi
    
    # Install buildx plugin (required for deploy target)
    print_status "Installing Docker buildx plugin..."
    sudo apt install -y docker-buildx-plugin
    print_success "Docker buildx plugin installed"
}

install_uv() {
    print_status "Installing uv..."
    if ! command_exists uv; then
        curl -fsSL https://astral.sh/uv/install.sh | sh
        print_status "Sourcing uv environment..."
        source "$HOME/.local/bin/env"
        print_success "uv installed successfully"
    else
        print_success "uv is already installed"
    fi
}

# Function to install kubectl
install_kubectl() {
    print_status "Installing kubectl..."
    if ! command_exists kubectl; then
        curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
        sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
        rm kubectl
        print_success "kubectl installed successfully"
    else
        print_success "kubectl is already installed"
    fi
}

# Function to install Helm
install_helm() {
    print_status "Installing Helm..."
    if ! command_exists helm; then
        curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3
        chmod 700 get_helm.sh
        ./get_helm.sh
        rm get_helm.sh
        print_success "Helm installed successfully"
    else
        print_success "Helm is already installed"
    fi
}

# Function to install Minikube
install_minikube() {
    print_status "Installing Minikube..."
    if ! command_exists minikube; then
        curl -LO https://github.com/kubernetes/minikube/releases/latest/download/minikube-linux-amd64
        sudo install minikube-linux-amd64 /usr/local/bin/minikube
        rm minikube-linux-amd64
        print_success "Minikube installed successfully"
    else
        print_success "Minikube is already installed"
    fi
}

# Function to install Git LFS
install_git_lfs() {
    print_status "Installing Git LFS..."
    if ! command_exists git-lfs; then
        sudo apt-get update
        sudo apt-get install -y git-lfs
        git lfs install
        print_success "Git LFS installed successfully"
    else
        print_success "Git LFS is already installed"
    fi
}

install_azcli() {
    print_status "Installing Azure CLI..."
    if ! command_exists az; then
        curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
        print_success "Azure CLI installed successfully"
    else
        print_success "Azure CLI is already installed"
    fi
}

install_terraform() {
    print_status "Installing Terraform..."
    if ! command_exists terraform; then
        sudo apt-get update && sudo apt-get install -y gnupg software-properties-common
        wget -O- https://apt.releases.hashicorp.com/gpg | gpg --dearmor | sudo tee /usr/share/keyrings/hashicorp-archive-keyring.gpg > /dev/null
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(grep -oP '(?<=UBUNTU_CODENAME=).*' /etc/os-release || lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
        sudo apt update
        sudo apt-get install terraform
        print_success "Terraform installed successfully"
    else
        print_success "Terraform is already installed"
    fi
}

# Function to check Docker
check_docker() {
    print_status "Checking Docker..."
    if command_exists docker; then
        if docker info >/dev/null 2>&1; then
            print_success "Docker is running"
        else
            print_error "Docker is installed but not running"
            return 1
        fi
    else
        print_error "Docker is not installed"
        return 1
    fi
}

# Function to check kubectl
check_kubectl() {
    print_status "Checking kubectl..."
    if command_exists kubectl; then
        print_success "kubectl is installed"
    else
        print_error "kubectl is not installed"
        return 1
    fi
}

# Function to check Helm
check_helm() {
    print_status "Checking Helm..."
    if command_exists helm; then
        print_success "Helm is installed"
    else
        print_error "Helm is not installed"
        return 1
    fi
}

# Function to check Minikube
check_minikube() {
    print_status "Checking Minikube..."
    if command_exists minikube; then
        if minikube status >/dev/null 2>&1; then
            print_success "Minikube is running"
        else
            print_warning "Minikube is installed but not running"
        fi
    else
        print_warning "Minikube is not installed (only needed for local development)"
    fi
}

# Function to check Azure CLI
check_azure_cli() {
    print_status "Checking Azure CLI..."
    if command_exists az; then
        if az account show >/dev/null 2>&1; then
            local subscription
            subscription=$(az account show --query name -o tsv)
            print_success "Azure CLI is logged in (subscription: $subscription)"
        else
            print_warning "Azure CLI is installed but not logged in"
        fi
    else
        print_warning "Azure CLI is not installed (only needed for AKS deployment)"
    fi
}

# Function to check Terraform
check_terraform() {
    print_status "Checking Terraform..."
    if command_exists terraform; then
        print_success "Terraform is installed"
    else
        print_warning "Terraform is not installed (only needed for AKS deployment)"
    fi
}


# Function to setup configuration file
setup_config_file() {
    local overwrite_existing=${1:-false}
    
    print_status "Setting up configuration..."
    
    if [ ! -f "deployment/env" ]; then
        cp deployment/env.template deployment/env
        print_success "Configuration file created from template"
    else
        print_warning "Configuration file already exists"
        if [ "$overwrite_existing" = "true" ]; then
            read -r -p "Do you want to overwrite it? (y/N): " -n 1
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                cp deployment/env.template deployment/env
                print_success "Configuration file overwritten"
            fi
        fi
    fi
}

# Function to configure LangFuse
configure_langfuse() {
    print_linebreak
    print_status "Configuring LangFuse (optional monitoring)..."
    
    # Source the env file to check current values
    if [ -f "deployment/env" ]; then
        source deployment/env
    fi
    
    print_status "LangFuse: Optional LLM monitoring and observability platform."
    print_status "Tracks AI model usage, costs, and performance metrics for debugging and optimization."
    
    # Use a meaningful current value for the check
    local current_langfuse_config=""
    if [ "$LANGFUSE_ENABLED" = "true" ] && [ -n "$LANGFUSE_HOST" ] && [ -n "$LANGFUSE_PUBLIC_KEY" ]; then
        current_langfuse_config="$LANGFUSE_HOST"
    fi
    
    configure_service "LANGFUSE" "LangFuse configuration" "$current_langfuse_config" "" false "configure_langfuse_wrapper"
}

# Helper function to prompt for value update if already configured
prompt_for_update() {
    local var_name="$1"
    local display_name="$2"
    local current_value="$3"
    local default_value="$4"
    local is_secret="${5:-false}"
    
    if [ -n "$current_value" ] && [ "$current_value" != "$default_value" ]; then
        printf "%s is already configured. Set a new value? (y/N): " "$display_name"
        read -r response
        if [[ "$response" =~ ^[Yy]$ ]]; then
            return 0  # Proceed with update
        else
            print_status "Keeping existing $display_name"
            return 1  # Skip update
        fi
    fi
    return 0  # Not configured, proceed with setup
}

# Helper function to read and set a configuration value
read_and_set_config() {
    local var_name="$1"
    local display_name="$2"
    local prompt_text="$3"
    local is_secret="${4:-false}"
    local value

    if [ "$is_secret" = true ]; then
        read -rs -p "$prompt_text" value
        echo
    else
        read -r -p "$prompt_text" value
    fi
    
    # Only update if value is not empty
    if [ -n "$value" ]; then
        portable_sed "s|.*export $var_name=.*|export $var_name=\"$value\"|" deployment/env
    fi
    return 0
}

# Helper function for GHCR configuration
configure_ghcr_optional() {
    read -r -p "Enter your GitHub username (press Enter to skip): " ghcr_username
    if [ -n "$ghcr_username" ]; then
        read -rs -p "Enter your GitHub Personal Access Token (PAT): " ghcr_pat
        echo
        
        # Compute GHCR_AUTH
        ghcr_auth=$(echo -n "$ghcr_username:$ghcr_pat" | base64 --wrap=0)
        portable_sed "s|.*export GHCR_AUTH=.*|export GHCR_AUTH=\"$ghcr_auth\"|" deployment/env
        return 0
    else
        # Clear GHCR_AUTH if skipped
        portable_sed "s|.*export GHCR_AUTH=.*|export GHCR_AUTH=\"\"|" deployment/env
        return 1
    fi
}

# Helper function for Docker Hub configuration
configure_docker_hub() {
    read -r -p "Enter your Docker Hub username (optional, press Enter to skip): " docker_username
    if [ -n "$docker_username" ]; then
        read -rs -p "Enter your Docker Hub Personal Access Token: " docker_pat
        echo
        
        # Set Docker credentials (handles both commented and uncommented lines)
        portable_sed "s|.*export DOCKER_USERNAME=.*|export DOCKER_USERNAME=\"$docker_username\"|" deployment/env
        portable_sed "s|.*export DOCKER_PAT=.*|export DOCKER_PAT=\"$docker_pat\"|" deployment/env
        return 0
    fi
    return 1
}

# Unified helper function to configure any service
configure_service() {
    local var_name="$1"
    local display_name="$2"
    local current_value="$3"
    local default_value="$4"
    local is_required="${5:-false}"
    local config_function="$6"
    
    # Check if already configured and user wants to keep it
    if ! prompt_for_update "$var_name" "$display_name" "$current_value" "$default_value"; then
        return 0  # User chose to keep existing value, exit early
    fi
    
    # At this point, we need to configure (either new or updating existing)
    if [ "$is_required" = true ]; then
        # Required - always prompt (no skip option)
        if [ -n "$config_function" ]; then
            $config_function
            print_success "$display_name configured"
        fi
    else
        # Optional - prompt with skip option
        if [ -n "$config_function" ]; then
            if $config_function; then
                print_success "$display_name configured"
            else
                print_status "$display_name disabled"
            fi
        else
            # No config function provided - use simple API key configuration
            if configure_simple_api_key "$var_name" "Enter your $display_name (press Enter to skip): "; then
                print_success "$display_name configured"
            else
                print_status "$display_name disabled"
            fi
        fi
    fi
}

# Helper function for simple API key configuration
configure_simple_api_key() {
    local var_name="$1"
    local prompt_text="$2"
    local is_secret="${3:-true}"
    local value

    if [ "$is_secret" = true ]; then
        read -rs -p "$prompt_text" value
        echo
    else
        read -r -p "$prompt_text" value
    fi
    
    if [ -n "$value" ]; then
        # Check if the export line exists anywhere in the file; if not, append it, else update it
        if grep -q "export $var_name=" deployment/env; then
            portable_sed "s|.*export $var_name=.*|export $var_name=\"$value\"|" deployment/env
        else
            echo "export $var_name=\"$value\"" >> deployment/env
        fi
        return 0
    else
        # Clear the key if skipped (set to empty string)
        portable_sed "s|.*export $var_name=.*|export $var_name=\"\"|" deployment/env
        return 1
    fi
}


# Wrapper functions for specific configurations

configure_docker_hub_optional() {
    read -r -p "Enter your Docker Hub username (press Enter to skip): " docker_username
    if [ -n "$docker_username" ]; then
        read -rs -p "Enter your Docker Hub Personal Access Token: " docker_pat
        echo
        
        # Set Docker credentials
        portable_sed "s|.*export DOCKER_USERNAME=.*|export DOCKER_USERNAME=\"$docker_username\"|" deployment/env
        portable_sed "s|.*export DOCKER_PAT=.*|export DOCKER_PAT=\"$docker_pat\"|" deployment/env
        return 0
    else
        # Clear Docker credentials if skipped
        portable_sed "s|.*export DOCKER_USERNAME=.*|export DOCKER_USERNAME=\"\"|" deployment/env
        portable_sed "s|.*export DOCKER_PAT=.*|export DOCKER_PAT=\"\"|" deployment/env
        return 1
    fi
}

configure_otel_wrapper() {
    read -r -p "Enter OTEL endpoint URL (press Enter to skip): " otel_endpoint
    if [ -n "$otel_endpoint" ]; then
        read -r -p "Enter OTEL protocol (http/grpc): " otel_protocol
        read -rs -p "Enter OTEL token (including Basic or Bearer, optional, press Enter to skip): " otel_token
        echo
        
        # Update the env file
        portable_sed "s|.*export OTEL_ENDPOINT=.*|export OTEL_ENDPOINT=\"$otel_endpoint\"|" deployment/env
        portable_sed "s|.*export OTEL_PROTOCOL=.*|export OTEL_PROTOCOL=\"$otel_protocol\"|" deployment/env
        
        if [ -n "$otel_token" ]; then
            portable_sed "s|.*export OTEL_TOKEN=.*|export OTEL_TOKEN=\"$otel_token\"|" deployment/env
        fi
        return 0
    else
        # Disable OTEL
        portable_sed "s|.*export OTEL_ENDPOINT=.*|# export OTEL_ENDPOINT=\"\"|" deployment/env
        portable_sed "s|.*export OTEL_PROTOCOL=.*|# export OTEL_PROTOCOL=\"http\"|" deployment/env
        portable_sed "s|.*export OTEL_TOKEN=.*|# export OTEL_TOKEN=\"\"|" deployment/env
        return 1
    fi
}

configure_langfuse_wrapper() {
    read -r -p "Enter LangFuse host URL (press Enter to skip): " langfuse_host
    if [ -n "$langfuse_host" ]; then
        read -r -p "Enter LangFuse public key: " langfuse_public_key
        read -rs -p "Enter LangFuse secret key: " langfuse_secret_key
        echo
        
        # Update the env file
        portable_sed "s|.*export LANGFUSE_ENABLED=.*|export LANGFUSE_ENABLED=true|" deployment/env
        portable_sed "s|.*export LANGFUSE_HOST=.*|export LANGFUSE_HOST=\"$langfuse_host\"|" deployment/env
        portable_sed "s|.*export LANGFUSE_PUBLIC_KEY=.*|export LANGFUSE_PUBLIC_KEY=\"$langfuse_public_key\"|" deployment/env
        portable_sed "s|.*export LANGFUSE_SECRET_KEY=.*|export LANGFUSE_SECRET_KEY=\"$langfuse_secret_key\"|" deployment/env
        return 0
    else
        # Disable and clear LangFuse configuration
        portable_sed "s|.*export LANGFUSE_ENABLED=.*|export LANGFUSE_ENABLED=false|" deployment/env
        portable_sed "s|.*export LANGFUSE_HOST=.*|export LANGFUSE_HOST=\"\"|" deployment/env
        portable_sed "s|.*export LANGFUSE_PUBLIC_KEY=.*|export LANGFUSE_PUBLIC_KEY=\"\"|" deployment/env
        portable_sed "s|.*export LANGFUSE_SECRET_KEY=.*|export LANGFUSE_SECRET_KEY=\"\"|" deployment/env
        return 1
    fi
}

configure_llm_budget_wrapper() {
    read -r -p "Enter LLM budget (press Enter for \$100 default): " budget_value
    if [ -n "$budget_value" ]; then
        # Set the budget value
        portable_sed "s|.*export LITELLM_MAX_BUDGET=.*|export LITELLM_MAX_BUDGET=\"$budget_value\"|" deployment/env
    else
        # Use default value
        portable_sed "s|.*export LITELLM_MAX_BUDGET=.*|export LITELLM_MAX_BUDGET=\"100\"|" deployment/env
    fi
    return 0
}

# Function to configure required API keys for local development
configure_local_api_keys() {
    print_status "Configuring required API keys for local development..."
    
    # Source the env file to check current values
    if [ -f "deployment/env" ]; then
        source deployment/env
    fi
    
    # OpenAI API Key (Optional)
    print_linebreak
    print_status "OpenAI API Key (Optional): Powers AI-driven vulnerability analysis and patch generation."
    print_status "The patcher component performs best with OpenAI models (GPT-4o/GPT-4o-mini)."
    print_status "Generate your API key at: https://platform.openai.com/settings/organization/api-keys"
    configure_service "OPENAI_API_KEY" "OpenAI API key" "$OPENAI_API_KEY" "<your-openai-api-key>" false
    
    # Anthropic API Key (Optional)
    print_linebreak
    print_status "Anthropic API Key (Optional): Powers AI-driven fuzzing seed generation."
    print_status "The seed generation component performs best with Anthropic models (Claude 3.5/4 Sonnet)."
    print_status "Generate your API key at: https://console.anthropic.com/settings/keys"
    configure_service "ANTHROPIC_API_KEY" "Anthropic API key" "$ANTHROPIC_API_KEY" "<your-anthropic-api-key>" false
    
    # Anthropic API Key (Optional)
    print_linebreak
    print_status "Google Gemini API Key (Optional): Fallback model."
    print_status "Use this model as a fallback if other models are not configured or not available."
    print_status "Generate your API key at: https://aistudio.google.com/apikey"
    configure_service "GEMINI_API_KEY" "Gemini API key" "$GEMINI_API_KEY" "<your-gemini-api-key>" false

    # GitHub Personal Access Token (Optional)
    print_linebreak
    print_status "GitHub Personal Access Token (Optional): Access to private GitHub resources."
    print_status "Only needed if Buttercup will access private repositories or packages."
    # shellcheck disable=SC2153  # GHCR_AUTH is an external env var, not a misspelling of ghcr_auth
    configure_service "GHCR_AUTH" "GitHub authentication" "$GHCR_AUTH" "<your-ghcr-base64-auth>" false "configure_ghcr_optional"
    
    # Docker Hub credentials (optional)
    print_linebreak
    print_status "Docker Hub Credentials (Optional): Gives higher rate limits when pulling public base images."
    print_status "Recommended for reliable builds, but not strictly required for operation."
    # shellcheck disable=SC2153  # DOCKER_USERNAME is an external env var, not a misspelling
    configure_service "DOCKER_USERNAME" "Docker Hub credentials" "$DOCKER_USERNAME" "<your-docker-username>" false "configure_docker_hub_optional"
    
    # Validate that at least one LLM API key is configured
    if [ -f "deployment/env" ]; then
        source deployment/env
    fi
    
    if [ -z "$OPENAI_API_KEY" ] || [ "$OPENAI_API_KEY" = "<your-openai-api-key>" ]; then
        openai_configured=false
    else
        openai_configured=true
    fi
    
    if [ -z "$ANTHROPIC_API_KEY" ] || [ "$ANTHROPIC_API_KEY" = "<your-anthropic-api-key>" ]; then
        anthropic_configured=false
    else
        anthropic_configured=true
    fi

    if [ -z "$GEMINI_API_KEY" ] || [ "$GEMINI_API_KEY" = "<your-gemini-api-key>" ]; then
        gemini_configured=false
    else
        gemini_configured=true
    fi
    
    if [ "$openai_configured" = false ] && [ "$anthropic_configured" = false ] && [ "$gemini_configured" = false ]; then
        print_error "At least one LLM API key (OpenAI, Anthropic, or Gemini) must be configured."
        print_error "Rerun the setup and set at least one LLM API key."
        return 1
    fi
    
    print_success "API keys configured successfully"
}

generate_litellm_master_key() {
    # If LITELLM_MASTER_KEY is already configured, skip key generation
    if [ -f "deployment/env" ]; then
        source deployment/env
    fi
    if [ "${LITELLM_MASTER_KEY:-}" != "" ] && [ "$LITELLM_MASTER_KEY" != "d5179c62ae1c7366e3ee09775d0993d5" ]; then
        print_status "LITELLM_MASTER_KEY is already configured, skipping LiteLLM master key generation."
        return 0
    fi

    print_linebreak
    print_status "Configuring LiteLLM master key..."
    local litellm_master_key
    litellm_master_key=$(openssl rand -hex 16)
    portable_sed "s|.*export LITELLM_MASTER_KEY=.*|export LITELLM_MASTER_KEY=\"$litellm_master_key\"|" deployment/env
    print_success "LiteLLM master key configured successfully"
}

generate_crs_key_id_token() {
    # If CRS_KEY_ID is already configured, skip key generation
    if [ -f "deployment/env" ]; then
        source deployment/env
    fi
    if [ "${CRS_KEY_ID:-}" != "" ] && [ "$CRS_KEY_ID" != "515cc8a0-3019-4c9f-8c1c-72d0b54ae561" ]; then
        print_status "CRS_KEY_ID/TOKEN/TOKEN_HASH are already configured, skipping CRS keys generation."
        return 0
    fi

    print_linebreak
    print_status "Configuring CRS key ID/token..."
    local auth_tool_output
    local crs_key_id
    local crs_key_token
    local crs_key_token_hash
    auth_tool_output=$(pushd orchestrator && uv run python3 ./src/buttercup/orchestrator/task_server/auth_tool.py --env)
    crs_key_id=$(echo "$auth_tool_output" | grep "BUTTERCUP_TASK_SERVER_API_KEY_ID" | cut -d'=' -f2-)
    crs_key_token=$(echo "$auth_tool_output" | grep "^API_TOKEN" | cut -d'=' -f2-)
    crs_key_token_hash=$(echo "$auth_tool_output" | grep "^BUTTERCUP_TASK_SERVER_API_TOKEN_HASH" | cut -d'=' -f2-)

    portable_sed "s|.*export CRS_KEY_ID=.*|export CRS_KEY_ID=\"$crs_key_id\"|" deployment/env
    portable_sed "s|.*export CRS_KEY_TOKEN=.*|export CRS_KEY_TOKEN=\"$crs_key_token\"|" deployment/env
    portable_sed "s|.*export CRS_KEY_TOKEN_HASH=.*|export CRS_KEY_TOKEN_HASH='$crs_key_token_hash'|" deployment/env
    print_success "CRS key ID/token configured successfully"
}

configure_llm_budget() {
    print_linebreak
    print_status "Configuring LLM Budget..."

    # Source the env file to check current values
    if [ -f "deployment/env" ]; then
        source deployment/env
    fi

    print_status "LLM Budget: Maximum budget for LiteLLM."
    print_status "Set LLM budget across all components. Budget is per-deployment."

    configure_service "LITELLM_MAX_BUDGET" "LiteLLM max budget" "$LITELLM_MAX_BUDGET" "100" false "configure_llm_budget_wrapper"
}


# Function to configure OTEL telemetry (simplified for local deployment)
configure_otel() {
    print_linebreak
    print_status "Configuring SigNoz for local observability..."
    
    # Source the env file to check current values
    if [ -f "deployment/env" ]; then
        source deployment/env
    fi
    
    print_status "SigNoz: Local observability platform for distributed tracing and metrics."
    print_status "Provides detailed performance monitoring and system observability for debugging."

    # Check if already configured and user wants to keep it
    if [ "$DEPLOY_SIGNOZ" = "true" ]; then
        if ! prompt_for_update "DEPLOY_SIGNOZ" "SigNoz deployment" "local" "" false; then
            return 0  # User chose to keep existing value, exit early
        fi
    fi

    # Enable local SigNoz deployment by default for quickstart
    portable_sed "s|.*export DEPLOY_SIGNOZ=.*|export DEPLOY_SIGNOZ=true|" deployment/env
    print_success "Local SigNoz deployment enabled for observability"
}

# Function to check configuration file
check_config() {
    print_status "Checking configuration file..."
    if [ ! -f "deployment/env" ]; then
        print_error "Configuration file deployment/env does not exist"
        print_status "Run: cp deployment/env.template deployment/env"
        return 1
    fi
    
    print_success "Configuration file exists"
    
    # Source the env file to check variables
    source deployment/env
    
    # Check cluster type
    if [ -n "$CLUSTER_TYPE" ]; then
        print_success "CLUSTER_TYPE is set to: $CLUSTER_TYPE"
    else
        print_error "CLUSTER_TYPE is not set"
        return 1
    fi
    
    # Check template
    if [ -n "$BUTTERCUP_K8S_VALUES_TEMPLATE" ]; then
        print_success "BUTTERCUP_K8S_VALUES_TEMPLATE is set to: $BUTTERCUP_K8S_VALUES_TEMPLATE"
    else
        print_error "BUTTERCUP_K8S_VALUES_TEMPLATE is not set"
        return 1
    fi
}

# Function to check AKS configuration
check_aks_config() {
    print_status "Checking AKS configuration..."
    
    local errors=0
    
    # Check Terraform variables
    local terraform_vars=(
        "TF_VAR_ARM_CLIENT_ID"
        "TF_VAR_ARM_CLIENT_SECRET"
        "TF_VAR_ARM_TENANT_ID"
        "TF_VAR_ARM_SUBSCRIPTION_ID"
    )
    
    for var in "${terraform_vars[@]}"; do
        if [ -z "${!var}" ] || [ "${!var}" = "<your-*>" ]; then
            print_error "Required Terraform variable $var is not set or has placeholder value"
            errors=$((errors + 1))
        fi
    done
    
    # Check API keys
    local api_vars=(
        "OPENAI_API_KEY"
        "ANTHROPIC_API_KEY"
        "GEMINI_API_KEY"
        "GHCR_AUTH"
        "CRS_KEY_ID"
        "CRS_KEY_TOKEN"
        "COMPETITION_API_KEY_ID"
        "COMPETITION_API_KEY_TOKEN"
    )
    
    for var in "${api_vars[@]}"; do
        if [ -z "${!var}" ] || [ "${!var}" = "<your-*>" ]; then
            print_error "Required API variable $var is not set or has placeholder value"
            errors=$((errors + 1))
        fi
    done
    
    # Check Tailscale (optional but recommended)
    if [ "$TAILSCALE_ENABLED" = "true" ]; then
        local tailscale_vars=(
            "TS_CLIENT_ID"
            "TS_CLIENT_SECRET"
            "TS_OP_TAG"
        )
        
        for var in "${tailscale_vars[@]}"; do
            if [ -z "${!var}" ] || [ "${!var}" = "<your-*>" ]; then
                print_error "Tailscale variable $var is not set or has placeholder value"
                errors=$((errors + 1))
            fi
        done
    fi
    
    # Check optional LangFuse configuration
    if [ "$LANGFUSE_ENABLED" = "true" ]; then
        local langfuse_vars=(
            "LANGFUSE_HOST"
            "LANGFUSE_PUBLIC_KEY"
            "LANGFUSE_SECRET_KEY"
        )
        
        for var in "${langfuse_vars[@]}"; do
            if [ -z "${!var}" ] || [ "${!var}" = "<your-*>" ]; then
                print_error "LangFuse variable $var is not set or has placeholder value"
                errors=$((errors + 1))
            fi
        done
    fi
    
    # Check optional SigNoz/OTEL configuration
    if [ "$DEPLOY_SIGNOZ" = "true" ]; then
        print_status "SigNoz local deployment is enabled"
    elif [ -n "$OTEL_ENDPOINT" ] && [ "$OTEL_ENDPOINT" != "" ]; then
        if [ -z "$OTEL_PROTOCOL" ] || [ "$OTEL_PROTOCOL" = "<your-*>" ]; then
            print_error "OTEL_PROTOCOL is not set when OTEL_ENDPOINT is configured"
            errors=$((errors + 1))
        fi
    fi
    
    if [ $errors -eq 0 ]; then
        print_success "AKS configuration is valid"
    else
        print_error "AKS configuration has $errors error(s)"
        return $errors
    fi
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

install_uv_mac() {
    if command_exists uv; then
        print_success "uv is already installed"
    else
        print_status "Installing uv..."
        brew install uv
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

install_kubectl_mac() {
    if command_exists kubectl; then
        print_success "kubectl is already installed"
    else
        print_status "Installing kubectl..."
        brew install kubectl
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

install_azcli_mac() {
    if command_exists az; then
        print_success "az is already installed"
    else
        print_status "Installing az..."
        brew install azure-cli
    fi
}

install_terraform_mac() {
    if command_exists terraform; then
        print_success "Terraform is already installed"
    else
        print_status "Installing Terraform..."
        brew tap hashicorp/tap
        brew install hashicorp/tap/terraform
    fi
}
