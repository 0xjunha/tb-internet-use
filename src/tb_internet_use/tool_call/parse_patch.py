"""Read a patch of the `apply_patch` tool into the file changes it makes, without applying it.

Codex and Copilot CLI write a patch in the same notation, e.g. `*** Begin Patch`, then `*** Add File: a.txt` with `+` lines, `*** Update File: b.py` with `@@` hunks, or `*** Delete File: c.txt`, then `*** End Patch`.
"""

import re

from tb_internet_use.tool_call.model import (
    DeleteFileAction,
    EditFileAction,
    ToolCallAction,
    WriteFileAction,
)

_PATCH_FILE = re.compile(r"^\*\*\* (Add|Update|Delete) File: (.+)$", re.MULTILINE)
_MOVE_TO = "*** Move to: "


def parse_patch(patch: str) -> list[ToolCallAction]:
    """List the file changes of an apply_patch patch as ToolCallActions, in order.

    An added file is a write, each hunk that changes an updated file an edit, and a deleted file a DeleteFileAction, as for the delete tool of any harness.
    A hunk that changes nothing, which only places the next one, gives no ToolCallAction.
    A text without a file header gives an empty list.
    """
    actions: list[ToolCallAction] = []
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
            if lines and lines[0].startswith(_MOVE_TO):
                path = lines.pop(0).removeprefix(_MOVE_TO).strip()
            actions.extend(
                EditFileAction(path, old, new)
                for old, new in _hunk_changes_from_lines(lines)
            )
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
