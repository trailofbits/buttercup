# Fuzzer Runner

A libfuzzer-based fuzzer runner that can be used as a command-line tool.
It is useful to separate the clusterfuzz dependency (and its older indirect dependencies like protobuf==3.20) from the rest of the system.

## Features

- Run fuzzers with various engines and sanitizers
- Merge corpus files
