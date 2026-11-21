"""Tests for export/parse_url_path.py."""

import pytest

from tb_internet_use.export.parse_url_path import parse_url_path


@pytest.mark.parametrize(
    ("url", "url_path"),
    [
        ("https://a.org/x/y?q=1", "/x/y"),
        ("https://huggingface.co/api/models?search=x", "/api/models"),
        ("https://a.org/x#top", "/x"),
        ("https://a.org/x/", "/x/"),
        # A user and a port sit before the path.
        ("http://user:pw@a.org:8080/x", "/x"),
        ("http://[::1]:8000/x", "/x"),
        ("git+https://github.com/a/b", "/a/b"),
        # The path stays as written, in its case and with its escapes.
        ("https://a.org/A%20b", "/A%20b"),
        # A `/` in the query is no part of the path.
        ("https://a.org/x?next=/y", "/x"),
        # A URL without a path, also one whose query or fragment follows the host.
        ("https://a.org", ""),
        ("https://a.org?next=/y", ""),
        ("https://a.org#/y", ""),
    ],
)
def test_path_is_read_without_query_and_fragment(url: str, url_path: str):
    assert parse_url_path(url) == url_path


@pytest.mark.parametrize(
    "text",
    [
        # A URL without a scheme, without a host and as scp writes it.
        "pypi.org/simple",
        "file:///tmp/x",
        "git@github.com:a/b.git",
        # A host that `parse_url` does not read.
        "http://[::1/x",
    ],
)
def test_url_whose_host_cannot_be_read_gives_none(text: str):
    assert parse_url_path(text) is None
