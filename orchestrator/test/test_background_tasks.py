"""Tests for the background task management system."""

import pytest
import time
from datetime import datetime
from unittest.mock import Mock, patch

from buttercup.orchestrator.scheduler.background_tasks import BackgroundTask, BackgroundTaskManager


class MockBackgroundTask(BackgroundTask):
    """Test implementation of BackgroundTask."""
    
    def __init__(self, name: str, interval: float, success: bool = True):
        super().__init__(name, interval)
        self.success = success
        self.execute_count = 0
    
    def execute(self) -> bool:
        self.execute_count += 1
        if not self.success:
            raise ValueError("Test error")
        return True


class TestBackgroundTaskExecution:
    """Test the BackgroundTask class."""
    
    def test_task_should_run_initially(self):
        """Test that tasks should run on first check."""
        task = MockBackgroundTask("test", 1.0)
        assert task.should_run() is True
    
    def test_task_should_not_run_immediately_after(self):
        """Test that tasks respect interval."""
        task = MockBackgroundTask("test", 1.0)
        task.last_run = datetime.now()
        assert task.should_run() is False
    
    def test_task_execution_success(self):
        """Test successful task execution."""
        task = MockBackgroundTask("test", 1.0, success=True)
        task.run()
        
        assert task.execute_count == 1
        assert task.success_count == 1
        assert task.error_count == 0
        assert task.last_run is not None
    
    def test_task_execution_failure(self):
        """Test failed task execution."""
        task = MockBackgroundTask("test", 1.0, success=False)
        task.run()
        
        assert task.execute_count == 1
        assert task.success_count == 0
        assert task.error_count == 1
        assert task.last_run is not None
    
    def test_task_status(self):
        """Test task status reporting."""
        task = MockBackgroundTask("test", 1.0)
        task.run()
        
        status = task.get_status()
        assert status["name"] == "test"
        assert status["interval"] == 1.0
        assert status["success_count"] == 1
        assert status["error_count"] == 0
        assert status["is_running"] is False
        assert status["last_run"] is not None


class TestBackgroundTaskManager:
    """Test the BackgroundTaskManager class."""
    
    def test_add_task(self):
        """Test adding tasks to the manager."""
        manager = BackgroundTaskManager()
        task = MockBackgroundTask("test", 1.0)
        
        manager.add_task(task)
        assert len(manager.tasks) == 1
        assert manager.tasks[0] == task
    
    def test_start_stop_tasks(self):
        """Test starting and stopping background tasks."""
        manager = BackgroundTaskManager()
        task = MockBackgroundTask("test", 0.1)  # Short interval for testing
        manager.add_task(task)
        
        # Start tasks
        manager.start()
        time.sleep(0.3)  # Let it run a few times
        
        # Check that task executed
        assert task.execute_count > 0
        
        # Stop tasks
        manager.stop()
        execute_count_after_stop = task.execute_count
        time.sleep(0.2)
        
        # Verify no more executions after stop
        assert task.execute_count == execute_count_after_stop
    
    def test_get_status(self):
        """Test getting status of all tasks."""
        manager = BackgroundTaskManager()
        task1 = MockBackgroundTask("test1", 1.0)
        task2 = MockBackgroundTask("test2", 2.0)
        
        manager.add_task(task1)
        manager.add_task(task2)
        
        status = manager.get_status()
        assert len(status["tasks"]) == 2
        assert status["active_threads"] == 0  # Not started yet
        
        # Start and check again
        manager.start()
        status = manager.get_status()
        assert status["active_threads"] == 2
        
        manager.stop()
    
    def test_health_check(self):
        """Test health check functionality."""
        manager = BackgroundTaskManager()
        task = MockBackgroundTask("test", 1.0)
        manager.add_task(task)
        
        # Should be healthy before start (no threads to check)
        assert manager.health_check() is True
        
        # Start and check
        manager.start()
        assert manager.health_check() is True
        
        # Simulate many errors
        task.error_count = 10
        assert manager.health_check() is False
        
        manager.stop()
    
    def test_multiple_tasks_concurrent_execution(self):
        """Test that multiple tasks run concurrently."""
        manager = BackgroundTaskManager()
        task1 = MockBackgroundTask("test1", 0.1)
        task2 = MockBackgroundTask("test2", 0.1)
        task3 = MockBackgroundTask("test3", 0.1)
        
        manager.add_task(task1)
        manager.add_task(task2)
        manager.add_task(task3)
        
        manager.start()
        time.sleep(0.3)
        
        # All tasks should have executed
        assert task1.execute_count > 0
        assert task2.execute_count > 0
        assert task3.execute_count > 0
        
        manager.stop()