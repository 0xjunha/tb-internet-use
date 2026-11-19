"""Tests for network_request/parse_url.py."""

import pytest

from tb_internet_use.network_request.parse_url import parse_url


@pytest.mark.parametrize(
    ("url", "host_name"),
    [
        ("https://pypi.org/simple/x", "pypi.org"),
        ("http://user:pw@a.org:8080/x", "a.org"),
        ("http://[::1]:8000/x", "::1"),
        ("https://a.org?q=1", "a.org"),
        ("https://a.org#top", "a.org"),
        ("https://a.org:", "a.org"),
        # A scheme with a `+`, as pip writes a git address.
        ("git+https://github.com/a/b", "github.com"),
        # The host stays as written, so later code can tell it holds a template.
        ("https://$HOST/x", "$HOST"),
        ("https://PyPI.org/x", "PyPI.org"),
        # A templated port is still a port.
        ("http://localhost:$PORT/x", "localhost"),
        # A colon inside a template is no port.
        ("https://${HOST:-a.org}/x", "${HOST:-a.org}"),
    ],
)
def test_host_name_is_read_without_user_port_and_brackets(url: str, host_name: str):
    assert parse_url(url) == host_name


@pytest.mark.parametrize(
    "text",
    [
        "pypi.org/simple",
        "file:///tmp/x",
        "https://",
        # A scheme only later in the text is no URL that starts here.
        "x=https://a.org",
        # An IPv6 address whose bracket does not close.
        "http://[::1/x",
        # A backslash of an escaped quote in a code string, or of a regular expression.
        "https://example.com\\",
        "https://data\\.arcrail\\.eu/x",
    ],
)
def test_a_text_without_a_scheme_or_a_readable_host_gives_none(text: str):
    assert parse_url(text) is None
