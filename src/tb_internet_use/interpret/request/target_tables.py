"""Define the tables of programs whose targets name hosts, which `targets` reads to find the hosts of a candidate request.

`docs/behavior-tables.md` shows them for review.
"""

# Programs that read a target without a scheme as a URL, e.g. pypi.org/simple in `curl pypi.org/simple`.
SCHEMELESS_URL_PROGRAMS = frozenset({"curl"})
# Programs whose first target is the host they connect to or look up, e.g. a.org in `nc a.org 80` or `nslookup a.org`. Later targets are not read.
PROGRAMS_WITH_HOST_AS_FIRST_TARGET = frozenset(
    {"nc", "ping", "dig", "nslookup", "host"}
)
# Name lookup programs whose every target is a host, e.g. a.org and b.org in `getent hosts a.org b.org`.
PROGRAMS_WITH_HOST_AS_EVERY_TARGET = frozenset({"getent"})
