#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "redis>=5.0.0",
#     "rich>=13.0.0",
# ]
# ///
"""
Monitor CRS results for found bugs and generated reports.
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import redis
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.columns import Columns
from rich.layout import Layout
from rich.align import Align


console = Console(force_terminal=True)


class CRSMonitor:
    """Monitor CRS queues and results."""
    
    def __init__(self, redis_host: str = "localhost", redis_port: int = 6379):
        self.redis_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            decode_responses=True
        )
        self.base_path = Path("/node_data/crs_scratch")
        self.services = [
            "redis",
            "litellm",  # Might be running via uvx
            "task-server",
            "scheduler", 
            "task-downloader",
            "unified-fuzzer",
            "program-model",
            "patcher",
            "seed-gen"
        ]
        
    def check_redis_connection(self) -> bool:
        """Check if Redis is accessible."""
        try:
            self.redis_client.ping()
            return True
        except redis.ConnectionError:
            return False
            
    def get_docker_service_status(self) -> Dict[str, Tuple[str, str]]:
        """Get status of Docker services."""
        status = {}
        
        try:
            # Run docker compose ps with JSON output
            result = subprocess.run(
                ["docker", "compose", "ps", "--format", "json"],
                capture_output=True,
                text=True,
                check=True
            )
            
            if result.stdout:
                # Parse each line as a JSON object
                for line in result.stdout.strip().split('\n'):
                    if line:
                        try:
                            service_info = json.loads(line)
                            name = service_info.get("Service", "")
                            state = service_info.get("State", "unknown")
                            health = service_info.get("Health", "")
                            status[name] = (state, health)
                        except json.JSONDecodeError:
                            continue
                            
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Fallback to simple ps if JSON format not available
            try:
                result = subprocess.run(
                    ["docker", "compose", "ps"],
                    capture_output=True,
                    text=True
                )
                
                lines = result.stdout.strip().split('\n')
                for line in lines[1:]:  # Skip header
                    if line and "buttercup" in line:
                        parts = line.split()
                        if len(parts) >= 2:
                            # Extract service name from container name
                            container = parts[0]
                            if "buttercup-" in container:
                                service = container.replace("buttercup-", "").replace("-1", "")
                                state = "running" if "Up" in line else "stopped"
                                health = "healthy" if "healthy" in line else ""
                                status[service] = (state, health)
                                
            except Exception:
                pass
                
        # Check for LiteLLM running via uvx
        try:
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True,
                text=True
            )
            if "litellm" in result.stdout and "uvx" in result.stdout:
                status["litellm"] = ("running", "uvx")
        except Exception:
            pass
            
        return status
            
    def get_queue_counts(self) -> Dict[str, int]:
        """Get counts for all relevant queues."""
        queues = {
            "Download Tasks": "orchestrator_download_tasks_queue",
            "Ready Tasks": "tasks_ready_queue",
            "Build Queue": "fuzzer_build_queue",
            "Build Output": "fuzzer_build_output_queue",
            "Crashes": "crashes_queue",
            "Patches": "patches_queue",
            "Confirmed Vulnerabilities": "confirmed_vulnerabilities_queue",
            "Traced Vulnerabilities": "traced_vulnerabilities_queue",
        }
        
        counts = {}
        for name, queue in queues.items():
            try:
                count = self.redis_client.llen(queue)
                counts[name] = count
            except Exception:
                counts[name] = -1
                
        return counts
        
    def get_recent_crashes(self, limit: int = 5) -> List[Dict]:
        """Get recent crashes from the queue."""
        crashes = []
        try:
            # Get crashes from queue (don't remove them)
            crash_data = self.redis_client.lrange("crashes_queue", 0, limit - 1)
            for crash_json in crash_data:
                try:
                    crash = json.loads(crash_json)
                    crashes.append(crash)
                except json.JSONDecodeError:
                    continue
        except Exception:
            pass
            
        return crashes
        
    def get_recent_patches(self, limit: int = 5) -> List[Dict]:
        """Get recent patches from the queue."""
        patches = []
        try:
            patch_data = self.redis_client.lrange("patches_queue", 0, limit - 1)
            for patch_json in patch_data:
                try:
                    patch = json.loads(patch_json)
                    patches.append(patch)
                except json.JSONDecodeError:
                    continue
        except Exception:
            pass
            
        return patches
        
    def find_task_artifacts(self, task_id: str) -> Dict[str, List[Path]]:
        """Find artifacts for a specific task."""
        artifacts = {
            "crashes": [],
            "patches": [],
            "reports": [],
            "logs": []
        }
        
        task_path = self.base_path / task_id
        if not task_path.exists():
            return artifacts
            
        # Look for crash files
        for crash_file in task_path.rglob("crash-*"):
            artifacts["crashes"].append(crash_file)
            
        # Look for patches
        for patch_file in task_path.rglob("*.patch"):
            artifacts["patches"].append(patch_file)
            
        # Look for reports
        for report_file in task_path.rglob("*report*.txt"):
            artifacts["reports"].append(report_file)
            
        # Look for logs
        for log_file in task_path.rglob("*.log"):
            artifacts["logs"].append(log_file)
            
        return artifacts
        
    def create_service_status_table(self) -> Table:
        """Create a compact table showing Docker service status."""
        table = Table(title="Services", show_header=True, show_lines=False)
        table.add_column("Service", style="cyan", width=15)
        table.add_column("Status", justify="center", width=6)
        
        service_status = self.get_docker_service_status()
        
        # Show only essential services in compact form
        essential_services = ["redis", "litellm", "unified-fuzzer", "scheduler", "patcher"]
        
        for service in essential_services:
            if service in service_status:
                state, health = service_status[service]
                
                # Determine icon
                if state == "running":
                    if health == "healthy":
                        icon = "✅"
                    elif health == "uvx":
                        icon = "🚀"
                    else:
                        icon = "🟢"
                else:
                    icon = "❌"
            else:
                icon = "❓"
                
            table.add_row(service, icon)
                
        return table
        
    def create_queue_status_table(self) -> Table:
        """Create a status table with queue information."""
        table = Table(title="Queue Status", show_header=True, show_lines=False, show_edge=True)
        table.add_column("Queue", style="cyan")
        table.add_column("Count", style="magenta", justify="right")
        table.add_column("", justify="center", width=3)
        
        counts = self.get_queue_counts()
        for name, count in counts.items():
            if count == -1:
                table.add_row(name, "Error", "❌")
            elif count == 0:
                table.add_row(name, str(count), "⏳")
            else:
                status = "✅" if name in ["Crashes", "Patches"] else "🔄"
                table.add_row(name, str(count), status)
                
        return table
        
    def create_crashes_panel(self) -> Panel:
        """Create a panel showing recent crashes."""
        crashes = self.get_recent_crashes()
        
        if not crashes:
            content = Text("No crashes found yet", style="dim")
        else:
            lines = []
            for i, crash in enumerate(crashes, 1):
                task_id = crash.get("task_id", "unknown")
                crash_type = crash.get("crash_type", "unknown")
                timestamp = crash.get("timestamp", "")
                
                lines.append(f"[bold]{i}.[/bold] Task: {task_id}")
                lines.append(f"   Type: [red]{crash_type}[/red]")
                lines.append(f"   Time: {timestamp}")
                lines.append("")
                
            content = Text.from_markup("\n".join(lines))
            
        return Panel(content, title="Recent Crashes", border_style="red")
        
    def create_patches_panel(self) -> Panel:
        """Create a panel showing recent patches."""
        patches = self.get_recent_patches()
        
        if not patches:
            content = Text("No patches generated yet", style="dim")
        else:
            lines = []
            for i, patch in enumerate(patches, 1):
                task_id = patch.get("task_id", "unknown")
                vuln_id = patch.get("vulnerability_id", "unknown")
                timestamp = patch.get("timestamp", "")
                
                lines.append(f"[bold]{i}.[/bold] Task: {task_id}")
                lines.append(f"   Vuln: [yellow]{vuln_id}[/yellow]")
                lines.append(f"   Time: {timestamp}")
                lines.append("")
                
            content = Text.from_markup("\n".join(lines))
            
        return Panel(content, title="Generated Patches", border_style="green")
        
    def create_summary_panel(self) -> Panel:
        """Create a summary panel with key statistics."""
        service_status = self.get_docker_service_status()
        queue_counts = self.get_queue_counts()
        
        # Count running services from our expected list only
        expected_services = set(self.services)
        running_services = sum(1 for service, (state, _) in service_status.items() 
                             if service in expected_services and state == "running")
        # Total is our expected service count
        total_services = len(self.services)
        
        # Get key metrics
        crashes = queue_counts.get("Crashes", 0)
        patches = queue_counts.get("Patches", 0)
        ready_tasks = queue_counts.get("Ready Tasks", 0)
        
        # Create summary text
        lines = [
            f"[bold]Services:[/bold] {running_services}/{total_services} running",
            f"[bold]Crashes Found:[/bold] [red]{crashes}[/red]" if crashes > 0 else "[bold]Crashes Found:[/bold] [dim]0[/dim]",
            f"[bold]Patches Generated:[/bold] [green]{patches}[/green]" if patches > 0 else "[bold]Patches Generated:[/bold] [dim]0[/dim]",
            f"[bold]Tasks Ready:[/bold] {ready_tasks}",
        ]
        
        content = Text.from_markup("\n".join(lines))
        return Panel(content, title="Summary", border_style="cyan")
        
    def monitor_live(self, refresh_interval: int = 2, show_services: bool = True):
        """Monitor CRS status with live updates."""
        console.print("[bold cyan]CRS Results Monitor[/bold cyan]")
        console.print(f"Redis: {self.redis_client.connection_pool.connection_kwargs['host']}:{self.redis_client.connection_pool.connection_kwargs['port']}")
        console.print(f"Data path: {self.base_path}")
        
        if not self.check_redis_connection():
            console.print("[red]Error: Cannot connect to Redis![/red]")
            console.print("Make sure CRS services are running:")
            console.print("  ./scripts/local/local-dev.sh --minimal up")
            sys.exit(1)
            
        with Live(console=console, refresh_per_second=1/refresh_interval, vertical_overflow="visible") as live:
            while True:
                # Create main components
                queue_table = self.create_queue_status_table()
                crashes_panel = self.create_crashes_panel()
                patches_panel = self.create_patches_panel()
                
                if show_services:
                    # With services: compact layout
                    service_table = self.create_service_status_table()
                    summary_panel = self.create_summary_panel()
                    
                    # Arrange in grid
                    layout = Layout()
                    layout.split_row(
                        Layout(name="left", ratio=3),
                        Layout(name="right", ratio=1)
                    )
                    
                    # Left side: main content
                    layout["left"].split_column(
                        Layout(queue_table),
                        Layout(Columns([crashes_panel, patches_panel], equal=True))
                    )
                    
                    # Right side: services and summary
                    layout["right"].split_column(
                        Layout(service_table, size=10),
                        Layout(summary_panel)
                    )
                else:
                    # Without services: original layout
                    # Add empty line between table and panels for proper separation
                    content = [
                        queue_table,
                        Text(""),  # Empty line for separation
                        Columns([crashes_panel, patches_panel], equal=True)
                    ]
                    
                    from rich.console import Group
                    layout = Group(*content)
                
                # Update display
                live.update(Panel(
                    layout,
                    title=f"🔍 CRS Monitor - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Ctrl+C to exit",
                    border_style="bold blue"
                ))
                
                time.sleep(refresh_interval)
                
    def show_task_details(self, task_id: str):
        """Show detailed information about a specific task."""
        console.print(f"\n[bold]Task Details: {task_id}[/bold]\n")
        
        artifacts = self.find_task_artifacts(task_id)
        
        # Show crashes
        if artifacts["crashes"]:
            console.print("[red]Crashes found:[/red]")
            for crash in artifacts["crashes"]:
                console.print(f"  • {crash.relative_to(self.base_path)}")
                
        # Show patches
        if artifacts["patches"]:
            console.print("\n[green]Patches generated:[/green]")
            for patch in artifacts["patches"]:
                console.print(f"  • {patch.relative_to(self.base_path)}")
                # Show first few lines of patch
                try:
                    lines = patch.read_text().splitlines()[:10]
                    for line in lines:
                        console.print(f"    {line}", style="dim")
                    if len(patch.read_text().splitlines()) > 10:
                        console.print("    ...", style="dim")
                except Exception:
                    pass
                    
        # Show reports
        if artifacts["reports"]:
            console.print("\n[yellow]Reports:[/yellow]")
            for report in artifacts["reports"]:
                console.print(f"  • {report.relative_to(self.base_path)}")
                
        if not any(artifacts.values()):
            console.print("[dim]No artifacts found for this task[/dim]")


def main():
    parser = argparse.ArgumentParser(
        description="Monitor CRS results for bugs and patches"
    )
    
    parser.add_argument(
        "--task-id",
        help="Show details for a specific task ID"
    )
    
    parser.add_argument(
        "--redis-host",
        default="localhost",
        help="Redis host (default: localhost)"
    )
    
    parser.add_argument(
        "--redis-port",
        type=int,
        default=6379,
        help="Redis port (default: 6379)"
    )
    
    parser.add_argument(
        "--refresh",
        type=int,
        default=2,
        help="Refresh interval in seconds (default: 2)"
    )
    
    parser.add_argument(
        "--no-services",
        action="store_true",
        help="Hide service status panel"
    )
    
    args = parser.parse_args()
    
    monitor = CRSMonitor(args.redis_host, args.redis_port)
    
    try:
        if args.task_id:
            monitor.show_task_details(args.task_id)
        else:
            monitor.monitor_live(args.refresh, show_services=not args.no_services)
    except KeyboardInterrupt:
        # Clear the live display properly
        pass
    finally:
        console.print("\n[yellow]Monitoring stopped[/yellow]")
        

if __name__ == "__main__":
    main()