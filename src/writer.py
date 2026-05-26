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


def extract_markdown_section(markdown: str, heading: str) -> list[str]:
    lines = markdown.splitlines()
    section_lines: list[str] = []
    in_section = False

    for line in lines:
        if line.strip() == f"## {heading}":
            in_section = True
            continue

        if in_section and line.startswith("## "):
            break

        if in_section:
            section_lines.append(line)

    return [line.strip() for line in section_lines if line.strip()]


def first_section_value(markdown: str, heading: str, default: str = "Unknown") -> str:
    section_lines = extract_markdown_section(markdown, heading)

    if not section_lines:
        return default

    first_line = section_lines[0]
    if first_line.startswith("- "):
        return first_line[2:].strip() or default

    return first_line


def summary_index_record(item: dict[str, Any]) -> dict[str, str]:
    path = item["path"]
    markdown = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        link_path = path.relative_to(OUTPUT_DIR).as_posix()
    except ValueError:
        link_path = path.as_posix()

    repository = first_section_value(markdown, "Repository", item["name"])
    maturity = first_section_value(markdown, "Maturity")
    primary_next_step = first_section_value(
        markdown,
        "Primary Suggested Next Step",
        "No explicit next step found in README",
    )
    confidence = first_section_value(markdown, "Confidence / Notes")

    if confidence.startswith("Confidence:"):
        confidence = confidence.removeprefix("Confidence:").strip()

    return {
        "repository": repository,
        "path": link_path,
        "maturity": maturity,
        "primary_next_step": primary_next_step,
        "confidence": confidence,
    }


def escape_table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def write_baseline_index(summaries: list[dict[str, Any]]) -> Path:
    ensure_output_dirs()
    lines = ["# Baseline Repository Index", ""]

    if not summaries:
        lines.append("No repository summaries were generated.")
    else:
        lines.extend(
            [
                "| Repository | Maturity | Primary Suggested Next Step | Confidence |",
                "| --- | --- | --- | --- |",
            ]
        )
        for item in summaries:
            record = summary_index_record(item)
            repository = escape_table_cell(record["repository"])
            maturity = escape_table_cell(record["maturity"])
            primary_next_step = escape_table_cell(record["primary_next_step"])
            confidence = escape_table_cell(record["confidence"])

            lines.append(
                f"| [{repository}]({record['path']}) | {maturity} | {primary_next_step} | {confidence} |"
            )

    path = OUTPUT_DIR / "baseline-index.md"
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path
