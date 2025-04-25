"""Varint encoder/decoder
varint from https://github.com/fmoo/python-varint/blob/master/varint.py
"""

from io import BytesIO


import sys

if sys.version > "3":

    def _byte(b: int) -> bytes:
        return bytes((b,))
else:

    def _byte(b: int) -> str:  # type: ignore[misc]
        return chr(b)


def encode(number: int) -> bytes:
    """Pack `number` into varint bytes"""
    buf = b""
    while True:
        towrite = number & 0x7F
        number >>= 7
        if number:
            buf += _byte(towrite | 0x80)
        else:
            buf += _byte(towrite)
            break
    return buf


def decode_stream(stream: BytesIO) -> int:
    """Read a varint from `stream`"""
    shift = 0
    result = 0
    while True:
        i = _read_one(stream)
        result |= (i & 0x7F) << shift
        shift += 7
        if not (i & 0x80):
            break

    return result


def decode_bytes(buf: bytes) -> int:
    """Read a varint from from `buf` bytes"""
    return decode_stream(BytesIO(buf))


def _read_one(stream: BytesIO) -> int:
    """Read a byte from the file (as an integer)

    raises EOFError if the stream ends while reading bytes.
    """
    c = stream.read(1)
    if c == b"":
        raise EOFError("Unexpected EOF while reading bytes")
    return ord(c)
