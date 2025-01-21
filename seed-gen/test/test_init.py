"""Initial testing module."""

import seed_gen


def test_version() -> None:
    version = getattr(seed_gen, "__version__", None)
    assert version is not None
    assert isinstance(version, str)
