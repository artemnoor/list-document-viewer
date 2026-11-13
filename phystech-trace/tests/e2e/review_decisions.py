#!/usr/bin/env python3
"""Exercise confirm/reject through Gateway for a synthetic E2E project."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


TRACE_ROOT = Path(__file__).resolve().parents[2]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8084")
    parser.add_argument("--project-id", required=True)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    with httpx.Client(timeout=httpx.Timeout(30, connect=8)) as client:
        response = client.get(f"{base}/api/projects/{args.project_id}")
        require(response.status_code == 200, f"Gateway project read failed: HTTP {response.status_code}")
        project = response.json()
        links = (project.get("linking_result") or {}).get("links", [])
        reviewable = [link for link in links if link.get("verification_status") == "not_reviewed" and link.get("status") in {"proposed", "review"}]
        require(len(reviewable) >= 2, "Synthetic project needs at least two independently reviewable links")
        decisions: list[dict[str, Any]] = []

        for link, status in zip(reviewable[:2], ("confirmed", "rejected")):
            original_evidence = link.get("evidence", [])
            decision = client.patch(
                f"{base}/api/projects/{args.project_id}/links/{link['link_id']}",
                json={"status": status},
            )
            require(decision.status_code == 200, f"Gateway {status} decision failed: HTTP {decision.status_code} {decision.text[:500]}")
            updated = next((item for item in decision.json().get("linking_result", {}).get("links", []) if item.get("link_id") == link["link_id"]), None)
            require(updated is not None, f"Gateway response omitted decided link {link['link_id']}")
            expected_verification = "human_confirmed" if status == "confirmed" else "human_rejected"
            require(updated.get("status") == status and updated.get("verification_status") == expected_verification, f"Gateway did not persist {status} for {link['link_id']}")
            require(updated.get("evidence", []) == original_evidence, f"Human review changed evidence for {link['link_id']}")
            decisions.append({
                "link_id": link["link_id"], "relationship_type": link.get("relationship_type"),
                "status": status, "verification_status": expected_verification,
                "evidence_count": len(original_evidence),
            })

        persisted = client.get(f"{base}/api/projects/{args.project_id}")
        require(persisted.status_code == 200, f"Gateway reread failed: HTTP {persisted.status_code}")
        saved = {item.get("link_id"): item for item in (persisted.json().get("linking_result") or {}).get("links", [])}
        for decision in decisions:
            require(saved.get(decision["link_id"], {}).get("verification_status") == decision["verification_status"], "Human review decision was not durable")

    report = {
        "status": "review-api-passed", "project_id": args.project_id,
        "decisions": decisions,
        "checks": ["Gateway PATCH confirmed one reviewable link", "Gateway PATCH rejected one reviewable link", "Evidence remained unchanged and both decisions persisted on reread"],
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    results = TRACE_ROOT / "tests" / "e2e" / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "review-decisions.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest_path = results / "latest-run.json"
    if latest_path.exists():
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        if latest.get("project_id") == args.project_id:
            latest["human_review"] = {"status": report["status"], "decisions": decisions}
            latest.setdefault("checks", []).append("Confirm/reject decisions persisted through Gateway without changing evidence")
            latest_path.write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
