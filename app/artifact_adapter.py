from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any


class ArtifactStoreError(ValueError):
    """Safe public error for unavailable or invalid immutable artifacts."""


class FileArtifactAdapter:
    """Resolve project-scoped, content-addressed JSON files with a bounded cache.

    Layout: ``<root>/<sha256(project_id)>/<sha256>.json``. The caller-provided
    artifact ID is an opaque logical identifier and is never used as a path.
    Files must be provisioned by a trusted artifact service before verification.
    """

    def __init__(self, root: str | Path, *, max_artifact_bytes: int, cache_bytes: int):
        self.root = Path(root).expanduser().resolve()
        self.max_artifact_bytes = max_artifact_bytes
        self.cache_bytes = cache_bytes
        self._cache: OrderedDict[tuple[str, str, str], tuple[dict[str, Any], int]] = OrderedDict()
        self._cache_size = 0
        self._lock = threading.RLock()

    @staticmethod
    def _project_key(project_id: str) -> str:
        return hashlib.sha256(project_id.encode("utf-8")).hexdigest()

    def _path(self, project_id: str, sha256: str) -> Path:
        project_root = (self.root / self._project_key(project_id)).resolve()
        path = (project_root / f"{sha256}.json").resolve()
        if project_root.parent != self.root or path.parent != project_root:
            raise ArtifactStoreError("Artifact is unavailable")
        return path

    def resolve(self, project_id: str, artifact_id: str, sha256: str) -> dict[str, Any]:
        key = (project_id, artifact_id, sha256)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return json.loads(json.dumps(cached[0]))

        path = self._path(project_id, sha256)
        digest = hashlib.sha256()
        chunks: list[bytes] = []
        size = 0
        try:
            with path.open("rb") as stream:
                while True:
                    chunk = stream.read(min(1024 * 1024, self.max_artifact_bytes + 1 - size))
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > self.max_artifact_bytes:
                        raise ArtifactStoreError("Artifact exceeds the configured size limit")
                    digest.update(chunk)
                    chunks.append(chunk)
        except FileNotFoundError as exc:
            raise ArtifactStoreError("Artifact is unavailable") from exc
        except OSError as exc:
            raise ArtifactStoreError("Artifact is unavailable") from exc
        if digest.hexdigest() != sha256:
            raise ArtifactStoreError("Artifact integrity check failed")
        try:
            value = json.loads(b"".join(chunks))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArtifactStoreError("Artifact is not valid JSON") from exc
        if not isinstance(value, dict):
            raise ArtifactStoreError("Artifact must contain a JSON object")

        if size <= self.cache_bytes:
            with self._lock:
                existing = self._cache.pop(key, None)
                if existing is not None:
                    self._cache_size -= existing[1]
                while self._cache and self._cache_size + size > self.cache_bytes:
                    _, (_, removed_size) = self._cache.popitem(last=False)
                    self._cache_size -= removed_size
                self._cache[key] = (value, size)
                self._cache_size += size
        return json.loads(json.dumps(value))
