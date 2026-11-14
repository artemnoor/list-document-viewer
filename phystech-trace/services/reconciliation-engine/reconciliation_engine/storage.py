import json
import hashlib
import os
import threading
from pathlib import Path
from typing import Any


class ResultStore:
    """Local durable JSON result store; suitable for a single service instance."""

    def __init__(self, directory: str):
        self.directory = Path(directory)
        self._lock = threading.RLock()

    def _project_directory(self, project_id: str) -> Path:
        if project_id == "local":
            return self.directory
        project_key = hashlib.sha256(project_id.encode("utf-8")).hexdigest()
        return self.directory / project_key

    def save(self, result: dict[str, Any], project_id: str = "local") -> None:
        result_id = result["reconciliation_id"]
        if not result_id.isalnum():
            raise ValueError("Invalid reconciliation ID")
        payload = json.dumps(result, ensure_ascii=False, indent=2)
        with self._lock:
            directory = self._project_directory(project_id)
            directory.mkdir(parents=True, exist_ok=True)
            destination = directory / f"{result_id}.json"
            temporary = directory / f".{result_id}.tmp"
            temporary.write_text(payload, encoding="utf-8")
            os.replace(temporary, destination)

    def get(self, result_id: str, project_id: str = "local") -> dict[str, Any] | None:
        if not result_id.isalnum():
            return None
        path = self._project_directory(project_id) / f"{result_id}.json"
        with self._lock:
            if not path.is_file():
                return None
            return json.loads(path.read_text(encoding="utf-8"))

