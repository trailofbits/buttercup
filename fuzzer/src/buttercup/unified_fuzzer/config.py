"""Configuration for the unified fuzzer service."""

from typing import Annotated

from pydantic import Field
from pydantic_settings import BaseSettings


class UnifiedFuzzerConfig(BaseSettings):
    """Unified configuration for all fuzzer components."""
    
    class Config:
        cli_parse_args = True
        nested_model_default_partial_update = True
        env_nested_delimiter = "__"
        extra = "allow"
        env_prefix = "BUTTERCUP_UNIFIED_FUZZER_"
    
    # Common settings
    redis_url: Annotated[str, Field(default="redis://127.0.0.1:6379")]
    log_level: Annotated[str, Field(default="INFO")]
    log_max_line_length: Annotated[int | None, Field(default=None)]
    
    # Worker configuration
    num_fuzzer_workers: Annotated[int, Field(default=2)]
    
    # Builder settings
    builder_wdir: Annotated[str, Field(default="/tmp/builder")]
    builder_python: Annotated[str, Field(default="python")]
    builder_timer: Annotated[int, Field(default=1000)]
    builder_allow_pull: Annotated[bool, Field(default=True)]
    builder_allow_caching: Annotated[bool, Field(default=False)]
    builder_max_tries: Annotated[int, Field(default=3)]
    
    # Fuzzer settings
    fuzzer_wdir: Annotated[str, Field(default="/tmp/fuzzer")]
    fuzzer_python: Annotated[str, Field(default="python")]
    fuzzer_timer: Annotated[int, Field(default=1000)]
    fuzzer_timeout: Annotated[int, Field(default=1000)]
    fuzzer_crs_scratch_dir: Annotated[str, Field(default="/crs_scratch")]
    fuzzer_crash_dir_count_limit: Annotated[int, Field(default=0)]
    fuzzer_max_local_files: Annotated[int, Field(default=500)]
    fuzzer_max_pov_size: Annotated[int, Field(default=2 * 1024 * 1024)]  # 2 MiB
    
    # Coverage settings
    coverage_wdir: Annotated[str, Field(default="/tmp/coverage")]
    coverage_python: Annotated[str, Field(default="python")]
    coverage_timer: Annotated[int, Field(default=1000)]
    coverage_allow_pull: Annotated[bool, Field(default=True)]
    coverage_base_image_url: Annotated[str, Field(default="local/oss-fuzz")]
    coverage_llvm_cov_tool: Annotated[str, Field(default="llvm-cov")]
    coverage_sample_size: Annotated[int, Field(default=0)]
    
    # Tracer settings
    tracer_wdir: Annotated[str, Field(default="/tmp/tracer")]
    tracer_python: Annotated[str, Field(default="python")]
    tracer_timer: Annotated[int, Field(default=1000)]
    tracer_max_tries: Annotated[int, Field(default=3)]
    
    def to_dict(self) -> dict:
        """Convert configuration to dictionary organized by component."""
        return {
            'builder': {
                'wdir': self.builder_wdir,
                'python': self.builder_python,
                'timer': self.builder_timer,
                'allow_pull': self.builder_allow_pull,
                'allow_caching': self.builder_allow_caching,
                'max_tries': self.builder_max_tries,
            },
            'fuzzer': {
                'wdir': self.fuzzer_wdir,
                'python': self.fuzzer_python,
                'timer': self.fuzzer_timer,
                'timeout': self.fuzzer_timeout,
                'crs_scratch_dir': self.fuzzer_crs_scratch_dir,
                'crash_dir_count_limit': self.fuzzer_crash_dir_count_limit,
                'max_local_files': self.fuzzer_max_local_files,
                'max_pov_size': self.fuzzer_max_pov_size,
            },
            'coverage': {
                'wdir': self.coverage_wdir,
                'python': self.coverage_python,
                'timer': self.coverage_timer,
                'allow_pull': self.coverage_allow_pull,
                'base_image_url': self.coverage_base_image_url,
                'llvm_cov_tool': self.coverage_llvm_cov_tool,
                'sample_size': self.coverage_sample_size,
            },
            'tracer': {
                'wdir': self.tracer_wdir,
                'python': self.tracer_python,
                'timer': self.tracer_timer,
                'max_tries': self.tracer_max_tries,
            },
            'num_fuzzer_workers': self.num_fuzzer_workers,
        }