#!/bin/bash -x
#
# Run buttercup-task-downloader on all challenges in a given directory.
# Expected directory structure:
# <input_dir>/
#   <challenge_name>-delta-1/
#     <src-name>.tar.gz
#     oss-fuzz.tar.gz
#     diff-<shasum>.tar.gz
#
# See for example aixcc-challenge repository artifacts.
#

# Check if directory argument is provided
if [ $# -ne 1 ]; then
    echo "Usage: $0 <directory>"
    exit 1
fi

input_dir="$1"
# Convert to absolute path
input_dir=$(realpath "$input_dir")

# Find all directories ending with -delta-1
find "$input_dir" -type d -name "*-delta-1" | while read -r dir; do
    # Get absolute path of the directory
    full_path=$(realpath "$dir")
    
    # Extract the base name of the directory
    dir_name=$(basename "$dir")
    
    echo "Processing directory: $dir_name"
    
    # Find the source tarball
    src_tar=$(find "$full_path" -name "*.tar.gz" -not -name "oss-fuzz.tar.gz" -not -name "diff-*.tar.gz")
    fuzz_tar="$full_path/oss-fuzz.tar.gz"
    diff_tar=$(find "$full_path" -name "diff-*.tar.gz")

    # this could be not always true, but it's a good guess
    project_name=$(echo "$dir_name" | cut -d '-' -f 1)
    # Look at the first dir inside the src_tar to guess the focus
    focus=$(tar -tf "$src_tar" | head -n 1)
    # remove any trailing slashes
    focus=$(echo "$focus" | sed 's:/*$::')
    
    if [ -z "$src_tar" ] || [ ! -f "$fuzz_tar" ] || [ -z "$diff_tar" ]; then
        echo "Error: Missing required files in $dir_name"
        continue
    fi
    
    # Convert to file:// URLs
    src_url="file://$src_tar"
    fuzz_url="file://$fuzz_tar"
    diff_url="file://$diff_tar"
    
    echo "Running buttercup-task-downloader for $dir_name"
    uv run buttercup-task-downloader --download_dir ../tasks_storage/ process \
        --task_type delta \
        --repo_url "$src_url" \
        --fuzz_tooling_url "$fuzz_url" \
        --diff_url "$diff_url" \
        --project_name "$project_name" \
        --focus "$focus" \
        $dir_name
done
