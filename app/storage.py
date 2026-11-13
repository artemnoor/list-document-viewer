from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.contracts import validate_result_contract
from app.engine import canonical_fingerprint, run_verification
from app.explanations import ReviewExplanationProvider
from app.models import (
    VerificationHistory,
    VerificationRequest,
    VerificationResult,
    VerificationStatus,
    VerificationSummary,
)


class RunNotFound(KeyError):
    pass


class SQLiteVerificationStore:
    """Small durable run store; identical requests are idempotent by input hash."""

    def __init__(self, path: str | Path, explanation_provider: ReviewExplanationProvider | None = None):
        self.path = str(path)
        self.explanation_provider = explanation_provider
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS verification_runs (
                verification_id TEXT PRIMARY KEY,
                input_fingerprint TEXT NOT NULL UNIQUE,
                project_id TEXT NOT NULL,
                calculation_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                overall_status TEXT NOT NULL,
                result_json TEXT NOT NULL
            )"""
        )
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_verification_project_created ON verification_runs(project_id, created_at DESC)")

    @staticmethod
    def _deserialize_result(serialized: str) -> VerificationResult:
        """Read current results and add an explicit marker to pre-metadata records."""
        data = json.loads(serialized)
        if "input_metadata" not in data:
            data["input_metadata"] = {
                "available": False,
                "reason": "legacy_record_predates_input_metadata",
            }
        return VerificationResult.model_validate(data)

    def create(self, request: VerificationRequest) -> VerificationResult:
        fingerprint = canonical_fingerprint(request)
        verification_id = f"ver_{fingerprint[:24]}"
        existing_result: str | None = None
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT result_json FROM verification_runs WHERE input_fingerprint = ?",
                    (fingerprint,),
                ).fetchone()
                if row:
                    existing_result = row["result_json"]
                    self._db.execute("COMMIT")
                else:
                    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    result = run_verification(request, verification_id, created_at, fingerprint, self.explanation_provider)
                    validate_result_contract(result)
                    serialized = result.model_dump_json(exclude_none=False)
                    self._db.execute(
                        "INSERT INTO verification_runs VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            result.verification_id,
                            fingerprint,
                            result.project_id,
                            result.calculation_id,
                            result.created_at,
                            result.overall_status.value,
                            serialized,
                        ),
                    )
                    self._db.execute("COMMIT")
                    return result
            except Exception:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        assert existing_result is not None
        return self._deserialize_result(existing_result)

    def get(self, verification_id: str) -> VerificationResult:
        with self._lock:
            row = self._db.execute(
                "SELECT result_json FROM verification_runs WHERE verification_id = ?", (verification_id,)
            ).fetchone()
        if not row:
            raise RunNotFound(verification_id)
        return self._deserialize_result(row["result_json"])

    def history(
        self, project_id: str | None = None, limit: int = 50, offset: int = 0
    ) -> VerificationHistory:
        with self._lock:
            if project_id:
                rows = self._db.execute(
                    "SELECT * FROM verification_runs WHERE project_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (project_id, limit, offset),
                ).fetchall()
            else:
                rows = self._db.execute(
                    "SELECT * FROM verification_runs ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
        items = [
            VerificationSummary(
                verification_id=row["verification_id"],
                project_id=row["project_id"],
                calculation_id=row["calculation_id"],
                created_at=row["created_at"],
                overall_status=VerificationStatus(row["overall_status"]),
                indicator_count=len(json.loads(row["result_json"])["indicators"]),
                status_counts=json.loads(row["result_json"])["summary"],
            )
            for row in rows
        ]
        return VerificationHistory(items=items, limit=limit, offset=offset)

    def close(self) -> None:
        with self._lock:
            self._db.close()
