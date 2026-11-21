"""Read the query of the URL that a target word names, by the syntax of RFC 3986, so that a URL that asks a host for nothing but its first page can be told apart.

For example, `https://pypi.org` and `https://www.google.com/` have neither a path nor a query, while `https://duckduckgo.com/?q=x` asks a search with its query.
"""

import re

from tb_internet_use.export.parse_url_path import url_after_authority_of

# The text of a URL from its `?` up to its fragment, without the `?`.
_QUERY = re.compile(r"^[^?#]*\?([^#]*)")


def parse_url_query(target: str, host_name: str) -> str | None:
    """Read the query without its `?` and fragment of the URL that a target word names, found as `parse_url_path` finds it, e.g. `q=x` for `https://duckduckgo.com/?q=x#k` and `duckduckgo.com`.

    A URL without a query gives an empty text, e.g. `https://a.org/x` or `https://a.org/x#?q=1`, and so does a `?` that nothing follows, e.g. `https://a.org/?`.
    It returns None when the word names no URL of `host_name`, as `parse_url_path` does, e.g. `https://b.org/?q=x` for `a.org`.
    """
    after_authority = url_after_authority_of(target, host_name)
    if after_authority is None:
        return None
    query_match = _QUERY.match(after_authority)
    return query_match.group(1) if query_match else ""
