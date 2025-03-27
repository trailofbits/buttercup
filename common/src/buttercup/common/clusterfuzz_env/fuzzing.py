"""Fuzzing module."""

PUBLIC_ENGINES = (
    'libFuzzer',
    'afl',
    'honggfuzz',
    'googlefuzztest',
    'centipede',
)

PRIVATE_ENGINES = ('syzkaller',)

ENGINES = PUBLIC_ENGINES + PRIVATE_ENGINES
