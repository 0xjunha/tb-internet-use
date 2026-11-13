"""Tests for callrun/written_files.py."""

import pytest

from tb_internet_use.callrun.written_files import WrittenFiles
from tb_internet_use.shell import parse_shell
from tb_internet_use.toolcall.model import EditFileAction, ToolCallKey, WriteFileAction

FIRST = ToolCallKey("trial", "main", 1, 0)
SECOND = ToolCallKey("trial", "main", 2, 0)


def _files_after(*texts: str) -> WrittenFiles:
    """The written files after commands of the texts ran, each text in the second call."""
    files = WrittenFiles()
    files.record_tool_step(WriteFileAction("/app/f.sh", "curl u\n"), FIRST)
    for text in texts:
        for command in parse_shell(text).commands:
            files.record_command(command, SECOND)
    return files


@pytest.mark.parametrize(
    ("text", "content"),
    [
        ("ls", "curl u\n"),
        ("cat > f.sh <<EOF\nwget v\nEOF", "wget v\n"),
        ("cat >> f.sh <<EOF\nwget v\nEOF", "curl u\nwget v\n"),
        ("tee f.sh <<EOF\nwget v\nEOF", "wget v\n"),
        ("tee -a f.sh <<EOF\nwget v\nEOF", "curl u\nwget v\n"),
        ("echo 'wget v' > f.sh", None),
        ("generate | tee f.sh", None),
        ("sed -i 's/curl/wget/' f.sh", None),
        ("sed -n 1p f.sh", "curl u\n"),
    ],
)
def test_content_after_a_command(text: str, content: str | None):
    write = _files_after(text).latest_write("f.sh")
    assert write is not None and write.content == content


def test_sed_script_is_no_file():
    files = _files_after("sed -i -e 's/a/b/' -e 's/c/d/' x.sh")
    assert files.latest_write("x.sh") is not None
    assert files.latest_write("s/a/b/") is None


@pytest.mark.parametrize(
    ("old", "new", "content"),
    [
        ("curl", "wget", "wget u\n"),
        ("absent", "x", None),
        ("u", "v", None),  # occurs twice
    ],
)
def test_edit_applies_only_where_the_old_text_occurs_once(
    old: str, new: str, content: str | None
):
    files = WrittenFiles()
    files.record_tool_step(WriteFileAction("f.sh", "curl u\n"), FIRST)
    files.record_tool_step(EditFileAction("f.sh", old, new), SECOND)
    write = files.latest_write("f.sh")
    assert write is not None and (write.content, write.written_by) == (content, SECOND)


def test_edit_of_an_unwritten_file_gives_unknown_content():
    files = WrittenFiles()
    files.record_tool_step(EditFileAction("f.sh", "a", "b"), FIRST)
    write = files.latest_write("f.sh")
    assert write is not None and write.content is None


def test_a_path_that_names_several_written_files_gives_unknown_content():
    files = WrittenFiles()
    files.record_tool_step(WriteFileAction("/app/a/run.sh", "curl u"), FIRST)
    files.record_tool_step(WriteFileAction("/app/b/run.sh", "wget v"), SECOND)
    write = files.latest_write("run.sh")
    assert write is not None and (write.content, write.written_by) == (None, SECOND)
    one = files.latest_write("a/run.sh")
    assert one is not None and one.content == "curl u"
