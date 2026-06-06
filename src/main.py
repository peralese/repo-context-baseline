from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from compare_openclaw import generate_comparisons
from writer import repo_summary_path, write_baseline_index, write_repo_inventory, write_repo_summary


DEFAULT_CONFIG_PATH = "config.json"


def load_dotenv(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        name, value = stripped.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")

        if name and name not in os.environ:
            os.environ[name] = value


def load_config(path: str) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as file:
        config = json.load(file)

    required_fields = ["github_owner", "owner_type", "openai_model"]
    missing = [field for field in required_fields if not config.get(field)]
    if missing:
        raise ValueError(f"Missing required config fields: {', '.join(missing)}")

    if config["github_owner"] == "YOUR_GITHUB_USERNAME":
        raise ValueError("Update github_owner in config.json before running.")

    if config["owner_type"] not in {"user", "org"}:
        raise ValueError("owner_type must be either 'user' or 'org'")

    return config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate operational project baselines from GitHub repository READMEs."
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Path to config JSON.")
    parser.add_argument("--limit", type=int, help="Override config max_repos.")
    parser.add_argument("--dry-run", action="store_true", help="List repos without calling OpenAI or writing summaries.")
    parser.add_argument("--repo", help="Only process one repository by name.")
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip repos that already have outputs/summaries/<repo-name>.md.",
    )
    parser.add_argument(
        "--compare-openclaw",
        action="store_true",
        help="Compare outputs/summaries/*.md with /Users/erickperales/Projects/<repo-name>/context.md.",
    )
    parser.add_argument(
        "--projects-dir",
        default="/Users/erickperales/Projects",
        help="Project root used by --compare-openclaw.",
    )
    return parser.parse_args()


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise EnvironmentError(f"Missing required environment variable: {name}")
    return value


def select_repositories(
    repos: list[dict[str, Any]],
    *,
    include_archived: bool,
    include_forks: bool,
    include_private: bool,
    repo_name: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    selected = []

    for repo in repos:
        if repo_name and repo["name"] != repo_name:
            continue
        if repo.get("archived") and not include_archived:
            continue
        if repo.get("fork") and not include_forks:
            continue
        if repo.get("private") and not include_private:
            continue

        selected.append(repo)

        if len(selected) >= limit:
            break

    return selected


def repo_record(repo: dict[str, Any], readme_status: str) -> dict[str, Any]:
    return {
        "name": repo["name"],
        "url": repo["html_url"],
        "default_branch": repo.get("default_branch", ""),
        "private": repo.get("private", False),
        "archived": repo.get("archived", False),
        "fork": repo.get("fork", False),
        "readme_status": readme_status,
    }


def main() -> int:
    args = parse_args()

    try:
        if args.compare_openclaw:
            results = generate_comparisons(projects_dir=Path(args.projects_dir), repo_name=args.repo)
            missing = sum(1 for result in results if result.overall == "Missing OpenClaw Context")
            print(f"Wrote {len(results)} comparison report(s) to outputs/comparisons")
            if args.repo:
                print("Skipped comparison index update for single-repository run.")
            else:
                print("Wrote outputs/openclaw-comparison-index.md")
            print(f"Missing OpenClaw contexts: {missing}")
            return 0

        load_dotenv()
        config = load_config(args.config)
        github_token = require_env("GITHUB_TOKEN")
        from github_client import GitHubClient, GitHubError
        from summarizer import OpenAISummarizer, SummarizerError

        if not args.dry_run:
            openai_api_key = require_env("OPENAI_API_KEY")
        else:
            openai_api_key = ""

        limit = args.limit or int(config.get("max_repos", 25))
        include_missing_readme = bool(config.get("include_missing_readme", False))

        github = GitHubClient(github_token)

        print(f"Listing repositories for {config['owner_type']} '{config['github_owner']}'...")
        repos = github.list_repositories(
            owner=config["github_owner"],
            owner_type=config["owner_type"],
            include_private=bool(config.get("include_private", True)),
        )

        selected = select_repositories(
            repos,
            include_archived=bool(config.get("include_archived", False)),
            include_forks=bool(config.get("include_forks", False)),
            include_private=bool(config.get("include_private", True)),
            repo_name=args.repo,
            limit=limit,
        )

        if args.repo and not selected:
            print(f"No repository matched --repo {args.repo!r} after filters were applied.")
            return 1

        print(f"Selected {len(selected)} repository/repositories.")

        if args.dry_run:
            for repo in selected:
                summary_path = repo_summary_path(repo["name"])
                status = "existing summary" if summary_path.exists() else "new summary"
                print(f"- {repo['name']} ({repo['html_url']}) [{status}]")
            print("Dry run complete. No OpenAI calls were made and no generated outputs were written.")
            return 0

        summarizer = OpenAISummarizer(api_key=openai_api_key, model=config["openai_model"])
        output_records = []
        written_summaries = []

        for index, repo in enumerate(selected, start=1):
            print(f"[{index}/{len(selected)}] Processing {repo['name']}...")
            existing_summary_path = repo_summary_path(repo["name"])

            if args.skip_existing and existing_summary_path.exists():
                output_records.append(repo_record(repo, "existing_skipped"))
                written_summaries.append(
                    {"name": repo["name"], "path": existing_summary_path, "url": repo["html_url"]}
                )
                print(f"  Skipping existing summary at {existing_summary_path}")
                continue

            readme = github.fetch_readme(
                owner=config["github_owner"],
                repo=repo["name"],
                default_branch=repo.get("default_branch", ""),
            )

            if readme is None:
                print(f"  README not found for {repo['name']}.")
                if not include_missing_readme:
                    output_records.append(repo_record(repo, "missing_skipped"))
                    print("  Skipping because include_missing_readme is false.")
                    continue
                readme_content = "README not found."
                readme_status = "missing_included"
            else:
                readme_content = readme
                readme_status = "found"

            summary = summarizer.generate_overview(
                repo_name=repo["name"],
                repo_url=repo["html_url"],
                readme_content=readme_content,
                readme_missing=readme is None,
            )
            summary_path = write_repo_summary(repo["name"], summary)
            output_records.append(repo_record(repo, readme_status))
            written_summaries.append({"name": repo["name"], "path": summary_path, "url": repo["html_url"]})
            print(f"  Wrote {summary_path}")

        repos_path = write_repo_inventory(output_records)
        index_path = write_baseline_index(written_summaries)
        print(f"Wrote {repos_path}")
        print(f"Wrote {index_path}")
        print("Baseline generation complete.")
        return 0

    except Exception as error:
        handled_error_names = {"GitHubError", "SummarizerError"}
        if isinstance(error, (EnvironmentError, FileNotFoundError, ValueError, json.JSONDecodeError)) or (
            error.__class__.__name__ in handled_error_names
        ):
            print(f"Error: {error}", file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    raise SystemExit(main())
