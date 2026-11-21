"""Tests for export/parse_url_path.py."""

import pytest

from tb_internet_use.export.parse_url_path import parse_url_path


@pytest.mark.parametrize(
    ("target", "host_name", "url_path"),
    [
        ("https://a.org/x/y?q=1", "a.org", "/x/y"),
        ("https://huggingface.co/api/models?search=x", "huggingface.co", "/api/models"),
        ("https://a.org/x#top", "a.org", "/x"),
        ("https://a.org/x/", "a.org", "/x/"),
        # A user and a port sit before the path.
        ("http://user:pw@a.org:8080/x", "a.org", "/x"),
        ("http://[::1]:8000/x", "::1", "/x"),
        ("git+https://github.com/a/b", "github.com", "/a/b"),
        # The path stays as written, in its case and with its escapes.
        ("https://a.org/A%20b", "a.org", "/A%20b"),
        # A `/` in the query is no part of the path.
        ("https://a.org/x?next=/y", "a.org", "/x"),
        # A URL without a path, also one whose query or fragment follows the host.
        ("https://a.org", "a.org", ""),
        ("https://a.org?next=/y", "a.org", ""),
        ("https://a.org#/y", "a.org", ""),
        # A URL without a scheme, as curl reads it, also with a port or without a path.
        ("api.github.com/search/code?q=x", "api.github.com", "/search/code"),
        (
            "go.dev/dl/go1.22.0.linux-amd64.tar.gz",
            "go.dev",
            "/dl/go1.22.0.linux-amd64.tar.gz",
        ),
        ("localhost:8000/health", "localhost", "/health"),
        ("a.org", "a.org", ""),
        ("a.org?next=/y", "a.org", ""),
        # A URL without a scheme keeps its own host, not that of a URL in its query.
        ("a.org/r?to=https://b.org/x", "a.org", "/r"),
        # The direct reference of PEP 508 that pip reads.
        ("x@https://a.org/x.whl", "a.org", "/x.whl"),
        ("x[extra]@git+https://github.com/a/b", "github.com", "/a/b"),
    ],
)
def test_path_is_read_without_query_and_fragment(
    target: str, host_name: str, url_path: str
):
    assert parse_url_path(target, host_name) == url_path


@pytest.mark.parametrize(
    ("target", "host_name"),
    [
        # A URL without a host and an address as scp writes it.
        ("file:///tmp/x", "tmp"),
        ("git@github.com:a/b.git", "github.com"),
        # A host that `parse_url` does not read.
        ("http://[::1/x", "::1"),
        # A URL of another host, also when that host is in the query of a URL without a scheme.
        ("https://b.org/x", "a.org"),
        ("a.org/r?to=https://b.org/x", "b.org"),
    ],
)
def test_word_that_names_no_url_of_the_host_gives_none(target: str, host_name: str):
    assert parse_url_path(target, host_name) is None
