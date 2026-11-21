"""Read the path of a URL that has a scheme, by the syntax of RFC 3986, so that a host whose paths give different services can be looked up by it.

For example, `https://huggingface.co/api/models?search=x` has the path `/api/models`, which serves an API, while `https://huggingface.co/a/b/resolve/main/model.bin` serves a model file.
"""

import re

from tb_internet_use.network_request.parse_url import SCHEME_AND_SLASHES, parse_url

# The character that ends the authority of a URL, i.e. the first `/`, `?` or `#` after the scheme.
_AUTHORITY_END = re.compile(r"[/?#]")
# The character that ends the path of a URL.
_PATH_END = re.compile(r"[?#]")


def parse_url_path(url: str) -> str | None:
    """Read the path of a URL without its query and fragment, e.g. `/x/y` for `https://a.org/x/y?q=1`, and an empty text for a URL without a path, e.g. `https://a.org` or `https://a.org?q=1`.

    It returns None for a URL whose host `parse_url` cannot read, e.g. `pypi.org/simple` without a scheme, `file:///tmp/x` without a host or `git@github.com:a/b.git` as scp writes it.
    The path is kept as the trajectory writes it, in its case and with its escapes, e.g. `/A%20b` for `https://a.org/A%20b`.
    """
    scheme_match = SCHEME_AND_SLASHES.match(url)
    if scheme_match is None or parse_url(url) is None:
        return None
    after_scheme = url[scheme_match.end() :]
    authority_end_match = _AUTHORITY_END.search(after_scheme)
    if authority_end_match is None or authority_end_match.group() != "/":
        return ""
    return _PATH_END.split(after_scheme[authority_end_match.start() :], maxsplit=1)[0]
