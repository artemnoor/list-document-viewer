"""Run the supplied case through public APIs, excluding answer keys from model input."""
import argparse
import json
import mimetypes
from pathlib import Path
import time

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, help="Extracted dataset directory; required for a new project")
    parser.add_argument("--project-id", help="Observe an existing project without starting it again")
    parser.add_argument("--base-url", default="http://127.0.0.1:8084")
    parser.add_argument("--classification", choices=["confidential", "public", "synthetic", "anonymized"], default="confidential")
    parser.add_argument("--report-row")
    parser.add_argument("--period-start")
    parser.add_argument("--period-end")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--output", type=Path, default=Path("case19-result.json"))
    args = parser.parse_args()
    if not args.project_id and (not args.dataset or not args.dataset.is_dir()):
        parser.error("--dataset must point to the extracted dataset directory")
    with httpx.Client(base_url=args.base_url, timeout=300) as client:
        def request(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        project_id = args.project_id
        if not project_id:
            # Only numbered source documents; README and answer workbook never enter the project.
            sources = sorted(p for p in args.dataset.iterdir() if p.is_file() and p.name[:2].isdigit() and p.name[:2] != "00")
            reports = [p for p in sources if p.name.startswith("01_")]
            primary = [p for p in sources if p not in reports]
            if len(reports) != 1 or not primary:
                parser.error("Expected one 01_ report and numbered supporting documents")
            project_id = request("POST", "/api/projects", json={"name": "Case 19 — full dataset", "data_classification": args.classification, "allow_external_llm": True, "verification_scope": {"report_row": args.report_row, "period_start": args.period_start, "period_end": args.period_end}})["id"]
            print("Project:", project_id, flush=True)
            for role, files in (("kfz", reports), ("primary", primary)):
                request("POST", f"/api/projects/{project_id}/documents", data={"role": role}, files=[("files", (p.name, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "application/octet-stream")) for p in files])
            request("POST", f"/api/projects/{project_id}/process")

        deadline = time.monotonic() + args.timeout
        previous = None
        while time.monotonic() < deadline:
            try:
                project = request("GET", f"/api/projects/{project_id}")
            except httpx.TransportError:
                time.sleep(2)
                continue
            state = (project["status"], [(key, value.get("status"), value.get("completed"), value.get("current_file")) for key, value in project["stages"].items()])
            if state != previous:
                print(state, flush=True)
                previous = state
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
            if project["status"] not in {"running", "draft"}:
                print("Result:", project["status"], project.get("last_error"), flush=True)
                # Completion alone does not prove agreement with the independently held answer key.
                return 0 if project["status"] == "completed" else 2
            time.sleep(5)
        raise TimeoutError(f"Project {project_id} did not finish within {args.timeout}s")


if __name__ == "__main__":
    raise SystemExit(main())
