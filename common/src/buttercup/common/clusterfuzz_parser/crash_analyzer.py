# Default page size of 4KB.
NULL_DEREFERENCE_BOUNDARY = 0x1000

ASSERT_CRASH_ADDRESSES = [
    0x0000bbadbeef,
    0x0000fbadbeef,
    0x00001f75b7dd,
    0x0000977537dd,
    0x00009f7537dd,
]

def address_to_integer(address):
  """Attempt to convert an address from a string (hex) to an integer."""
  try:
    return int(address, 16)
  except:
    return 0
  

def is_null_dereference(int_address):
  """Check to see if this is a null dereference crash address."""
  return int_address < NULL_DEREFERENCE_BOUNDARY


def is_assert_crash_address(int_address):
  """Check to see if this is an ASSERT crash based on the address."""
  return int_address in ASSERT_CRASH_ADDRESSES