"""Static disclosure inventory; never infers identities or changes evidence."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

from pastor_transcript_extractor.evaluation_storage import (
    generated_relative_path,
    private_evidence_relative_path,
)


SIGNALS = {
    "local_user_path": re.compile(r"/Users/[^/\s]+/|/home/[^/\s]+/|[A-Z]:\\\\Users\\\\"),
    "named_person_cue": re.compile(r"\b(?:Brother|Sister|Pastor|Dr\.)\s+[A-Z][a-z]+"),
    "source_text_field": re.compile(r'"(?:target_text|leading_context|trailing_context|source_context|transcript|excerpt)"\s*:'),
    "source_identifier": re.compile(r'"(?:youtube_video_id|classification_path)"\s*:|https?://(?:www\.)?(?:youtube\.com|youtu\.be)/'),
}


def audit_repository(repo_root: Path) -> dict:
    """Inspect tracked review/document files, with no excerpts in the report.

    Signals are candidates for review, not an anonymization guarantee. Runtime
    caches and the application database are never opened by this audit.
    """
    repo_root = repo_root.resolve()
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z"],
        check=True, capture_output=True,
    )
    records = []
    inspected = 0
    for name in sorted(result.stdout.decode().split("\0")):
        if not name or Path(name).suffix.lower() not in {".json", ".md", ".csv", ".tsv", ".jsonl"}:
            continue
        path = repo_root / name
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(repo_root):
            continue
        inspected += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        signals = {key: len(pattern.findall(text)) for key, pattern in SIGNALS.items()}
        signals = {key: count for key, count in signals.items() if count}
        private = private_evidence_relative_path(name, repo_root=repo_root) is not None
        generated = generated_relative_path(name, repo_root=repo_root) is not None
        if signals or generated:
            records.append({
                "path": name, "byte_size": path.stat().st_size, "signals": signals,
                "action": "migrate" if generated else "review_retained_source",
                "private_review_evidence": private,
            })
    return {
        "schema_version": 1,
        "status": "STATIC_REVIEW_ONLY",
        "provider_requests": 0,
        "inspected_tracked_files": inspected,
        "migrate_files": sum(r["action"] == "migrate" for r in records),
        "migrate_bytes": sum(r["byte_size"] for r in records if r["action"] == "migrate"),
        "retained_review_candidates": sum(r["action"] == "review_retained_source" for r in records),
        "limitations": [
            "Pattern cues are not exhaustive person-name detection or a privacy clearance.",
            "This audits current tracked working files, not Git index contents or history.",
            "Migration and ignore rules do not remove previously tracked Git blobs.",
            "Retained source candidates include legitimate fixtures, contracts and author attribution; do not delete automatically.",
        ],
        "records": records,
    }


def write_repository_audit(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = ["# Repository evidence storage audit", "",
             f"Static inspection: {report['inspected_tracked_files']} tracked files; provider requests: 0.", "",
             f"Migrate: {report['migrate_files']} files ({report['migrate_bytes']} bytes). "
             f"Retained source candidates: {report['retained_review_candidates']}.", "",
             "## Limits", "", *[f"- {limit}" for limit in report["limitations"]], "",
             "## File inventory", "", "| Action | Path | Bytes | Signals |", "| --- | --- | ---: | --- |"]
    for record in report["records"]:
        signals = ", ".join(f"{key}={count}" for key, count in record["signals"].items())
        lines.append(f"| {record['action']} | {record['path']} | {record['byte_size']} | {signals} |")
    path.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
