"""Collects a repository's review conventions as documents for retrieval.

Two sources: guideline files committed to the repo (CONTRIBUTING.md, style
guides, ...) and recent comments human reviewers left on past PRs, which show
the team's unwritten rules next to the code they were about.
"""

from typing import Any

import requests
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from pr_reviewer.reviewer.repo_tools import RepoReader

CONVENTION_DIRS = ("", ".github", "docs")
CONVENTION_FILENAMES = {
    "contributing.md", "styleguide.md", "style_guide.md", "conventions.md",
    "coding_guidelines.md", "review_guidelines.md", "agents.md",
}
CHUNK_CHARS = 1500
CHUNK_OVERLAP = 150
MIN_COMMENT_CHARS = 30
# The end of a diff hunk is the code the reviewer commented on.
HUNK_TAIL_CHARS = 800

_HEADER_SPLITTER = MarkdownHeaderTextSplitter([("#", "h1"), ("##", "h2"), ("###", "h3")], strip_headers=False)
_CHUNKER = RecursiveCharacterTextSplitter(chunk_size=CHUNK_CHARS, chunk_overlap=CHUNK_OVERLAP)


def find_convention_paths(repo: RepoReader) -> list[str]:
    paths = []
    for directory in CONVENTION_DIRS:
        try:
            entries = repo.list_directory(directory)
        except requests.HTTPError:
            continue  # directory doesn't exist in this repo
        paths += [p for p in entries if p.rsplit("/", 1)[-1].lower() in CONVENTION_FILENAMES]
    return paths


def guideline_documents(repo: RepoReader) -> list[Document]:
    documents = []
    for path in find_convention_paths(repo):
        sections = _HEADER_SPLITTER.split_text(repo.read_file(path))
        for chunk in _CHUNKER.split_documents(sections):
            documents.append(Document(page_content=chunk.page_content, metadata={"kind": "guideline", "source": path}))
    return documents


def review_comment_documents(comments: list[dict[str, Any]]) -> list[Document]:
    documents = []
    for comment in comments:
        body = (comment.get("body") or "").strip()
        if (comment.get("user") or {}).get("type") == "Bot" or len(body) < MIN_COMMENT_CHARS:
            continue
        hunk = (comment.get("diff_hunk") or "")[-HUNK_TAIL_CHARS:]
        documents.append(
            Document(
                page_content=f"Reviewer comment on {comment['path']}:\n{body}\n\nCode:\n{hunk}",
                metadata={"kind": "past_review", "source": comment.get("html_url") or comment["path"]},
            )
        )
    return documents
