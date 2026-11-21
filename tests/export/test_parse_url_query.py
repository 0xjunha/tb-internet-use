"""Tests for export/parse_url_query.py."""

import pytest

from tb_internet_use.export.parse_url_query import parse_url_query


@pytest.mark.parametrize(
    ("target", "host_name", "url_query"),
    [
        ("https://duckduckgo.com/?q=x", "duckduckgo.com", "q=x"),
        ("https://a.org/x?q=1&p=2#k", "a.org", "q=1&p=2"),
        # A query right after the host, also of a URL without a scheme.
        ("https://a.org?q=1", "a.org", "q=1"),
        ("a.org?q=1", "a.org", "q=1"),
        # A `?` in the fragment is no query.
        ("https://a.org/x#?q=1", "a.org", ""),
        # A URL without a query, also one with a `?` that nothing follows.
        ("https://pypi.org", "pypi.org", ""),
        ("https://www.google.com/", "www.google.com", ""),
        ("https://a.org/?", "a.org", ""),
        # The query of the direct reference of PEP 508 that pip reads.
        ("x@https://a.org/x.whl?sha=1", "a.org", "sha=1"),
    ],
)
def test_query_is_read_without_its_mark_and_fragment(
    target: str, host_name: str, url_query: str
):
    assert parse_url_query(target, host_name) == url_query


@pytest.mark.parametrize(
    ("target", "host_name"),
    [
        ("https://b.org/?q=x", "a.org"),
        ("git@github.com:a/b.git", "github.com"),
    ],
)
def test_word_that_names_no_url_of_the_host_gives_none(target: str, host_name: str):
    assert parse_url_query(target, host_name) is None
