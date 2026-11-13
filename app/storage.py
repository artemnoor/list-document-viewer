from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
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
    VerificationCompleteness,
    VerificationConclusion,
)


class RunNotFound(KeyError):
    pass


class SQLiteVerificationStore:
    """Small durable run store; identical requests are idempotent by input hash."""

    def __init__(self, path: str | Path, explanation_provider: ReviewExplanationProvider | None = None):
        self.path = str(path)
        self.explanation_provider = explanation_provider
        self.max_processing_seconds = max(1.0, float(os.getenv("VERIFICATION_MAX_PROCESSING_SECONDS", "30")))
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA busy_timeout = 5000")
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
        """Adapt historical rows without presenting unvalidated statuses as proof."""
        data = json.loads(serialized)
        if data.get("schema_version") in {"1.0.0", "1.1.0"}:
            original_overall = data.get("overall_status", "needs_review")
            statuses: list[str] = []
            for indicator in data.get("indicators", []):
                historic = indicator.get("status", "needs_review")
                indicator["legacy_status"] = historic
                if historic in {VerificationStatus.MATCHED.value, VerificationStatus.MISMATCH.value}:
                    indicator["status"] = VerificationStatus.NEEDS_REVIEW.value
                    indicator.setdefault("diagnostics", []).append({
                        "code": "legacy_result_unverified",
                        "message": "Historical result predates independent calculation and evidence integrity checks.",
                    })
                indicator["trust"] = {
                    "technical_validity": "not_checked",
                    "automatic_link_confirmation": "unconfirmed",
                    "human_confirmation": "unconfirmed",
                    "calculation_trust": "unproven",
                }
                statuses.append(indicator["status"])
            counts = {status.value: statuses.count(status.value) for status in VerificationStatus}
            total = len(statuses)
            not_applicable = counts[VerificationStatus.NOT_APPLICABLE.value]
            unresolved = total - counts[VerificationStatus.MATCHED.value] - counts[VerificationStatus.MISMATCH.value] - not_applicable
            migrated_overall = VerificationStatus.NEEDS_REVIEW.value if original_overall in {"matched", "mismatch"} else original_overall
            data["schema_version"] = "1.2.0"
            data["integrity_status"] = "legacy_unverified"
            data["legacy_overall_status"] = original_overall
            data["overall_status"] = migrated_overall
            data["summary"] = counts
            data["completeness"] = VerificationCompleteness(
                total_indicators=total,
                applicable_indicators=total - not_applicable,
                verified_indicators=0,
                matched_indicators=0,
                mismatched_indicators=0,
                not_applicable_indicators=not_applicable,
                unresolved_indicators=unresolved,
                complete=False,
            ).model_dump(mode="json")
            data["conclusion"] = VerificationConclusion(
                overall_status=migrated_overall,
                has_proven_mismatch=False,
                coverage_complete=False,
                mismatch_count=0,
                unresolved_count=unresolved,
                not_applicable_count=not_applicable,
            ).model_dump(mode="json")
            data.setdefault("diagnostics", []).append({
                "code": "legacy_result_unverified",
                "message": "This stored result was adapted to Verification 1.2.0 but was not re-run through the current validators.",
            })
        if "input_metadata" not in data:
            data["input_metadata"] = {
                "available": False,
                "reason": "legacy_record_predates_input_metadata",
            }
        return VerificationResult.model_validate(data)

    def create(self, request: VerificationRequest) -> VerificationResult:
        fingerprint = canonical_fingerprint(request)
        verification_id = f"ver_{fingerprint[:24]}"
        with self._lock:
            row = self._db.execute(
                "SELECT result_json FROM verification_runs WHERE input_fingerprint = ?",
                (fingerprint,),
            ).fetchone()
        if row:
            return self._deserialize_result(row["result_json"])

        # Deterministic processing and optional Polza calls happen with no DB
        # lock or write transaction held. The unique fingerprint handles races.
        created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        result = run_verification(
            request,
            verification_id,
            created_at,
            fingerprint,
            self.explanation_provider,
            deadline=time.monotonic() + self.max_processing_seconds,
        )
        validate_result_contract(result)
        serialized = result.model_dump_json(exclude_none=False)

        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT result_json FROM verification_runs WHERE input_fingerprint = ?",
                    (fingerprint,),
                ).fetchone()
                if row:
                    self._db.execute("COMMIT")
                    return self._deserialize_result(row["result_json"])
                self._db.execute(
                    "INSERT INTO verification_runs VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(input_fingerprint) DO NOTHING",
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
                row = self._db.execute(
                    "SELECT result_json FROM verification_runs WHERE input_fingerprint = ?",
                    (fingerprint,),
                ).fetchone()
                self._db.execute("COMMIT")
            except Exception:
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
        assert row is not None
        return self._deserialize_result(row["result_json"])

    def get(self, verification_id: str) -> VerificationResult:
        with self._lock:
            row = self._db.execute(
                "SELECT result_json FROM verification_runs WHERE verification_id = ?", (verification_id,)
            ).fetchone()
        if not row:
            raise RunNotFound(verification_id)
        return self._deserialize_result(row["result_json"])

    def get_for_project(self, verification_id: str, project_id: str) -> VerificationResult:
        with self._lock:
            row = self._db.execute(
                "SELECT result_json FROM verification_runs WHERE verification_id = ? AND project_id = ?",
                (verification_id, project_id),
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
        items = []
        for row in rows:
            result = self._deserialize_result(row["result_json"])
            items.append(VerificationSummary(
                verification_id=result.verification_id,
                project_id=result.project_id,
                calculation_id=result.calculation_id,
                created_at=result.created_at,
                overall_status=result.overall_status,
                indicator_count=len(result.indicators),
                status_counts=result.summary,
            ))
        return VerificationHistory(items=items, limit=limit, offset=offset)

    def close(self) -> None:
        with self._lock:
            self._db.close()
