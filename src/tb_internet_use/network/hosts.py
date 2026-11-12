"""Make hosts from the names and URLs that candidate requests and output lines hold, with the kind each name shows."""

import ipaddress
import re

from tb_internet_use.network.model import Host, HostKind

# A character that a shell or code template computes, e.g. $ in `$HOST` or { in `{host}`.
_TEMPLATE_CHARACTER = re.compile(r"[${}]")
# Names that resolve to this machine or its private network, e.g. localhost or db.internal.
_LOCAL_NAME = re.compile(r"(?:^|\.)(?:localhost|local|internal)$")
# Names reserved for examples and tests by RFC 2606 and RFC 6761, e.g. example.com or x.test.
_RESERVED_NAME = re.compile(
    r"(?:^|\.)(?:example\.(?:com|net|org)|example|test|invalid)$"
)


def host_from_name(name: str) -> Host:
    """Make a host from a name, lower case and without brackets, with its kind."""
    normalized_name = name.lower().strip("[]")
    return Host(normalized_name, _host_kind(normalized_name))


def host_name_in_url(url: str) -> str | None:
    """Take the host name from a URL that has a scheme, without user, port and brackets."""
    if "://" not in url:
        return None
    authority = re.split(r"[/?#]", url.split("://", 1)[1], maxsplit=1)[0]
    host_and_port = authority.rsplit("@", 1)[-1]
    if host_and_port.startswith("["):  # an IPv6 address, e.g. `[::1]:8000`
        host_name = host_and_port[1:].split("]", 1)[0]
    else:
        host_name = host_and_port.split(":", 1)[0]
    return host_name or None


def _host_kind(name: str) -> HostKind:
    """Judge a host's kind by its name alone, e.g. LOCAL for 127.0.0.1 and RESERVED for example.com."""
    if _TEMPLATE_CHARACTER.search(name):
        return HostKind.TEMPLATED
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        # 0 is short for 0.0.0.0, e.g. in `curl 0:8000`.
        if _LOCAL_NAME.search(name) or name == "0":
            return HostKind.LOCAL
        if _RESERVED_NAME.search(name):
            return HostKind.RESERVED
        return HostKind.PUBLIC if "." in name else HostKind.SINGLE_LABEL
    is_local = (
        address.is_private
        or address.is_loopback
        or address.is_unspecified
        or address.is_link_local
    )
    return HostKind.LOCAL if is_local else HostKind.PUBLIC
