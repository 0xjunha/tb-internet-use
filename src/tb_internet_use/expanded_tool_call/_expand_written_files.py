"""Expand the files that each tool call of a trial wrote, each with the later commands and tools that read or use it.

A file that a call wrote can carry what the call got to a later call, e.g. a.tgz of `curl -s -o a.tgz u` that `tar xzf a.tgz` unpacks later, or log of `curl u > log` that `cat log` shows later.
Which use belongs to which write is decided once by `TrialFileContents` as `expand_ran_texts` reads the calls in order, so this piece only gathers the file touches by the call that wrote the file.
"""

from collections.abc import Sequence

from tb_internet_use.expanded_tool_call._expand_ran_texts import (
    FILE_USE_KIND_OF_FILE_TOUCH_KIND,
    FileTouchKind,
    RanTextsOfToolCall,
    WrittenFileKey,
)
from tb_internet_use.expanded_tool_call.model import (
    FileUse,
    WrittenFile,
    WrittenFileWriter,
)
from tb_internet_use.tool_call.model import ToolCallKey


def expand_written_files(
    ran_texts_of_tool_calls: Sequence[RanTextsOfToolCall],
) -> tuple[tuple[WrittenFile, ...], ...]:
    """Expand the written files of each call with their writers and later uses, one tuple per call in the order of `ran_texts_of_tool_calls`.

    The writes of one call that share a `WrittenFileKey` make one `WrittenFile`, with one writer per write in the order of the file touches, e.g. both commands of `bash fetch.sh > log` when fetch.sh runs `curl a`.
    A call lists its written files in the order of their first writes.
    Each use is added to every written file of its `written_file_keys`, in call order and then in the order of the file touches of the using call.
    A use that repeats an earlier one of the same written file is kept once, e.g. `cat log log` after `curl u > log`.
    A removal is no use, so a touch of kind `DELETES` adds nothing.
    A call that did not run has written files too, since its writes say what its text writes, but `expand_ran_texts` records no uses for it and links no later use to its writes.
    """
    written_file_keys_of_tool_call: dict[ToolCallKey, list[WrittenFileKey]] = {
        ran_texts_of_tool_call.tool_call_key: []
        for ran_texts_of_tool_call in ran_texts_of_tool_calls
    }
    writers_of_written_file_key: dict[WrittenFileKey, list[WrittenFileWriter]] = {}
    file_uses_of_written_file_key: dict[WrittenFileKey, list[FileUse]] = {}
    for ran_texts_of_tool_call in ran_texts_of_tool_calls:
        for file_touch in ran_texts_of_tool_call.file_touches:
            if file_touch.kind == FileTouchKind.WRITES:
                (written_file_key,) = file_touch.written_file_keys
                if file_touch.channel is None:
                    raise ValueError(
                        f"write of {file_touch.path} in {written_file_key.tool_call_key} without a channel"
                    )
                if (
                    written_file_key.tool_call_key
                    != ran_texts_of_tool_call.tool_call_key
                ):
                    raise ValueError(
                        f"write of {file_touch.path} in {ran_texts_of_tool_call.tool_call_key} belongs to the written file of {written_file_key.tool_call_key}"
                    )
                if written_file_key not in writers_of_written_file_key:
                    written_file_keys_of_tool_call[
                        ran_texts_of_tool_call.tool_call_key
                    ].append(written_file_key)
                    writers_of_written_file_key[written_file_key] = []
                    file_uses_of_written_file_key[written_file_key] = []
                writers_of_written_file_key[written_file_key].append(
                    WrittenFileWriter(file_touch.command_id, file_touch.channel)
                )
            elif file_touch.kind == FileTouchKind.DELETES:
                # A removal neither writes the file nor shows or uses what it holds, so it gives no writer and no use. It ends the link to the write, which `TrialFileContents` has already applied to the later touches.
                continue
            else:
                file_use = FileUse(
                    ran_texts_of_tool_call.tool_call_key,
                    file_touch.command_id,
                    FILE_USE_KIND_OF_FILE_TOUCH_KIND[file_touch.kind],
                    file_touch.fits_several_written_files,
                )
                for written_file_key in file_touch.written_file_keys:
                    if written_file_key not in file_uses_of_written_file_key:
                        raise ValueError(
                            f"use of {file_touch.path} in {ran_texts_of_tool_call.tool_call_key} names a written file that no earlier write made"
                        )
                    file_uses_of_written_file_key[written_file_key].append(file_use)
    return tuple(
        tuple(
            WrittenFile(
                written_file_key.path,
                tuple(writers_of_written_file_key[written_file_key]),
                tuple(dict.fromkeys(file_uses_of_written_file_key[written_file_key])),
            )
            for written_file_key in written_file_keys_of_tool_call[
                ran_texts_of_tool_call.tool_call_key
            ]
        )
        for ran_texts_of_tool_call in ran_texts_of_tool_calls
    )
