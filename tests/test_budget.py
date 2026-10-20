import pytest

from pr_reviewer.reviewer.budget import CHARS_PER_TOKEN, OmittedFile, TokenBudget, is_ignored, select_files, truncate_patch


def file(name, patch="@@ -1 +1 @@\n+x", status="modified"):
    return {"filename": name, "status": status, "patch": patch}


@pytest.mark.parametrize(
    "name",
    ["poetry.lock", "package-lock.json", "web/yarn.lock", "go.sum", "static/app.min.js", "dist/bundle.js",
     "packages/ui/node_modules/x/index.js", "api/service_pb2.py", "__snapshots__/view.snap"],
)
def test_ignores_lock_and_generated_files(name):
    assert is_ignored(name)


@pytest.mark.parametrize("name", ["app.py", "src/build_config.py", "docs/distribution.md"])
def test_keeps_regular_source_files(name):
    assert not is_ignored(name)


def test_omits_unreviewable_files_with_reasons():
    selection = select_files(
        [file("app.py"), file("poetry.lock"), file("logo.png", patch=None), file("old.py", status="removed")],
        TokenBudget(diff_tokens=1000, file_tokens=1000),
    )

    assert [f["filename"] for f in selection.files] == ["app.py"]
    assert selection.omitted == [
        OmittedFile("poetry.lock", "lock file or generated code"),
        OmittedFile("logo.png", "binary or too large for GitHub to diff"),
        OmittedFile("old.py", "file deleted"),
    ]


def test_admits_smallest_files_first_and_keeps_original_order():
    big = file("big.py", patch="+" + "x" * 400)
    small_a = file("a.py", patch="+" + "a" * 40)
    small_b = file("b.py", patch="+" + "b" * 40)

    selection = select_files([small_b, big, small_a], TokenBudget(diff_tokens=50, file_tokens=1000))

    assert [f["filename"] for f in selection.files] == ["b.py", "a.py"]
    assert selection.omitted == [OmittedFile("big.py", "over the review token budget")]


def test_truncates_patch_at_line_boundary():
    patch = "\n".join(f"+line {i}" for i in range(100))

    truncated, was_truncated = truncate_patch(patch, max_tokens=10)

    assert was_truncated
    assert len(truncated) <= 10 * CHARS_PER_TOKEN
    assert truncated.splitlines()[-1].startswith("+line ")


def test_selected_files_are_copies_flagged_when_truncated():
    original = file("app.py", patch="\n".join(f"+line {i}" for i in range(100)))

    [selected] = select_files([original], TokenBudget(diff_tokens=1000, file_tokens=10)).files

    assert selected["truncated"] is True
    assert "truncated" not in original
