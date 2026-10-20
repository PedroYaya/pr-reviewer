"""Vector index over a repository's review conventions."""

from typing import Any

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.tools import BaseTool, tool
from langchain_core.vectorstores import InMemoryVectorStore

# Per-file retrieval keeps one large file from dominating the results.
RESULTS_PER_FILE = 2
QUERY_PATCH_CHARS = 2000
SEARCH_TOOL_RESULTS = 4


class ConventionIndex:
    def __init__(self, store: InMemoryVectorStore):
        self._store = store

    @classmethod
    def build(cls, embeddings: Embeddings, documents: list[Document]) -> "ConventionIndex | None":
        if not documents:
            return None
        store = InMemoryVectorStore(embeddings)
        store.add_documents(documents)
        return cls(store)

    def search(self, query: str, k: int) -> list[Document]:
        return self._store.similarity_search(query, k=k)

    def relevant_to(self, files: list[dict[str, Any]], k: int) -> list[Document]:
        """Best matches across all changed files, de-duplicated, highest score first."""
        best: dict[str, tuple[float, Document]] = {}
        for file in files:
            query = f"{file['filename']}\n{(file.get('patch') or '')[:QUERY_PATCH_CHARS]}"
            for document, score in self._store.similarity_search_with_score(query, k=RESULTS_PER_FILE):
                if document.id not in best or score > best[document.id][0]:
                    best[document.id] = (score, document)
        ranked = sorted(best.values(), key=lambda item: item[0], reverse=True)
        return [document for _, document in ranked[:k]]


def format_documents(documents: list[Document]) -> str:
    return "\n\n".join(
        f"[{d.metadata['kind']}: {d.metadata['source']}]\n{d.page_content}" for d in documents
    )


def make_convention_tool(index: ConventionIndex) -> BaseTool:
    @tool
    def search_conventions(query: str) -> str:
        """Search the team's coding guidelines and past human review comments. Use it to check whether a pattern in the diff breaks a team rule."""
        documents = index.search(query, k=SEARCH_TOOL_RESULTS)
        return format_documents(documents) or "No matching conventions."

    return search_conventions
