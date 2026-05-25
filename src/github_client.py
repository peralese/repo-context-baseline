from __future__ import annotations

import base64
import time
from typing import Any

import requests


GITHUB_API_URL = "https://api.github.com"


class GitHubError(Exception):
    """Raised when GitHub API requests fail."""


class GitHubClient:
    def __init__(self, token: str) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def list_repositories(
        self,
        *,
        owner: str,
        owner_type: str,
        include_private: bool,
    ) -> list[dict[str, Any]]:
        if owner_type == "org":
            url = f"{GITHUB_API_URL}/orgs/{owner}/repos"
            params = {"type": "all" if include_private else "public", "per_page": 100}
        elif include_private:
            url = f"{GITHUB_API_URL}/user/repos"
            params = {"type": "all", "per_page": 100}
        else:
            url = f"{GITHUB_API_URL}/users/{owner}/repos"
            params = {"type": "public", "per_page": 100}

        repos: list[dict[str, Any]] = []

        while url:
            response = self._request("GET", url, params=params)
            repos.extend(response.json())
            url = response.links.get("next", {}).get("url")
            params = None

        if owner_type == "user" and include_private:
            owner_lower = owner.lower()
            return [
                repo
                for repo in repos
                if repo.get("owner", {}).get("login", "").lower() == owner_lower
            ]

        return repos

    def fetch_readme(self, *, owner: str, repo: str, default_branch: str) -> str | None:
        url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/readme"
        params = {"ref": default_branch} if default_branch else None
        response = self._request("GET", url, params=params, allow_not_found=True)

        if response is None:
            return None

        payload = response.json()
        encoded_content = payload.get("content")
        if not encoded_content:
            return None

        return base64.b64decode(encoded_content).decode("utf-8", errors="replace")

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        allow_not_found: bool = False,
    ) -> requests.Response | None:
        response = self.session.request(method, url, params=params, timeout=30)

        if response.status_code == 404 and allow_not_found:
            return None

        if response.status_code in {403, 429}:
            remaining = response.headers.get("X-RateLimit-Remaining")
            reset_at = response.headers.get("X-RateLimit-Reset")
            if remaining == "0" and reset_at:
                wait_seconds = max(int(reset_at) - int(time.time()), 0)
                raise GitHubError(
                    f"GitHub rate limit reached. Try again in about {wait_seconds} seconds."
                )
            raise GitHubError(f"GitHub API returned {response.status_code}: {response.text}")

        if response.status_code >= 400:
            raise GitHubError(f"GitHub API returned {response.status_code}: {response.text}")

        return response
