"""Read whether a host name is public, local or reserved by the standards alone, and give the form of a name that they do not settle.

The standards are the address blocks of IPv4 and IPv6 that `ipaddress` does not read as global, i.e. the shared block `100.64.0.0/10` of RFC 6598 and the blocks it reads as private, e.g. the loopback, link-local and unspecified blocks.
They also name `localhost` and the reserved names of RFC 6761, the example names of RFC 2606, and the `.local` name of RFC 6762.
`.internal` is read as local too, since ICANN set it aside for private networks in 2024.
An IPv4 address may be written in the short forms that `inet_aton` of POSIX reads, e.g. `127.1` for `127.0.0.1`, since the resolvers of the C library and tools such as curl read a host that way.
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
# An IPv4 address of one to three decimal parts as `inet_aton` reads it, the last part filling the remaining bytes, e.g. `0` for `0.0.0.0` or `127.0.1` for `127.0.0.1`.
# A part with a leading zero is octal there and a part with `0x` hexadecimal, and neither is read, since no host in the trajectories is written so.
_SHORT_IPV4_ADDRESS = re.compile(r"(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){0,2}")
# Names reserved for examples and tests by RFC 2606 and RFC 6761, e.g. `example.com`, `api.example.org` or `x.test`.
_RESERVED_NAME = re.compile(
    r"(?:^|\.)(?:example\.(?:com|net|org)|example|test|invalid)$"
)


def parse_host_name(host_name: str) -> HostNameScope | UnknownHostNameScope:
    """Read the scope of a host name, ignoring case, IPv6 brackets and one trailing dot, e.g. LOCAL for `127.0.0.1`, RESERVED for `example.com` and PUBLIC for `8.8.8.8`.

    A trailing dot only marks a name as fully qualified by RFC 1034, so `example.com.` reads as `example.com` and `localhost.` as `localhost`.
    An IP address is PUBLIC only when `ipaddress` reads it as global, so the shared block `100.64.0.0/10` of RFC 6598 is LOCAL although it is not private.
    A name that holds `$`, `{` or `}` is TEMPLATED, since its value is set when the command runs.
    A short form of an IPv4 address is read as the address, so `0` is LOCAL as `0.0.0.0`, e.g. `curl 0:8000`, and `127.0.1` as `127.0.0.1`.
    Any other name is DOTTED_NAME when it holds a dot and SINGLE_LABEL when it does not.
    """
    host_name = host_name.lower().strip("[]").removesuffix(".")
    if TEMPLATE_CHARACTER.search(host_name):
        return UnknownHostNameScope(UnknownHostNameScopeReason.TEMPLATED)
    try:
        address = ipaddress.ip_address(host_name)
    except ValueError:
        address = _ipv4_address_of_short_form(host_name)
    if address is None:
        return _host_name_scope_of_name(host_name)
    # An address that is not global is private, loopback, link-local, unspecified or shared, e.g. `::1`, `169.254.169.254`, `0.0.0.0` or `100.64.0.1`.
    if address.is_global:
        return HostNameScope.PUBLIC
    return HostNameScope.LOCAL


def _ipv4_address_of_short_form(host_name: str) -> ipaddress.IPv4Address | None:
    """Find the IPv4 address that a short form writes, e.g. `127.0.0.1` for `127.0.1`, or None when the name is no short form or a part is too large, e.g. `300.1`."""
    if not _SHORT_IPV4_ADDRESS.fullmatch(host_name):
        return None
    *leading_parts, last_part = (int(part) for part in host_name.split("."))
    last_part_length = 4 - len(leading_parts)
    if any(part > 255 for part in leading_parts) or last_part >= 256**last_part_length:
        return None
    return ipaddress.IPv4Address(
        bytes(leading_parts) + last_part.to_bytes(last_part_length, "big")
    )


def _host_name_scope_of_name(
    host_name: str,
) -> HostNameScope | UnknownHostNameScope:
    """Find the scope of a lower-case host name that is no IP address, e.g. LOCAL for `db.internal` and SINGLE_LABEL for `db`."""
    if _LOCAL_NAME.search(host_name):
        return HostNameScope.LOCAL
    if _RESERVED_NAME.search(host_name):
        return HostNameScope.RESERVED
    if "." in host_name:
        return UnknownHostNameScope(UnknownHostNameScopeReason.DOTTED_NAME)
    return UnknownHostNameScope(UnknownHostNameScopeReason.SINGLE_LABEL)
