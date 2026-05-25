from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


OUTPUT_DIR = Path("outputs")
SUMMARY_DIR = OUTPUT_DIR / "summaries"


def ensure_output_dirs() -> None:
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)


def safe_filename(repo_name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", repo_name).strip("-")
    return cleaned or "repository"


def repo_summary_path(repo_name: str) -> Path:
    return SUMMARY_DIR / f"{safe_filename(repo_name)}.md"


def write_repo_summary(repo_name: str, summary: str) -> Path:
    ensure_output_dirs()
    path = repo_summary_path(repo_name)
    path.write_text(summary.rstrip() + "\n", encoding="utf-8")
    return path


def write_repo_inventory(records: list[dict[str, Any]]) -> Path:
    ensure_output_dirs()
    path = OUTPUT_DIR / "repos.json"
    path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    return path


def write_baseline_index(summaries: list[dict[str, Any]]) -> Path:
    ensure_output_dirs()
    lines = ["# Baseline Repository Index", ""]

    if not summaries:
        lines.append("No repository summaries were generated.")
    else:
        for item in summaries:
            lines.append(f"- [{item['name']}]({item['path'].as_posix()}) - {item['url']}")

    path = OUTPUT_DIR / "baseline-index.md"
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path
