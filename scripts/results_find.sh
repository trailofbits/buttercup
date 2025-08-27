#!/bin/bash

if [ "$#" -ne 1 ]; then
    echo "usage: $0 <keyword>"
    exit 1
fi

find tasks_storage -name "task_meta.json" -exec grep -rIil "$1" {} \; | cut -d '/' -f 1-2 | sort -u