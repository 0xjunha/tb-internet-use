"""Read the host name of a URL that has a scheme, by the authority syntax of RFC 3986.

A URL can carry a user, a password and a port around its host, e.g. `http://user:pw@a.org:8080/x`, and only the host is written as a host of a request.
The host is kept as the trajectory writes it, so `https://$HOST/x` gives `$HOST`.
"""

import re

from tb_internet_use.network_request.parse_host_name import TEMPLATE_CHARACTER

# A scheme as RFC 3986 writes it, with the `//` that opens an authority, e.g. `https://` or `git+ssh://`.
SCHEME_AND_SLASHES = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")
# A character that RFC 3986 allows nowhere in a URL, and so in no host.
_BACKSLASH = "\\"


def parse_url(url: str) -> str | None:
    """Read the host name of a URL, without its user, its port and the brackets of an IPv6 address, e.g. `a.org` for `http://user:pw@a.org:8080/x`.

    It returns None when the text does not start with a scheme and `//`, e.g. `pypi.org/simple`, or names no host, e.g. `file:///tmp/x`.
    It also returns None for an IPv6 address whose bracket does not close, e.g. `http://[::1/x`, since its host cannot be read.
    It returns None for a host with a backslash too, which no host name or address holds, e.g. `example.com\\` of `href=\\"https://example.com\\"` in a code string or `data\\.arcrail\\.eu` of a regular expression, since the text around the URL is escaped and the host it stands for is not read here.
    The last colon and what follows it are the port, also when the port is a template, so `http://localhost:$PORT/x` gives `localhost`.
    A colon stays in the host when the text before it holds a template character, so `${HOST:-a.org}` is kept whole.
    """
    scheme_match = SCHEME_AND_SLASHES.match(url)
    if scheme_match is None:
        return None
    authority = re.split(r"[/?#]", url[scheme_match.end() :], maxsplit=1)[0]
    host_and_port = authority.rsplit("@", 1)[-1]
    if host_and_port.startswith("["):
        if "]" not in host_and_port:
            return None
        host_name = host_and_port[1:].split("]", 1)[0]
    else:
        host_name = _host_name_without_port(host_and_port)
    if _BACKSLASH in host_name:
        return None
    return host_name or None


def _host_name_without_port(host_and_port: str) -> str:
    """Find the host before the port of an authority without brackets, e.g. `localhost` for `localhost:$PORT` and `${HOST:-a.org}` for itself."""
    host_name, colon, _ = host_and_port.rpartition(":")
    if not colon or TEMPLATE_CHARACTER.search(host_name):
        return host_and_port
    return host_name
