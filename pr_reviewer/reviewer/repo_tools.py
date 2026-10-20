"""Read-only repository tools the review agent can call for extra context."""

from typing import Protocol

import requests
from langchain_core.tools import BaseTool, tool

from pr_reviewer.common.github_client import GitHubAppClient

# Keep tool results small; a whole large file would blow the token budget.
MAX_FILE_CHARS = 20_000


class RepoReader(Protocol):
    def read_file(self, path: str) -> str: ...

    def list_directory(self, path: str) -> list[str]: ...


class GitHubRepoReader:
    """Reads files at the PR head commit through the GitHub App installation."""

    def __init__(self, github: GitHubAppClient, installation_id: int, owner: str, repo: str, ref: str):
        self._github = github
        self._installation_id = installation_id
        self._owner = owner
        self._repo = repo
        self._ref = ref

    def read_file(self, path: str) -> str:
        return self._github.get_file_content(self._installation_id, self._owner, self._repo, path, self._ref)

    def list_directory(self, path: str) -> list[str]:
        return self._github.list_directory(self._installation_id, self._owner, self._repo, path, self._ref)


def make_repo_tools(reader: RepoReader) -> list[BaseTool]:
    @tool
    def read_file(path: str) -> str:
        """Read a file from the repository at the PR's head commit. Use it to see code around the diff, callers, or tests."""
        try:
            content = reader.read_file(path)
        except requests.HTTPError as error:
            return f"Could not read {path}: {error}"
        if len(content) > MAX_FILE_CHARS:
            return content[:MAX_FILE_CHARS] + f"\n... [truncated, {len(content)} chars total]"
        return content

    @tool
    def list_directory(path: str) -> str:
        """List the entries of a repository directory at the PR's head commit. Use an empty string for the root."""
        try:
            return "\n".join(reader.list_directory(path)) or "(empty)"
        except requests.HTTPError as error:
            return f"Could not list {path or '/'}: {error}"

    return [read_file, list_directory]
