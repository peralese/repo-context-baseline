from __future__ import annotations

from openai import OpenAI


MAX_README_CHARS = 24000


class SummarizerError(Exception):
    """Raised when overview generation fails."""


class OpenAISummarizer:
    def __init__(self, *, api_key: str, model: str) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def generate_overview(
        self,
        *,
        repo_name: str,
        repo_url: str,
        readme_content: str,
        readme_missing: bool,
    ) -> str:
        prompt = build_prompt(
            repo_name=repo_name,
            repo_url=repo_url,
            readme_content=truncate_readme(readme_content),
            readme_missing=readme_missing,
        )

        try:
            response = self.client.responses.create(
                model=self.model,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "You generate concise operational project overviews from repository READMEs. "
                            "Do not merely summarize. Extract maturity, capabilities, gaps, operational signals, "
                            "and implied next steps. If no clear next step exists, say exactly: "
                            "No explicit next step found in README"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            )
            return response.output_text.strip()
        except Exception as error:  # noqa: BLE001 - preserve simple MVP error handling around SDK calls.
            raise SummarizerError(f"OpenAI overview generation failed: {error}") from error


def truncate_readme(readme_content: str) -> str:
    if len(readme_content) <= MAX_README_CHARS:
        return readme_content

    return (
        readme_content[:MAX_README_CHARS]
        + "\n\n[README truncated before OpenAI processing because it exceeded MVP size limits.]"
    )


def build_prompt(*, repo_name: str, repo_url: str, readme_content: str, readme_missing: bool) -> str:
    readme_note = (
        "The README is missing. Produce a low-confidence overview and clearly state that operational "
        "information is insufficient."
        if readme_missing
        else "Use the README below as the only evidence source."
    )

    return f"""Repository name: {repo_name}
Repository URL: {repo_url}

{readme_note}

Create a standardized markdown overview using exactly this structure:

# Project Overview

## Repository
{repo_name}

## Repository URL
{repo_url}

## Purpose
<short explanation>

## Current State
- ...

## Key Capabilities
- ...

## Inferred Tech Stack
- ...

## Operational Signals
- items that indicate what is currently active, incomplete, or important

## Open Issues / Gaps
- ...

## Suggested Next Step
- ...

## Confidence / Notes
- ...

Important instructions:
- Do not simply summarize the README.
- Extract what the project appears to do.
- Infer how mature the project looks from README signals.
- Identify existing capabilities.
- Identify what seems incomplete.
- Identify the next step implied by the README.
- If the README has no clear next step, include exactly this bullet: No explicit next step found in README
- Say when the README lacks enough operational information.
- Keep the overview concise and useful for later comparison against another project-context summary.

README:
```markdown
{readme_content}
```
"""
