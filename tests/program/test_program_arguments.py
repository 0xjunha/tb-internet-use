"""Tests for program/arguments.py."""

import pytest

from tb_internet_use.program.arguments import file_arguments, parse_arguments


@pytest.mark.parametrize(
    ("program", "arguments", "options", "plain"),
    [
        (
            "curl",
            "-fsSL -o out u",
            [("-f", None), ("-s", None), ("-S", None), ("-L", None), ("-o", "out")],
            ["u"],
        ),
        (
            "curl",
            "-sSLoout u",
            [("-s", None), ("-S", None), ("-L", None), ("-o", "out")],
            ["u"],
        ),
        ("curl", "--output=out u", [("--output", "out")], ["u"]),
        ("curl", "-H a:b u -- -x", [("-H", "a:b")], ["u", "-x"]),
        ("curl", "--url-query a=b u", [("--url-query", "a=b")], ["u"]),
        (
            "pip",
            "install --timeout 60 x",
            [("--timeout", "60")],
            ["install", "x"],
        ),
        (
            "pip",
            "install --extra-index-url https://e.org -r reqs.txt x",
            [("--extra-index-url", "https://e.org"), ("-r", "reqs.txt")],
            ["install", "x"],
        ),
        ("tail", "-n 5 log", [("-n", "5")], ["log"]),
        ("head", "-$n log", [("-$n", None)], ["log"]),
        ("cat", "- log", [], ["-", "log"]),
        ("wget", "-qO- u", [("-q", None), ("-O", "-")], ["u"]),
        # Words after the file go to the code, so -c is no inline code here.
        ("python", "-u get.py -c cfg", [("-u", None)], ["get.py", "-c", "cfg"]),
        ("python", "-uc code x", [("-u", None), ("-c", "code")], ["x"]),
        ("node", "-pe code", [("-pe", "code")], []),
        # -pe is one option only in node.
        ("curl", "-pe u", [("-p", None), ("-e", None)], ["u"]),
        ("pip", "download -d out x", [("-d", "out")], ["download", "x"]),
    ],
)
def test_parse_arguments(program: str, arguments: str, options: list, plain: list[str]):
    parsed = parse_arguments(program, tuple(arguments.split()))
    assert list(parsed.options) == options
    assert list(parsed.plain_arguments) == plain


@pytest.mark.parametrize(
    ("program", "arguments", "files"),
    [
        ("grep", "-n error log", ["log"]),
        ("grep", "-e error -e warn log", ["log"]),
        ("sed", "-i s/a/b/ f g", ["f", "g"]),
        ("sed", "-i -e s/a/b/ f", ["f"]),
        ("tail", "-n 5 -f log", ["log"]),
        ("cat", "a b", ["a", "b"]),
    ],
)
def test_file_arguments(program: str, arguments: str, files: list[str]):
    parsed = parse_arguments(program, tuple(arguments.split()))
    assert list(file_arguments(program, parsed)) == files
