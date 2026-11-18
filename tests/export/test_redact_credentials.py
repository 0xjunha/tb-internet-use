"""Tests for _redact_credentials.py, with made-up credentials that match no real key."""

from collections import Counter

import pytest

from tb_internet_use.export import _redact_credentials
from tb_internet_use.export._redact_credentials import redact_credentials

RULE = "treat_url_query_value_and_fragment_as_credential"

# (text, redacted text, uses of the rule)
CASES = [
    # The userinfo of a URL, with and without a scheme.
    ("https://user:pass@a.org/x", "https://REDACTED@a.org/x", 0),
    ("user:pass@a.org/x", "REDACTED@a.org/x", 0),
    # A password that holds `@` is hidden up to the last `@` of the authority.
    ("https://user:p@ss@a.org/x", "https://REDACTED@a.org/x", 0),
    # The query values and the fragment, whatever their names.
    (
        "https://a.org/x?token=sk-test-xxxx&page=2#frag",
        "https://a.org/x?token=REDACTED&page=REDACTED#REDACTED",
        1,
    ),
    ("https://duckduckgo.com/html?q=x", "https://duckduckgo.com/html?q=REDACTED", 1),
    # An `@` in a query value is no userinfo, since the authority ends at `?`.
    ("https://a.org?mail=a@b.org", "https://a.org?mail=REDACTED", 1),
    # A `?` in the fragment belongs to the fragment.
    ("https://a.org/x#a?b=c", "https://a.org/x#REDACTED", 1),
    # Empty values, a part without `=` and an empty fragment have nothing to hide.
    ("https://a.org/x?a=&flag&b=1#", "https://a.org/x?a=&flag&b=REDACTED#", 1),
    ("https://a.org/x?", "https://a.org/x?", 0),
    # Several URLs in one text are one use, and the whitespace between pieces stays.
    (
        "curl  https://a.org/x?k=v\thttps://u:p@b.org/y#k",
        "curl  https://a.org/x?k=REDACTED\thttps://REDACTED@b.org/y#REDACTED",
        1,
    ),
    # A piece without `://` keeps its query.
    ("a.org/x?token=abc", "a.org/x?token=abc", 0),
    # A token as the user name after a scheme with `+` inside a piece is hidden once, and the text before it stays.
    (
        "name@git+https://ghp_xxxxxxxxxxxxxxxxxxxx@github.com/a/b",
        "name@git+https://REDACTED@github.com/a/b",
        0,
    ),
    # A password that holds `@` with no scheme is hidden up to the last `@`.
    ("u:p@ss@a.org/x", "REDACTED@a.org/x", 0),
    # A URL in a query value belongs to the value, since the query starts at the first `?`.
    (
        "https://a.org/x?next=https://b.org/y?k=v",
        "https://a.org/x?next=REDACTED",
        1,
    ),
    # An npm alias has the shape of a userinfo with no scheme and is hidden, since a narrower shape would rest on no count of the data.
    ("npm:react@18", "REDACTED@18", 0),
    # A closing quote after a query value is taken into the value and hidden with it.
    ("'https://a.org/x?k=v'", "'https://a.org/x?k=REDACTED", 1),
    # The text after whitespace inside a URL is a piece of its own and stays as written.
    (
        "https://a.org/search?q=hello world&token=abc#frag",
        "https://a.org/search?q=REDACTED world&token=abc#frag",
        1,
    ),
]

# Texts of rows that hold no credential.
TEXTS_LEFT_ALONE = [
    "requests",
    "how to x?",
    "pkg==1.0",
    "numpy==1.26.4",
    "https://a.org/x",
    # An `@` in a path is no userinfo, since the authority ends at `/`.
    "https://www.npmjs.com/package/@types/node",
    # An scp address has no password, so it is no userinfo without a scheme.
    "git@github.com:a/b.git",
    # An `@` after the query of an address with a port and no scheme is no userinfo, since the authority ends at `?`.
    "a.org:8080?mail=a@b.org",
    "git checkout 3f2a9c1e5b7d8a0c4e6f1b2d3a4c5e6f7a8b9c0d",
    "command 2 in /home/u/fetch.sh written by call 11.0",
]


@pytest.mark.parametrize(("text", "redacted_text", "rule_use_count"), CASES)
def test_credentials_are_redacted_and_the_rule_is_counted_once_per_text(
    text: str, redacted_text: str, rule_use_count: int
):
    judgment_rule_use_counts: Counter[str] = Counter()

    assert (
        redact_credentials(text, judgment_rule_use_counts=judgment_rule_use_counts)
        == redacted_text
    )
    assert judgment_rule_use_counts == Counter({RULE: rule_use_count})


@pytest.mark.parametrize("text", TEXTS_LEFT_ALONE)
def test_texts_without_credentials_are_left_alone(text: str):
    judgment_rule_use_counts: Counter[str] = Counter()

    assert (
        redact_credentials(text, judgment_rule_use_counts=judgment_rule_use_counts)
        == text
    )
    assert not judgment_rule_use_counts


@pytest.mark.parametrize("text", [text for text, _, _ in CASES] + TEXTS_LEFT_ALONE)
def test_redacting_twice_gives_what_redacting_once_gives(text: str):
    judgment_rule_use_counts: Counter[str] = Counter()
    redacted_text = redact_credentials(
        text, judgment_rule_use_counts=judgment_rule_use_counts
    )

    assert (
        redact_credentials(
            redacted_text, judgment_rule_use_counts=judgment_rule_use_counts
        )
        == redacted_text
    )


def test_query_values_and_fragment_stay_when_the_rule_says_no(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        _redact_credentials,
        "treat_url_query_value_and_fragment_as_credential",
        lambda text, *, use_counts: False,
    )

    assert (
        redact_credentials(
            "https://u:p@a.org/x?token=abc#k", judgment_rule_use_counts=Counter()
        )
        == "https://REDACTED@a.org/x?token=abc#k"
    )


def test_userinfo_without_scheme_after_a_name_and_at_sign_is_left_as_written():
    assert (
        redact_credentials("name@user:pw@a.org/x", judgment_rule_use_counts=Counter())
        == "name@user:pw@a.org/x"
    )
