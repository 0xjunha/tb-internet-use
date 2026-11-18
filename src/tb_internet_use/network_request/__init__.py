"""Extract the network requests of one trial from the commands, code and web tool calls that its calls ran, one request per target."""

from tb_internet_use.network_request._extract_network_requests import (
    extract_network_requests,
)

__all__ = ["extract_network_requests"]
