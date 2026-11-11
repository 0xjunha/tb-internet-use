"""Shared types for the hosts and printing programs that candidate requests and observations both name, so an output line can be linked to its request.

A line such as `Could not resolve host: pypi.org` belongs only to a request to pypi.org, and `Successfully installed requests` only to a run that prints pip lines.
"""

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class Host:
    """Host named by a request target or an output line, with its kind."""

    name: str  # lower case and without brackets, e.g. pypi.org or `::1`
    kind: HostKind


class HostKind(StrEnum):
    """Kind of a host, judged by its name alone."""

    # Has a dot and is none of the kinds below, e.g. pypi.org.
    PUBLIC = "public"
    # Localhost, a .local or .internal name, or a loopback, private, link-local or unspecified address.
    LOCAL = "local"
    # Has no dot, e.g. a container service such as db.
    SINGLE_LABEL = "single_label"
    # Reserved for examples and tests, e.g. example.com or x.test.
    RESERVED = "reserved"
    # Holds $, { or }, so the name is computed when the command runs.
    TEMPLATED = "templated"


class PrintingProgram(StrEnum):
    """Program, program run with an option, or code, whose output lines the observation patterns know.

    A candidate request lists the printing programs its run may include, and an observation lists the printing programs of its line.
    Comparing the two sets links a line to its request.
    """

    PIP = "pip"
    # pip run as `pip index versions`.
    PIP_INDEX = "pip_index"
    UV = "uv"
    NPM = "npm"
    APT = "apt"
    APK = "apk"
    GIT = "git"
    CURL = "curl"
    WGET = "wget"
    PLAYWRIGHT = "playwright"
    DOCKER = "docker"
    # A run that prints response headers, e.g. `curl -i` or `wget -S`.
    HTTP_HEADERS = "http_headers"
    # curl run with -f, which prints error 22 for an HTTP error.
    HTTP_FAILURE = "http_failure"
    # Python or JavaScript code, which prints what its network libraries print.
    CODE = "code"
