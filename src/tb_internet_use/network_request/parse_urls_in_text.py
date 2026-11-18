"""Read the `http://` and `https://` URLs written anywhere in a text, e.g. in the words of a command or in code.

A program or a code call that no fact covers can still show a URL, e.g. `mytool https://a.org/x`, and only such a URL can make the request uncertain instead of absent.
"""

import re

# A URL with an http or https scheme, ending before a space, a quote, a backtick, an angle bracket or a closing bracket, e.g. `https://a.org/x` in `"https://a.org/x"`.
# A braced variable is taken whole, so `https://${HOST}/x` keeps its `}`.
_URL = re.compile(r"""https?://(?:\$?\{[^{}\s]*\}|[^\s'"<>`)\]}])+""")


def parse_urls_in_text(text: str) -> tuple[str, ...]:
    """Read the `http://` and `https://` URLs of a text in the order they appear, each once, e.g. `https://a.org/x` once for `curl https://a.org/x https://a.org/x`.

    A URL ends before whitespace, a quote, a backtick, `<`, `>`, `)`, `]` or `}`, so `(see https://a.org/x)` gives `https://a.org/x`.
    A `}` that closes a braced variable stays in the URL, e.g. `https://github.com/${REPO}/a.tgz`.
    Other punctuation stays in the URL, e.g. the comma of `https://a.org/x,`, since it can be part of a URL.
    A host without a scheme, e.g. `pypi.org/simple`, is no URL here.
    """
    return tuple(dict.fromkeys(_URL.findall(text)))
