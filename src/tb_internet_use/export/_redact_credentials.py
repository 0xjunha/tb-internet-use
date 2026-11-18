"""Redact the credentials in a text of a row before the row is written, i.e. the userinfo of a URL and, by a judgment rule, the query values and fragment of a URL.

Rows go to spreadsheets that people share, while a target can carry a token, e.g. `git+https://ghp_xxx@github.com/a/b` or `https://a.org/x?token=abc`.
Redaction is done only here, so no other code of the rows hides or misses a credential on its own.
"""

import re
from collections import Counter

from tb_internet_use.export.judgment_rules import (
    treat_url_query_value_and_fragment_as_credential,
)

_REDACTED = "REDACTED"
_WHITESPACE = re.compile(r"(\s+)")
# The authority after `://` up to its last `@`, which the WHATWG URL Standard reads as the user name and password, so a password that holds `@` is hidden whole. The authority ends at the first `/`, `?` or `#`.
_URL_USERINFO = re.compile(r"://[^/?#]*@")
# A user name and password with no scheme at the start of a piece, e.g. `user:pw@a.org/x`, up to the last `@` before the first `/`, `?` or `#`.
_USERINFO_WITHOUT_SCHEME = re.compile(r"[^/@:]+:[^/?#]*@")


def redact_credentials(text: str, *, judgment_rule_use_counts: Counter[str]) -> str:
    """Redact the credentials in each piece of a text between whitespace, keeping the rest as written.

    The userinfo of a URL becomes `REDACTED`, e.g. `https://user:pw@a.org/x` becomes `https://REDACTED@a.org/x` and `user:pw@a.org/x` becomes `REDACTED@a.org/x`.
    A piece without a password, e.g. the address `git@github.com:a/b.git`, is no userinfo with no scheme and stays.
    The query values and fragment of a piece that holds `://` become `REDACTED` when `treat_url_query_value_and_fragment_as_credential` says so, which it is asked once for the text.
    A piece without `://` keeps its `?`, `=` and `#`, so the search words `how to x?` and the package `pkg==1.0` stay.
    Redacting a redacted text gives the same text.
    """
    pieces = [_redact_userinfo(piece) for piece in _WHITESPACE.split(text)]
    if any(map(_has_query_value_or_fragment, pieces)) and (
        treat_url_query_value_and_fragment_as_credential(
            text, use_counts=judgment_rule_use_counts
        )
    ):
        pieces = [_redact_query_values_and_fragment(piece) for piece in pieces]
    return "".join(pieces)


def _redact_userinfo(piece: str) -> str:
    """Replace the userinfo after each `://` of a piece, and a user name and password at its start, by `REDACTED`."""
    piece = _URL_USERINFO.sub(f"://{_REDACTED}@", piece)
    userinfo_without_scheme = _USERINFO_WITHOUT_SCHEME.match(piece)
    if userinfo_without_scheme is None:
        return piece
    return f"{_REDACTED}@{piece[userinfo_without_scheme.end() :]}"


def _has_query_value_or_fragment(piece: str) -> bool:
    """Answer whether a piece that holds `://` has a query value or a fragment that is not empty."""
    if "://" not in piece:
        return False
    _, query, fragment = _url_parts_of(piece)
    return bool(fragment) or any(
        value for _, value in _query_names_and_values_of(query)
    )


def _redact_query_values_and_fragment(piece: str) -> str:
    """Replace each query value and the fragment of a piece that holds `://` by `REDACTED`, keeping an empty one and the names of the values."""
    if "://" not in piece:
        return piece
    before_query, query, fragment = _url_parts_of(piece)
    redacted_query = "&".join(
        name if value is None else f"{name}={_REDACTED if value else ''}"
        for name, value in _query_names_and_values_of(query)
    )
    text = before_query
    if query is not None:
        text += f"?{redacted_query}"
    if fragment is not None:
        text += f"#{_REDACTED if fragment else ''}"
    return text


def _url_parts_of(piece: str) -> tuple[str, str | None, str | None]:
    """Split a piece that holds `://` into the text before its query, its query and its fragment, as RFC 3986 places them after the first `://`."""
    scheme_end = piece.index("://") + len("://")
    rest = piece[scheme_end:]
    rest, hash_mark, fragment = rest.partition("#")
    rest, question_mark, query = rest.partition("?")
    return (
        piece[:scheme_end] + rest,
        query if question_mark else None,
        fragment if hash_mark else None,
    )


def _query_names_and_values_of(query: str | None) -> list[tuple[str, str | None]]:
    """Split a query at `&` into its names and values, a value being `None` for a part without `=`, e.g. `flag` in `a=1&flag`."""
    if query is None:
        return []
    names_and_values: list[tuple[str, str | None]] = []
    for part in query.split("&"):
        name, equals_sign, value = part.partition("=")
        names_and_values.append((name, value if equals_sign else None))
    return names_and_values
