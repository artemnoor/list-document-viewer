"""Atomic file persistence for document metadata and processing caches."""
import json
import os
from pathlib import Path
import tempfile


def atomic_write_bytes(path, content):
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def atomic_write_json(path, value):
    atomic_write_bytes(path, json.dumps(value, ensure_ascii=False, default=str).encode('utf-8'))


def read_json(path):
    """Missing or interrupted caches are recoverable; callers decide whether to retry."""
    try:
        result = json.loads(Path(path).read_text(encoding='utf-8'))
        return result if isinstance(result, dict) else None
    except (OSError, UnicodeError, ValueError):
        return None
