# Clusterfuzz commit 46968a275474422db32530a2126dfa30dc7f3d15

def search_bytes_in_file(search_bytes, file_handle):
  """Helper to search for bytes in a large binary file without memory
  issues.
  """
  # TODO(aarya): This is too brittle and will fail if we have a very large
  # line.
  for line in file_handle:
    if search_bytes in line:
      return True

  return False


def strip_from_left(string, prefix):
  """Strip a prefix from start from string."""
  if not string.startswith(prefix):
    return string
  return string[len(prefix):]


def strip_from_right(string, suffix):
  """Strip a suffix from end of string."""
  if not string.endswith(suffix):
    return string
  return string[:len(string) - len(suffix)]


def sub_string_exists_in(substring_list, string):
  """Return true if one of the substring in the list is found in |string|."""
  for substring in substring_list:
    if substring in string:
      return True

  return False
