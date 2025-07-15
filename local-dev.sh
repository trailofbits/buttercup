#!/usr/bin/env bash
# Helper script for local development with Docker Compose

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check prerequisites
check_prerequisites() {
    print_info "Checking prerequisites..."
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed. Please install Docker Desktop for macOS."
        exit 1
    fi
    
    # Check Docker Compose
    if ! docker compose version &> /dev/null; then
        print_error "Docker Compose is not available. Please ensure Docker Desktop is running."
        exit 1
    fi
    
    # Check if Docker is running
    if ! docker info &> /dev/null; then
        print_error "Docker daemon is not running. Please start Docker Desktop."
        exit 1
    fi
    
    # Create necessary directories
    mkdir -p crs_scratch tasks_storage node_data_storage
    
    print_info "Prerequisites check passed!"
}

# Function to show usage
usage() {
    echo "Usage: $0 {up|down|restart|logs|status|clean|rebuild}"
    echo ""
    echo "Commands:"
    echo "  up       - Start all services"
    echo "  down     - Stop all services"
    echo "  restart  - Restart all services"
    echo "  logs     - Show logs (optionally specify service name)"
    echo "  status   - Show status of all services"
    echo "  clean    - Clean up volumes and temporary data"
    echo "  rebuild  - Rebuild and restart all services"
    echo ""
    echo "Examples:"
    echo "  $0 up"
    echo "  $0 logs unified-fuzzer"
    echo "  $0 restart patcher"
}

# Main command handling
case "${1:-}" in
    up)
        check_prerequisites
        print_info "Starting Buttercup CRS services..."
        docker compose up -d
        print_info "Services started! Checking status..."
        sleep 5
        docker compose ps
        echo ""
        print_info "Access points:"
        echo "  - Task Server API: http://localhost:8000"
        echo "  - Buttercup UI: http://localhost:1323"
        echo "  - LiteLLM Proxy: http://localhost:8080"
        echo "  - Redis: localhost:6379"
        echo "  - Competition API: http://localhost:31323"
        ;;
    
    down)
        print_info "Stopping Buttercup CRS services..."
        docker compose down
        print_info "Services stopped."
        ;;
    
    restart)
        service="${2:-}"
        if [ -n "$service" ]; then
            print_info "Restarting service: $service"
            docker compose restart "$service"
        else
            print_info "Restarting all services..."
            docker compose restart
        fi
        ;;
    
    logs)
        service="${2:-}"
        if [ -n "$service" ]; then
            docker compose logs -f "$service"
        else
            docker compose logs -f
        fi
        ;;
    
    status)
        print_info "Service status:"
        docker compose ps
        echo ""
        print_info "Service health:"
        docker compose ps --format json | jq -r '.[] | "\(.Service): \(.Health // "No health check")"'
        ;;
    
    clean)
        print_warn "This will remove all local data and volumes. Continue? (y/N)"
        read -r response
        if [[ "$response" =~ ^[Yy]$ ]]; then
            print_info "Stopping services..."
            docker compose down -v
            print_info "Cleaning up local directories..."
            rm -rf crs_scratch/* tasks_storage/* node_data_storage/*
            print_info "Cleanup complete."
        else
            print_info "Cleanup cancelled."
        fi
        ;;
    
    rebuild)
        print_info "Rebuilding and restarting services..."
        docker compose down
        docker compose build --no-cache
        docker compose up -d
        print_info "Rebuild complete!"
        ;;
    
    *)
        usage
        exit 1
        ;;
esac