from pr_reviewer.reviewer.diff import commentable_lines, number_patch

PATCH = """@@ -1,3 +1,4 @@
 first
-old
+new
+added
 last
@@ -20,2 +21,2 @@ def tail():
-    return 1
+    return 2
 \\ No newline at end of file"""


def test_commentable_lines_follow_new_file_numbering():
    assert commentable_lines(PATCH) == {1, 2, 3, 4, 21, 22}


def test_removed_lines_and_markers_are_not_commentable():
    patch = "@@ -5,2 +5,1 @@\n-gone\n kept\n\\ No newline at end of file"

    assert commentable_lines(patch) == {5}


def test_number_patch_prefixes_new_line_numbers():
    numbered = number_patch(PATCH).splitlines()

    assert numbered[0].strip() == "@@ -1,3 +1,4 @@"
    assert numbered[2] == "      -old"
    assert numbered[3] == "    2 +new"
    assert numbered[8] == "   21 +    return 2"


def test_empty_patch():
    assert commentable_lines("") == set()
