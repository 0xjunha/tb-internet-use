"""Read a patch of the `apply_patch` tool into the file changes it makes, without applying it.

Codex and Copilot CLI write a patch in the same notation, e.g. `*** Begin Patch`, then `*** Add File: a.txt` with `+` lines, `*** Update File: b.py` with `@@` hunks and an optional `*** Move to: d.py` line before them, or `*** Delete File: c.txt`, then `*** End Patch`.
"""

import re

from tb_internet_use.tool_call.model import (
    DeleteFileAction,
    EditFileAction,
    WriteFileAction,
)

_PATCH_FILE = re.compile(r"^\*\*\* (Add|Update|Delete) File: (.+)$", re.MULTILINE)
_MOVE_TO = "*** Move to: "


def parse_patch(
    patch: str,
) -> list[WriteFileAction | EditFileAction | DeleteFileAction]:
    """List the file changes of an apply_patch patch as ToolCallActions, in order.

    An added file is a write, each hunk that changes an updated file an edit, and a deleted file a DeleteFileAction, as for the delete tool of any harness.
    An updated file with `*** Move to:` is a write without content at the new path, then the edits of its hunks at that path, then a removal of the old path, e.g. for `*** Update File: a.py` and `*** Move to: b.py` without hunks a `WriteFileAction("b.py")` and a `DeleteFileAction("a.py")`.
    A move to the same path is no move, so `*** Move to: a.py` under `*** Update File: a.py` gives only the edits of its hunks.
    A hunk that changes nothing, which only places the next one, gives no ToolCallAction.
    A text without a file header gives an empty list.
    """
    actions: list[WriteFileAction | EditFileAction | DeleteFileAction] = []
    headers = list(_PATCH_FILE.finditer(patch))
    for k, header in enumerate(headers):
        kind, path = header[1], header[2].strip()
        end = headers[k + 1].start() if k + 1 < len(headers) else None
        lines = patch[header.end() : end].split("\n")[1:]
        lines = [line for line in lines if not line.startswith("*** End")]
        while lines and not lines[-1]:
            lines.pop()
        if kind == "Delete":
            actions.append(DeleteFileAction(path))
        elif kind == "Add":
            content = "".join(line[1:] + "\n" for line in lines if line.startswith("+"))
            actions.append(WriteFileAction(path, content))
        else:
            new_path = None
            if lines and lines[0].startswith(_MOVE_TO):
                new_path = lines.pop(0).removeprefix(_MOVE_TO).strip()
            # A move to the path the file already has leaves it where it is.
            if new_path == path:
                new_path = None
            if new_path is not None:
                # The patch does not show what the file holds, so the write at the new path has no content.
                # What an earlier call wrote to the old path is not carried to the new one either, which claims less than following the move.
                actions.append(WriteFileAction(new_path))
            actions.extend(
                EditFileAction(new_path or path, old, new)
                for old, new in _hunk_changes_from_lines(lines)
            )
            if new_path is not None:
                actions.append(DeleteFileAction(path))
    return actions


def _hunk_changes_from_lines(lines: list[str]) -> list[tuple[str, str]]:
    """List the old and new text of each hunk that changes something. Hunks start at `@@`."""
    hunks: list[list[str]] = [[]]
    for line in lines:
        if line.startswith("@@"):
            hunks.append([])
        else:
            hunks[-1].append(line)
    return [
        (
            "\n".join(line[1:] for line in hunk if line[:1] in (" ", "-", "")),
            "\n".join(line[1:] for line in hunk if line[:1] in (" ", "+", "")),
        )
        for hunk in hunks
        if any(line[:1] in ("+", "-") for line in hunk)
    ]
