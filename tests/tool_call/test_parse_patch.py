"""Tests for parse_patch.py, with a made-up patch shaped as in the trajectories."""

from tb_internet_use.tool_call.model import (
    DeleteFileAction,
    EditFileAction,
    WriteFileAction,
)
from tb_internet_use.tool_call.parse_patch import parse_patch


def test_patch_gives_one_action_per_added_file_changed_hunk_and_deleted_file():
    patch = (
        "*** Begin Patch\n"
        "*** Update File: m.py\n*** Move to: n.py\n"
        "@@\n ctx\n\n-old\n+new\n@@ def f():\n anchor\n@@\n-gone\n"
        "*** Delete File: gone.txt\n"
        "*** Add File: new.txt\n+one\n+two\n"
        "*** End Patch\n"
    )
    assert parse_patch(patch) == [
        EditFileAction("n.py", "ctx\n\nold", "ctx\n\nnew"),
        EditFileAction("n.py", "gone", ""),
        DeleteFileAction("gone.txt"),
        WriteFileAction("new.txt", "one\ntwo\n"),
    ]
    assert parse_patch("not a patch") == []
