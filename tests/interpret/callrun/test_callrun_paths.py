"""Tests for interpret/callrun/_paths.py."""

import pytest

from tb_internet_use.interpret.callrun._paths import can_name_same_file


@pytest.mark.parametrize(
    ("path", "other_path", "same"),
    [
        ("fetch.log", "fetch.log", True),
        ("./fetch.log", "fetch.log", True),
        ("fetch.log", "/app/fetch.log", True),
        ("/app/fetch.log", "logs/../fetch.log", True),
        ("out/fetch.log", "/app/out/fetch.log", True),
        ("$LOG/fetch.log", "/tmp/fetch.log", True),
        ("~/fetch.log", "/root/fetch.log", True),
        ("/app/fetch.log", "/tmp/fetch.log", False),  # two absolute paths
        ("a/fetch.log", "b/fetch.log", False),
        ("a/fetch.log", "/app/b/fetch.log", False),  # never by the base name alone
        (
            "/fetch.log",
            "app/fetch.log",
            False,
        ),  # an absolute path cannot end a relative one
        ("$LOG", "/tmp/fetch.log", False),  # a directory alone names no file
        ("fetch.log", "fetch.log.1", False),
    ],
)
def test_can_name_same_file(path: str, other_path: str, same: bool):
    assert can_name_same_file(path, other_path) == same
    assert can_name_same_file(other_path, path) == same
