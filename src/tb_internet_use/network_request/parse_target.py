"""Read one target word in the notation of its program, giving the host it names, the kind its notation sets and whether it is a local path.

The same word means different things in different notations, e.g. `a.org:x` is an scp-like address for git and a host and path for rsync, and `main:main` is a git refspec that names no host.
A pip requirement follows PEP 508 and pip's reading of it, so it can be a package name, a `git+` address, a URL or a path on the machine, e.g. `requests`, `git+https://github.com/a/b`, `https://a.org/x.whl` or `./dist/x.whl`.
"""

import re

from tb_internet_use.network_request.model import (
    NetworkRequestTargetKind,
    ParsedTarget,
    TargetNotation,
)
from tb_internet_use.network_request.parse_url import SCHEME_AND_SLASHES, parse_url

# A URL with a scheme anywhere in a word, e.g. in `git+https://github.com/a/b` or the direct reference `x@https://a.org/x.whl` of PEP 508.
URL_IN_WORD = re.compile(SCHEME_AND_SLASHES.pattern + r"\S*")
# A host at the start of a URL without a scheme, e.g. `pypi.org` in `pypi.org/simple`, `localhost` in `localhost:8000/x` or `a.org` in `a.org?q=1`.
_SCHEMELESS_HOST = re.compile(r"^([\w.-]+)(?::\d+)?(?:[/?#]|$)")
# A remote git address without a scheme, e.g. `github.com` in `git@github.com:a/b.git`.
# The host needs a user or a dot, so a refspec such as `main:main` in `git fetch origin main:main` is no address.
_SCP_LIKE_ADDRESS = re.compile(r"^(?:[\w.-]+@([\w.-]+)|([\w-]+(?:\.[\w-]+)+)):")
# A pip requirement that names a path on the machine, e.g. `/x`, `~/x`, `.`, `..`, `./x`, `../x` or `.[dev]`.
_LOCAL_PATH_START = re.compile(r"^(?:[/~]|\.\.?(?:/|\[|$))")
# A pip requirement that names an archive file, which pip reads as a path, e.g. `x-1.0-py3-none-any.whl`.
_ARCHIVE_FILE_END = re.compile(r"\.(?:whl|zip|tar\.gz|tgz)$")


def parse_target(target: str, target_notation: TargetNotation) -> ParsedTarget:
    """Read the host, the kind and whether it is a local path of one target word written in `target_notation`, e.g. host `github.com` for `git@github.com:a/b.git` as a URL or scp-like address.

    The host is None when the word names none or none can be read from it, e.g. `requests` as a pip requirement or `main:main` as a git address.
    The kind is None unless the notation sets it apart from the kind of the program's row, as a `git+` address or a URL does for a pip requirement.
    Only a pip requirement can be a local path, since only that notation reads a word as a package name, a URL or a path.
    """
    match target_notation:
        case TargetNotation.URL:
            return ParsedTarget(parse_url(target), None, is_local_path=False)
        case TargetNotation.URL_OR_SCHEMELESS_URL:
            return ParsedTarget(
                _host_name_from_url_or_schemeless_url(target), None, is_local_path=False
            )
        case TargetNotation.URL_OR_SCP_LIKE_ADDRESS:
            return ParsedTarget(
                _host_name_from_url_or_scp_like_address(target),
                None,
                is_local_path=False,
            )
        case TargetNotation.HOST_NAME:
            return ParsedTarget(
                _host_name_from_user_and_host(target), None, is_local_path=False
            )
        case TargetNotation.RSYNC_ADDRESS:
            return ParsedTarget(
                _host_name_from_rsync_address(target), None, is_local_path=False
            )
        case TargetNotation.PIP_REQUIREMENT:
            return _parsed_target_from_pip_requirement(target)
        case TargetNotation.NAME:
            return ParsedTarget(None, None, is_local_path=False)
        case TargetNotation.HOST_AND_PORT_TUPLE:
            return ParsedTarget(target or None, None, is_local_path=False)


def _host_name_from_url_or_schemeless_url(target: str) -> str | None:
    """Find the host of a URL that may lack its scheme, e.g. `pypi.org` for `pypi.org/simple`, as curl reads it."""
    if (host_name := parse_url(target)) is not None:
        return host_name
    schemeless_host_match = _SCHEMELESS_HOST.match(target)
    return schemeless_host_match.group(1) if schemeless_host_match else None


def _host_name_from_url_or_scp_like_address(target: str) -> str | None:
    """Find the host of a git URL or of an address as scp writes it, e.g. `github.com` for `git@github.com:a/b.git`, and None for a local path or a refspec."""
    if "://" in target:
        return parse_url(target)
    scp_like_address_match = _SCP_LIKE_ADDRESS.match(target)
    if scp_like_address_match is None:
        return None
    return scp_like_address_match.group(1) or scp_like_address_match.group(2)


def _host_name_from_user_and_host(target: str) -> str | None:
    """Find the host of a word that names a host, with or without a user, e.g. `box` for `user@box` and `8.8.8.8` for the server word `@8.8.8.8` of dig."""
    return target.rsplit("@", 1)[-1] or None


def _host_name_from_rsync_address(target: str) -> str | None:
    """Find the host of an rsync address, e.g. `box` for `user@box:/tmp` or `rsync://box/module`, and None for a local path such as `./a` or `/b`."""
    if "://" in target:
        return parse_url(target)
    if ":" not in target or target.startswith(("/", ".")):
        return None
    return _host_name_from_user_and_host(target.split(":", 1)[0])


def _parsed_target_from_pip_requirement(requirement: str) -> ParsedTarget:
    """Read a pip requirement as a `git+` address, a URL, a local path or a package name, in that order.

    A `file` URL such as `file:///tmp/x.whl` or `git+file:///repo` names a path on the machine.
    A requirement that holds `/` and no URL is a path too, e.g. `src/pkg` in `pip install -e src/pkg`, since a name of PEP 508 cannot hold `/`.
    """
    if url_match := URL_IN_WORD.search(requirement):
        url = url_match.group()
        if _is_file_url(url):
            return ParsedTarget(None, None, is_local_path=True)
        target_kind = (
            NetworkRequestTargetKind.REPOSITORY_URL
            if url.startswith("git+")
            else NetworkRequestTargetKind.URL
        )
        return ParsedTarget(parse_url(url), target_kind, is_local_path=False)
    is_local_path = bool(
        "/" in requirement
        or _LOCAL_PATH_START.match(requirement)
        or _ARCHIVE_FILE_END.search(requirement)
    )
    return ParsedTarget(None, None, is_local_path=is_local_path)


def _is_file_url(url: str) -> bool:
    """Tell whether a URL has the scheme `file` or a scheme that ends in `+file`, e.g. `git+file:///repo`."""
    scheme = url.split("://", 1)[0].lower()
    return scheme == "file" or scheme.endswith("+file")
