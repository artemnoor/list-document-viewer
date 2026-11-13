import json
import os
import threading
from pathlib import Path
from typing import Any


class ResultStore:
    """Local durable JSON result store; suitable for a single service instance."""

    def __init__(self, directory: str):
        self.directory = Path(directory)
        self._lock = threading.RLock()

    def save(self, result: dict[str, Any]) -> None:
        result_id = result["reconciliation_id"]
        if not result_id.isalnum():
            raise ValueError("Invalid reconciliation ID")
        payload = json.dumps(result, ensure_ascii=False, indent=2)
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            destination = self.directory / f"{result_id}.json"
            temporary = self.directory / f".{result_id}.tmp"
            temporary.write_text(payload, encoding="utf-8")
            os.replace(temporary, destination)

    def get(self, result_id: str) -> dict[str, Any] | None:
        if not result_id.isalnum():
            return None
        path = self.directory / f"{result_id}.json"
        with self._lock:
            if not path.is_file():
                return None
            return json.loads(path.read_text(encoding="utf-8"))

