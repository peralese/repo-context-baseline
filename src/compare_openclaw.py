from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from writer import OUTPUT_DIR, SUMMARY_DIR, escape_table_cell, safe_filename


DEFAULT_PROJECTS_DIR = Path("/Users/erickperales/Projects")
COMPARISON_DIR = OUTPUT_DIR / "comparisons"
COMPARISON_INDEX_PATH = OUTPUT_DIR / "openclaw-comparison-index.md"

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "be",
    "by",
    "for",
    "from",
    "has",
    "in",
    "into",
    "is",
    "it",
    "no",
    "not",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "under",
    "uses",
    "with",
}

ACTION_VERBS = {
    "add",
    "build",
    "capture",
    "complete",
    "configure",
    "create",
    "document",
    "enhance",
    "evaluate",
    "fix",
    "generate",
    "implement",
    "improve",
    "integrate",
    "investigate",
    "prioritize",
    "refine",
    "resume",
    "run",
    "test",
    "update",
    "validate",
    "write",
}

HEADING_ALIASES = {
    "repository": "repository",
    "project": "repository",
    "purpose": "purpose",
    "maturity": "maturity",
    "working state": "current_state",
    "current state": "current_state",
    "in progress": "in_progress",
    "active work": "in_progress",
    "current work": "in_progress",
    "open issues": "open_issues",
    "open issues / gaps": "open_issues",
    "gaps": "open_issues",
    "gaps / risks": "open_issues",
    "known limitations": "open_issues",
    "limitations": "open_issues",
    "risks": "open_issues",
    "next step": "next_step",
    "primary suggested next step": "next_step",
    "suggested next step": "next_step",
    "recommended next step": "next_step",
    "suggested resume prompt": "resume_prompt",
    "operational signals": "operational_signals",
    "confidence / notes": "confidence",
}


@dataclass
class ComparisonResult:
    repo_name: str
    report_path: Path
    overall: str
    current_state: str
    open_issues: str
    next_step: str
    operational_specificity: str
    recommended_fix: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare README-derived baselines with local OpenClaw context.md files."
    )
    parser.add_argument(
        "--summaries-dir",
        default=str(SUMMARY_DIR),
        help="Directory containing baseline summary markdown files.",
    )
    parser.add_argument(
        "--projects-dir",
        default=str(DEFAULT_PROJECTS_DIR),
        help="Directory containing project folders with context.md files.",
    )
    parser.add_argument(
        "--repo",
        help="Only compare one baseline summary by repository name.",
    )
    return parser.parse_args()


def normalize_heading(value: str) -> str:
    value = value.strip().strip("#").strip()
    value = re.sub(r"\s+", " ", value).lower()
    return HEADING_ALIASES.get(value, value.replace(" ", "_"))


def markdown_sections(markdown: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None

    for line in markdown.splitlines():
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            current = normalize_heading(heading.group(2))
            sections.setdefault(current, [])
            continue

        if current:
            stripped = line.strip()
            if stripped:
                sections[current].append(stripped)

    return sections


def section_text(sections: dict[str, list[str]], *names: str) -> str:
    lines: list[str] = []
    for name in names:
        lines.extend(sections.get(name, []))
    return "\n".join(lines).strip()


def bullets(text: str, *, max_items: int = 4) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        cleaned = re.sub(r"^\s*[-*]\s+", "", line).strip()
        if cleaned:
            items.append(cleaned)
        if len(items) >= max_items:
            break
    return items


def tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", text.lower())
        if token not in STOP_WORDS
    }


def overlap_score(left: str, right: str) -> float:
    left_tokens = tokens(left)
    right_tokens = tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(1, min(len(left_tokens), len(right_tokens)))


def grade_alignment(baseline_text: str, openclaw_text: str) -> str:
    if not baseline_text and not openclaw_text:
        return "Missing"
    if baseline_text and not openclaw_text:
        return "Missing"
    if not baseline_text and openclaw_text:
        return "Partial"

    score = overlap_score(baseline_text, openclaw_text)
    if score >= 0.35:
        return "Good"
    if score >= 0.15:
        return "Partial"
    return "Weak"


def has_actionable_next_step(text: str) -> bool:
    lowered = text.lower()
    if not text or "no explicit next step" in lowered or lowered.strip() in {"none", "- none"}:
        return False
    return bool(tokens(text) & ACTION_VERBS)


def next_step_grade(baseline_text: str, openclaw_text: str) -> str:
    if not openclaw_text:
        return "Missing"
    if has_actionable_next_step(openclaw_text) and overlap_score(baseline_text, openclaw_text) >= 0.12:
        return "Good"
    if has_actionable_next_step(openclaw_text):
        return "Partial"
    return "Weak"


def evaluation_value(grade: str) -> str:
    if grade == "Good":
        return "Yes"
    if grade in {"Partial", "Weak"}:
        return "Partial"
    return "No"


def missing_or_weak(*grades: str) -> bool:
    return any(grade in {"Missing", "Weak"} for grade in grades)


def overall_assessment(grades: list[str], openclaw_exists: bool) -> str:
    if not openclaw_exists:
        return "Missing OpenClaw Context"
    good_count = grades.count("Good")
    if good_count >= 3 and "Weak" not in grades and "Missing" not in grades:
        return "Aligned"
    if missing_or_weak(*grades) and good_count == 0:
        return "Weakly Aligned"
    return "Partially Aligned"


def important_terms(text: str) -> list[str]:
    selected = sorted(tokens(text), key=lambda item: (-len(item), item))
    return selected[:8]


def notable_differences(
    baseline: dict[str, str],
    openclaw: dict[str, str],
    grades: dict[str, str],
) -> list[str]:
    differences: list[str] = []

    if grades["current_state"] in {"Weak", "Missing"}:
        differences.append("Baseline current-state signals are not clearly reflected in OpenClaw context.")
    if grades["open_issues"] in {"Weak", "Missing"}:
        differences.append("Baseline gaps or risks are not clearly captured as OpenClaw open issues.")
    if grades["next_step"] in {"Weak", "Missing"}:
        differences.append("OpenClaw next-step capture is missing, vague, or not aligned with the baseline next step.")

    active_work = openclaw.get("in_progress", "")
    if active_work:
        differences.append("OpenClaw adds active in-progress work that the README-derived baseline cannot know.")

    baseline_terms = set(important_terms(baseline.get("combined", "")))
    openclaw_terms = set(important_terms(openclaw.get("combined", "")))
    omitted = sorted(baseline_terms - openclaw_terms)[:4]
    if omitted:
        differences.append(f"README-derived operational terms with limited OpenClaw coverage: {', '.join(omitted)}.")

    if not differences:
        differences.append("No major deterministic differences found.")
    return differences[:5]


def recommended_fix(overall: str, grades: dict[str, str], openclaw: dict[str, str]) -> str:
    if overall == "Missing OpenClaw Context":
        return "Create or capture a local OpenClaw context.md for this project."
    if grades["next_step"] in {"Missing", "Weak"}:
        return "Improve Next Step capture so OpenClaw records one concrete, verb-led action."
    if grades["open_issues"] in {"Missing", "Weak"}:
        return "Tune OpenClaw capture to preserve README gaps, risks, and known limitations as open issues."
    if grades["current_state"] in {"Missing", "Weak"}:
        return "Tune OpenClaw capture to preserve the baseline current-state and maturity signals."
    if openclaw.get("in_progress"):
        return "No fix needed; OpenClaw adds useful active-work context."
    return "No fix needed."


def make_short_bullets(text: str, *, max_items: int = 4) -> list[str]:
    items = bullets(text, max_items=max_items)
    if items:
        return items
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return [sentence.strip() for sentence in sentences if sentence.strip()][:max_items]


def comparison_report(
    *,
    repo_name: str,
    baseline_sections: dict[str, list[str]],
    openclaw_sections: dict[str, list[str]] | None,
    openclaw_context_path: Path,
) -> tuple[str, ComparisonResult]:
    report_path = COMPARISON_DIR / f"{safe_filename(repo_name)}.md"

    baseline = {
        "purpose": section_text(baseline_sections, "purpose"),
        "maturity": section_text(baseline_sections, "maturity"),
        "current_state": section_text(baseline_sections, "current_state", "maturity"),
        "open_issues": section_text(baseline_sections, "open_issues"),
        "next_step": section_text(baseline_sections, "next_step"),
        "operational": section_text(baseline_sections, "operational_signals", "current_state"),
    }
    baseline["combined"] = "\n".join(baseline.values())

    if openclaw_sections is None:
        overall = "Missing OpenClaw Context"
        result = ComparisonResult(
            repo_name=repo_name,
            report_path=report_path,
            overall=overall,
            current_state="Missing",
            open_issues="Missing",
            next_step="Missing",
            operational_specificity="Missing",
            recommended_fix="Create or capture a local OpenClaw context.md for this project.",
        )
        lines = [
            f"# Context Comparison: {repo_name}",
            "",
            "## Overall Assessment",
            overall,
            "",
            "## Baseline Summary",
            *[f"- {item}" for item in make_short_bullets(baseline["combined"])],
            "",
            "## OpenClaw Context Summary",
            f"- Missing OpenClaw context at `{openclaw_context_path}`.",
            "",
            "## Alignment",
            "- Current State: Missing",
            "- Open Issues: Missing",
            "- Next Step: Missing",
            "- Operational Specificity: Missing",
            "",
            "## Notable Differences",
            "- No OpenClaw context was available for comparison.",
            "",
            "## Evaluation",
            "- Does OpenClaw produce useful operational context? No",
            "- Is the OpenClaw Next Step actionable? No",
            "- Does OpenClaw clearly reflect README-only limitations when evidence is weak? Not Applicable",
            "",
            "## Recommended Fix",
            f"- {result.recommended_fix}",
        ]
        return "\n".join(lines).rstrip() + "\n", result

    openclaw = {
        "purpose": section_text(openclaw_sections, "purpose"),
        "current_state": section_text(openclaw_sections, "current_state"),
        "in_progress": section_text(openclaw_sections, "in_progress"),
        "open_issues": section_text(openclaw_sections, "open_issues"),
        "next_step": section_text(openclaw_sections, "next_step"),
        "operational": section_text(openclaw_sections, "current_state", "in_progress", "open_issues", "next_step"),
    }
    openclaw["combined"] = "\n".join(openclaw.values())

    grades = {
        "current_state": grade_alignment(baseline["current_state"], openclaw["current_state"]),
        "open_issues": grade_alignment(baseline["open_issues"], openclaw["open_issues"]),
        "next_step": next_step_grade(baseline["next_step"], openclaw["next_step"]),
        "operational_specificity": grade_alignment(baseline["operational"], openclaw["operational"]),
    }
    overall = overall_assessment(list(grades.values()), True)
    fix = recommended_fix(overall, grades, openclaw)

    result = ComparisonResult(
        repo_name=repo_name,
        report_path=report_path,
        overall=overall,
        current_state=grades["current_state"],
        open_issues=grades["open_issues"],
        next_step=grades["next_step"],
        operational_specificity=grades["operational_specificity"],
        recommended_fix=fix,
    )

    limitation_reflection = "Not Applicable"
    if baseline["open_issues"]:
        limitation_reflection = evaluation_value(grades["open_issues"])

    lines = [
        f"# Context Comparison: {repo_name}",
        "",
        "## Overall Assessment",
        overall,
        "",
        "## Baseline Summary",
        *[f"- {item}" for item in make_short_bullets(baseline["combined"])],
        "",
        "## OpenClaw Context Summary",
        *[f"- {item}" for item in make_short_bullets(openclaw["combined"])],
        "",
        "## Alignment",
        f"- Current State: {grades['current_state']}",
        f"- Open Issues: {grades['open_issues']}",
        f"- Next Step: {grades['next_step']}",
        f"- Operational Specificity: {grades['operational_specificity']}",
        "",
        "## Notable Differences",
        *[f"- {item}" for item in notable_differences(baseline, openclaw, grades)],
        "",
        "## Evaluation",
        f"- Does OpenClaw produce useful operational context? {evaluation_value(grades['operational_specificity'])}",
        f"- Is the OpenClaw Next Step actionable? {'Yes' if has_actionable_next_step(openclaw['next_step']) else 'No'}",
        f"- Does OpenClaw clearly reflect README-only limitations when evidence is weak? {limitation_reflection}",
        "",
        "## Recommended Fix",
        f"- {fix}",
    ]
    return "\n".join(lines).rstrip() + "\n", result


def write_comparison_index(results: list[ComparisonResult]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "# OpenClaw Comparison Index",
        "",
        "| Repository | Overall Assessment | Current State | Open Issues | Next Step | Recommended Fix |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    for result in results:
        link_path = result.report_path.relative_to(OUTPUT_DIR).as_posix()
        repository = escape_table_cell(result.repo_name)
        fix = escape_table_cell(result.recommended_fix)
        lines.append(
            f"| [{repository}]({link_path}) | {result.overall} | {result.current_state} | "
            f"{result.open_issues} | {result.next_step} | {fix} |"
        )

    COMPARISON_INDEX_PATH.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return COMPARISON_INDEX_PATH


def selected_summary_paths(summaries_dir: Path, repo_name: str | None) -> list[Path]:
    if repo_name:
        path = summaries_dir / f"{safe_filename(repo_name)}.md"
        if not path.exists():
            raise FileNotFoundError(f"Baseline summary not found for repository: {repo_name}")
        return [path]

    return sorted(path for path in summaries_dir.glob("*.md") if path.is_file())


def generate_comparisons(
    *,
    summaries_dir: Path = SUMMARY_DIR,
    projects_dir: Path = DEFAULT_PROJECTS_DIR,
    repo_name: str | None = None,
    write_index: bool | None = None,
) -> list[ComparisonResult]:
    COMPARISON_DIR.mkdir(parents=True, exist_ok=True)
    summary_paths = selected_summary_paths(summaries_dir, repo_name)
    single_repo_run = repo_name is not None
    results: list[ComparisonResult] = []

    for summary_path in summary_paths:
        current_repo_name = summary_path.stem
        baseline_markdown = summary_path.read_text(encoding="utf-8")
        baseline_sections = markdown_sections(baseline_markdown)
        openclaw_context_path = projects_dir / current_repo_name / "context.md"

        if openclaw_context_path.exists():
            openclaw_sections = markdown_sections(openclaw_context_path.read_text(encoding="utf-8"))
        else:
            openclaw_sections = None

        report, result = comparison_report(
            repo_name=current_repo_name,
            baseline_sections=baseline_sections,
            openclaw_sections=openclaw_sections,
            openclaw_context_path=openclaw_context_path,
        )
        result.report_path.write_text(report, encoding="utf-8")
        results.append(result)

    should_write_index = not single_repo_run if write_index is None else write_index
    if should_write_index:
        write_comparison_index(results)
    return results


def main() -> int:
    args = parse_args()
    results = generate_comparisons(
        summaries_dir=Path(args.summaries_dir),
        projects_dir=Path(args.projects_dir),
        repo_name=args.repo,
    )
    missing = sum(1 for result in results if result.overall == "Missing OpenClaw Context")
    print(f"Wrote {len(results)} comparison report(s) to {COMPARISON_DIR}")
    if args.repo:
        print("Skipped comparison index update for single-repository run.")
    else:
        print(f"Wrote {COMPARISON_INDEX_PATH}")
    print(f"Missing OpenClaw contexts: {missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
