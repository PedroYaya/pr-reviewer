from langchain_core.documents import Document

from pr_reviewer.common.embedding_cache import CachedEmbeddings, InMemoryKeyValueStore
from pr_reviewer.reviewer.conventions import find_convention_paths, guideline_documents, review_comment_documents
from pr_reviewer.reviewer.retrieval import ConventionIndex
from tests.fakes import FakeRepo, KeywordEmbeddings

CONTRIBUTING = """# Contributing

## Errors
Never swallow exceptions; log them with logger.exception.

## Tests
Every bug fix needs a regression test.
"""


def test_finds_convention_files_in_known_directories():
    repo = FakeRepo({
        "CONTRIBUTING.md": "x",
        ".github/REVIEW_GUIDELINES.md": "x",
        "docs/StyleGuide.md": "x",
        "docs/api.md": "x",
        "src/conventions.md": "x",  # outside the known directories
    })

    assert find_convention_paths(repo) == ["CONTRIBUTING.md", ".github/REVIEW_GUIDELINES.md", "docs/StyleGuide.md"]


def test_splits_guidelines_by_section():
    documents = guideline_documents(FakeRepo({"CONTRIBUTING.md": CONTRIBUTING}))

    # The splitter merges a heading with no body ("# Contributing") into the next section.
    assert len(documents) == 2
    assert "swallow exceptions" in documents[0].page_content
    assert documents[1].page_content == "## Tests\nEvery bug fix needs a regression test."
    assert all(d.metadata == {"kind": "guideline", "source": "CONTRIBUTING.md"} for d in documents)


def test_keeps_substantive_human_review_comments():
    comments = [
        {"path": "app.py", "body": "Please use the shared retry helper instead of a loop.", "diff_hunk": "@@ -1 +1 @@\n+for i in range(3):",
         "user": {"type": "User"}, "html_url": "https://github.com/acme/repo/pull/1#r1"},
        {"path": "app.py", "body": "LGTM", "diff_hunk": "", "user": {"type": "User"}},
        {"path": "app.py", "body": "Automated finding from a bot that is long enough", "diff_hunk": "", "user": {"type": "Bot"}},
    ]

    [document] = review_comment_documents(comments)

    assert document.metadata == {"kind": "past_review", "source": "https://github.com/acme/repo/pull/1#r1"}
    assert "shared retry helper" in document.page_content
    assert "+for i in range(3):" in document.page_content


def test_retrieves_conventions_matching_each_changed_file():
    embeddings = KeywordEmbeddings(["exception", "test", "sql"])
    index = ConventionIndex.build(embeddings, guideline_documents(FakeRepo({"CONTRIBUTING.md": CONTRIBUTING})) + [
        Document("Use parameterized sql queries.", metadata={"kind": "guideline", "source": "db.md"}),
    ])
    files = [
        {"filename": "handler.py", "patch": "+except Exception:\n+    pass  # exception ignored"},
        {"filename": "repo.py", "patch": '+cursor.execute(f"select ... {sql}")'},
    ]

    contents = [d.page_content for d in index.relevant_to(files, k=2)]

    assert len(contents) == 2
    assert any("swallow exceptions" in c for c in contents)
    assert "Use parameterized sql queries." in contents


def test_build_returns_none_without_documents():
    assert ConventionIndex.build(KeywordEmbeddings(["x"]), []) is None


def test_embedding_cache_only_embeds_new_texts():
    inner = KeywordEmbeddings(["a"])
    store = InMemoryKeyValueStore()
    cached = CachedEmbeddings(inner, store, namespace="test-model", ttl_seconds=60)

    first = cached.embed_documents(["a", "b"])
    second = cached.embed_documents(["b", "a", "c"])

    assert inner.embedded == ["a", "b", "c"]
    assert second == [first[1], first[0], inner.embed_query("c")]
    assert all(key.startswith("emb:test-model:") for key in store.data)
