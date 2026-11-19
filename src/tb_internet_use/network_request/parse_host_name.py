"""Read whether a host name is public, local or reserved by the standards alone, and give the form of a name that they do not settle.

The standards are the address blocks of IPv4 and IPv6 that `ipaddress` does not read as global, i.e. the shared block `100.64.0.0/10` of RFC 6598 and the blocks it reads as private, e.g. the loopback, link-local and unspecified blocks.
They also name `localhost` and the reserved names of RFC 6761, the example names of RFC 2606, and the `.local` name of RFC 6762.
`.internal` is read as local too, since ICANN set it aside for private networks in 2024.
A name such as `files.acme.org` or `db` is in no such list, so whether it is public is a choice of `judgment_rules.py`.
"""

import ipaddress
import re

from tb_internet_use.network_request.model import (
    HostNameScope,
    UnknownHostNameScope,
    UnknownHostNameScopeReason,
)

# A character that a shell or code template computes, e.g. `$` in `$HOST` or `{` in `{host}.org`.
TEMPLATE_CHARACTER = re.compile(r"[${}]")
# Names that resolve to this machine or its private network, e.g. `localhost`, `app.localhost`, `printer.local` or `db.internal`.
_LOCAL_NAME = re.compile(r"(?:^|\.)(?:localhost|local|internal)$")
# Names reserved for examples and tests by RFC 2606 and RFC 6761, e.g. `example.com`, `api.example.org` or `x.test`.
_RESERVED_NAME = re.compile(
    r"(?:^|\.)(?:example\.(?:com|net|org)|example|test|invalid)$"
)


def parse_host_name(host_name: str) -> HostNameScope | UnknownHostNameScope:
    """Read the scope of a host name, ignoring case, IPv6 brackets and one trailing dot, e.g. LOCAL for `127.0.0.1`, RESERVED for `example.com` and PUBLIC for `8.8.8.8`.

    A trailing dot only marks a name as fully qualified by RFC 1034, so `example.com.` reads as `example.com` and `localhost.` as `localhost`.
    An IP address is PUBLIC only when `ipaddress` reads it as global, so the shared block `100.64.0.0/10` of RFC 6598 is LOCAL although it is not private.
    A name that holds `$`, `{` or `}` is TEMPLATED, since its value is set when the command runs.
    `0` is LOCAL, since tools read it as `0.0.0.0`, e.g. `curl 0:8000`.
    Any other name is DOTTED_NAME when it holds a dot and SINGLE_LABEL when it does not.
    """
    host_name = host_name.lower().strip("[]").removesuffix(".")
    if TEMPLATE_CHARACTER.search(host_name):
        return UnknownHostNameScope(UnknownHostNameScopeReason.TEMPLATED)
    try:
        address = ipaddress.ip_address(host_name)
    except ValueError:
        return _host_name_scope_of_name(host_name)
    # An address that is not global is private, loopback, link-local, unspecified or shared, e.g. `::1`, `169.254.169.254`, `0.0.0.0` or `100.64.0.1`.
    if address.is_global:
        return HostNameScope.PUBLIC
    return HostNameScope.LOCAL


def _host_name_scope_of_name(
    host_name: str,
) -> HostNameScope | UnknownHostNameScope:
    """Find the scope of a lower-case host name that is no IP address, e.g. LOCAL for `db.internal` and SINGLE_LABEL for `db`."""
    if _LOCAL_NAME.search(host_name) or host_name == "0":
        return HostNameScope.LOCAL
    if _RESERVED_NAME.search(host_name):
        return HostNameScope.RESERVED
    if "." in host_name:
        return UnknownHostNameScope(UnknownHostNameScopeReason.DOTTED_NAME)
    return UnknownHostNameScope(UnknownHostNameScopeReason.SINGLE_LABEL)
