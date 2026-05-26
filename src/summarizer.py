from __future__ import annotations

from openai import OpenAI


MAX_README_CHARS = 24000


class SummarizerError(Exception):
    """Raised when baseline generation fails."""


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
                            "You generate concise operational project baselines from repository READMEs. "
                            "Do not merely summarize the README. Extract documentation-derived operational state "
                            "for comparison against OpenClaw context.md outputs. Keep architecture detail brief, "
                            "separate evidence from inference, and use the required fallback wording when evidence "
                            "is missing."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            )
            return response.output_text.strip()
        except Exception as error:  # noqa: BLE001 - preserve simple MVP error handling around SDK calls.
            raise SummarizerError(f"OpenAI baseline generation failed: {error}") from error


def truncate_readme(readme_content: str) -> str:
    if len(readme_content) <= MAX_README_CHARS:
        return readme_content

    return (
        readme_content[:MAX_README_CHARS]
        + "\n\n[README truncated before OpenAI processing because it exceeded MVP size limits.]"
    )


def build_prompt(*, repo_name: str, repo_url: str, readme_content: str, readme_missing: bool) -> str:
    readme_note = (
        "The README is missing. Produce a low-confidence baseline and clearly state that operational "
        "information is insufficient."
        if readme_missing
        else "Use the README below as the only evidence source."
    )

    return f"""Repository name: {repo_name}
Repository URL: {repo_url}

{readme_note}

Create a standardized markdown baseline using exactly this structure:

# Project Baseline

## Repository
{repo_name}

## Repository URL
{repo_url}

## Purpose
<1-2 sentences only>

## Maturity
<Choose exactly one: Prototype, Early Working App, Functional MVP, Mature Local Tool, Unknown. Include a one-sentence reason.>

## Current State
- <3-5 bullets max; focus on what appears implemented or working>

## Key Capabilities
- <3-6 bullets max; focus on user-visible or operational capabilities>

## Inferred Tech Stack
- <concise bullets only; avoid long explanations>

## Operational Signals
- <2-5 bullets max; include evidence of active workflow, automation, tests, CI/CD, services, deployment, roadmap, or maintenance>
- <If none found, use exactly one bullet: No strong operational signals found in README>

## Gaps / Risks
- <2-5 bullets max; include missing docs, incomplete features, unclear next steps, operational risks, or README weaknesses>
- <If none found, use exactly one bullet: No explicit gaps found in README>

## Primary Suggested Next Step
- <Exactly one bullet. Use the single most actionable next step from the README. If inferred rather than explicit, start with "Inferred: ". If there is not enough evidence, use exactly: No explicit next step found in README>

## Additional Follow-Up
- <0-3 bullets max; optional secondary items only; do not repeat the primary next step>

## Confidence / Notes
- Confidence: High / Medium / Low
- <1-2 short notes explaining why>

Important instructions:
- Do not simply summarize the README.
- Extract operational project state from README evidence.
- Prioritize README sections named Next Steps, TODO, Roadmap, Open Issues, In Progress, Known Limitations, Changelog, or Recent Work.
- Deprioritize installation instructions, generic feature lists, badges, marketing descriptions, and long architecture explanations.
- Do not pretend the README contains information it does not contain.
- If the README has no explicit next step, say so using exactly: No explicit next step found in README
- If inferring a next step, make it conservative and label it with "Inferred: ".
- Do not generate multiple competing next steps in Primary Suggested Next Step.
- Keep the total baseline concise, ideally under 700 words.
- Avoid hype, marketing language, and broad roadmap paragraphs.

README:
```markdown
{readme_content}
```
"""
