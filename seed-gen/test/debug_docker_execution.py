#!/usr/bin/env python3
"""Standalone script to debug Docker execution for debug subagent.

This script helps diagnose issues with:
1. Docker container access
2. File mounting
3. GDB script execution
4. Path resolution

Run with: python seed-gen/test/debug_docker_execution.py
"""

import logging
import subprocess
import sys
import tempfile
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


def test_docker_available():
    """Test if Docker is available and the debug image can be pulled."""
    logger.info("=" * 60)
    logger.info("TEST 1: Docker Availability")
    logger.info("=" * 60)
    
    try:
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            logger.info(f"✓ Docker available: {result.stdout.decode().strip()}")
        else:
            logger.error("✗ Docker not working")
            return False
    except FileNotFoundError:
        logger.error("✗ Docker not found in PATH")
        return False
    except Exception as e:
        logger.error(f"✗ Error checking Docker: {e}")
        return False
    
    # Test if we can access the debug image
    logger.info("\nTesting debug container image access...")
    try:
        result = subprocess.run(
            ["docker", "run", "--rm", "gcr.io/oss-fuzz-base/base-runner-debug", "echo", "test"],
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0:
            logger.info("✓ Debug container image accessible")
            return True
        else:
            logger.warning(f"⚠ Debug container might not be available: {result.stderr.decode()}")
            logger.info("You may need to pull the image first:")
            logger.info("  docker pull gcr.io/oss-fuzz-base/base-runner-debug")
            return False
    except subprocess.TimeoutExpired:
        logger.error("✗ Docker command timed out")
        return False
    except Exception as e:
        logger.error(f"✗ Error accessing debug container: {e}")
        return False


def test_file_mounting():
    """Test mounting files into Docker container."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 2: File Mounting")
    logger.info("=" * 60)
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Hello from mounted file!")
        f.flush()
        test_file = Path(f.name)
    
    try:
        logger.info(f"Created test file: {test_file}")
        logger.info(f"  Absolute path: {test_file.resolve()}")
        logger.info(f"  Exists: {test_file.exists()}")
        logger.info(f"  Is file: {test_file.is_file()}")
        logger.info(f"  Size: {test_file.stat().st_size} bytes")
        
        # Test mounting as individual file
        docker_cmd = [
            "docker", "run", "--rm",
            "-v", f"{test_file.resolve().as_posix()}:/tmp/test_mount.txt",
            "gcr.io/oss-fuzz-base/base-runner-debug",
            "cat", "/tmp/test_mount.txt",
        ]
        
        logger.info(f"\nRunning: {' '.join(docker_cmd)}")
        
        result = subprocess.run(
            docker_cmd,
            capture_output=True,
            timeout=30,
        )
        
        logger.info(f"Return code: {result.returncode}")
        logger.info(f"Stdout: {result.stdout.decode('utf-8', errors='ignore')}")
        if result.stderr:
            logger.info(f"Stderr: {result.stderr.decode('utf-8', errors='ignore')}")
        
        if result.returncode == 0 and b"Hello from mounted file!" in result.stdout:
            logger.info("✓ File mounting works correctly")
            return True
        else:
            logger.error("✗ File mounting failed")
            logger.error(f"  Expected 'Hello from mounted file!' in output")
            return False
            
    except Exception as e:
        logger.error(f"✗ Error testing file mount: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if test_file.exists():
            test_file.unlink()


def test_gdb_script_execution():
    """Test executing a GDB script in the container."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 3: GDB Script Execution")
    logger.info("=" * 60)
    
    # Create a simple GDB script
    gdb_script = """# Simple GDB test script
set confirm off
set pagination off
echo \\n=== GDB Test Script ===\\n
echo Testing GDB execution...\\n
info registers
echo \\n=== Script Complete ===\\n
quit
"""
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".gdb", delete=False) as f:
        f.write(gdb_script)
        f.flush()
        script_path = Path(f.name)
    
    # Create a simple binary to debug (use /bin/true)
    test_binary = Path("/bin/true")
    if not test_binary.exists():
        logger.warning("⚠ /bin/true not found, trying /bin/false")
        test_binary = Path("/bin/false")
        if not test_binary.exists():
            logger.error("✗ No suitable test binary found")
            return False
    
    try:
        logger.info(f"GDB script: {script_path}")
        logger.info(f"  Size: {script_path.stat().st_size} bytes")
        logger.info(f"Test binary: {test_binary}")
        
        # Create a dummy input file
        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
            f.write(b"dummy input")
            input_file = Path(f.name)
        
        try:
            # Mount files and run GDB
            docker_cmd = [
                "docker", "run", "--rm", "--privileged", "--shm-size=2g",
                "-v", f"{script_path.resolve().as_posix()}:/tmp/test_script.gdb",
                "-v", f"{input_file.resolve().as_posix()}:/tmp/test_input.bin",
                "-v", f"{test_binary.parent.as_posix()}:/out",
                "gcr.io/oss-fuzz-base/base-runner-debug",
                "gdb",
                "-batch",
                "-x", "/tmp/test_script.gdb",
                "--args",
                f"/out/{test_binary.name}",
                "/tmp/test_input.bin",
            ]
            
            logger.info(f"\nRunning: {' '.join(docker_cmd[:10])}...")
            
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                timeout=60,
            )
            
            output = result.stdout.decode("utf-8", errors="ignore")
            error = result.stderr.decode("utf-8", errors="ignore")
            
            logger.info(f"Return code: {result.returncode}")
            logger.info(f"Output length: {len(output)} chars")
            logger.info(f"Error length: {len(error)} chars")
            
            if output:
                logger.info(f"\nGDB Output (first 500 chars):\n{output[:500]}")
            if error:
                logger.info(f"\nGDB Errors:\n{error[:500]}")
            
            # Check for success indicators
            success_indicators = [
                "GDB Test Script",
                "Script Complete",
                "registers",
                "rax",
            ]
            
            found_indicators = [ind for ind in success_indicators if ind.lower() in output.lower()]
            
            if found_indicators:
                logger.info(f"✓ GDB script executed (found indicators: {found_indicators})")
                return True
            elif len(output) > 100:
                logger.warning("⚠ GDB produced output but no expected indicators found")
                logger.warning("  This might still be okay - check the output above")
                return True
            else:
                logger.error("✗ GDB script execution failed or produced no output")
                if error:
                    logger.error(f"  Error: {error[:200]}")
                return False
                
        finally:
            if input_file.exists():
                input_file.unlink()
                
    except subprocess.TimeoutExpired:
        logger.error("✗ GDB command timed out")
        return False
    except Exception as e:
        logger.error(f"✗ Error executing GDB script: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if script_path.exists():
            script_path.unlink()


def test_path_resolution():
    """Test path resolution issues."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 4: Path Resolution")
    logger.info("=" * 60)
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("test")
        test_file = Path(f.name)
    
    try:
        logger.info(f"Original path: {test_file}")
        logger.info(f"  is_absolute: {test_file.is_absolute()}")
        logger.info(f"  resolved: {test_file.resolve()}")
        logger.info(f"  as_posix: {test_file.resolve().as_posix()}")
        
        # Test that resolved path works with Docker
        docker_cmd = [
            "docker", "run", "--rm",
            "-v", f"{test_file.resolve().as_posix()}:/tmp/path_test.txt",
            "gcr.io/oss-fuzz-base/base-runner-debug",
            "test", "-f", "/tmp/path_test.txt",
        ]
        
        result = subprocess.run(docker_cmd, capture_output=True, timeout=10)
        
        if result.returncode == 0:
            logger.info("✓ Path resolution works correctly")
            return True
        else:
            logger.error("✗ Path resolution issue")
            return False
            
    finally:
        if test_file.exists():
            test_file.unlink()


def main():
    """Run all diagnostic tests."""
    logger.info("Debug Subagent Docker Execution Diagnostics")
    logger.info("=" * 60)
    
    results = {
        "Docker Available": test_docker_available(),
        "File Mounting": test_file_mounting(),
        "GDB Script Execution": test_gdb_script_execution(),
        "Path Resolution": test_path_resolution(),
    }
    
    logger.info("\n" + "=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        logger.info(f"{status}: {test_name}")
    
    all_passed = all(results.values())
    
    if all_passed:
        logger.info("\n✅ All tests passed! Docker execution should work.")
    else:
        logger.info("\n❌ Some tests failed. Common issues:")
        logger.info("  1. Docker not running: sudo systemctl start docker")
        logger.info("  2. Debug image not available: docker pull gcr.io/oss-fuzz-base/base-runner-debug")
        logger.info("  3. Permission issues: Check Docker group membership")
        logger.info("  4. File paths: Ensure all paths are absolute and files exist")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())

