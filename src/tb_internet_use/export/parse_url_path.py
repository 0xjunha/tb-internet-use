"""Read the path of the URL that a target word names, by the syntax of RFC 3986, so that a host whose paths give different services can be looked up by it.

For example, `https://huggingface.co/api/models?search=x` has the path `/api/models`, which serves an API, while `https://huggingface.co/a/b/resolve/main/model.bin` serves a model file.
The URL can lack its scheme, since curl reads `api.github.com/search/code?q=x` as a URL of `api.github.com`, or follow a name, since pip reads the direct reference `x@https://a.org/x.whl` of PEP 508 as a URL of `a.org`.
"""

import re

from tb_internet_use.network_request.model import TargetNotation
from tb_internet_use.network_request.parse_target import URL_IN_WORD, parse_target
from tb_internet_use.network_request.parse_url import SCHEME_AND_SLASHES

# The character that ends the authority of a URL, i.e. the first `/`, `?` or `#` after the scheme, or from the start of a URL without a scheme.
_AUTHORITY_END = re.compile(r"[/?#]")
# The character that ends the path of a URL.
_PATH_END = re.compile(r"[?#]")


def parse_url_path(target: str, host_name: str) -> str | None:
    """Read the path without its query and fragment of the URL that a target word names, when `parse_target` reads `host_name` as the host of that URL, e.g. `/x/y` for `https://a.org/x/y?q=1` or `a.org/x/y?q=1` and `a.org`.

    A URL without a path gives an empty text, e.g. `https://a.org` or `a.org?q=1`.
    The URL is the whole word when `parse_target` reads a host from it as curl writes a URL, with or without a scheme, and otherwise the first URL with a scheme in the word, as `parse_target` finds it in a pip requirement, e.g. `https://a.org/x.whl` in `x@https://a.org/x.whl`.
    It returns None when the word names no such URL of `host_name`, e.g. `file:///tmp/x` without a host, `git@github.com:a/b.git` as scp writes it, or `https://b.org/x` for `a.org`.
    The path is kept as the trajectory writes it, in its case and with its escapes, e.g. `/A%20b` for `https://a.org/A%20b`.
    """
    url = _url_of_target(target)
    if (
        url is None
        or parse_target(url, TargetNotation.URL_OR_SCHEMELESS_URL).host_name
        != host_name
    ):
        return None
    scheme_match = SCHEME_AND_SLASHES.match(url)
    after_scheme = url[scheme_match.end() :] if scheme_match else url
    authority_end_match = _AUTHORITY_END.search(after_scheme)
    if authority_end_match is None or authority_end_match.group() != "/":
        return ""
    return _PATH_END.split(after_scheme[authority_end_match.start() :], maxsplit=1)[0]


def _url_of_target(target: str) -> str | None:
    """Find the URL that a target word names, the word itself when it reads as a URL with or without a scheme, else its first URL with a scheme, e.g. `https://a.org/x.whl` in `x@https://a.org/x.whl`."""
    if parse_target(target, TargetNotation.URL_OR_SCHEMELESS_URL).host_name is not None:
        return target
    url_match = URL_IN_WORD.search(target)
    return url_match.group() if url_match else None
