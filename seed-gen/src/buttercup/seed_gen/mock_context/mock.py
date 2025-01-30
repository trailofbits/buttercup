from buttercup.seed_gen.utils import resolve_module_subpath

LIBPNG_HARNESS_PATH = resolve_module_subpath("mock_context/libpng-exemplar/libpng_read_fuzzer.cc")
LIBPNG_DIFF_PATH = resolve_module_subpath(
    "mock_context/libpng-exemplar/2c894c66108f0724331a9e5b4826e351bf2d094b.diff"
)


def get_harness(challenge: str) -> str:
    if challenge == "libpng":
        return LIBPNG_HARNESS_PATH.read_text()
    raise ValueError(f"Unknown challenge: {challenge}")


def get_additional_context(challenge: str) -> str:
    if challenge == "libpng":
        return ""
    raise ValueError(f"Unknown challenge: {challenge}")


def get_diff(challenge: str) -> str:
    if challenge == "libpng":
        return LIBPNG_DIFF_PATH.read_text()
    raise ValueError(f"Unknown challenge: {challenge}")
