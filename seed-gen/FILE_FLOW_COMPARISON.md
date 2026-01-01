# File Flow Comparison: Fuzzer Bot vs Debug System

## ASCII Art Flow Diagrams

### Fuzzer Bot Flow (Reference Implementation)
```
┌─────────────────────────────────────────────────────────────────┐
│                    FUZZER BOT FILE FLOW                         │
└─────────────────────────────────────────────────────────────────┘

Step 1: Get Build Directory
────────────────────────────
   task.get_build_dir()
   ↓
   .../build/out/<project_name>
   ↓

Step 2: Construct Binary Path
──────────────────────────────
   build_dir / harness_name
   ↓
   .../build/out/<project_name>/<harness_name>
   ↓

Step 3: Direct File Access (NO DOCKER)
───────────────────────────────────────
   FuzzConfiguration(
       corpus_path,
       str(binary_path),  ← Direct host path
       engine,
       sanitizer
   )
   ↓
   [Fuzzer runs directly on host]
   ↓
   [No file mounting needed]
```

### Debug Subagent Flow (Current Implementation)
```
┌─────────────────────────────────────────────────────────────────┐
│              DEBUG SUBAGENT FILE FLOW                           │
└─────────────────────────────────────────────────────────────────┘

Step 1: Create GDB Script File
──────────────────────────────
   tempfile.NamedTemporaryFile(delete=False)
   ↓
   /tmp/tmpXXXXXX.gdb
   ↓
   f.write(debug_script)
   f.flush() ✓
   ↓
   debug_script_path = Path(f.name)

Step 2: Resolve All Paths
──────────────────────────
   debug_script_path.resolve() ✓
   pov_input_path.resolve() ✓
   ↓
   [All paths become absolute]

Step 3: Get Build Directory
────────────────────────────
   task.get_build_dir()
   ↓
   .../build/out/<project_name>
   ↓

Step 4: Find Binary
───────────────────
   build_dir / harness_name
   ↓
   .../build/out/<project_name>/<harness_name>
   ↓
   [Verify exists] ✓
   [Set execute permissions] ✓

Step 5: Setup Docker Mounts
────────────────────────────
   mount_dirs = {
       debug_script_path → /tmp/debug_script.gdb  (FILE)
       pov_input_path    → /tmp/<pov_name>         (FILE)
       out_dir           → /out                    (DIR)
   }
   where out_dir = build_dir.parent = .../build/out

Step 6: Construct Container Binary Path
─────────────────────────────────────────
   project_name = build_dir.name
   binary_path = /out/<project_name>/<harness_name>
   ↓
   /out/<project_name>/<harness_name>

Step 7: Execute in Docker Container
────────────────────────────────────
   docker run \
     -v <host_script>:/tmp/debug_script.gdb \
     -v <host_pov>:/tmp/<pov_name> \
     -v <host_build_out>:/out \
     gcr.io/oss-fuzz-base/base-runner-debug \
     gdb -batch -x /tmp/debug_script.gdb \
         --args /out/<project_name>/<harness_name> \
                /tmp/<pov_name>
   ↓
   [GDB executes in container]
   ↓
   [Debug output captured]

Step 8: Cleanup
───────────────
   [Script file NOT deleted] ✓
   [Relies on OS cleanup]
```

## Key Differences

### File Handling
| Aspect | Fuzzer Bot | Debug Subagent | Debug Subagent Task |
|--------|-----------|----------------|---------------------|
| **Docker Required** | ❌ No | ✅ Yes | ✅ Yes |
| **File Mounting** | N/A | ✅ Files + Dir | ✅ Files + Dir |
| **Path Resolution** | N/A | ✅ Yes | ✅ Yes (now fixed) |
| **File Flush** | N/A | ✅ Yes | ✅ Yes (now fixed) |
| **File Verification** | N/A | ✅ Yes | ✅ Yes (now fixed) |
| **Cleanup Strategy** | N/A | ⚠️ OS cleanup | ⚠️ OS cleanup (now fixed) |

### Binary Path Construction
| Component | Fuzzer Bot | Debug Subagent |
|-----------|-----------|----------------|
| **Host Path** | `build_dir / harness_name` | `build_dir / harness_name` |
| **Container Path** | N/A | `/out/<project_name>/<harness_name>` |
| **Mount Strategy** | N/A | Mount `build_dir.parent` → `/out` |

## Path Structure Comparison

```
HOST FILESYSTEM STRUCTURE:
──────────────────────────
.../build/out/
  └── <project_name>/
      └── <harness_name>  ← Binary location

DOCKER CONTAINER STRUCTURE:
───────────────────────────
/out/
  └── <project_name>/
      └── <harness_name>  ← Binary location (mounted from host)

/tmp/
  ├── debug_script.gdb    ← GDB script (mounted from host)
  └── <pov_name>         ← PoV input (mounted from host)
```

## Mount Mapping

```
Host → Container
────────────────
.../build/out                    → /out
.../build/out/<project_name>     → /out/<project_name>
.../build/out/<project_name>/<binary> → /out/<project_name>/<binary>

/tmp/tmpXXXXXX.gdb               → /tmp/debug_script.gdb
<path_to_pov>/pov.bin            → /tmp/pov.bin
```

## Issues Fixed

1. ✅ **Added `flush()`** to `debug_subagent_task.py` - ensures file is written before Docker access
2. ✅ **Added path resolution** to `debug_subagent_task.py` - handles relative paths and symlinks
3. ✅ **Fixed file cleanup** - removed immediate deletion, matches `debug_subagent.py` behavior
4. ✅ **Added file verification** - checks file exists and is a file before mounting

