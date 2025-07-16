#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright 2023 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""OSS-Fuzz helper script for building and running fuzzers."""

import os
import sys


def main():
    """Main entry point for helper script."""
    # Fake helper.py for local testing with CRS
    if len(sys.argv) > 1 and sys.argv[1] == "check_build":
        # Always report build does NOT exist to trigger building
        project = sys.argv[-1]
        fuzzer_path = f"/out/{project}_fuzzer"
        print(f"Build does not exist: {fuzzer_path}")
        return 1
    elif len(sys.argv) > 1 and sys.argv[1] == "build_image":
        print("Fake build_image - success")
        return 0
    elif len(sys.argv) > 1 and sys.argv[1] == "build_fuzzers":
        print("Fake build_fuzzers - creating fake fuzzer")
        # Create fake fuzzer that simulates crashes
        project = sys.argv[-1]
        os.makedirs("/out", exist_ok=True)
        
        # Create a simple fake fuzzer
        fuzzer_content = '''#!/bin/bash
# Fake fuzzer that simulates crashes
echo "Running fake fuzzer..."

# Read input
INPUT=$(cat)

# Check for crash triggers
if echo "$INPUT" | grep -q "CRASH"; then
    echo "==12345==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x602000000018"
    echo "SUMMARY: AddressSanitizer: heap-buffer-overflow /src/crashy.c:31:13 in process_data"
    exit 77
fi

if echo "$INPUT" | grep -q "DIV0"; then
    echo "==12345==ERROR: AddressSanitizer: FPE on unknown address"
    echo "SUMMARY: AddressSanitizer: FPE /src/crashy.c:42:28 in process_data"
    exit 77
fi

if echo "$INPUT" | grep -q "NULLPTR"; then
    echo "==12345==ERROR: AddressSanitizer: SEGV on unknown address"
    echo "SUMMARY: AddressSanitizer: SEGV /src/crashy.c:48:14 in process_data"
    exit 77
fi

echo "No crash found"
exit 0
'''
        fuzzer_path = f"/out/{project}_fuzzer"
        with open(fuzzer_path, 'w') as f:
            f.write(fuzzer_content)
        os.chmod(fuzzer_path, 0o755)
        
        # Create seed corpus with crash-triggering inputs
        corpus_dir = f"/out/{project}_fuzzer_seed_corpus"
        os.makedirs(corpus_dir, exist_ok=True)
        with open(f"{corpus_dir}/crash1", "w") as f:
            f.write("CRASH")
        with open(f"{corpus_dir}/crash2", "w") as f:
            f.write("DIV0")
        with open(f"{corpus_dir}/crash3", "w") as f:
            f.write("NULLPTR")
            
        print(f"Created fake fuzzer at {fuzzer_path}")
        return 0
    else:
        print(f"Fake helper.py called with: {sys.argv}")
        return 0


if __name__ == "__main__":
    result = main()
    sys.exit(result)