"""Tests for network_request/parse_urls_in_text.py."""

import pytest

from tb_internet_use.network_request.parse_urls_in_text import parse_urls_in_text


@pytest.mark.parametrize(
    ("text", "urls"),
    [
        pytest.param(
            "curl https://a.org/x http://b.org:8080/y?q=1#z",
            ("https://a.org/x", "http://b.org:8080/y?q=1#z"),
            id="several URLs in order",
        ),
        pytest.param(
            "mytool https://a.org/x https://b.org https://a.org/x",
            ("https://a.org/x", "https://b.org"),
            id="a repeated URL once",
        ),
        pytest.param(
            """requests.get("https://a.org/x", headers={'Referer': 'https://b.org'})""",
            ("https://a.org/x", "https://b.org"),
            id="URLs in double and single quotes",
        ),
        pytest.param(
            "`https://a.org/x` <https://b.org/y> [see](https://c.org/z) {https://d.org}",
            ("https://a.org/x", "https://b.org/y", "https://c.org/z", "https://d.org"),
            id="URLs in backticks and brackets",
        ),
        pytest.param(
            "mytool https://github.com/${REPO}/a.tgz https://${HOST}/x",
            ("https://github.com/${REPO}/a.tgz", "https://${HOST}/x"),
            id="a braced variable stays whole",
        ),
        pytest.param(
            """{"u":"https://a.org/x"}""",
            ("https://a.org/x",),
            id="a URL in JSON-like text ends before its quote",
        ),
        pytest.param(
            "see https://a.org/x, then https://b.org/y.",
            ("https://a.org/x,", "https://b.org/y."),
            id="a trailing comma or period stays in the URL",
        ),
        pytest.param(
            "x=https://a.org/x;git+https://github.com/a/b",
            ("https://a.org/x;git+https://github.com/a/b",),
            id="a URL inside a word runs to the next stop character",
        ),
        pytest.param(
            "pip install -i pypi.org/simple x; git clone git@github.com:a/b.git",
            (),
            id="hosts without a scheme are no URLs",
        ),
        pytest.param(
            "ftp://a.org/x file:///tmp/x HTTPS://A.ORG/x https://",
            (),
            id="other schemes, an upper-case scheme and a scheme alone are no URLs",
        ),
        pytest.param("echo hello", (), id="text without a URL"),
    ],
)
def test_parse_urls_in_text(text: str, urls: tuple[str, ...]):
    assert parse_urls_in_text(text) == urls
