ROOT_DIR := $(shell dirname $(realpath $(firstword $(MAKEFILE_LIST))))

HOST_CRS_SCRATCH = $(ROOT_DIR)/crs_scratch
OSS_FUZZ_DIR = $(HOST_CRS_SCRATCH)/oss-fuzz

local-volumes:
	mkdir -p $(HOST_CRS_SCRATCH)

oss-fuzz:
	test -d $(OSS_FUZZ_DIR) || git clone https://github.com/google/oss-fuzz.git $(OSS_FUZZ_DIR)

up: local-volumes oss-fuzz
	docker compose up -d $(services)

demo: local-volumes oss-fuzz
	TARGET_PACKAGE=nginx docker compose up -d $(services)

down:
	docker compose down --remove-orphans
