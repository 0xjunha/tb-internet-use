"""Expand the uses of files that no call of the trajectory is known to have written, from the file touches that `expand_ran_texts` recorded for each call.

Such a file has no content in the trajectory, e.g. README.md of the task image in `cat README.md`, or a file that a program saved under a name the text does not show.
A line of a result that shows such a file is no trace of the call's own work, so the uses are listed for the later steps beside the uses of written files.
"""

from collections.abc import Sequence

from tb_internet_use.expanded_tool_call._expand_ran_texts import (
    FILE_USE_KIND_OF_FILE_TOUCH_KIND,
    FileTouch,
    RanTextsOfToolCall,
)
from tb_internet_use.expanded_tool_call.model import (
    FileUseWithoutKnownWriter,
)


def expand_file_uses_without_known_writer(
    ran_texts_of_tool_calls: Sequence[RanTextsOfToolCall],
) -> tuple[tuple[FileUseWithoutKnownWriter, ...], ...]:
    """Expand the uses of files without a known writer of each call, one tuple per call in the order of `ran_texts_of_tool_calls`.

    A use is a touch that shows, uses or names a file and meets no written file, apart from a read of the file where the harness saved a result, e.g. `cat /tmp/out1.txt`, which shows output and no file content.
    A call that did not run has no such touch, since `expand_ran_texts` records no use for it.
    """
    return tuple(
        _file_uses_without_known_writer_of(ran_texts_of_tool_call.file_touches)
        for ran_texts_of_tool_call in ran_texts_of_tool_calls
    )


def _file_uses_without_known_writer_of(
    file_touches: Sequence[FileTouch],
) -> tuple[FileUseWithoutKnownWriter, ...]:
    """Give the uses without a known writer among the file touches of one call, in touch order and once for each command, path and kind, e.g. one for `cat a a`."""
    file_uses_without_known_writer = (
        FileUseWithoutKnownWriter(
            file_touch.command_id,
            file_touch.path,
            FILE_USE_KIND_OF_FILE_TOUCH_KIND[file_touch.kind],
        )
        for file_touch in file_touches
        if file_touch.kind in FILE_USE_KIND_OF_FILE_TOUCH_KIND
        and not file_touch.written_file_keys
        and not file_touch.reads_harness_output_file
    )
    return tuple(dict.fromkeys(file_uses_without_known_writer))
