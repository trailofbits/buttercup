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

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
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

# Function to check if running as root
check_not_root() {
    if [[ $EUID -eq 0 ]]; then
        print_error "This script should not be run as root"
        exit 1
    fi
}

# Function to check if brew exists
brew_exists() {
    print_status "Checking if brew exists..."
    if ! command_exists brew; then
        print_error "brew is not installed. Please install it from https://brew.sh/"
        exit 1
    else
        print_success "brew is installed"
    fi
}

# Function to install Docker
install_docker() {
    print_status "Installing Docker..."
    if ! command_exists docker; then
        curl -fsSL https://get.docker.com | sh
        print_status "Adding user to Docker group (sudo required)..."
        sudo usermod -aG docker $USER
        print_success "Docker installed successfully"
        print_warning "You need to log out and back in for Docker group changes to take effect"
    else
        print_success "Docker is already installed"
    fi
}

install_docker_mac() {
    print_status "Installing Docker (also installs Kubectl)..."
    if ! command_exists docker; then
        brew install --cask docker
        print_success "Docker installed successfully"
    else
        print_success "Docker is already installed"
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

install_helm_mac() {
    print_status "Installing Helm..."
    if ! command_exists helm; then
        brew install helm
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

install_minikube_mac() {
    print_status "Installing Minikube..."
    if ! command_exists minikube; then
        brew install minikube
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

install_git_lfs_mac() {
    print_status "Installing Git LFS..."
    if ! command_exists git-lfs; then
        brew install git-lfs
        print_success "Git LFS installed successfully"
    else
        print_success "Git LFS is already installed"
    fi
}

# Function to install Just
install_just() {
    print_status "Installing Just..."
    if ! command_exists just; then
        if command_exists curl; then
            # Install using the official installer
            curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash
        elif command_exists apt-get; then
            sudo apt-get update
            sudo apt-get install -y just
        elif command_exists yum; then
            sudo yum install -y just
        elif command_exists brew; then
            brew install just
        else
            print_error "Could not install Just. Please install it manually."
            return 1
        fi
        print_success "Just installed successfully"
    else
        print_success "Just is already installed"
    fi
}

install_just_mac() {
    print_status "Installing Just..."
    if ! command_exists just; then
        brew install just
        print_success "Just installed successfully"
    else
        print_success "Just is already installed"
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
            local subscription=$(az account show --query name -o tsv)
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

# Function to check Just
check_just() {
    print_status "Checking Just..."
    if command_exists just; then
        print_success "Just is installed"
    else
        print_error "Just is not installed"
        return 1
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
            read -p "Do you want to overwrite it? (y/n): " -n 1 -r
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
    print_status "Configuring LangFuse (optional monitoring)..."
    
    # Source the env file to check current values
    if [ -f "deployment/env" ]; then
        source deployment/env
    fi
    
    # Check if LangFuse is already enabled
    if [ "$LANGFUSE_ENABLED" = "true" ] && [ -n "$LANGFUSE_HOST" ] && [ -n "$LANGFUSE_PUBLIC_KEY" ]; then
        print_status "LangFuse is already configured:"
        echo "  Host: $LANGFUSE_HOST"
        echo "  Public Key: $LANGFUSE_PUBLIC_KEY"
        read -p "Do you want to reconfigure LangFuse? (y/n): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_status "Keeping existing LangFuse configuration"
            return
        fi
    fi
    
    read -p "Do you want to enable LangFuse for LLM monitoring? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_status "LangFuse configuration:"
        read -p "Enter LangFuse host URL: " langfuse_host
        read -p "Enter LangFuse public key: " langfuse_public_key
        read -s -p "Enter LangFuse secret key: " langfuse_secret_key
        echo
        
        # Update the env file
        portable_sed "s|.*export LANGFUSE_ENABLED=.*|export LANGFUSE_ENABLED=true|" deployment/env
        portable_sed "s|.*export LANGFUSE_HOST=.*|export LANGFUSE_HOST=\"$langfuse_host\"|" deployment/env
        portable_sed "s|.*export LANGFUSE_PUBLIC_KEY=.*|export LANGFUSE_PUBLIC_KEY=\"$langfuse_public_key\"|" deployment/env
        portable_sed "s|.*export LANGFUSE_SECRET_KEY=.*|export LANGFUSE_SECRET_KEY=\"$langfuse_secret_key\"|" deployment/env
        
        print_success "LangFuse configured successfully"
    else
        print_status "LangFuse disabled"
        portable_sed "s|.*export LANGFUSE_ENABLED=.*|export LANGFUSE_ENABLED=false|" deployment/env
    fi
}

# Function to configure required API keys for local development
configure_local_api_keys() {
    print_status "Configuring required API keys for local development..."
    
    # Source the env file to check current values
    if [ -f "deployment/env" ]; then
        source deployment/env
    fi
    
    # OpenAI API Key
    if [ -n "$OPENAI_API_KEY" ] && [ "$OPENAI_API_KEY" != "<your-openai-api-key>" ]; then
        print_status "OpenAI API key is already configured"
    else
        read -s -p "Enter your OpenAI API key: " openai_key
        echo
        portable_sed "s|.*export OPENAI_API_KEY=.*|export OPENAI_API_KEY=\"$openai_key\"|" deployment/env
    fi
    
    # Anthropic API Key
    if [ -n "$ANTHROPIC_API_KEY" ] && [ "$ANTHROPIC_API_KEY" != "<your-anthropic-api-key>" ]; then
        print_status "Anthropic API key is already configured"
    else
        read -s -p "Enter your Anthropic API key: " anthropic_key
        echo
        portable_sed "s|.*export ANTHROPIC_API_KEY=.*|export ANTHROPIC_API_KEY=\"$anthropic_key\"|" deployment/env
    fi
    
    # GitHub Container Registry
    if [ -n "$GHCR_AUTH" ] && [ "$GHCR_AUTH" != "<your-ghcr-base64-auth>" ]; then
        print_status "GitHub Container Registry authentication is already configured"
    else
        read -p "Enter your GitHub username (press Enter to use 'USERNAME'): " ghcr_username
        if [ -z "$ghcr_username" ]; then
            ghcr_username="USERNAME"
        fi
        read -s -p "Enter your GitHub Personal Access Token (PAT): " ghcr_pat
        echo
        
        # Compute GHCR_AUTH
        ghcr_auth=$(echo -n "$ghcr_username:$ghcr_pat" | base64)
        portable_sed "s|.*export GHCR_AUTH=.*|export GHCR_AUTH=\"$ghcr_auth\"|" deployment/env
    fi
    
    # Docker Hub credentials (optional)
    if [ -n "$DOCKER_USERNAME" ] && [ "$DOCKER_USERNAME" != "<your-docker-username>" ]; then
        print_status "Docker Hub credentials are already configured (username: $DOCKER_USERNAME)"
    else
        read -p "Enter your Docker Hub username (optional, press Enter to skip): " docker_username
        if [ -n "$docker_username" ]; then
            read -s -p "Enter your Docker Hub Personal Access Token: " docker_pat
            echo
            
            # Set Docker credentials (handles both commented and uncommented lines)
            portable_sed "s|.*export DOCKER_USERNAME=.*|export DOCKER_USERNAME=\"$docker_username\"|" deployment/env
            portable_sed "s|.*export DOCKER_PAT=.*|export DOCKER_PAT=\"$docker_pat\"|" deployment/env
        fi
    fi
    
    print_success "API keys configured successfully"
}



# Function to configure OTEL telemetry
configure_otel() {
    print_status "Configuring OpenTelemetry telemetry (optional)..."
    
    # Source the env file to check current values
    if [ -f "deployment/env" ]; then
        source deployment/env
    fi
    
    # Check if OTEL is already configured
    if [ -n "$OTEL_ENDPOINT" ] && [ "$OTEL_ENDPOINT" != "" ] && [ "$OTEL_ENDPOINT" != "<your-otel-endpoint>" ]; then
        print_status "OpenTelemetry is already configured:"
        echo "  Endpoint: $OTEL_ENDPOINT"
        echo "  Protocol: $OTEL_PROTOCOL"
        read -p "Do you want to reconfigure OpenTelemetry? (y/n): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_status "Keeping existing OpenTelemetry configuration"
            return
        fi
    fi
    
    read -p "Do you want to enable OpenTelemetry telemetry? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_status "OpenTelemetry configuration:"
        read -p "Enter OTEL endpoint URL: " otel_endpoint
        read -p "Enter OTEL protocol (http/grpc): " otel_protocol
        read -s -p "Enter OTEL token (optional, press Enter to skip): " otel_token
        echo
        
        # Update the env file
        portable_sed "s|.*export OTEL_ENDPOINT=.*|export OTEL_ENDPOINT=\"$otel_endpoint\"|" deployment/env
        portable_sed "s|.*export OTEL_PROTOCOL=.*|export OTEL_PROTOCOL=\"$otel_protocol\"|" deployment/env
        
        if [ -n "$otel_token" ]; then
            portable_sed "s|.*export OTEL_TOKEN=.*|export OTEL_TOKEN=\"$otel_token\"|" deployment/env
        fi
        
        print_success "OpenTelemetry configured successfully"
    else
        print_status "OpenTelemetry disabled"
        portable_sed "s|.*export OTEL_ENDPOINT=.*|# export OTEL_ENDPOINT=\"\"|" deployment/env
        portable_sed "s|.*export OTEL_PROTOCOL=.*|# export OTEL_PROTOCOL=\"http\"|" deployment/env
        portable_sed "s|.*export OTEL_TOKEN=.*|# export OTEL_TOKEN=\"\"|" deployment/env
    fi
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

# Function to check Minikube configuration
check_minikube_config() {
    print_status "Checking Minikube configuration..."
    
    local errors=0
    
    # Check required API keys
    local required_vars=(
        "OPENAI_API_KEY"
        "ANTHROPIC_API_KEY"
        "GHCR_AUTH"
    )
    
    for var in "${required_vars[@]}"; do
        if [ -z "${!var}" ] || [ "${!var}" = "<your-*>" ]; then
            print_error "Required variable $var is not set or has placeholder value"
            errors=$((errors + 1))
        fi
    done
    
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
    
    # Check optional OTEL configuration
    if [ -n "$OTEL_ENDPOINT" ] && [ "$OTEL_ENDPOINT" != "" ]; then
        if [ -z "$OTEL_PROTOCOL" ] || [ "$OTEL_PROTOCOL" = "<your-*>" ]; then
            print_error "OTEL_PROTOCOL is not set when OTEL_ENDPOINT is configured"
            errors=$((errors + 1))
        fi
    fi
    
    if [ $errors -eq 0 ]; then
        print_success "Minikube configuration is valid"
    else
        print_error "Minikube configuration has $errors error(s)"
        return $errors
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
    
    # Check optional OTEL configuration
    if [ -n "$OTEL_ENDPOINT" ] && [ "$OTEL_ENDPOINT" != "" ]; then
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
