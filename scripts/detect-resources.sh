#!/bin/bash

# System Resource Detection Script for Buttercup CRS
# Analyzes available system resources and generates appropriate pod resource configurations

set -e

# Source common functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

# Function to convert memory units to MiB
convert_to_mib() {
    local input="$1"
    local value
    local unit
    
    # Extract numeric value and unit
    if [[ $input =~ ^([0-9.]+)([KMGT]?i?B?)$ ]]; then
        value="${BASH_REMATCH[1]}"
        unit="${BASH_REMATCH[2]}"
    else
        echo "0"
        return
    fi
    
    case "$unit" in
        "B"|"") echo "$((${value%.*} / 1048576))" ;;
        "KB"|"K") echo "$((${value%.*} / 1024))" ;;
        "KiB") echo "$((${value%.*}))" ;;
        "MB"|"M") echo "${value%.*}" ;;
        "MiB") echo "${value%.*}" ;;
        "GB"|"G") echo "$((${value%.*} * 1024))" ;;
        "GiB") echo "$((${value%.*} * 1024))" ;;
        "TB"|"T") echo "$((${value%.*} * 1048576))" ;;
        "TiB") echo "$((${value%.*} * 1048576))" ;;
        *) echo "0" ;;
    esac
}

# Function to get system resources using docker system info
detect_system_resources() {
    print_status "Detecting system resources..."
    
    # Check if Docker is available
    if ! command -v docker >/dev/null 2>&1; then
        print_error "Docker is not installed or not in PATH"
        return 1
    fi
    
    # Check if Docker daemon is running
    if ! docker info >/dev/null 2>&1; then
        print_error "Docker daemon is not running"
        return 1
    fi
    
    # Get system info from Docker - try multiple approaches
    local total_cpus=0
    local total_memory_bytes=0
    
    # Try docker system info with JSON format first
    if command -v jq >/dev/null 2>&1; then
        # Use jq for robust JSON parsing if available
        local docker_info
        if docker_info=$(docker system info --format "{{json .}}" 2>/dev/null); then
            total_cpus=$(echo "$docker_info" | jq -r '.NCPU // 0' 2>/dev/null || echo "0")
            total_memory_bytes=$(echo "$docker_info" | jq -r '.MemTotal // 0' 2>/dev/null || echo "0")
        fi
    else
        # Fallback to docker system info without JSON
        local docker_info
        if docker_info=$(docker system info 2>/dev/null); then
            total_cpus=$(echo "$docker_info" | grep "CPUs:" | awk '{print $2}' 2>/dev/null || echo "0")
            total_memory_bytes=$(echo "$docker_info" | grep "Total Memory:" | awk '{print $3}' | sed 's/GiB//' 2>/dev/null || echo "0")
            # Convert GiB to bytes if we got a GiB value
            if [ "$total_memory_bytes" != "0" ] && [[ "$total_memory_bytes" =~ ^[0-9.]+$ ]]; then
                total_memory_bytes=$(echo "$total_memory_bytes * 1073741824" | bc 2>/dev/null || echo "0")
            else
                total_memory_bytes=0
            fi
        fi
    fi
    
    # Convert memory from bytes to MiB
    local total_memory_mib=$((total_memory_bytes / 1048576))
    
    # Fallback to platform-specific commands if Docker info fails
    if [ "$total_cpus" = "0" ] || [ "$total_memory_mib" = "0" ]; then
        print_warning "Docker system info incomplete, falling back to platform-specific detection"
        
        # Detect platform
        local platform
        platform=$(uname -s)
        
        case "$platform" in
            "Linux")
                if [ "$total_cpus" = "0" ] && [ -f /proc/cpuinfo ]; then
                    total_cpus=$(grep -c "^processor" /proc/cpuinfo 2>/dev/null || echo "4")
                fi
                
                if [ "$total_memory_mib" = "0" ] && [ -f /proc/meminfo ]; then
                    local mem_kb
                    mem_kb=$(grep "^MemTotal:" /proc/meminfo | awk '{print $2}' 2>/dev/null || echo "4194304")
                    total_memory_mib=$((mem_kb / 1024))
                fi
                ;;
            "Darwin")
                if [ "$total_cpus" = "0" ]; then
                    total_cpus=$(sysctl -n hw.ncpu 2>/dev/null || echo "4")
                fi
                
                if [ "$total_memory_mib" = "0" ]; then
                    local mem_bytes
                    mem_bytes=$(sysctl -n hw.memsize 2>/dev/null || echo "4294967296")
                    total_memory_mib=$((mem_bytes / 1048576))
                fi
                ;;
            *)
                print_warning "Unsupported platform: $platform, using default values"
                ;;
        esac
    fi
    
    # Set minimum values if detection failed
    [ "$total_cpus" = "0" ] && total_cpus=4
    [ "$total_memory_mib" = "0" ] && total_memory_mib=4096
    
    print_status "Detected system resources:"
    echo "  CPUs: $total_cpus"
    echo "  Memory: $((total_memory_mib / 1024)) GB (${total_memory_mib} MiB)"
    
    # Export for use by other functions
    export DETECTED_CPUS="$total_cpus"
    export DETECTED_MEMORY_MIB="$total_memory_mib"
}

# Helper function to display memory in GB format
display_memory_gb() {
    local memory_str="$1"
    local memory_value="${memory_str%Mi}"
    local memory_gb=$((memory_value / 1024))
    local memory_mb_remainder=$((memory_value % 1024))
    
    if [ "$memory_gb" -gt 0 ] && [ "$memory_mb_remainder" -eq 0 ]; then
        echo "${memory_gb}G"
    elif [ "$memory_gb" -gt 0 ]; then
        echo "${memory_gb}.$(printf "%02d" $((memory_mb_remainder * 100 / 1024)))G (${memory_str})"
    else
        echo "$memory_str"
    fi
}

# Function to calculate pod resource allocations
calculate_pod_resources() {
    local total_cpus="$DETECTED_CPUS"
    local total_memory_mib="$DETECTED_MEMORY_MIB"
    
    # First calculate minikube cluster resources
    local minikube_cpus=$((total_cpus * 90 / 100))
    local minikube_memory_mib=$((total_memory_mib * 90 / 100))
    
    # Apply minimum minikube requirements
    [ "$minikube_cpus" -lt 4 ] && minikube_cpus=4
    local minikube_memory_gb=$((minikube_memory_mib / 1024))
    [ "$minikube_memory_gb" -lt 8 ] && minikube_memory_gb=8 && minikube_memory_mib=$((minikube_memory_gb * 1024))
    
    # Pod resources are based on minikube cluster resources, not host resources
    # Reserve 20% of minikube resources for Kubernetes system overhead
    local available_cpus_millicores=$((minikube_cpus * 800))  # 80% of minikube CPUs, in millicores
    local available_memory_mib=$((minikube_memory_mib * 80 / 100))  # 80% of minikube memory

    # Disk size scales with memory but has reasonable bounds
    local minikube_disk_gb=$((minikube_memory_gb * 2))
    [ "$minikube_disk_gb" -lt 40 ] && minikube_disk_gb=40
    [ "$minikube_disk_gb" -gt 200 ] && minikube_disk_gb=200
    
    print_status "Calculated minikube cluster resources:"
    echo "  CPUs: $minikube_cpus"
    echo "  Memory: ${minikube_memory_gb}g"
    echo "  Disk: ${minikube_disk_gb}g"
    
    print_status "Available for pods: ${available_cpus_millicores}m CPU, $((available_memory_mib / 1024))G (${available_memory_mib}Mi) memory"
    
    # Calculate resource allocations based on service priorities
    # Build-bot is CPU intensive and runs multiple replicas
    # Scale replicas based on minikube CPUs, not host CPUs
    local build_bot_replicas
    if [ "$minikube_cpus" -ge 8 ]; then
        build_bot_replicas=4
    elif [ "$minikube_cpus" -ge 4 ]; then
        build_bot_replicas=2
    else
        build_bot_replicas=1
    fi
    
    # Allocate 40% of available CPU to build-bot fleet
    local build_bot_total_cpu=$((available_cpus_millicores * 40 / 100))
    # Ensure we don't divide by zero
    [ "$build_bot_replicas" -eq 0 ] && build_bot_replicas=1
    local build_bot_cpu_per_pod=$((build_bot_total_cpu / build_bot_replicas))
    local build_bot_cpu_limit="${build_bot_cpu_per_pod}m"
    local build_bot_cpu_request="$((build_bot_cpu_per_pod / 2))m"
    
    # Allocate 25% of available memory to build-bot fleet
    local build_bot_total_memory=$((available_memory_mib * 25 / 100))
    local build_bot_memory_per_pod=$((build_bot_total_memory / build_bot_replicas))
    local build_bot_memory_limit="${build_bot_memory_per_pod}Mi"
    local build_bot_memory_request="$((build_bot_memory_per_pod / 2))Mi"
    
    # DinD daemon gets 30% of CPU and 40% of memory (it's resource intensive)
    local dind_cpu_limit="$((available_cpus_millicores * 30 / 100))m"
    local dind_cpu_request="$((available_cpus_millicores * 10 / 100))m"
    local dind_memory_limit="$((available_memory_mib * 40 / 100))Mi"
    local dind_memory_request="$((available_memory_mib * 10 / 100))Mi"
    
    # Scheduler gets 10% of CPU and 10% of memory
    local scheduler_cpu_limit="$((available_cpus_millicores * 10 / 100))m"
    local scheduler_cpu_request="$((available_cpus_millicores * 5 / 100))m"
    local scheduler_memory_limit="$((available_memory_mib * 10 / 100))Mi"
    local scheduler_memory_request="$((available_memory_mib * 5 / 100))Mi"
    
    # Redis gets 5% of CPU and 10% of memory
    local redis_cpu_limit="$((available_cpus_millicores * 5 / 100))m"
    local redis_cpu_request="$((available_cpus_millicores * 2 / 100))m"
    local redis_memory_limit="$((available_memory_mib * 10 / 100))Mi"
    local redis_memory_request="$((available_memory_mib * 5 / 100))Mi"
    
    # Scratch cleaner gets 5% of CPU and 5% of memory
    local scratch_cleaner_cpu_limit="$((available_cpus_millicores * 5 / 100))m"
    local scratch_cleaner_cpu_request="$((available_cpus_millicores * 2 / 100))m"
    local scratch_cleaner_memory_limit="$((available_memory_mib * 5 / 100))Mi"
    local scratch_cleaner_memory_request="$((available_memory_mib * 2 / 100))Mi"
    
    # LiteLLM replicas based on minikube cluster size
    local litellm_replicas=1
    if [ "$minikube_cpus" -ge 16 ] && [ "$minikube_memory_mib" -ge 16384 ]; then
        litellm_replicas=2
    fi
    
    # Apply minimum resource limits to ensure functionality
    # Extract numeric values for comparison
    local build_bot_cpu_num="${build_bot_cpu_limit%m}"
    local build_bot_memory_num="${build_bot_memory_limit%Mi}"
    local dind_cpu_num="${dind_cpu_limit%m}"
    local dind_memory_num="${dind_memory_limit%Mi}"
    local scheduler_cpu_num="${scheduler_cpu_limit%m}"
    local scheduler_memory_num="${scheduler_memory_limit%Mi}"
    local redis_cpu_num="${redis_cpu_limit%m}"
    local redis_memory_num="${redis_memory_limit%Mi}"
    
    [ "$build_bot_cpu_num" -lt 250 ] && build_bot_cpu_limit="250m" && build_bot_cpu_request="125m"
    [ "$build_bot_memory_num" -lt 256 ] && build_bot_memory_limit="256Mi" && build_bot_memory_request="128Mi"
    [ "$dind_cpu_num" -lt 500 ] && dind_cpu_limit="500m" && dind_cpu_request="250m"
    [ "$dind_memory_num" -lt 1024 ] && dind_memory_limit="1024Mi" && dind_memory_request="512Mi"
    [ "$scheduler_cpu_num" -lt 100 ] && scheduler_cpu_limit="100m" && scheduler_cpu_request="50m"
    [ "$scheduler_memory_num" -lt 256 ] && scheduler_memory_limit="256Mi" && scheduler_memory_request="128Mi"
    [ "$redis_cpu_num" -lt 100 ] && redis_cpu_limit="100m" && redis_cpu_request="50m"
    [ "$redis_memory_num" -lt 256 ] && redis_memory_limit="256Mi" && redis_memory_request="128Mi"
    
    print_status "Calculated pod resource allocations:"
    echo "  Build-bot replicas: $build_bot_replicas"
    echo "  Build-bot CPU: $build_bot_cpu_request/$build_bot_cpu_limit"
    echo "  Build-bot Memory: $(display_memory_gb $build_bot_memory_request)/$(display_memory_gb $build_bot_memory_limit)"
    echo "  DinD CPU: $dind_cpu_request/$dind_cpu_limit"
    echo "  DinD Memory: $(display_memory_gb $dind_memory_request)/$(display_memory_gb $dind_memory_limit)"
    echo "  Scheduler CPU: $scheduler_cpu_request/$scheduler_cpu_limit"
    echo "  Scheduler Memory: $(display_memory_gb $scheduler_memory_request)/$(display_memory_gb $scheduler_memory_limit)"
    echo "  Redis CPU: $redis_cpu_request/$redis_cpu_limit"
    echo "  Redis Memory: $(display_memory_gb $redis_memory_request)/$(display_memory_gb $redis_memory_limit)"
    echo "  Scratch Cleaner CPU: $scratch_cleaner_cpu_request/$scratch_cleaner_cpu_limit"
    echo "  Scratch Cleaner Memory: $(display_memory_gb $scratch_cleaner_memory_request)/$(display_memory_gb $scratch_cleaner_memory_limit)"
    echo "  LiteLLM replicas: $litellm_replicas"
    
    # Export calculated values
    export CALC_BUILD_BOT_REPLICAS="$build_bot_replicas"
    export CALC_BUILD_BOT_CPU_LIMIT="$build_bot_cpu_limit"
    export CALC_BUILD_BOT_MEMORY_LIMIT="$build_bot_memory_limit"
    export CALC_BUILD_BOT_CPU_REQUEST="$build_bot_cpu_request"
    export CALC_BUILD_BOT_MEMORY_REQUEST="$build_bot_memory_request"
    
    export CALC_DIND_CPU_LIMIT="$dind_cpu_limit"
    export CALC_DIND_MEMORY_LIMIT="$dind_memory_limit"
    export CALC_DIND_CPU_REQUEST="$dind_cpu_request"
    export CALC_DIND_MEMORY_REQUEST="$dind_memory_request"
    
    export CALC_SCHEDULER_CPU_LIMIT="$scheduler_cpu_limit"
    export CALC_SCHEDULER_MEMORY_LIMIT="$scheduler_memory_limit"
    export CALC_SCHEDULER_CPU_REQUEST="$scheduler_cpu_request"
    export CALC_SCHEDULER_MEMORY_REQUEST="$scheduler_memory_request"
    
    export CALC_REDIS_CPU_LIMIT="$redis_cpu_limit"
    export CALC_REDIS_MEMORY_LIMIT="$redis_memory_limit"
    export CALC_REDIS_CPU_REQUEST="$redis_cpu_request"
    export CALC_REDIS_MEMORY_REQUEST="$redis_memory_request"
    
    export CALC_SCRATCH_CLEANER_CPU_LIMIT="$scratch_cleaner_cpu_limit"
    export CALC_SCRATCH_CLEANER_MEMORY_LIMIT="$scratch_cleaner_memory_limit"
    export CALC_SCRATCH_CLEANER_CPU_REQUEST="$scratch_cleaner_cpu_request"
    export CALC_SCRATCH_CLEANER_MEMORY_REQUEST="$scratch_cleaner_memory_request"
    
    export CALC_LITELLM_REPLICAS="$litellm_replicas"    

    export CALC_MINIKUBE_CPUS="$minikube_cpus"
    export CALC_MINIKUBE_MEMORY="${minikube_memory_gb}g"
    export CALC_MINIKUBE_DISK_SIZE="${minikube_disk_gb}g"
}

# Function to update environment file with calculated values
update_env_file() {
    local env_file="$1"
    
    if [ ! -f "$env_file" ]; then
        print_error "Environment file not found: $env_file"
        return 1
    fi
    
    print_status "Updating environment file with calculated values..."
    
    # Update replica counts
    sed -i "s|^export BUILD_BOT_REPLICAS=.*|export BUILD_BOT_REPLICAS=$CALC_BUILD_BOT_REPLICAS|" "$env_file"
    sed -i "s|^export LITELLM_REPLICAS=.*|export LITELLM_REPLICAS=$CALC_LITELLM_REPLICAS|" "$env_file"
    
    # Update build-bot resources
    sed -i "s|^export BUILD_BOT_CPU_LIMIT=.*|export BUILD_BOT_CPU_LIMIT=$CALC_BUILD_BOT_CPU_LIMIT|" "$env_file"
    sed -i "s|^export BUILD_BOT_MEMORY_LIMIT=.*|export BUILD_BOT_MEMORY_LIMIT=$CALC_BUILD_BOT_MEMORY_LIMIT|" "$env_file"
    sed -i "s|^export BUILD_BOT_CPU_REQUEST=.*|export BUILD_BOT_CPU_REQUEST=$CALC_BUILD_BOT_CPU_REQUEST|" "$env_file"
    sed -i "s|^export BUILD_BOT_MEMORY_REQUEST=.*|export BUILD_BOT_MEMORY_REQUEST=$CALC_BUILD_BOT_MEMORY_REQUEST|" "$env_file"
    
    # Update DinD resources
    sed -i "s|^export DIND_CPU_LIMIT=.*|export DIND_CPU_LIMIT=$CALC_DIND_CPU_LIMIT|" "$env_file"
    sed -i "s|^export DIND_MEMORY_LIMIT=.*|export DIND_MEMORY_LIMIT=$CALC_DIND_MEMORY_LIMIT|" "$env_file"
    sed -i "s|^export DIND_CPU_REQUEST=.*|export DIND_CPU_REQUEST=$CALC_DIND_CPU_REQUEST|" "$env_file"
    sed -i "s|^export DIND_MEMORY_REQUEST=.*|export DIND_MEMORY_REQUEST=$CALC_DIND_MEMORY_REQUEST|" "$env_file"
    
    # Update scheduler resources
    sed -i "s|^export SCHEDULER_CPU_LIMIT=.*|export SCHEDULER_CPU_LIMIT=$CALC_SCHEDULER_CPU_LIMIT|" "$env_file"
    sed -i "s|^export SCHEDULER_MEMORY_LIMIT=.*|export SCHEDULER_MEMORY_LIMIT=$CALC_SCHEDULER_MEMORY_LIMIT|" "$env_file"
    sed -i "s|^export SCHEDULER_CPU_REQUEST=.*|export SCHEDULER_CPU_REQUEST=$CALC_SCHEDULER_CPU_REQUEST|" "$env_file"
    sed -i "s|^export SCHEDULER_MEMORY_REQUEST=.*|export SCHEDULER_MEMORY_REQUEST=$CALC_SCHEDULER_MEMORY_REQUEST|" "$env_file"
    
    # Update Redis resources
    sed -i "s|^export REDIS_CPU_LIMIT=.*|export REDIS_CPU_LIMIT=$CALC_REDIS_CPU_LIMIT|" "$env_file"
    sed -i "s|^export REDIS_MEMORY_LIMIT=.*|export REDIS_MEMORY_LIMIT=$CALC_REDIS_MEMORY_LIMIT|" "$env_file"
    sed -i "s|^export REDIS_CPU_REQUEST=.*|export REDIS_CPU_REQUEST=$CALC_REDIS_CPU_REQUEST|" "$env_file"
    sed -i "s|^export REDIS_MEMORY_REQUEST=.*|export REDIS_MEMORY_REQUEST=$CALC_REDIS_MEMORY_REQUEST|" "$env_file"
    
    # Update scratch cleaner resources
    sed -i "s|^export SCRATCH_CLEANER_CPU_LIMIT=.*|export SCRATCH_CLEANER_CPU_LIMIT=$CALC_SCRATCH_CLEANER_CPU_LIMIT|" "$env_file"
    sed -i "s|^export SCRATCH_CLEANER_MEMORY_LIMIT=.*|export SCRATCH_CLEANER_MEMORY_LIMIT=$CALC_SCRATCH_CLEANER_MEMORY_LIMIT|" "$env_file"
    sed -i "s|^export SCRATCH_CLEANER_CPU_REQUEST=.*|export SCRATCH_CLEANER_CPU_REQUEST=$CALC_SCRATCH_CLEANER_CPU_REQUEST|" "$env_file"
    sed -i "s|^export SCRATCH_CLEANER_MEMORY_REQUEST=.*|export SCRATCH_CLEANER_MEMORY_REQUEST=$CALC_SCRATCH_CLEANER_MEMORY_REQUEST|" "$env_file"
    
    # Update minikube resources
    sed -i "s|^export MINIKUBE_CPUS=.*|export MINIKUBE_CPUS=$CALC_MINIKUBE_CPUS|" "$env_file"
    sed -i "s|^export MINIKUBE_MEMORY=.*|export MINIKUBE_MEMORY=$CALC_MINIKUBE_MEMORY|" "$env_file"
    sed -i "s|^export MINIKUBE_DISK_SIZE=.*|export MINIKUBE_DISK_SIZE=$CALC_MINIKUBE_DISK_SIZE|" "$env_file"
    
    print_success "Environment file updated successfully"
}

# Main function
main() {
    local env_file="${1:-deployment/env}"
    
    print_status "Starting system resource detection and configuration..."
    
    # Detect system resources
    detect_system_resources || exit 1
    
    # Calculate optimal pod resource allocations
    calculate_pod_resources || exit 1
    
    # Update environment file if provided
    if [ -n "$1" ]; then
        update_env_file "$env_file" || exit 1
    fi
    
    print_success "Resource detection and configuration completed!"
}

# Run main function if script is executed directly
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    main "$@"
fi