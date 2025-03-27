# Clusterfuzz commit 46968a275474422db32530a2126dfa30dc7f3d15

import os
import re
import stat
import tempfile
import logging 
from buttercup.common.clusterfuzz_parser import utils
from buttercup.common.clusterfuzz_env import environment

logs = logging.getLogger(__name__)

EXTRA_BUILD_DIR = '__extra_build'

ALLOWED_FUZZ_TARGET_EXTENSIONS = ['', '.exe', '.par']
FUZZ_TARGET_SEARCH_BYTES = b'LLVMFuzzerTestOneInput'
VALID_TARGET_NAME_REGEX = re.compile(r'^[a-zA-Z0-9@_.-]+$')
BLOCKLISTED_TARGET_NAME_REGEX = re.compile(r'^(jazzer_driver.*)$')
EXTRA_BUILD_DIR = '__extra_build'



def is_fuzz_target_local(file_path, file_handle=None):
  """Returns whether |file_path| is a fuzz target binary (local path)."""
  # TODO(hzawawy): Handle syzkaller case.
  if '@' in file_path:
    # GFT targets often have periods in the name that get misinterpreted as an
    # extension.
    filename = os.path.basename(file_path)
    file_extension = ''
  else:
    filename, file_extension = os.path.splitext(os.path.basename(file_path))

  if not VALID_TARGET_NAME_REGEX.match(filename):
    # Check fuzz target has a valid name (without any special chars).
    return False

  if BLOCKLISTED_TARGET_NAME_REGEX.match(filename):
    # Check fuzz target an explicitly disallowed name (e.g. binaries used for
    # jazzer-based targets).
    return False

  if file_extension not in ALLOWED_FUZZ_TARGET_EXTENSIONS:
    # Ignore files with disallowed extensions (to prevent opening e.g. .zips).
    return False

  if not file_handle and not os.path.exists(file_path):
    # Ignore non-existent files for cases when we don't have a file handle.
    return False

  if filename.endswith('_fuzzer'):
    return True

  # TODO(aarya): Remove this optimization if it does not show up significant
  # savings in profiling results.
  fuzz_target_name_regex = environment.get_value('FUZZER_NAME_REGEX')
  if fuzz_target_name_regex:
    return bool(re.match(fuzz_target_name_regex, filename))

  if os.path.exists(file_path) and not stat.S_ISREG(os.stat(file_path).st_mode):
    # Don't read special files (eg: /dev/urandom).
    logs.warn('Tried to read from non-regular file: %s.' % file_path)
    return False

  # Use already provided file handle or open the file.
  local_file_handle = file_handle or open(file_path, 'rb')

  # TODO(metzman): Bound this call so we don't read forever if something went
  # wrong.
  result = utils.search_bytes_in_file(FUZZ_TARGET_SEARCH_BYTES,
                                      local_file_handle)

  if not file_handle:
    # If this local file handle is owned by our function, close it now.
    # Otherwise, it is caller's responsibility.
    local_file_handle.close()

  return result



def walk(directory, **kwargs):
  """Wrapper around walk to resolve compatibility issues."""
  return os.walk(directory, **kwargs)


def get_fuzz_targets(path):
  """Get list of fuzz targets paths (local)."""
  fuzz_target_paths = []

  for root, _, files in walk(path):
    for filename in files:
      if os.path.basename(root) == EXTRA_BUILD_DIR:
        # Ignore extra binaries.
        continue

      file_path = os.path.join(root, filename)
      if is_fuzz_target_local(file_path):
        fuzz_target_paths.append(file_path)

  return fuzz_target_paths
