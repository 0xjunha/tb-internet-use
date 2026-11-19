"""Tests for parse_patch.py, with a made-up patch shaped as in the trajectories."""

from tb_internet_use.tool_call.model import (
    DeleteFileAction,
    EditFileAction,
    WriteFileAction,
)
from tb_internet_use.tool_call.parse_patch import parse_patch


def test_patch_gives_one_action_per_added_file_changed_hunk_and_deleted_file_and_two_more_per_move():
    patch = (
        "*** Begin Patch\n"
        "*** Update File: m.py\n*** Move to: n.py\n"
        "@@\n ctx\n\n-old\n+new\n@@ def f():\n anchor\n@@\n-gone\n"
        "*** Delete File: gone.txt\n"
        "*** Add File: new.txt\n+one\n+two\n"
        "*** End Patch\n"
    )
    assert parse_patch(patch) == [
        WriteFileAction("n.py"),
        EditFileAction("n.py", "ctx\n\nold", "ctx\n\nnew"),
        EditFileAction("n.py", "gone", ""),
        DeleteFileAction("m.py"),
        DeleteFileAction("gone.txt"),
        WriteFileAction("new.txt", "one\ntwo\n"),
    ]
    assert parse_patch("not a patch") == []


def test_move_without_hunks_writes_the_new_path_and_removes_the_old_one():
    patch = (
        "*** Begin Patch\n*** Update File: a.py\n*** Move to: b.py\n@@\n*** End Patch"
    )
    assert parse_patch(patch) == [WriteFileAction("b.py"), DeleteFileAction("a.py")]


def test_move_to_the_same_path_is_no_move_and_keeps_the_file():
    patch = (
        "*** Begin Patch\n*** Update File: a.py\n*** Move to: a.py\n"
        "@@\n-old\n+new\n*** End Patch"
    )
    assert parse_patch(patch) == [EditFileAction("a.py", "old", "new")]
