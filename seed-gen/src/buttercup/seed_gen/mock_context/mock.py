from buttercup.seed_gen.utils import resolve_module_subpath

LIBPNG_HARNESS_PATH = resolve_module_subpath("mock_context/libpng-exemplar/libpng_read_fuzzer.cc")

LIBPNG_FUNCTION_PATH_png_handle_tRNS = resolve_module_subpath(
    "mock_context/libpng-exemplar/function_png_handle_tRNS.c"
)


def get_harness(challenge: str) -> str:
    if challenge == "libpng":
        return LIBPNG_HARNESS_PATH.read_text()
    raise ValueError(f"Unknown challenge: {challenge}")


def get_additional_context(challenge: str) -> str:
    if challenge == "libpng":
        return ""
    raise ValueError(f"Unknown challenge: {challenge}")


def get_function_def(function_name: str) -> str:
    if function_name == "png_handle_tRNS":
        return LIBPNG_FUNCTION_PATH_png_handle_tRNS.read_text()
    raise ValueError(f"Unknown function: {function_name}")
