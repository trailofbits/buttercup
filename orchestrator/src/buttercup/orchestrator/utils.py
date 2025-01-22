import hashlib
from pathlib import Path
import requests


def response_stream_to_file(session: requests.Session, url: str, filepath: Path | None = None) -> str:
    sha256_hash = hashlib.sha256()
    with session.get(url, stream=True) as response:
        response.raise_for_status()
        file_handle = open(filepath, "wb") if filepath else None
        try:
            for chunk in response.iter_content(chunk_size=8192):
                sha256_hash.update(chunk)
                if file_handle:
                    file_handle.write(chunk)
        finally:
            if file_handle:
                file_handle.close()

    return sha256_hash.hexdigest()
